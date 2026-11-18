"""Who is calling (plan §3.5 IAM + IAP; CLAUDE.md §4.1, §4.4; ADR-0039).

Two ways to establish the officer, chosen by `C2_IDENTITY`:

- **sandbox** — the simulated sign-in of the mock e-Office (a profile picked on the sign-in
  screen, sent as `X-Sandbox-User`). Only sandbox profiles with a login are accepted. Never the
  identity of a real deployment.
- **iap** — Identity-Aware Proxy. IAP signs a JWT for every request that passed it
  (`x-goog-iap-jwt-assertion`). The frontend service forwards that assertion unchanged as
  `X-C2-IAP-Assertion` (it cannot forge one: only IAP holds the signing key). c2-api verifies it
  itself — ES256 signature against IAP's published keys, issuer, audience, expiry — and maps the
  verified e-mail to an e-Office user through the directory. Anything else (no header, a bad
  signature, the wrong audience, an expired token, an e-mail not in the directory) is "not signed
  in". In this mode `X-Sandbox-User` is ignored.

Nothing here decides access; it only says who is asking. Access is decided per record later.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Protocol

log = logging.getLogger("c2.identity")

SANDBOX_HEADER = "X-Sandbox-User"
IAP_HEADER = "X-C2-IAP-Assertion"  # set by the frontend from IAP's x-goog-iap-jwt-assertion
IAP_ISSUER = "https://cloud.google.com/iap"
IAP_KEYS_URL = "https://www.gstatic.com/iap/verify/public_key"  # {kid: PEM}, ES256
KEYS_TTL_S = 3600.0
CLOCK_SKEW_S = 30
MAX_TOKEN_BYTES = 8192  # an IAP assertion is ~1 KB; anything far larger is not one


class Headers(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...


class IdentityError(Exception):
    """Identity configuration is unusable. Raised at startup, never per request."""


class IapKeys:
    """IAP's public keys, fetched once and refreshed hourly (and at once for an unknown key id,
    at most once a minute, so a key rotation does not lock everyone out)."""

    def __init__(self, fetch: Callable[[], Mapping[str, str]] | None = None) -> None:
        self._fetch = fetch or _fetch_iap_keys
        self._keys: dict[str, str] = {}
        self._at = 0.0
        self._lock = threading.Lock()

    def get(self, kid: str | None) -> dict[str, str]:
        with self._lock:
            now = time.monotonic()
            stale = now - self._at > KEYS_TTL_S
            unknown = kid is not None and kid not in self._keys and now - self._at > 60
            if not self._keys or stale or unknown:
                try:
                    self._keys = dict(self._fetch())
                    self._at = now
                except Exception as exc:  # keep the old keys; with none, nobody is verified
                    log.error("IAP keys not refreshed: %s", type(exc).__name__)
            return dict(self._keys)


def _fetch_iap_keys() -> Mapping[str, str]:
    with urllib.request.urlopen(IAP_KEYS_URL, timeout=5) as resp:  # noqa: S310 — fixed https URL
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError("IAP keys: unexpected document")
    return {str(k): str(v) for k, v in data.items()}


class IapIdentity:
    """Verifies the IAP assertion and maps its e-mail to an e-Office user (fail closed)."""

    def __init__(
        self,
        audiences: tuple[str, ...],
        directory: Callable[[str], str | None],
        keys: IapKeys | None = None,
    ) -> None:
        if not audiences or not all(a.startswith("/projects/") for a in audiences):
            raise IdentityError(
                "C2_IAP_AUDIENCES must list IAP audiences such as "
                "/projects/<number>/locations/<region>/services/<service>"
            )
        self.audiences = audiences
        self.directory = directory
        self.keys = keys or IapKeys()

    def claims(self, token: str) -> dict[str, Any] | None:
        """The verified claims, or None. Never raises for a bad token."""
        if not token or len(token) > MAX_TOKEN_BYTES:
            return None
        from google.auth import jwt  # the `gcp` extra (google-auth)

        try:
            header = jwt.decode_header(token)  # type: ignore[no-untyped-call]
            if header.get("alg") != "ES256":
                return None
            certs = self.keys.get(header.get("kid"))
            if not certs:
                return None
            claims = jwt.decode(  # type: ignore[no-untyped-call]
                token,
                certs=certs,
                audience=list(self.audiences),
                clock_skew_in_seconds=CLOCK_SKEW_S,
            )
        except Exception:  # bad signature, audience, expiry, format: all just "not signed in"
            return None
        if claims.get("iss") != IAP_ISSUER or not claims.get("email"):
            return None
        return dict(claims)

    def __call__(self, headers: Headers) -> str | None:
        got = self.claims(str(headers.get(IAP_HEADER) or ""))
        if got is None:
            return None
        return self.directory(str(got["email"]).strip().lower())


class SandboxIdentity:
    """The mock e-Office's simulated sign-in (sandbox only)."""

    def __init__(self, known: Callable[[str], str | None]) -> None:
        self.known = known

    def __call__(self, headers: Headers) -> str | None:
        uid = headers.get(SANDBOX_HEADER)
        if not uid or len(uid) > 64:
            return None
        return self.known(str(uid))
