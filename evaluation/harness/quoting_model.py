"""A deterministic stand-in for the model, for evaluation sweeps only (ADR-0053 acceptance).

NOT the real model and never used by the app: it answers a cited-answer prompt by quoting the
first line of each piece of evidence it was given (up to three), so answers pass the citation
check, get cached and can be served again — which is what a cache leakage sweep must exercise.
Anything else it is asked (noting drafts, contradiction checks) it declines, as a model that is
unavailable would; the app then answers without it.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.llm import LLMError

EV = re.compile(r'<evidence id="(EV-[0-9a-f]+)" doc="([^"]+)"[^>]*>\n(.*?)\n</evidence>', re.S)


class QuotingModel:
    name = "quoting-stand-in"

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        if not prompt_id.startswith("answer_cited"):
            raise LLMError("stand-in answers cited questions only")
        out = []
        for eid, _, text in EV.findall(user)[:3]:
            line = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 20), None)
            if line:
                out.append({"text": line, "evidence_ids": [eid], "quote": line})
        return {"statements": out}
