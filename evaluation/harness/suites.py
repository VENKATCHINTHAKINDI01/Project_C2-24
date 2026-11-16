"""Evaluation suites (plan §13; CLAUDE.md §9.3): retrieval, conflicts (pre-send), leakage matrix,
touchpoint scenarios. EVALUATION ONLY — reads the ground truth; the app never does."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents.brief import approval_brief
from app.agents.dfa import draft_for_approval
from app.agents.first_cut import first_cut_note
from app.agents.intents import RELATED, Intent, IntentSlots, build_request
from app.agents.local_reference import local_reference
from app.agents.receipts import review_receipt
from app.agents.tools import ToolContext, ToolName, call_tool
from app.auth.policy import check
from app.auth.store import InMemoryAuthzStore
from app.config import load_hierarchy
from app.conflict.facts import extract_proposal_facts
from app.conflict.presend import PreSendReport, presend_check
from app.conflict.procedural import AuthorityRules, load_authority_rules
from app.connectors.eoffice import FileContext, NoteRef, PageRef, ReceiptContext
from app.graph.repository import Direction
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys
from app.ingestion.metadata import extract_metadata
from app.noting.chain import file_so_far
from app.noting.references import ReferenceConfig, suggest_references
from app.precedent.links import suggest_links
from app.retrieval.evidence import CandidateSpan, build_package
from app.retrieval.ladder import LadderRequest, LadderResult, ladder_label, run_ladder
from app.retrieval.references import LookupStatus, lookup_reference
from app.retrieval.scoped import L1Criteria
from app.temporal.engine import status_as_of
from app.updates.reconcile import notices_for
from evaluation.harness import metrics as m
from evaluation.harness.sandbox_flow import EXTENDED, run_extended
from evaluation.harness.stack import ONTOLOGY, Stack, build_stack
from tests.unit.mock_access import CLASSES, CORPUS, MATRIX, POLICY, USER_IDS, new_store, rows

GT = CORPUS / "ground_truth"
IMPLEMENTED_TYPES = ("A", "C", "E", "F")  # deterministic (CLAUDE.md §6.5)
ALL_TYPES = ("A", "B", "C", "D", "E", "F", "G")
NOT_YET = (
    "not wired into this v1 harness — B and G (Gemini) and D (precedent) are measured on set v2 by "
    "evaluation/presend_v2.py"
)


def _load(name: str) -> Any:
    return json.loads((GT / name).read_text("utf-8"))


def _load_seed() -> Any:
    return json.loads((CORPUS / "eoffice" / "seed.json").read_text("utf-8"))


@dataclass
class Run:
    request: LadderRequest | None
    result: LadderResult | None
    ranked: list[str]  # corpus doc ids, ladder order
    note: str = ""
    presend: PreSendReport | None = None


class Harness:
    def __init__(self, stack: Stack, slots: dict[str, Any], rules_path: Path | None = None) -> None:
        self.s = stack
        self.slots = slots
        self.as_of = dt.date.fromisoformat(slots["as_of"])
        self.rules: AuthorityRules = load_authority_rules(
            rules_path or ONTOLOGY / "authority_rules.yaml"
        )
        self.golden = {q["id"]: q for q in _load("golden_questions.json")}
        self.conflicts: list[dict[str, Any]] = _load("conflicts.json")
        self.scenarios: list[dict[str, Any]] = _load("touchpoint_scenarios.json")["scenarios"]
        self.raw_ref = {r["id"]: r["raw_reference"] for r in rows("documents_index.csv")}

    # ---- plumbing -----------------------------------------------------------------------------

    def store(self) -> InMemoryAuthzStore:
        return new_store()

    def ladder(self, req: LadderRequest) -> LadderResult:
        st = self.s.stores
        return run_ladder(
            req,
            index=st.index,
            l2=self.s.l2,
            graph=st.graph,
            cfg=self.s.cfg,
            store=self.store(),
            policy=POLICY,
            classification=CLASSES,
        )

    def ranked(self, res: LadderResult) -> list[str]:
        cids = [d.canonical_id for d in res.documents] + list(res.graph_hits)
        return list(dict.fromkeys(self.s.doc_of.get(c, c) for c in cids))

    def disclosures(self, user: str, doc_ids: Iterable[str]) -> list[str]:
        """Doc ids the independent access matrix says this officer may NOT see."""
        return sorted({d for d in doc_ids if not MATRIX.get((d, user), False)})

    def visible(self, user: str, cid: str) -> bool:
        did = self.s.doc_of.get(cid)
        return did is not None and MATRIX.get((did, user), False)

    def _note(self, cid: str) -> tuple[str, Any]:
        text = self.s.text_of[cid]
        return text, extract_metadata(text, self.s.departments)

    def presend(self, did: str, user: str) -> PreSendReport:
        cid = self.s.cid_of[did]
        text, meta = self._note(cid)
        tags_of = {c: t for c in self.s.stores.graph.node_ids() if (t := self.s.tags(c))}
        return presend_check(
            cid,
            text,
            meta,
            user_id=user,
            instruments=self.s.stores.instruments,
            relations=list(self.s.stores.relations),
            tags_of=tags_of,
            rules=self.rules,
            store=self.store(),
            policy=POLICY,
            classification=CLASSES,
            windows=[w for ws in self.s.stores.windows.values() for w in ws],
            awaiting_review=tuple(self.s.stores.awaiting.values()),
        )

    def _draft_in_file(self, file_no: str, user: str) -> str | None:
        """Stand-in for the connector's context: the latest note in the open file."""
        docs = [
            (d or dt.date.min, c)
            for c, d in self.s.stores.files.get(file_no, [])
            if self.visible(user, c)
        ]
        return self.s.doc_of[max(docs)[1]] if docs else None

    def _cited_ids(self, did: str) -> tuple[str, ...]:
        _, meta = self._note(self.s.cid_of[did])
        known = set(self.s.doc_of)
        out = []
        for ref in meta.references:
            if ref.canonical_id is None or ref.raw.startswith("file:"):
                continue
            cid = ref.canonical_id
            try:
                cid = next((k for k in lookup_keys(cid) if k in known), cid)
            except InvalidCanonicalIdError:
                pass
            out.append(cid)
        return tuple(dict.fromkeys(out))[:10]

    def run_spec(self, spec: dict[str, Any], question: str, user: str) -> Run:
        intent = spec["intent"]
        if intent == "file_check":
            did = self._draft_in_file(spec["file_no"], user)
            if did is None:
                return Run(None, None, [], note="no draft visible in the file")
            ids = self._cited_ids(did)
            req = build_request(Intent.CONFLICT_CHECK, IntentSlots(canonical_ids=ids), user)
            res = self.ladder(req)
            return Run(
                req, res, self.ranked(res), note=f"draft {did}", presend=self.presend(did, user)
            )
        if "reference" in spec:
            look = lookup_reference(
                user,
                question,
                departments=self.s.departments,
                retriever=self.s.stores.index,
                store=self.store(),
                policy=POLICY,
                classification=CLASSES,
            )
            if look.status is not LookupStatus.FOUND or look.canonical_id is None:
                return Run(None, None, [], note=f"reference lookup: {look.status.value}")
            req = build_request(
                Intent(intent), IntentSlots(canonical_ids=(look.canonical_id,)), user
            )
        else:
            raw = dict(spec.get("slots", {}))
            if raw.get("text") == "@question":
                raw["text"] = question
            req = build_request(Intent(intent), IntentSlots.model_validate(raw), user)
        res = self.ladder(req)
        return Run(req, res, self.ranked(res))

    def package_ids(self, user: str, run: Run) -> list[str]:
        """Doc ids that reach the evidence package (re-checked, plan §5.2)."""
        if run.result is None:
            return []
        cands = []
        label = ladder_label(run.result)
        for did in run.ranked:
            cid = self.s.cid_of.get(did, did)
            tags = self.s.tags(cid)
            if tags is None:
                continue
            inst = self.s.stores.instruments.get(cid)
            cands.append(
                CandidateSpan(
                    canonical_id=cid,
                    span_text=(self.s.text_of.get(cid) or cid)[:200],
                    source_uri=f"mock://{did}",
                    doc_type="unknown",
                    hierarchy_level=inst.hierarchy_level if inst else 0,
                    status="unknown",
                    ladder_level=label,
                    tags=tags,
                )
            )
        pkg = build_package(
            "eval",
            user,
            self.as_of,
            cands,
            store=self.store(),
            policy=POLICY,
            classification=CLASSES,
        )
        return [self.s.doc_of.get(i.canonical_id, i.canonical_id) for i in pkg.items]

    # ---- suite 1 · retrieval --------------------------------------------------------------------

    def retrieval(self) -> dict[str, Any]:
        per: list[dict[str, Any]] = []
        for qid, q in self.golden.items():
            spec = self.slots["questions"][qid]
            run = self.run_spec(spec, q["question"], q["user"])
            rel = set(q["expected_docs"])
            got = run.ranked
            row: dict[str, Any] = {
                "id": qid,
                "user": q["user"],
                "intent": spec["intent"],
                "answer_status": q["answer_status"],
                "expected_level": q["expected_ladder_level"],
                "level": ladder_label(run.result) if run.result else "—",
                "expected_docs": sorted(rel),
                "ranked": got,
                "forbidden_hits": sorted(set(q["forbidden_docs"]) & set(got)),
                "matrix_disclosures": self.disclosures(q["user"], got),
                "note": run.note,
            }
            if rel:
                row |= {
                    "recall@5": m.recall_at(got, rel, 5),
                    "recall@10": m.recall_at(got, rel, 10),
                    "precision@5": m.precision_at(got, rel, 5),
                    "rr": m.reciprocal_rank(got, rel),
                    "ndcg@10": m.ndcg_at(got, rel, 10),
                }
            per.append(row)
        ans = [r for r in per if r["expected_docs"]]
        lvl = [r for r in per if r["expected_level"] != "—"]
        no_ans = [r for r in per if r["answer_status"] != "answered"]
        summary = {
            "answerable_questions": len(ans),
            "recall@5": m.mean([r["recall@5"] for r in ans]),
            "recall@10": m.mean([r["recall@10"] for r in ans]),
            "precision@5": m.mean([r["precision@5"] for r in ans]),
            "mrr": m.mean([r["rr"] for r in ans]),
            "ndcg@10": m.mean([r["ndcg@10"] for r in ans]),
            "full_recall_questions": sum(r["recall@10"] == 1.0 for r in ans),
            "ladder_level_accuracy": m.mean(
                [float(r["level"] == r["expected_level"]) for r in lvl]
            ),
            "ladder_level_questions": len(lvl),
            "no_answer_questions": len(no_ans),
            "no_answer_with_forbidden_docs": sum(bool(r["forbidden_hits"]) for r in no_ans),
            "no_answer_retrieved_nothing": sum(not r["ranked"] for r in no_ans),
            "answer_status_accuracy": "not measurable yet — needs Gemini generation (GCP)",
        }
        return {"summary": summary, "questions": per}

    # ---- suite 2 · conflicts (pre-send, touchpoint 11) -------------------------------------------

    def conflict(self) -> dict[str, Any]:
        cfg = self.slots["presend"]
        tally = {t: {"tp": 0, "fp": 0, "fn": 0} for t in ALL_TYPES}
        runs: list[dict[str, Any]] = []
        for did, user in {**cfg["drafts"], **cfg["clean_controls"]}.items():
            rep = self.presend(did, user)
            want = {c["type"] for c in self.conflicts if c["in"] == did}
            got = {f.type.value for f in rep.flags}
            for t in ALL_TYPES:
                tally[t]["tp"] += int(t in want and t in got)
                tally[t]["fp"] += int(t not in want and t in got)
                tally[t]["fn"] += int(t in want and t not in got)
            evid_ok = {}
            for f in rep.flags:
                exp = {
                    e
                    for c in self.conflicts
                    if c["in"] == did and c["type"] == f.type.value
                    for e in c["evidence"]
                }
                cited = {self.s.doc_of.get(e, e) for e in f.evidence_ids}
                if exp:
                    evid_ok[f.type.value] = bool(cited & exp)
            runs.append(
                {
                    "draft": did,
                    "user": user,
                    "control": did in cfg["clean_controls"],
                    "outcome": rep.outcome.value,
                    "expected_types": sorted(want),
                    "flagged_types": sorted(got),
                    "missed": sorted(want - got),
                    "false_flags": sorted(got - want),
                    "uncertain_flags": sorted({f.type.value for f in rep.flags if not f.certain}),
                    "awaiting_review": [self.s.doc_of.get(c, c) for c in rep.awaiting_review],
                    "evidence_matches_answer_key": evid_ok,
                    "status_unconfirmed": [self.s.doc_of.get(c, c) for c in rep.status_unconfirmed],
                    "fact_gaps": list(rep.fact_gaps),
                    "type_c_rules_verified": rep.authority.rules_verified
                    if rep.authority
                    else None,
                }
            )
        per_type = {
            t: {**tally[t], **m.prf(**tally[t]), "implemented": t in IMPLEMENTED_TYPES}
            | ({} if t in IMPLEMENTED_TYPES else {"status": NOT_YET})
            for t in ALL_TYPES
        }
        det = {k: sum(tally[t][k] for t in IMPLEMENTED_TYPES) for k in ("tp", "fp", "fn")}
        controls = [r for r in runs if r["control"]]
        return {
            "summary": {
                "deterministic_A_C_E_F": {**det, **m.prf(**det)},
                "clean_control_false_flags": sum(len(r["flagged_types"]) for r in controls),
                "clean_controls_reported_clear": sum(r["outcome"] == "clear" for r in controls),
                "note": "with the mock rule file (ADR-0010) no control can be 'clear' — "
                "'review_needed' is the correct outcome",
            },
            "per_type": per_type,
            "runs": runs,
        }

    # ---- suite 3 · leakage matrix (pass bar: zero) -------------------------------------------

    def leakage(self) -> dict[str, Any]:
        paths: dict[str, dict[str, int]] = {}
        found: list[dict[str, Any]] = []

        def record(path: str, user: str, what: str, docs: Iterable[str]) -> None:
            bad = self.disclosures(user, docs)
            p = paths.setdefault(path, {"checks": 0, "disclosures": 0})
            p["checks"] += 1
            p["disclosures"] += len(bad)
            if bad:
                found.append({"path": path, "user": user, "case": what, "docs": bad})

        specs = {
            qid: (self.slots["questions"][qid], q["question"]) for qid, q in self.golden.items()
        }
        for tid, spec in self.slots["touchpoints"].items():
            specs[tid] = (spec, spec["slots"].get("text", ""))
        cids = sorted(self.s.doc_of)
        for user in USER_IDS:
            for qid, (spec, question) in specs.items():
                run = self.run_spec(spec, question, user)
                record("question → retrieved set", user, qid, run.ranked)
                record("question → evidence package", user, qid, self.package_ids(user, run))
                if run.presend:
                    record(
                        "file check → pre-send evidence", user, qid, self._presend_docs(run.presend)
                    )
            for cid in cids:  # exact ID (L0) and graph expansion (L3) from every document
                res = self.ladder(
                    LadderRequest(
                        user_id=user,
                        canonical_ids=(cid,),
                        relations=RELATED,
                        direction=Direction.BOTH,
                    )
                )
                record("exact ID + graph", user, self.s.doc_of[cid], self.ranked(res))
                subj = next((d.subject for d in self.s.documents() if d.canonical_id == cid), "")
                if subj:
                    res = self.ladder(LadderRequest(user_id=user, text_query=subj))
                    record("keyword (L2) by subject", user, self.s.doc_of[cid], self.ranked(res))
            res = self.ladder(LadderRequest(user_id=user, criteria=L1Criteria()))
            record("count / list-all (L1)", user, "all", self.ranked(res))
            for did, raw in self.raw_ref.items():  # existence: reference lookup
                look = lookup_reference(
                    user,
                    raw,
                    departments=self.s.departments,
                    retriever=self.s.stores.index,
                    store=self.store(),
                    policy=POLICY,
                    classification=CLASSES,
                )
                ids = [look.canonical_id] if look.canonical_id else []
                ids += list(look.choices)
                record(
                    "reference lookup (existence)",
                    user,
                    did,
                    [self.s.doc_of.get(i, i) for i in ids if i in self.s.doc_of],
                )
            for did in self.slots["presend"]["drafts"]:
                if MATRIX.get((did, user)):
                    rep = self.presend(did, user)
                    record("pre-send report", user, did, self._presend_docs(rep))
        total = sum(p["disclosures"] for p in paths.values())
        return {
            "summary": {
                "checks": sum(p["checks"] for p in paths.values()),
                "disclosures": total,
                "pass": total == 0,
            },
            "paths": paths,
            "disclosures": found,
        }

    def _presend_docs(self, rep: PreSendReport) -> list[str]:
        """Every document a pre-send report names: flag evidence, status list, and any canonical
        ID or e-File number of an indexed document mentioned in the explanations."""
        ids = {e for f in rep.flags for e in f.evidence_ids} | set(rep.status_unconfirmed)
        text = " ".join(f.explanation for f in rep.flags)
        for cid in self.s.doc_of:
            tags = self.s.tags(cid)
            if cid in text or (tags and tags.file_no and tags.file_no in text):
                ids.add(cid)
        return [self.s.doc_of.get(i, i) for i in ids if i in self.s.doc_of]

    # ---- suite 4 · touchpoint scenarios -----------------------------------------------------

    def _tool_ctx(self, user: str, as_of: str) -> ToolContext:
        return ToolContext(
            user_id=user,
            as_of=dt.date.fromisoformat(as_of),
            index=self.s.stores.index,
            l2=self.s.l2,
            graph=self.s.stores.graph,
            cfg=self.s.cfg,
            store=self.store(),
            policy=POLICY,
            classification=CLASSES,
            hierarchy=load_hierarchy(ONTOLOGY / "hierarchy.yaml"),
            instruments=self.s.stores.instruments,
            relations=tuple(self.s.stores.relations),
        )

    def _brief(self, sc: dict[str, Any], c_rows: dict[str, Any]) -> dict[str, Any]:
        """TP13: the brief names the expected documents and the deterministic flags of the draft.
        Documents that are evidence ONLY for types not built yet (B, D, G — Gemini) are reported,
        not required."""
        user, exp = sc["user"], sc["expected"]
        f = next(
            x for x in _load_seed()["files"] if x["computer_no"] == sc["context"]["computer_no"]
        )
        docs = self.s.documents()
        b = approval_brief(
            ctx=self._tool_ctx(user, sc["as_of"]),
            file_no=f["file_no"],
            subject=f["subject"],
            movement=(),
            documents=docs,
            text_of=lambda c: self.s.text_of.get(c, ""),
            tags_of={d.canonical_id: d.tags for d in docs},
            rules=self.rules,
            windows=[w for ws in self.s.stores.windows.values() for w in ws],
            departments=self.s.departments,
            awaiting_review=tuple(self.s.stores.awaiting.values()),
        )

        def did(c: str) -> str:
            return self.s.doc_of.get(c.split("#")[0], c)

        named = {did(b.draft_id)} if b.draft_id else set()
        for g in b.governing:
            named.add(did(g.cited))
            if g.status and g.status.by:
                named.add(did(g.status.by))
        if b.presend:
            named |= {did(e) for fl in b.presend.flags for e in fl.evidence_ids}
        named |= {did(d.canonical_id) for p in b.precedents for d in p.documents}
        draft = did(b.draft_id) if b.draft_id else ""
        later_only = {
            e
            for c in self.conflicts
            if c["in"] == draft and c["type"] not in IMPLEMENTED_TYPES
            for e in c["evidence"]
        } - {
            e
            for c in self.conflicts
            if c["in"] == draft and c["type"] in IMPLEMENTED_TYPES
            for e in c["evidence"]
        }
        want = set(exp["docs"])
        required = want - later_only
        flags = {fl.type.value for fl in b.presend.flags} if b.presend else set()
        det = {c["type"] for c in self.conflicts if c["in"] == draft} & set(IMPLEMENTED_TYPES)
        return {
            "run": True,
            "pass": required <= named and not set(exp["forbidden_docs"]) & named and det <= flags,
            "missing_required": sorted(required - named),
            "waiting_for_gemini": sorted((want - named) & later_only),
            "flags": sorted(flags),
        }

    def _received_letter(self, sc: dict[str, Any]) -> dict[str, Any]:
        """TP04 replay: the scenario's held-back records, then the order arrives. The notice must
        list exactly the expected open files for the officer and none of the forbidden ones."""
        user, exp, setup = sc["user"], sc["expected"], sc["setup"]
        seed = _load_seed()
        rec = next(r for r in seed["receipts"] if r["computer_no"] == setup["event"]["receipt"])
        name = Path(rec["source_uri"]).name
        did = next(r["id"] for r in rows("documents_index.csv") if Path(r["file"]).name == name)
        open_files = frozenset(f["file_no"] for f in seed["files"] if f["state"] == "open")
        replay = build_stack(
            self.s.cfg,
            holdback=frozenset(setup["holdback"]),
            open_files=open_files,
            arrivals=(did,),
            transcribe=self.s.transcribe,
            ocr_version=self.s.ocr_version,
        )
        res = replay.arrived.get(did)
        mine = notices_for(
            user,
            list(res.notices) if res else [],
            store=self.store(),
            policy=POLICY,
            classification=CLASSES,
        )
        cno_of = {f["file_no"]: f["computer_no"] for f in seed["files"]}
        files = {cno_of.get(a.file_no, a.file_no) for n in mine for a in n.affected}
        changed = {(n.change.value, replay.doc_of.get(n.changed_doc, n.changed_doc)) for n in mine}
        want_flags = {("SUPERSEDES", f["cited"]) for f in exp["flags"] if f["type"] == "A"}
        as_of = dt.date.fromisoformat(sc["as_of"])
        flipped = all(
            status_as_of(
                replay.cid_of[c], as_of, replay.stores.instruments, replay.stores.relations
            ).status.value
            == "superseded"
            for _, c in want_flags
            if c in replay.cid_of
        )
        return {
            "run": True,
            "pass": files == set(exp["files"])
            and not files & set(exp["forbidden_files"])
            and want_flags <= changed
            and flipped,
            "files": sorted(files),
            "changes": sorted(changed),
        }

    def _receipt(self, sc: dict[str, Any]) -> dict[str, Any]:
        """TP02 (summary + validity flags) and TP03 (put in a file), as of the scenario's date."""
        user, exp = sc["user"], sc["expected"]
        seed = _load_seed()
        rec = next(r for r in seed["receipts"] if r["computer_no"] == sc["context"]["receipt"])
        dept = next(
            f["department"] for f in seed["files"] if f["dealing_section"] == rec["dealing_section"]
        )
        rctx = ReceiptContext(
            computer_no=rec["computer_no"],
            receipt_no=rec["receipt_no"],
            diary_date=dt.date.fromisoformat(rec["diary_date"]),
            sender=rec["sender"],
            letter_ref=rec["letter_ref"],
            letter_date=dt.date.fromisoformat(rec["letter_date"]) if rec["letter_date"] else None,
            main_category=rec["main_category"],
            subject=rec["subject"],
            department=dept,
            dealing_section=rec["dealing_section"],
        )
        rv = review_receipt(
            rctx,
            user_id=user,
            as_of=dt.date.fromisoformat(sc["as_of"]),
            departments=self.s.departments,
            index=self.s.stores.index,
            documents=self.s.documents,
            graph=self.s.stores.graph,
            instruments=self.s.stores.instruments,
            relations=list(self.s.stores.relations),
            text_of=lambda c: self.s.text_of.get(c, ""),
            store=self.store(),
            policy=POLICY,
            classification=CLASSES,
        )

        def did(c: str) -> str:
            return self.s.doc_of.get(c, c)

        got_docs = {did(rv.document.canonical_id)} if rv.document else set()
        got_docs |= {did(c) for c in rv.cited}
        got_flags = sorted((f.type.value, did(f.cited)) for f in rv.flags)
        want_flags = sorted(
            (f["type"], f["cited"]) for f in exp["flags"] if isinstance(exp["flags"], list)
        )
        want, forbid = set(exp["docs"]), set(exp["forbidden_docs"])
        ok = want <= got_docs and not forbid & got_docs and got_flags == want_flags
        if sc["touchpoint"] == 3:  # never force a match; the answer key's file is related only
            cno_of = {f["file_no"]: f["computer_no"] for f in seed["files"]}
            related = {cno_of.get(f, f) for f in rv.related_files}
            put_in = {cno_of.get(f, f) for f in rv.put_in}
            named = set(re.findall(r"File (\d{7})", exp["answer_key"]))
            ok = ok and rv.suggestion == "new_file" and not put_in and named <= related
        return {
            "run": True,
            "pass": ok,
            "docs": sorted(got_docs),
            "flags": got_flags,
            "expected_flags": want_flags,
            "suggestion": rv.suggestion,
        }

    def _link_file(self, sc: dict[str, Any]) -> dict[str, Any]:
        """TP09: precedent files to link, within the officer's scope, never the open file."""
        user, exp = sc["user"], sc["expected"]
        seed_files = _load_seed()["files"]
        cno_of = {f["file_no"]: f["computer_no"] for f in seed_files}
        open_f = next(f for f in seed_files if f["computer_no"] == sc["context"]["computer_no"])
        ctx = ToolContext(
            user_id=user,
            as_of=dt.date.fromisoformat(sc["as_of"]),
            index=self.s.stores.index,
            l2=self.s.l2,
            graph=self.s.stores.graph,
            cfg=self.s.cfg,
            store=self.store(),
            policy=POLICY,
            classification=CLASSES,
            hierarchy=load_hierarchy(ONTOLOGY / "hierarchy.yaml"),
            instruments=self.s.stores.instruments,
            relations=tuple(self.s.stores.relations),
        )

        def file_of(cid: str) -> str | None:
            t = self.s.tags(cid)
            return t.file_no if t else None

        links = suggest_links(ctx, open_f["subject"], open_f["file_no"], file_of)
        got_files = {cno_of.get(s.file_no, s.file_no) for s in links}
        got_docs = {
            self.s.doc_of.get(d.canonical_id, d.canonical_id) for s in links for d in s.documents
        }
        want_f, forbid_f = set(exp["files"]), set(exp["forbidden_files"])
        want_d, forbid_d = set(exp["docs"]), set(exp["forbidden_docs"])
        return {
            "run": True,
            "pass": want_f <= got_files
            and not forbid_f & got_files
            and want_d <= got_docs
            and not forbid_d & got_docs,
            "expected_files": sorted(want_f),
            "files": sorted(got_files),
            "docs": sorted(got_docs),
        }

    def _file_so_far(self, sc: dict[str, Any]) -> dict[str, Any]:
        """TP08: note chain from the file's note documents the officer may see."""
        user, exp = sc["user"], sc["expected"]
        cno = sc["context"]["computer_no"]
        file_no = next(
            (f["file_no"] for f in _load_seed()["files"] if f["computer_no"] == cno), None
        )
        docs = [
            (cid, self.s.text_of.get(cid, ""))
            for cid, _ in self.s.stores.files.get(file_no or "", [])
            if self.visible(user, cid)
            and (d := next((x for x in self.s.documents() if x.canonical_id == cid), None))
            and d.doc_type.startswith("Noting")
        ]
        fs = file_so_far(docs)
        # gaps the answer key says must be named ("Notes #4–#5 are not available")
        want_gaps = tuple(
            (int(a), int(b or a))
            for a, b in re.findall(
                r"Notes? #(\d+)(?:[–-]#(\d+))? (?:is|are) not available", exp["answer_key"]
            )
        )
        got = {self.s.doc_of.get(c, c) for c in fs.sources}
        want, forbid = set(exp["docs"]), set(exp["forbidden_docs"])
        return {
            "run": True,
            "pass": want <= got and not forbid & got and fs.gaps == want_gaps,
            "expected_gaps": [list(g) for g in want_gaps],
            "expected_docs": sorted(want),
            "sources": sorted(got),
            "gaps": [list(g) for g in fs.gaps],
            "last_direction": fs.last_direction.note_no if fs.last_direction else None,
        }

    def _note_reference(self, sc: dict[str, Any]) -> dict[str, Any]:
        """TP07: reference to a previous note paragraph of the same file. The seed stands in for the
        connector's note/page metadata; the officer's request comes from slots_v1."""
        user, exp = sc["user"], sc["expected"]
        cno = sc["context"]["computer_no"]
        seed = _load_seed()
        f = next(x for x in seed["files"] if x["computer_no"] == cno)
        ctx = FileContext(
            computer_no=cno,
            file_no=f["file_no"],
            subject=f["subject"],
            department=f["department"],
            dealing_section=f["dealing_section"],
            classification=f["classification"],
            movement_trail=(),
            notes=tuple(
                NoteRef(
                    note_id=n["note_id"],
                    note_no=n["note_no"],
                    paragraph_from=n["paragraph_from"],
                    confirmed=n["state"] == "green",
                )
                for n in seed["notes"]
                if n["computer_no"] == cno
            ),
            pages=tuple(
                PageRef(
                    correspondence_id=c["correspondence_id"],
                    page_from=c["page_from"],
                    page_to=c["page_to"],
                    title=c["title"],
                    canonical_id=c.get("canonical_id"),
                )
                for c in seed["correspondence"]
                if c["computer_no"] == cno
            ),
        )
        store = self.store()

        def allowed(cid: str) -> bool:
            t = self.s.tags(cid)
            return t is not None and check(user, t, store, POLICY, CLASSES).allowed

        docs = [
            (cid, self.s.text_of.get(cid, ""), t)
            for cid, _ in self.s.stores.files.get(f["file_no"], [])
            if (t := self.s.tags(cid)) is not None
            and (d := next((x for x in self.s.documents() if x.canonical_id == cid), None))
            and d.doc_type.startswith("Noting")
        ]
        res = suggest_references(
            self.slots["reference_requests"][sc["id"]]["text"],
            ctx,
            docs,
            as_of=dt.date.fromisoformat(sc["as_of"]),
            allowed=lambda t: check(user, t, store, POLICY, CLASSES).allowed,
            order_visible=allowed,
            cfg=ReferenceConfig.model_validate(
                {k: v for k, v in self.slots["reference_config"].items() if not k.startswith("_")}
            ),
        )
        want = exp["citation"]
        top = res.suggestions[0] if res.suggestions else None
        named = {self.s.doc_of.get(sg.source or "", sg.source) for sg in res.suggestions}
        named.discard(None)
        disclosed = sorted(d for d in named if d and not MATRIX.get((d, user), False))
        ok_target = (
            top is not None
            and top.kind.value == want["target"]
            and top.target_id == want["note_id"]
            and top.paragraph == want["paragraph"]
        )
        return {
            "run": True,
            "pass": ok_target
            and set(exp["docs"]) <= named
            and not set(exp["forbidden_docs"]) & named
            and not disclosed,
            "expected": want,
            "got": top.model_dump(mode="json", exclude={"text"}) if top else None,
            "matched_by": res.matched_by.value,
            "sources": sorted(d for d in named if d),
            "matrix_disclosures": disclosed,
        }

    def _local_reference(self, sc: dict[str, Any]) -> dict[str, Any]:
        """TP10: the officer adds an order + paragraph as a local reference. Scored on what the
        status-coverage rule (owner, 3 Nov 2026) allows: supersession by a visible order, its date,
        both paragraphs. When the scenario expects a `current_version` the rule withholds, the row
        says so (`current_version_withheld`) — the expected value itself is not changed."""
        user, exp = sc["user"], sc["expected"]
        text = self.slots["local_references"][sc["id"]]["text"]
        look = lookup_reference(
            user,
            text,
            departments=self.s.departments,
            retriever=self.s.stores.index,
            store=self.store(),
            policy=POLICY,
            classification=CLASSES,
        )
        if look.status is not LookupStatus.FOUND or look.canonical_id is None:
            return {"run": True, "pass": False, "why": f"lookup {look.status.value}"}
        ctx = self._tool_ctx(user, sc["as_of"])
        res = call_tool(
            ctx, ToolName.CHECK_DOCUMENT_STATUS, {"canonical_ids": (look.canonical_id,)}
        )
        loc = local_reference(text, look.canonical_id, res, lambda c: self.s.text_of.get(c, ""))
        named = {
            self.s.doc_of.get(c, c)
            for c in (look.canonical_id, res.by, res.current_version)
            if c is not None
        }
        disclosed = sorted(d for d in named if not MATRIX.get((d, user), False))
        a_flags = [f for f in exp["flags"] if f["type"] == "A"]
        since_ok = all(
            res.since is not None and res.since.strftime("%d-%m-%Y") in f["detail"] for f in a_flags
        )
        a_ok = not a_flags or (res.status == "superseded" and res.by is not None)
        clause_ok = (
            loc.successor_clause is not None and loc.successor_clause.clause_id == exp["clause"]
        )
        withheld = exp.get("current_version") is not None and res.current_version is None
        current_ok = withheld or res.current_version == exp.get("current_version")
        return {
            "run": True,
            "pass": set(exp["docs"]) <= named
            and not set(exp["forbidden_docs"]) & named
            and not disclosed
            and a_ok
            and since_ok
            and clause_ok
            and current_ok,
            "status": res.status,
            "by": self.s.doc_of.get(res.by or "", res.by),
            "since": res.since.isoformat() if res.since else None,
            "cited_clause": loc.cited_clause.clause_id if loc.cited_clause else None,
            "successor_clause": loc.successor_clause.clause_id if loc.successor_clause else None,
            "current_version_withheld": withheld,
            "note": "current version not claimed (status-coverage rule; owner, 3 Nov 2026)"
            if withheld
            else "",
            "matrix_disclosures": disclosed,
        }

    # TP06 answer key: "approvals 2022 and 2025 inside relaxation windows, rejection 2023 under
    # the ban" — the year of each precedent decision and whether it fell inside a window.
    TP06_WINDOWS = {2022: True, 2023: False, 2025: True}

    def _first_cut(self, sc: dict[str, Any], c_rows: dict[str, Any]) -> dict[str, Any]:
        """TP06: cited points for a Yellow Note — orders that apply, their paragraphs, earlier
        decisions against the windows, open flags. The note's prose is Gemini's (not scored)."""
        user, exp = sc["user"], sc["expected"]
        f = next(
            x for x in _load_seed()["files"] if x["computer_no"] == sc["context"]["computer_no"]
        )
        did = self._draft_in_file(f["file_no"], user)
        if did is None:
            return {"run": True, "pass": False, "why": "no note in the file for this officer"}
        cid = self.s.cid_of[did]
        text, meta = self._note(cid)
        facts = extract_proposal_facts(text, meta, self.rules, cid)
        ctx = self._tool_ctx(user, sc["as_of"])

        def file_of(c: str) -> str | None:
            t = self.s.tags(c)
            return t.file_no if t else None

        links = suggest_links(ctx, f["subject"], f["file_no"], file_of)
        cut = first_cut_note(
            ctx=ctx,
            file_no=f["file_no"],
            subject=f["subject"],
            draft_note=cid,
            meta=meta,
            action=facts.facts.action if facts.facts else None,
            flags=self.presend(did, user).flags,
            precedents=[(lk.file_no, d.canonical_id) for lk in links for d in lk.documents],
            text_of=lambda c: self.s.text_of.get(c, ""),
            windows=[
                w
                for ws in self.s.stores.windows.values()
                for w in ws
                if self.visible(user, w.source.split("#", 1)[0])
            ],
        )
        named = {self.s.doc_of.get(c.split("#", 1)[0], c) for c in cut.citations}
        disclosed = sorted(d for d in named if not MATRIX.get((d, user), False))
        ref = c_rows.get(did)
        want_flags = set(ref["expected_types"]) & set(IMPLEMENTED_TYPES) if ref else set()
        got_flags = {x.type.value for x in cut.flags}
        uncited = [
            ln
            for ln in cut.body.splitlines()
            if ln.startswith("- ") and "\u201c" in ln and not re.search(r"\[AP-[^\]]+\]", ln)
        ]
        windows_ok = all(
            p.decided_on is not None
            and self.TP06_WINDOWS.get(p.decided_on.year) in (None, p.in_window)
            for p in cut.precedents
        ) and {p.decided_on.year for p in cut.precedents if p.decided_on} >= set(self.TP06_WINDOWS)
        # "Governing rule is 31/2025 (not 88/2022)": a superseded order must not be among the orders
        # that apply; it may still be cited as the source of a past window a precedent fell in.
        superseded_cited = {self.s.doc_of.get(c, c) for o in cut.orders for c in o.in_place_of}
        governing = {self.s.doc_of.get(o.canonical_id, o.canonical_id) for o in cut.orders}
        return {
            "run": True,
            "pass": set(exp["docs"]) <= named
            and not set(exp["forbidden_docs"]) & named
            and not disclosed
            and not superseded_cited & governing
            and want_flags <= got_flags
            and not uncited
            and windows_ok,
            "cited_docs": sorted(named),
            "points": [p.clause_id for p in cut.points],
            "precedents": [
                (self.s.doc_of.get(p.source, p.source), str(p.decided_on), p.in_window)
                for p in cut.precedents
            ],
            "flags": sorted(got_flags),
            "uncited_lines": uncited,
            "matrix_disclosures": disclosed,
        }

    def _dfa(self, sc: dict[str, Any], c_rows: dict[str, Any]) -> dict[str, Any]:
        """TP14: the deterministic parts of the DFA — "Read the following" (expected orders listed,
        superseded / unresolvable ones not), the pre-send flags travelling with it. Order
        paragraphs are Gemini's (not scored)."""
        user, exp = sc["user"], sc["expected"]
        f = next(
            x for x in _load_seed()["files"] if x["computer_no"] == sc["context"]["computer_no"]
        )
        did = self._draft_in_file(f["file_no"], user)
        if did is None:
            return {"run": True, "pass": False, "why": "no note in the file for this officer"}
        cid = self.s.cid_of[did]
        text, meta = self._note(cid)
        facts = extract_proposal_facts(text, meta, self.rules, cid)
        rep = self.presend(did, user)
        pv = draft_for_approval(
            ctx=self._tool_ctx(user, sc["as_of"]),
            file_no=f["file_no"],
            subject=f["subject"],
            draft_note=cid,
            meta=meta,
            action=facts.facts.action if facts.facts else None,
            flags=rep.flags,
            awaiting_review=tuple(self.s.stores.awaiting.values()),
        )
        listed = {self.s.doc_of.get(i.canonical_id, i.canonical_id) for i in pv.read_list}
        disclosed = sorted(d for d in listed if not MATRIX.get((d, user), False))
        # orders the answer key says must NOT be read: the superseded and the unresolvable ones
        not_read = {self.s.doc_of.get(x.cited, x.cited) for x in pv.left_out} | {
            self.s.doc_of.get(p, p) for i in pv.read_list for p in i.in_place_of
        }
        flags_str = exp.get("flags")
        tp11 = re.search(r"in=(D\d+)", flags_str) if isinstance(flags_str, str) else None
        ref = c_rows.get(tp11.group(1)) if tp11 else c_rows.get(did)
        want_flags = set(ref["expected_types"]) & set(IMPLEMENTED_TYPES) if ref else set()
        got_flags = {x.type.value for x in pv.flags}
        return {
            "run": True,
            "pass": set(exp["docs"]) <= listed
            and not set(exp["forbidden_docs"]) & listed
            and not disclosed
            and not not_read & listed
            and want_flags <= got_flags
            and bool(pv.body),
            "read_list": sorted(listed),
            "not_read": sorted(not_read),
            "flags": sorted(got_flags),
            "expected_flags": sorted(want_flags),
            "matrix_disclosures": disclosed,
        }

    def touchpoints(self, retrieval: dict[str, Any], conflict: dict[str, Any]) -> dict[str, Any]:
        q_rows = {r["id"]: r for r in retrieval["questions"]}
        c_rows = {r["draft"]: r for r in conflict["runs"]}
        out = []
        for sc in self.scenarios:
            sid, exp = sc["id"], sc["expected"]
            row: dict[str, Any] = {
                "id": sid,
                "touchpoint": sc["touchpoint_name"],
                "user": sc["user"],
            }
            flags = exp.get("flags")
            if sid.startswith("TP11") and isinstance(flags, str):
                did = re.search(r"in=(D\d+)", flags)
                c = c_rows.get(did.group(1)) if did else None
                if c is None:
                    row |= {"run": False, "why": "draft not in the pre-send suite"}
                else:
                    det = sorted(set(c["expected_types"]) & set(IMPLEMENTED_TYPES))
                    row |= {
                        "run": True,
                        "pass": c["user"] == sc["user"] and set(det) <= set(c["flagged_types"]),
                        "deterministic_expected": det,
                        "flagged": c["flagged_types"],
                        "outcome": c["outcome"],
                    }
            elif sid in self.slots["touchpoints"]:
                spec = self.slots["touchpoints"][sid]
                run = self.run_spec(spec, spec["slots"]["text"], sc["user"])
                want, forbid = set(exp["docs"]), set(exp["forbidden_docs"])
                row |= {
                    "run": True,
                    "pass": want <= set(run.ranked) and not forbid & set(run.ranked),
                    "expected_docs": sorted(want),
                    "ranked": run.ranked,
                    "level": ladder_label(run.result) if run.result else "—",
                    "expected_level": exp.get("ladder_level"),
                    "files_checked": False,
                }
            elif sc["touchpoint"] == 6:
                row |= self._first_cut(sc, c_rows)
            elif sc["touchpoint"] == 14:
                row |= self._dfa(sc, c_rows)
            elif sc["touchpoint"] == 10:
                row |= self._local_reference(sc)
            elif sc["touchpoint"] == 7:
                row |= self._note_reference(sc)
            elif sc["touchpoint"] == 8:
                row |= self._file_so_far(sc)
            elif sc["touchpoint"] == 9:
                row |= self._link_file(sc)
            elif sc["touchpoint"] in (2, 3):
                row |= self._receipt(sc)
            elif sc["touchpoint"] == 4:
                row |= self._received_letter(sc)
            elif sc["touchpoint"] == 13:
                row |= self._brief(sc, c_rows)
            elif sid == "TP20":
                pairs = [qid for group in exp["pairs"] for qid in group]
                rows_ = [q_rows[q] for q in pairs]
                row |= {
                    "run": True,
                    "pass": all(
                        not r["forbidden_hits"] and not r["matrix_disclosures"] for r in rows_
                    ),
                    "questions": pairs,
                    "criterion": "no forbidden or matrix-disallowed document for any officer",
                }
            elif sc["touchpoint"] in EXTENDED:  # end to end through the sandbox (ADR-0038)
                row |= run_extended(sc)
            else:
                row |= {"run": False, "why": "needs the sandbox screen flow (P8)"}
            out.append(row)
        ran = [r for r in out if r["run"]]
        return {
            "summary": {
                "scenarios": len(out),
                "run": len(ran),
                "passed": sum(bool(r["pass"]) for r in ran),
            },
            "scenarios": out,
        }
