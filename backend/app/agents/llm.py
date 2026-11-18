"""Gemini on Vertex AI behind one small interface (plan §2.1, §7; ADR-0017).

`LLMClient.generate_json` sends a versioned prompt (backend/prompts/) with an evidence block and
returns the model's JSON answer, constrained by a response schema. The model only ever sees what the
caller passes in, which must come from the authorised evidence package (CLAUDE.md §7.1).

Engines:
- `GeminiVertexClient`: live calls to the regional Vertex AI endpoint (asia-south1 by default), no
  global endpoint (ADR-0017 point 3). Billed.
- `CachingLLM`: a live client with an on-disk cache keyed by the full request, so an identical
  request is paid for once; `RecordedLLM` replays that cache only (no calls). Responses are kept per
  model ID, so models are never mixed.
- `OllamaClient`: an open model served by Ollama on THIS machine (loopback only), so no document
  text leaves the host. Fallback only (ADR-0021).
- `FailoverLLM`: primary first; after repeated failures it answers from the fallback, and it
  returns to the primary by itself once a trial call succeeds (circuit breaker, ADR-0021).
Any failure raises `LLMError`; callers fail closed (the check is reported as not run).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from app.config import REPO_ROOT, Settings

log = logging.getLogger(__name__)
PROMPTS = REPO_ROOT / "backend" / "prompts"


class LLMError(Exception):
    """The model could not answer. Never carries document text."""


def load_prompt(prompt_id: str) -> str:
    """A versioned prompt file ("conflict_contradiction.v1" → prompts/<id>.md)."""
    path = PROMPTS / f"{prompt_id}.md"
    if not path.is_file():
        raise LLMError(f"prompt {prompt_id} not found")
    return path.read_text(encoding="utf-8")


class LLMClient(Protocol):
    name: str  # e.g. "gemini-3.5-flash@asia-south1"

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]: ...


def stream_json(
    llm: LLMClient,
    *,
    prompt_id: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    on_text: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """`generate_json`, with the answer's text passed to `on_text` as it arrives (ADR-0033).
    Without `on_text` it IS `generate_json`. A client that cannot stream (saved answers, local
    Ollama) hands over its whole answer at once; the request and the answer are the same."""
    kw: dict[str, Any] = {"prompt_id": prompt_id, "system": system, "user": user, "schema": schema}
    if on_text is None:
        return llm.generate_json(**kw)
    streaming = getattr(llm, "stream_json", None)
    if streaming is None:
        out = llm.generate_json(**kw)
        on_text(json.dumps(out, ensure_ascii=False))
        return out
    result: dict[str, Any] = streaming(**kw, on_text=on_text)
    return result


def request_key(model: str, prompt_id: str, system: str, user: str, schema: dict[str, Any]) -> str:
    blob = json.dumps(
        {"model": model, "prompt": prompt_id, "system": system, "user": user, "schema": schema},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class GeminiVertexClient:
    """Live Gemini on the regional Vertex AI endpoint. Temperature 0; JSON answer with a schema."""

    def __init__(
        self,
        project: str,
        location: str,
        model: str,
        client: Any = None,
        timeout_s: float = 60.0,
    ) -> None:
        if not (project and location and model):
            raise LLMError("Gemini needs project, location and model")
        self.project, self.location, self.model = project, location, model
        self.timeout_s = timeout_s  # a stuck call ends closed, never hangs a request (ADR-0039)
        self.name = f"{model}@{location}"
        self._client = client

    def _sdk(self) -> Any:
        if self._client is None:
            try:
                from google import genai  # noqa: PLC0415 — optional `gcp` extra
            except ImportError as exc:  # pragma: no cover - depends on installed extras
                raise LLMError("google-genai not installed (uv sync --extra gcp)") from exc
            from google.genai import types  # noqa: PLC0415

            self._client = genai.Client(
                vertexai=True,
                project=self.project,
                location=self.location,
                http_options=types.HttpOptions(timeout=int(self.timeout_s * 1000)),
            )
        return self._client

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        client = self._sdk()
        try:
            from google.genai import types  # noqa: PLC0415

            config = types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=schema,
            )
            resp = client.models.generate_content(model=self.model, contents=user, config=config)
            out = json.loads(resp.text or "")
        except Exception as exc:  # SDK and JSON errors of many types; never pass content on
            raise LLMError(f"Gemini call failed: {type(exc).__name__}") from exc
        if not isinstance(out, dict):
            raise LLMError("Gemini answer is not a JSON object")
        return out

    def stream_json(
        self,
        *,
        prompt_id: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        on_text: Callable[[str], None],
    ) -> dict[str, Any]:
        """Same request and answer as `generate_json`, read as it is written (ADR-0033)."""
        client = self._sdk()
        parts: list[str] = []
        try:
            from google.genai import types  # noqa: PLC0415

            config = types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=schema,
            )
            for chunk in client.models.generate_content_stream(
                model=self.model, contents=user, config=config
            ):
                text = chunk.text or ""
                if text:
                    parts.append(text)
                    on_text(text)
            out = json.loads("".join(parts))
        except LLMError:
            raise
        except Exception as exc:  # SDK and JSON errors of many types; never pass content on
            raise LLMError(f"Gemini call failed: {type(exc).__name__}") from exc
        if not isinstance(out, dict):
            raise LLMError("Gemini answer is not a JSON object")
        return out


class CachingLLM:
    """A live client with a request-keyed cache on disk (`<dir>/<model>/<sha256>.json`)."""

    def __init__(self, live: GeminiVertexClient | OllamaClient, root: Path) -> None:
        self.live, self.name = live, live.name
        self.directory = root / live.model.replace("/", "_").replace(":", "_")
        self.last_from_cache = False  # a saved answer says nothing about the model's health

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        key = request_key(self.live.model, prompt_id, system, user, schema)
        path = self.directory / f"{key}.json"
        self.last_from_cache = path.is_file()
        if self.last_from_cache:
            return dict(json.loads(path.read_text("utf-8"))["response"])
        out = self.live.generate_json(prompt_id=prompt_id, system=system, user=user, schema=schema)
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"prompt": prompt_id, "model": self.live.model, "response": out}),
            "utf-8",
        )
        return out

    def stream_json(
        self,
        *,
        prompt_id: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        on_text: Callable[[str], None],
    ) -> dict[str, Any]:
        key = request_key(self.live.model, prompt_id, system, user, schema)
        path = self.directory / f"{key}.json"
        self.last_from_cache = path.is_file()
        if self.last_from_cache:
            out = dict(json.loads(path.read_text("utf-8"))["response"])
            on_text(json.dumps(out, ensure_ascii=False))
            return out
        out = stream_json(
            self.live, prompt_id=prompt_id, system=system, user=user, schema=schema, on_text=on_text
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"prompt": prompt_id, "model": self.live.model, "response": out}),
            "utf-8",
        )
        return out


LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class OllamaClient:
    """An open model served by Ollama on this machine (`/api/chat`, JSON answer constrained by
    the schema, temperature 0). The address must be loopback: document text never leaves the
    host (ADR-0021). Not billed."""

    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0) -> None:
        host = urlparse(base_url).hostname
        if urlparse(base_url).scheme != "http" or host not in LOOPBACK:
            raise LLMError("Ollama must be on this machine (http://localhost:<port>)")
        if not model:
            raise LLMError("Ollama needs a model name (C2_OLLAMA_MODEL)")
        self.base_url, self.model, self.timeout_s = base_url.rstrip("/"), model, timeout_s
        self.name = f"{model}@ollama-local"

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        body = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(  # noqa: S310 — loopback http only, checked in __init__
            f"{self.base_url}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                out = json.loads(json.loads(resp.read())["message"]["content"])
        except Exception as exc:  # connection, HTTP, JSON: never pass content on
            raise LLMError(f"Ollama call failed: {type(exc).__name__}") from exc
        if not isinstance(out, dict):
            raise LLMError("Ollama answer is not a JSON object")
        return out


class FailoverLLM:
    """Primary model with a local fallback and automatic return (ADR-0021).

    - closed (normal): the primary answers. If it fails, the fallback answers THAT request;
      after `threshold` failures in a row the breaker opens.
    - open: the fallback answers directly, so requests do not wait on a model that is down.
    - after `cooldown_s` the next request is a trial on the primary: success closes the breaker
      (back to the primary); failure reopens it with a longer wait (doubling, up to `max_s`).
    A saved (cached) answer is not a sign of health and never changes the state.
    `last_used` names the engine that gave the latest answer, so a flag can say so.
    """

    def __init__(
        self,
        primary: LLMClient,
        fallback: LLMClient,
        *,
        threshold: int = 2,
        cooldown_s: float = 60.0,
        max_s: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.primary, self.fallback = primary, fallback
        self.threshold, self.cooldown_s, self.max_s, self._clock = (
            threshold,
            cooldown_s,
            max_s,
            clock,
        )
        self.name = f"{primary.name} (fallback {fallback.name})"
        self.last_used = primary.name
        self._failures = 0
        self._open_until: float | None = None
        self._wait = cooldown_s

    @property
    def on_fallback(self) -> bool:
        """True while the breaker is open and the wait has not run out."""
        return self._open_until is not None and self._clock() < self._open_until

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        kw: dict[str, Any] = {"prompt_id": prompt_id, "system": system, "user": user}
        return self._call(lambda c: c.generate_json(**kw, schema=schema))

    def stream_json(
        self,
        *,
        prompt_id: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        on_text: Callable[[str], None],
    ) -> dict[str, Any]:
        """A primary that fails part-way is answered again by the fallback; what was streamed
        from the first was checked statement by statement, and the final answer replaces it."""
        kw: dict[str, Any] = {"prompt_id": prompt_id, "system": system, "user": user}
        return self._call(lambda c: stream_json(c, **kw, schema=schema, on_text=on_text))

    def _call(self, call: Callable[[LLMClient], dict[str, Any]]) -> dict[str, Any]:
        if not self.on_fallback:
            trial = self._open_until is not None  # wait over: one trial on the primary
            try:
                out = call(self.primary)
            except LLMError as exc:
                self._failures += 1
                if trial or self._failures >= self.threshold:
                    self._wait = min(self._wait * 2, self.max_s) if trial else self.cooldown_s
                    self._open_until = self._clock() + self._wait
                    log.warning(
                        "llm failover: primary down (%s); fallback for %ss", exc, self._wait
                    )
            else:
                if not getattr(self.primary, "last_from_cache", False):
                    if trial:
                        log.warning("llm failover: primary is back")
                    self._failures, self._open_until, self._wait = 0, None, self.cooldown_s
                self.last_used = self.primary.name
                return out
        out = call(self.fallback)  # LLMError here → caller fails closed
        self.last_used = self.fallback.name
        return out


class RecordedLLM:
    """Replays the cache only (tests, evaluation, sandbox without GCP). Unknown → LLMError."""

    def __init__(self, root: Path, model: str) -> None:
        self.model, self.name = model, f"{model}@recorded"
        self.directory = root / model

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        path = self.directory / f"{request_key(self.model, prompt_id, system, user, schema)}.json"
        if not path.is_file():
            raise LLMError("no recorded answer for this request")
        return dict(json.loads(path.read_text("utf-8"))["response"])


def llm_from_settings(settings: Settings) -> LLMClient | None:
    """The configured engine, or None (checks that need it are reported as not run). Bad config
    raises at startup; never falls back to another region or model."""
    if settings.llm_provider == "none":
        return None
    if settings.llm_provider == "recorded":
        return RecordedLLM(settings.llm_recorded_dir, settings.gemini_model)
    live = GeminiVertexClient(
        settings.gcp_project_id or "",
        settings.gemini_location or settings.gcp_region or "",
        settings.gemini_model,
        timeout_s=settings.llm_timeout_s,
    )
    primary = CachingLLM(live, settings.llm_recorded_dir)
    if settings.llm_fallback == "none":
        return primary
    local = OllamaClient(settings.ollama_base_url, settings.ollama_model or "")
    return FailoverLLM(
        primary,
        CachingLLM(local, settings.llm_recorded_dir),  # kept per model: answers are never mixed
        threshold=settings.llm_failover_threshold,
        cooldown_s=settings.llm_failover_cooldown_s,
    )
