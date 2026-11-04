# ADR-0006: Public G.O. corpus alongside synthetic data; `data_collection/` folder

- **Date:** 2026-10-22
- **Status:** Proposed (owner to accept)
- **Plan section:** §4.4, §5, §12, §14

## Context
No official department data will arrive (owner decision, Oct 2026). Since 14 Oct a separate workspace
(`~/Documents/c2-24-data-tools`) has collected real, **public** G.O.s (Finance, GAD, School Education, 2018–2025,
frozen as of 31-12-2025) and generated synthetic e-files grounded in them. ADR-0003 says to build on synthetic data;
CLAUDE.md §11.1 says new top-level folders need a decision record; the GCP runbook says "synthetic data only".
The owner asked to bring the collection code into Project_1 so real collection can start when GCP access arrives,
without disturbing work done so far.

## Decision
- Add top-level **`data_collection/`**: collectors, filters, checks and the e-file generator (Python scripts, own
  `requirements.txt` and `.venv`), plus `scope.yaml` as the maintained configuration. Outside `backend/`, so
  backend lint/type/tests are unaffected; the scripts are tooling, not application code.
- The **corpus stays outside the repository** (today in the old workspace, ≈640 MB) and is named in the git-ignored
  `data_collection/local.env` (`C2_DC_DATA_ROOT`). It is never committed; on access day it is copied to the private
  raw bucket under `public-go/` (`infrastructure/gcp/08_upload_public_corpus.sh`).
- **Synthetic data stays the source of metrics** (ADR-0003 unchanged). The public corpus adds realism: real
  numbering, Read-lists, supersession/amendment chains, dates and OCR noise. Synthetic e-files built on it join
  `data/synthetic/` as a new version once complete; until then only the generator moves.
- Notes move to `docs/data_collection/`. The owner's tracking sheet stays out of the repository.
- Collection stays in **test phase** (dry run, 1–2 files) until the owner approves full runs.

## Alternatives considered
| Option | Why not |
|---|---|
| Put collectors in `backend/app/ingestion/` | Must first meet strict mypy/ruff/tests: a large rewrite now, and collection is offline tooling, not the request path |
| Put them under `infrastructure/` | Not infrastructure code |
| Copy the corpus into the repo (git-ignored) | Owner chose to keep one copy in the old folder for now |
| Move the corpus | Old workspace would stop working on its own; owner chose to leave it |

## Consequences
- Two copies of the scripts exist until the old workspace is retired; **Project_1's copy is the maintained one**.
- Real public records enter the corpus: classification stays UNCLASSIFIED (public); access-control demos still rely
  on synthetic e-files and mock classifications. The GCP runbook's "synthetic data only" now reads "synthetic data
  plus the public G.O. corpus".
- Eval integrity: synthetic ground truth (`efiles_conflicts.json`) stays eval-only, same rule as `mock_v1`.
- Reversing: delete `data_collection/` and `docs/data_collection/`; the old workspace still holds code and data.

## Mentor input (if any)
— (mentor approved the overall plan in Oct 2026; this ADR to be shared)
