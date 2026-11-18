"""Who is calling (ADR-0039): the IAP assertion is verified here — signature, issuer, audience,
expiry — and its e-mail mapped through the directory; anything else is "not signed in". In IAP
mode the sandbox header means nothing."""

from __future__ import annotations

import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from google.auth import crypt, jwt

from app.auth.identity import IAP_HEADER, IapIdentity, IapKeys, IdentityError, SandboxIdentity
from app.config import Settings, get_settings
from app.main import create_app

AUD = "/projects/123/locations/asia-south1/services/c2-frontend"


def _key() -> tuple[str, str]:
    k = ec.generate_private_key(ec.SECP256R1())
    priv = k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = (
        k.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return priv, pub


PRIV, PUB = _key()
OTHER_PRIV, _ = _key()


def _token(priv: str = PRIV, kid: str = "k1", **claims: Any) -> str:
    now = int(time.time())
    body = {
        "iss": "https://cloud.google.com/iap",
        "aud": AUD,
        "email": "so.estt.one@example.org",
        "iat": now,
        "exp": now + 600,
        **claims,
    }
    token: bytes = jwt.encode(crypt.ES256Signer.from_string(priv, kid), body)  # type: ignore[no-untyped-call]
    return token.decode()


def _iap(directory: dict[str, str] | None = None) -> IapIdentity:
    d = directory if directory is not None else {"so.estt.one@example.org": "U01"}
    return IapIdentity((AUD,), d.get, IapKeys(lambda: {"k1": PUB}))


def test_a_valid_assertion_signs_in_the_mapped_officer() -> None:
    assert _iap()({IAP_HEADER: _token()}) == "U01"
    assert _iap()({IAP_HEADER: _token(email="SO.Estt.One@Example.org")}) == "U01"


@pytest.mark.parametrize(
    "token",
    [
        _token(priv=OTHER_PRIV),  # not signed by IAP
        _token(aud="/projects/999/locations/asia-south1/services/other"),
        _token(iss="https://evil.example"),
        _token(exp=int(time.time()) - 120, iat=int(time.time()) - 900),  # expired
        _token(kid="unknown"),
        _token(email="stranger@example.org"),  # verified, but not in the directory
        _token(email=""),
        "not-a-jwt",
        "",
        "x" * 20000,
    ],
)
def test_anything_else_is_not_signed_in(token: str) -> None:
    assert _iap()({IAP_HEADER: token}) is None


def test_hs256_and_unsigned_tokens_are_refused() -> None:
    import base64
    import json

    def b64(o: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()

    claims = {
        "iss": "https://cloud.google.com/iap",
        "aud": AUD,
        "email": "so.estt.one@example.org",
        "exp": int(time.time()) + 600,
    }
    assert _iap()({IAP_HEADER: f"{b64({'alg': 'none'})}.{b64(claims)}."}) is None
    assert _iap()({IAP_HEADER: f"{b64({'alg': 'HS256', 'kid': 'k1'})}.{b64(claims)}.sig"}) is None


def test_keys_are_cached_and_a_failed_refresh_keeps_the_old_ones() -> None:
    calls: list[int] = []

    def fetch() -> dict[str, str]:
        calls.append(1)
        if len(calls) > 1:
            raise OSError("network")
        return {"k1": PUB}

    keys = IapKeys(fetch)
    assert keys.get("k1") == {"k1": PUB} and keys.get("k1") == {"k1": PUB}
    assert len(calls) == 1


def test_configuration_errors_fail_at_startup() -> None:
    with pytest.raises(IdentityError):
        IapIdentity(("c2-frontend",), lambda _e: None)
    with pytest.raises(ValueError, match="C2_IAP_AUDIENCES"):
        Settings(identity="iap")


def test_sandbox_identity_accepts_only_known_logins() -> None:
    s = SandboxIdentity({"U01": "U01"}.get)
    assert s({"X-Sandbox-User": "U01"}) == "U01"
    assert s({"X-Sandbox-User": "POST-ASSISTANT"}) is None and s({}) is None
    assert s({"X-Sandbox-User": "U" * 500}) is None


def test_in_iap_mode_the_sandbox_header_means_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.auth.identity as ident

    monkeypatch.setattr(ident, "_fetch_iap_keys", lambda: {"k1": PUB})
    app = create_app(
        get_settings().model_copy(update={"sandbox": True, "identity": "iap", "iap_audiences": AUD})
    )
    with TestClient(app) as c:
        spoof = c.get("/assist/me/roles", headers={"X-Sandbox-User": "U01"})
        assert spoof.status_code == 401
        ok = c.get("/assist/me/roles", headers={IAP_HEADER: _token()})
        assert ok.status_code == 200 and ok.json() == {"monitoring": False}
        mon = c.get("/assist/me/roles", headers={IAP_HEADER: _token(email="monitor@example.org")})
        assert mon.json() == {"monitoring": True}
