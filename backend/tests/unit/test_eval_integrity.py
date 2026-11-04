"""Evaluation integrity guard (CLAUDE.md §9.2): application code never reads the ground truth."""

from __future__ import annotations

import re

from app.config import REPO_ROOT

APP_DIR = REPO_ROOT / "backend" / "app"
FORBIDDEN = re.compile(
    r"ground[_-]?truth|golden_questions|conflicts\.json|^\s*(from|import)\s+evaluation\b",
    re.IGNORECASE | re.MULTILINE,
)


def test_app_code_never_references_ground_truth() -> None:
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in APP_DIR.rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".yaml", ".yml", ".json", ".sql"}
        and FORBIDDEN.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
