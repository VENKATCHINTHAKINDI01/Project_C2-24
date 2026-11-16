"""OCR for scanned pages and photos (plan §4.1, §4.2; ADR-0017: Document AI in asia-south1).

`detect` routes image-only pages here. The result is a draft: per-page text plus a confidence.
The confidence gate (`gate.py`) decides whether it is trusted. While the threshold is uncalibrated,
every OCR'd extraction waits for a reviewer, who confirms or corrects the text before it is indexed
(`pipeline.confirm_extraction`).

- `OcrEngine` is the interface. Core modules never import a cloud SDK.
- `DocumentAiOcr` calls Document AI online processing in the configured region. The SDK is imported
  lazily, so base installs and unit tests need no GCP extras or credentials.
- `parse_document` turns Document AI's JSON (`Document.to_dict`) into `OcrResult`. Saved responses
  can be re-parsed without paying for OCR again.
- Language hints default to Telugu + English (config). Document bodies are never logged.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.config import Settings


class OcrError(Exception):
    """OCR could not run or returned nothing usable. The caller holds the file for review."""


class OcrParagraph(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class OcrPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int  # 1-based, as in the source file
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)  # None: engine gave none → hold
    languages: tuple[str, ...] = ()
    paragraphs: tuple[OcrParagraph, ...] = ()  # page / paragraph locators (ADR-0014 rule 3)


class OcrResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: str  # e.g. "documentai:asia-south1:<processor id>"
    pages: tuple[OcrPage, ...]

    def page(self, n: int) -> OcrPage | None:
        return next((p for p in self.pages if p.page == n), None)


class OcrEngine(Protocol):
    def read(self, data: bytes, media_type: str, pages: Sequence[int]) -> OcrResult:
        """OCR the given 1-based pages (all pages of a photo: `[1]`)."""
        ...


# ---- Document AI JSON → OcrResult ------------------------------------------------------------


def _int(v: Any) -> int:
    return int(v or 0)  # int64 fields arrive as strings in JSON, and 0 is omitted


def _span(text: str, layout: Mapping[str, Any]) -> str:
    anchor = layout.get("text_anchor") or {}
    return "".join(
        text[_int(s.get("start_index")) : _int(s.get("end_index"))]
        for s in anchor.get("text_segments") or ()
    )


def _confidence(items: Iterable[Mapping[str, Any]], text: str) -> float | None:
    """Mean element confidence weighted by text length; None when the engine reported none."""
    total = weight = 0.0
    for it in items:
        lay = it.get("layout") or {}
        c = lay.get("confidence")
        if c is None:
            continue
        w = max(len(_span(text, lay).strip()), 1)
        total += float(c) * w
        weight += w
    return round(total / weight, 4) if weight else None


def _rows_text(text: str, lines: Sequence[Mapping[str, Any]]) -> str | None:
    """Rebuild the page line by line from geometry: lines whose vertical centres fall within half a
    line height of each other form one row, read left to right. A right-aligned "Dated:" beside
    the G.O. number, which OCR may emit several lines later, lands back on the number's row.
    Returns None when the response has no line geometry; the caller then uses the text order."""
    items: list[tuple[float, float, float, str]] = []  # centre y, height, left x, text
    for ln in lines:
        lay = ln.get("layout") or {}
        verts = (lay.get("bounding_poly") or {}).get("normalized_vertices") or ()
        words = _span(text, lay).strip()
        if len(verts) < 3 or not words:
            continue
        ys = [float(v.get("y", 0.0)) for v in verts]
        xs = [float(v.get("x", 0.0)) for v in verts]
        items.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), words))
    if not items:
        return None
    heights = sorted(h for _, h, _, _ in items)
    tol = max(heights[len(heights) // 2] / 2, 1e-4)
    rows: list[list[tuple[float, float, float, str]]] = []
    for it in sorted(items):
        if rows and it[0] - sum(r[0] for r in rows[-1]) / len(rows[-1]) <= tol:
            rows[-1].append(it)
        else:
            rows.append([it])
    return "\n".join(" ".join(w for *_, w in sorted(r, key=lambda r: r[2])) for r in rows)


def parse_document(doc: Mapping[str, Any], engine: str, pages: Sequence[int]) -> OcrResult:
    """Pages missing from the response come back with empty text and no confidence, so they are
    held. OCR never fills a gap by guessing."""
    text = str(doc.get("text") or "")
    found: dict[int, OcrPage] = {}
    for i, pg in enumerate(doc.get("pages") or (), 1):
        n = _int(pg.get("page_number")) or i
        tokens = pg.get("tokens") or ()
        paras = pg.get("paragraphs") or ()
        conf = _confidence(tokens, text)
        if conf is None:
            conf = _confidence(paras, text)
        if conf is None and (pc := (pg.get("layout") or {}).get("confidence")) is not None:
            conf = round(float(pc), 4)
        found[n] = OcrPage(
            page=n,
            text=_rows_text(text, pg.get("lines") or ())
            or _span(text, pg.get("layout") or {}).strip(),
            confidence=min(max(conf, 0.0), 1.0) if conf is not None else None,
            languages=tuple(
                str(lang.get("language_code"))
                for lang in pg.get("detected_languages") or ()
                if lang.get("language_code")
            ),
            paragraphs=tuple(
                OcrParagraph(
                    text=_span(text, p.get("layout") or {}).strip(),
                    confidence=(p.get("layout") or {}).get("confidence"),
                )
                for p in paras
                if _span(text, p.get("layout") or {}).strip()
            ),
        )
    return OcrResult(
        engine=engine,
        pages=tuple(found.get(n) or OcrPage(page=n, text="", confidence=None) for n in pages),
    )


# ---- Document AI engine ----------------------------------------------------------------------


class DocumentAiOcr:
    """Document AI Enterprise OCR, online processing (plan §4.1). Region-pinned endpoint."""

    def __init__(
        self,
        project_id: str,
        location: str,
        processor_id: str,
        *,
        language_hints: Sequence[str] = ("te", "en"),
        max_online_pages: int = 15,
        processor_version: str | None = None,
        client: Any = None,
    ) -> None:
        if not (project_id and location and processor_id):
            raise OcrError("Document AI OCR needs project, location and processor ID")
        self.project_id, self.location, self.processor_id = project_id, location, processor_id
        self.language_hints = tuple(language_hints)
        self.max_online_pages = max_online_pages
        self._client = client
        # Pin the OCR model version: the processor default in asia-south1 is the 2020 stable model,
        # which cannot read Telugu (probe, 11 Nov 2026). None = the processor's default.
        self.processor_version = processor_version
        self.name = f"documentai:{location}:{processor_id}:{processor_version or 'default'}"

    def _sdk(self) -> Any:
        try:
            from google.cloud import documentai_v1  # noqa: PLC0415 — optional `gcp` extra
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise OcrError("google-cloud-documentai not installed (uv sync --extra gcp)") from exc
        return documentai_v1

    def raw(self, data: bytes, media_type: str, pages: Sequence[int]) -> dict[str, Any]:
        """The Document AI response as JSON-ready dict (kept to re-parse without paying again)."""
        if not pages:
            raise OcrError("no pages to OCR")
        if len(pages) > self.max_online_pages:
            raise OcrError(f"{len(pages)} pages > online limit {self.max_online_pages}; batch")
        if media_type not in ("application/pdf", "image/jpeg", "image/png", "image/tiff"):
            raise OcrError(f"media type {media_type} not supported for OCR")
        d = self._sdk()
        client = self._client or d.DocumentProcessorServiceClient(
            client_options={"api_endpoint": f"{self.location}-documentai.googleapis.com"}
        )
        options = d.ProcessOptions(
            ocr_config=d.OcrConfig(
                hints=d.OcrConfig.Hints(language_hints=list(self.language_hints))
            )
        )
        if media_type == "application/pdf":
            options.individual_page_selector = d.ProcessOptions.IndividualPageSelector(
                pages=list(pages)
            )
        request = d.ProcessRequest(
            name=client.processor_version_path(
                self.project_id, self.location, self.processor_id, self.processor_version
            )
            if self.processor_version
            else client.processor_path(self.project_id, self.location, self.processor_id),
            raw_document=d.RawDocument(content=data, mime_type=media_type),
            process_options=options,
        )
        try:
            result = client.process_document(request=request)
        except Exception as exc:  # SDK raises many types; never pass content on
            raise OcrError(f"Document AI call failed: {type(exc).__name__}") from exc
        out: dict[str, Any] = d.Document.to_dict(result.document)
        return out

    def read(self, data: bytes, media_type: str, pages: Sequence[int]) -> OcrResult:
        return parse_document(self.raw(data, media_type, pages), self.name, pages)


class RecordedOcr:
    """Replays saved Document AI responses keyed by the file's sha256 (no new cost). Used by the
    evaluation harness and tests; an unknown file raises OcrError, which holds the file."""

    def __init__(self, responses: Mapping[str, Mapping[str, Any]], engine: str) -> None:
        self._responses = dict(responses)
        self.name = engine

    def read(self, data: bytes, media_type: str, pages: Sequence[int]) -> OcrResult:
        key = hashlib.sha256(data).hexdigest()
        doc = self._responses.get(key)
        if doc is None:
            raise OcrError("no recorded OCR response for this file")
        return parse_document(doc, self.name, pages)


class RecordedOcrFiles:
    """Like RecordedOcr, but each saved response `<sha256>.json` is read from disk when its file
    is ingested and not kept: a whole corpus of responses does not fit in memory (the sandbox
    held about 3 GB for 60 files when it loaded them all at start)."""

    def __init__(self, directories: Sequence[Path], engine: str) -> None:
        self._dirs = tuple(directories)
        self.name = engine

    def read(self, data: bytes, media_type: str, pages: Sequence[int]) -> OcrResult:
        name = f"{hashlib.sha256(data).hexdigest()}.json"
        for d in self._dirs:
            path = d / name
            if path.is_file():
                return parse_document(json.loads(path.read_text("utf-8")), self.name, pages)
        raise OcrError("no recorded OCR response for this file")


# ---- caching and configuration -----------------------------------------------------------------


def version_dir(root: Path, processor_version: str | None) -> Path:
    """Responses are kept per OCR model version: a new version is a new read, never mixed."""
    return root / (processor_version or "processor-default")


def load_recorded(directory: Path) -> dict[str, dict[str, Any]]:
    """Saved responses `<sha256>.json` in `directory` (missing directory → none)."""
    if not directory.is_dir():
        return {}
    return {f.stem: json.loads(f.read_text("utf-8")) for f in sorted(directory.glob("*.json"))}


class CachingOcr:
    """Live Document AI with an on-disk cache keyed by file sha256, so a file is OCR'd (and billed)
    once. Responses are saved as Document AI returned them; `RecordedOcr` replays them."""

    def __init__(self, live: DocumentAiOcr, root: Path) -> None:
        self.live, self.name = live, live.name
        self.directory = version_dir(root, live.processor_version)

    def read(self, data: bytes, media_type: str, pages: Sequence[int]) -> OcrResult:
        path = self.directory / f"{hashlib.sha256(data).hexdigest()}.json"
        if path.is_file():
            return parse_document(json.loads(path.read_text("utf-8")), self.name, pages)
        doc = self.live.raw(data, media_type, pages)
        for pg in doc.get("pages") or ():  # page images are large and not needed to re-parse
            pg.pop("image", None)
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False), "utf-8")
        return parse_document(doc, self.name, pages)


def ocr_from_settings(settings: Settings) -> OcrEngine | None:
    """The configured engine, or None. Misconfiguration raises at startup (fail closed), never
    silently falls back to another region or provider."""
    if settings.ocr_provider == "none":
        return None
    location = settings.docai_location or settings.gcp_region or ""
    version = settings.docai_ocr_processor_version
    processor = settings.docai_ocr_processor_id or "recorded"
    name = f"documentai:{location}:{processor}:{version or 'default'}"
    if settings.ocr_provider == "recorded":
        return RecordedOcr(load_recorded(version_dir(settings.ocr_recorded_dir, version)), name)
    live = DocumentAiOcr(
        settings.gcp_project_id or "",
        location,
        settings.docai_ocr_processor_id or "",
        language_hints=settings.ocr_language_hints,
        processor_version=version,
    )
    return CachingOcr(live, settings.ocr_recorded_dir)
