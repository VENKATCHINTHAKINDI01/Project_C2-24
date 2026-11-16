# data_collection — public G.O. corpus tools (ADR-0006)

Collects **real, public** Andhra Pradesh G.O.s, gazettes and related records for C2-24, and generates the
**synthetic** e-Office files that sit on top of them. Moved here from the separate `c2-24-data-tools` workspace on
22 Oct 2026; behaviour unchanged (verified: identical reports on the same data).

- **Code** lives here. **Data does not**: the corpus (≈640 MB: PDFs, OCR text, metadata, links) stays in a data
  folder outside the repo, named in `local.env` (git-ignored). Nothing here is part of `backend/` checks.
- Public G.O.s are public records, not department data; they are still never committed (size, licence clarity).
  Synthetic e-files are labelled synthetic; every claim in them is quoted from a real order (CLAUDE.md §11.10).
- Current phase: **build → dry run → test on 1–2 files**. Full runs need an explicit flag (`FULL=1`, `--limit 0`).

## Setup (once, on your Mac)

```bash
cd ~/Documents/Project_1
cp data_collection/local.env.example data_collection/local.env     # then set C2_DC_DATA_ROOT
python3 -m venv data_collection/.venv
data_collection/.venv/bin/pip install -r data_collection/requirements.txt
```

`C2_DC_DATA_ROOT` is the folder that holds `staging/`, `seed/`, `logs/` — today `~/Documents/c2-24-data-tools`.
An environment variable of the same name overrides `local.env`.

## Layout

| Path | What |
|---|---|
| `scope.yaml` | Departments, dates (2018–2025, as of 31-12-2025), Ms only, keep/skip topics, skip patterns — **the maintained copy** |
| `tools/common.py` | Shared: data root, canonical IDs, OCR clean-up, references, topic filter, provenance |
| `tools/collect_ia.py`, `run_batches.sh` | Internet Archive mirror of GOIR (search API) |
| `tools/collect_goir.py` | GOIR (goir.ap.gov.in) — official register; held check before download |
| `tools/list_web.py`, `collect_web.py` | APUTF / CAG / Finance pages (listing, then guarded downloads) |
| `tools/collect_gazette.py` | AP e-Gazette search (year filter), rules/Acts; `--batch` lists Rules/Acts for FIN/GAD/School Education 2016–2025 (dry run), `--download --limit N` saves them |
| `tools/add_manual.py` | Register a PDF downloaded by hand |
| `tools/extract_relations.py` | SUPERSEDES / AMENDS / REPEALS / CLARIFIES / REFERENCES candidates |
| `tools/validate.py`, `audit_corpus.py` | Metadata, IDs, files, OCR quality, header date vs metadata |
| `tools/reconcile_dates.py` | Printed vs archive date (rule in ADR-0007); `--verify` records a person's decision |
| `tools/refilter.py`, `estimate_yield.py`, `find_holdback.py`, `check_coverage.py` | Filter, yield, demo holdback, coverage |
| `tools/generate_efiles.py`, `seed_from_mock.py` | Synthetic e-files (output joins `data/synthetic/` later, ADR-0006) |
| `tools/check_robots.py`, `inspect_form.py`, `test_archive.py` | Source checks before automating |
| `tools/ocr_corpus.py` | Document AI OCR of scans / unreadable PDFs (run from backend/ with the gcp extra; dry run shows pages + cost; `--scans-too` adds scans that only have the archive's OCR) |

## Everyday commands (from the Project_1 root)

```bash
PY=data_collection/.venv/bin/python; T=data_collection/tools
$PY $T/collect_goir.py --dept FIN01 --type MS --from 16-02-2024 --to 16-02-2024        # dry run
$PY $T/collect_goir.py --dept FIN01 --type MS --from 16-02-2024 --to 16-02-2024 --pick 1
bash $T/run_batches.sh                                  # archive, TEST MODE (FULL=1 for a full run)
$PY $T/extract_relations.py staging && $PY $T/validate.py staging
$PY $T/audit_corpus.py
$PY $T/reconcile_dates.py                               # report; --write to record
```

`staging` arguments resolve inside the data root, so commands work from any folder.

## Rules that must not change without a decision record

- Never guess a canonical ID, department, date or order type; unclear → `staging/_review/` with a reason; scans →
  `pending_ocr.jsonl`. Same ID + different subject = ID collision → review (suffix rule open, ADR-0007).
- Respect robots.txt, terms and crawl delays (≥10 s), identifying User-Agent, stop after 3 errors in a row;
  no captcha circumvention. Third-party copies (e.g. PRS) are `origin: unofficial-copy`.
- Printed date replaces the archive date only when corroborated or verified; both kept with evidence.
  `effective_from` is `assumed_issue_date` until extracted.

## To GCP (when access arrives)

`infrastructure/gcp/08_upload_public_corpus.sh` (dry run by default) copies `staging/` to the private raw bucket
under `public-go/`. Then Document AI OCR for scans, effective-date extraction, and re-run `reconcile_dates`,
`audit_corpus`, `extract_relations`. Notes and findings: `docs/data_collection/`.
