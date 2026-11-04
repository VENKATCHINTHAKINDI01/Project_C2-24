"""Test fixtures: mock corpus v1 → access-store tuples + document tags. SYNTHETIC data only.

users.csv has no search-privilege column, so each profile gets the e-Office scope plan §11.4
describes: Deputy Secretary and above → Department scope; Section Officers / Assistant
Secretaries → Section scope.
"""

from __future__ import annotations

import csv

from app.auth.models import DocumentAccessTags, SearchScope
from app.auth.policy import load_access_policy
from app.auth.store import AccessTuple, InMemoryAuthzStore, Relation
from app.config import REPO_ROOT, Classification, load_classification

CORPUS = REPO_ROOT / "data" / "synthetic" / "mock_v1"
ONTOLOGY = REPO_ROOT / "data" / "ontology"
POLICY = load_access_policy(ONTOLOGY / "access_policy.yaml")
CLASSES: Classification = load_classification(ONTOLOGY / "classification.yaml")


def rows(name: str) -> list[dict[str, str]]:
    with (CORPUS / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def user_tuples() -> list[AccessTuple]:
    out: list[AccessTuple] = []
    for u in rows("users.csv"):
        s = f"user:{u['user_id']}"
        rank = int(u["role_rank"])
        scope = SearchScope.DEPARTMENT if rank >= 3 else SearchScope.SECTION
        out += [
            AccessTuple(
                subject=s, relation=Relation.MEMBER_OF, object=f"department:{u['department']}"
            ),
            AccessTuple(
                subject=s, relation=Relation.HAS_CLEARANCE, object=f"clearance:{u['clearance']}"
            ),
            AccessTuple(subject=s, relation=Relation.HAS_RANK, object=f"rank:{rank}"),
            AccessTuple(
                subject=s, relation=Relation.HAS_SEARCH_SCOPE, object=f"scope:{scope.value}"
            ),
        ]
        if u["section"] != "ALL":
            out.append(
                AccessTuple(
                    subject=s, relation=Relation.IN_SECTION, object=f"section:{u['section']}"
                )
            )
        out += [
            AccessTuple(subject=s, relation=Relation.ASSIGNED, object=f"file:{f}")
            for f in u["assigned_files"].split(";")
            if f
        ]
    return out


def new_store() -> InMemoryAuthzStore:
    return InMemoryAuthzStore(user_tuples())


def doc_tags() -> dict[str, DocumentAccessTags]:
    out = {}
    for d in rows("documents_index.csv"):
        ref = d["raw_reference"]
        out[d["id"]] = DocumentAccessTags(
            doc_id=d["id"],
            department=d["department"],
            section=d["section"],
            classification=d["classification"],
            file_no=ref.removeprefix("File No.") if ref.startswith("File No.") else None,
        )
    return out


USER_IDS = [u["user_id"] for u in rows("users.csv")]
MATRIX = {
    (row["doc_id"], uid): row[uid] == "ALLOW"
    for row in rows("access_matrix.csv")
    for uid in USER_IDS
}
