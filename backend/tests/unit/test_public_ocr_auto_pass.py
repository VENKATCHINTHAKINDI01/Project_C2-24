"""Sandbox v2 OCR auto-pass (owner decision 13 Nov 2026, ADR-0020): a real PUBLIC order whose
lowest OCR page confidence reaches the sandbox value is indexed without waiting for a reviewer and
is listed as auto-passed. Synthetic or classified scans, and anything below the value, still
wait."""

from __future__ import annotations

import datetime as dt

import pytest
import yaml

from app.agents.runtime import AssistRuntime
from app.config import REPO_ROOT, get_settings, load_classification
from app.connectors.eoffice import SourceArtefact
from app.ingestion.pipeline import IngestStatus
from app.retrieval.ladder import LadderConfig
from tests.unit.mock_access import CORPUS
from tests.unit.test_ingestion_pipeline import HIER, IDX
from tests.unit.test_ocr import FakeEngine

ONT = get_settings().ontology_dir
DATA = (CORPUS / IDX["D09"]["file"]).read_bytes()  # a synthetic scan of a public G.O.


def _art(uri: str, classification: str = "UNCLASSIFIED") -> SourceArtefact:
    return SourceArtefact(
        source_uri=uri,
        filename="order.pdf",
        department="GAD01",
        section="SER.A",
        classification=classification,
        data=DATA,
    )


def _build(art: SourceArtefact, conf: float, auto: float | None) -> AssistRuntime:
    return AssistRuntime.build(
        [art],
        ontology_dir=ONT,
        hierarchy=HIER,
        classification=load_classification(ONT / "classification.yaml"),
        cfg=LadderConfig(l2_top_k=5, l2_min_score=1.0, l3_max_hops=1),
        calibrated=False,
        as_of=dt.date(2025, 12, 31),
        received_at=dt.datetime(2025, 12, 31, 9, tzinfo=dt.UTC),
        ocr=FakeEngine(conf=conf),
        public_ocr_auto_pass=auto,
    )


def _status(run: AssistRuntime, uri: str) -> IngestStatus:
    return next(r.status for (u, _), r in run.stores.results.items() if u == uri)


def test_public_order_at_or_above_the_value_is_indexed_and_listed() -> None:
    run = _build(_art("public://x/order.pdf"), conf=0.85, auto=0.80)
    assert _status(run, "public://x/order.pdf") is IngestStatus.INDEXED
    assert run.auto_passed == {"public://x/order.pdf": 0.85}


@pytest.mark.parametrize(
    ("uri", "classification", "conf", "auto"),
    [
        ("public://x/order.pdf", "UNCLASSIFIED", 0.79, 0.80),  # below the value
        ("mock://x/order.pdf", "UNCLASSIFIED", 0.99, 0.80),  # synthetic scan
        ("public://x/order.pdf", "RESTRICTED", 0.99, 0.80),  # not public
        ("public://x/order.pdf", "UNCLASSIFIED", 0.99, None),  # switched off (v1)
    ],
)
def test_everything_else_still_waits_for_a_reviewer(
    uri: str, classification: str, conf: float, auto: float | None
) -> None:
    run = _build(_art(uri, classification), conf=conf, auto=auto)
    assert _status(run, uri) is IngestStatus.HELD
    assert run.auto_passed == {}


def test_the_sandbox_value_is_the_owners_and_only_for_v2() -> None:
    cfg = yaml.safe_load((REPO_ROOT / "backend" / "config" / "sandbox.yaml").read_text("utf-8"))
    assert cfg["ocr"]["public_auto_pass_min_confidence"] == 0.80
    assert cfg["calibrated"] is False
