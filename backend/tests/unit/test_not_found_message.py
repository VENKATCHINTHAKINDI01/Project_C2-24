"""One answer for a cited order C2-24 does not hold and one the officer may not see (ADR-0016,
ADR-0019; CLAUDE.md §4.7). The backend and the sandbox screens must use the same words."""

from __future__ import annotations

from pathlib import Path

from app.auth.messages import CITED_NOT_FOUND, DOCUMENT_NOT_AVAILABLE, GUIDE, NOT_IN_COLLECTION

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "eoffice" / "src"
CITATIONS_TSX = FRONTEND / "components" / "Citations.tsx"


def test_message_covers_both_cases_and_never_says_does_not_exist() -> None:
    for msg in (CITED_NOT_FOUND, DOCUMENT_NOT_AVAILABLE):
        assert NOT_IN_COLLECTION in msg and GUIDE in msg
        assert "does not exist" not in msg.lower() and "doesn't exist" not in msg.lower()


def test_sandbox_screen_uses_the_same_words() -> None:
    tsx = CITATIONS_TSX.read_text("utf-8")
    assert f'"{NOT_IN_COLLECTION} {GUIDE}"' in tsx
    assert '"Not found in the records available to you"' in tsx
