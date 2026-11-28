"""Review sheet for the unconfirmed SUPERSEDES links in the graph (ADR-0058 era; CLAUDE.md §6, §8).

Run in Cloud Shell (read-only: one Spanner query, one BigQuery query, no writes):
    python3 evaluation/review_supersession_candidates.py > supersession_review.csv

For every candidate link "newer SUPERSEDES older" it looks in the newer order's indexed text for a
sentence naming the older order (number and year) AND replacement wording. The verdict is only a
HINT to help a person decide; nothing here confirms or rejects a link, and nothing is written back.
  stated   - a sentence names the older order and uses replacement wording
  mention  - the older order is named, but no replacement wording is in that sentence
  none     - the older order is not named in the newer order's text
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys

PROJECT, INSTANCE, DATABASE, DATASET = (
    "use-case-24-project",
    "c2-spanner",
    "c2graph",
    "c2_metadata",
)
REPLACES = re.compile(
    r"supersed|in\s+supersession|cancel|rescind|withdraw|repeal|stands?\s+(?:modified|replaced)|"
    r"in\s+(?:partial\s+)?modification|hereby\s+(?:amended|modified)|in\s+place\s+of",
    re.IGNORECASE,
)
CID = re.compile(r"^AP-[A-Z0-9]+-(?P<type>[A-Z]+)-(?P<no>\d+)-(?P<year>\d{4})$")


def sentences(text: str) -> list[str]:
    return [
        s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z(])|\n{2,}", text) if s.strip()
    ]


def names(sentence: str, no: str, year: str) -> bool:
    """The sentence refers to an order numbered `no` of `year` (a G.O.-style number, not any digit)."""
    return bool(
        re.search(rf"(?<![\d/]){int(no)}(?!\d)", sentence.replace(",", ""))
        and year in sentence
        and re.search(r"G\.?\s?O|order|circular|memo", sentence, re.IGNORECASE)
    )


def classify(text: str, target_id: str) -> tuple[str, str]:
    m = CID.match(target_id)
    if not m:
        return "none", ""
    hits = [s for s in sentences(text) if names(s, m["no"], m["year"])]
    for s in hits:
        if REPLACES.search(s):
            return "stated", s[:400]
    return ("mention", hits[0][:400]) if hits else ("none", "")


def gcloud_rows(sql: str) -> list[list]:
    out = subprocess.run(
        [
            "gcloud",
            "spanner",
            "databases",
            "execute-sql",
            DATABASE,
            f"--instance={INSTANCE}",
            f"--sql={sql}",
            "--format=json",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)["rows"]


def passages(ids: list[str]) -> dict[str, str]:
    quoted = ",".join(f"'{i}'" for i in ids)
    sql = (
        f"SELECT canonical_id, STRING_AGG(text, '\\n' ORDER BY passage_no) AS t "
        f"FROM `{PROJECT}.{DATASET}.passages` WHERE canonical_id IN ({quoted}) GROUP BY canonical_id"
    )
    out = subprocess.run(
        [
            "bq",
            "query",
            "--use_legacy_sql=false",
            "--format=json",
            "--max_rows=100000",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {r["canonical_id"]: r["t"] for r in json.loads(out)}


def main() -> None:
    edges = gcloud_rows(
        "SELECT source, target FROM graph_edges WHERE kind='SUPERSEDES' AND confirmed=false "
        "ORDER BY source, target"
    )
    text = passages(sorted({s for s, _ in edges}))
    w = csv.writer(sys.stdout)
    w.writerow(
        [
            "newer_order",
            "older_order",
            "hint",
            "sentence_in_newer_order",
            "decision",
            "reviewer",
            "date",
        ]
    )
    tally: dict[str, int] = {}
    for s, t in edges:
        hint, sent = classify(text.get(s, ""), t)
        tally[hint] = tally.get(hint, 0) + 1
        w.writerow([s, t, hint if s in text else "no_text", sent, "", "", ""])
    print(f"# {len(edges)} candidate links: {tally}", file=sys.stderr)


if __name__ == "__main__":
    main()
