# Mock e-Office sandbox seed — SYNTHETIC

**Mock e-Office sandbox — not NIC e-Office · synthetic data.** Generated; do not edit by hand.

Rebuild / check from the repo root:

```
python3 data/synthetic/tools/build_eoffice_seed.py          # writes seed.json
python3 data/synthetic/tools/build_eoffice_seed.py --check  # fails if out of date (also a unit test)
```

| Object | Count | Built from |
|---|---|---|
| Sandbox profiles | 8 + 2 staff posts | `users.csv`; search scope by rank (plan §11.4); Assistant Section Officers appear in notes but have no login |
| e-Files | 13 | Urban Services e-files in `manifest.json` (File No., Computer No., section, classification, subject) |
| Notes (Green) | 36 | "Note # n … name / post / time" in the e-file documents; author mapped to a profile **by post** |
| Correspondence | 3 | e-files with no notes (standing order, V&E report, annexure) |
| Movements | 25 | file sent to the author of the next note number; none across gaps (notes #4–#5 of the Vigilance file are not in the corpus) |
| Receipts | 10 | Finance / GAD orders received in the Urban Services secretariat (touchpoint 4) |

Field shapes follow the **NIC eFile 7.0 User Manual (Ver.7.0)**: Computer No. + Receipt No. `sequence/year/dealing section`,
Electronic/Physical nature, Non-SFS file heads, Green/Yellow notes, movement history.

**Assumed** (listed in `seed.json` → `sources` and per receipt in `assumed_fields`): receipt diary date = order date,
receipt dealing section `ESTT.I`, receipt Computer Nos from 9100001, search scope by rank. Not crucial decisions:
mock only, to be replaced by real data.

**Not in the seed:** relations, citations, conflicts, decisions, golden answers (evaluation only). Scanned notes
(`text_source: needs_ocr`) carry no text: ingestion must OCR them. Not yet seeded: Yellow-note versions, drafts (DFA),
file links, Previous/Later References (no corpus source for them yet).
