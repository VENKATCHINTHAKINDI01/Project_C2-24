# C2-24 operations checklist (GCP, asia-south1)

These are recurring checks for the deployed PoC. Each line names the script that does the check. Record the result as a session-log row in `PROGRESS.md`. Scripts run from `backend/` with `env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/<script>`. They are dry runs unless `APPLY=1` is set.

## Backups and recovery (ADR-0057)
> A backup that has never been successfully restored is not a tested recovery strategy.

| When | Check | Command | Pass |
|---|---|---|---|
| Daily (or after any alert) | Latest automated backup succeeded, is in Mumbai, and is less than 26 h old | `CHECK_ONLY=1 … 31_restore_drill.py` | `✓ backups current and in Mumbai` |
| On any "Cloud SQL automated backup failed" alert | Read the audit entry, fix the cause, take an on-demand backup, re-run the daily check | console → Logging; `gcloud sql backups create --instance <prefix>-sql --location asia-south1` | daily check passes |
| Monthly, and after ANY change to backup settings, the instance tier/edition, or the schema | **Full restore drill**: PITR clone and backup restore into a throwaway instance, row counts compared, clone deleted | `APPLY=1 I_ACCEPT_COST=1 … 31_restore_drill.py` | `RESULT: PASS`; record both restore times in PROGRESS.md |
| Before any destructive load (graph sync, migration that rewrites data) | Daily check passes; for a large change also take an on-demand backup in asia-south1 | as above | as above |
| After applying or changing backup settings | Settings read back as configured | `APPLY=1 RESTART_OK=1 … 29_cloudsql_backups.py` (or the dry run to read only) | all `✓` |
| Monthly | Backup cost against the estimate in ADR-0057 | Billing report, SKU "Backups" in asia-south1 | within estimate, or ADR updated |

## Cloud Run access settings — do not change (ADR-0065)
The TechBharat admins own who can reach c2-frontend and c2-api (auth, IAP, ingress, IAM/IAP bindings). Changing them caused the c2-frontend 403s.
- Redeploy only with `20_api_service.sh` / `23_frontend_service.sh` (default `PART=dev`): they keep an existing service's access settings as they are.
- Never run `gcloud run services update … --ingress/--[no-]allow-unauthenticated/--iap`, `add-/remove-iam-policy-binding`, `set-iam-policy`, `gcloud iap web …`, or change these in the console, without the admins' agreement first.
- After agreement: `SECURITY_CHANGE=approved PART=owner IAP_MEMBERS=… APPLY=1 bash 23_frontend_service.sh`. Without the flag the commands are printed, not run.
- After every deploy: open the c2-frontend URL in a browser; a 403 means report to the admins — do not try to fix it by changing access.

## Evaluation on GCP (ADR-0068)
Heavy and billed suites run as the Cloud Run Job `c2-eval`, not on a laptop. From `infrastructure/gcp/`:

| When | Command | Pass |
|---|---|---|
| After changing backend, evaluation or synthetic data | `APPLY=1 bash 32_eval_job.sh build` | image tagged `latest` |
| Before every release | `APPLY=1 MODE=leakage bash 32_eval_job.sh run` (all 21 officers) | 0 disclosures, every officer swept |
| Before a release that changes prompts or the model's role | `APPLY=1 MODE=ragas bash 32_eval_job.sh run`; `APPLY=1 MODE=conversation bash 32_eval_job.sh run` | RAGAS not below the baseline; `critical_failures: 0` |
| After a run | `APPLY=1 bash 32_eval_job.sh fetch` | reports in `evaluation/reports/`; record them in PROGRESS.md |

## Other alerts already in place
- **Tracking buffer full** (`28_tracking_alert.sh`, ADR-0049): BigQuery query-log rows were dropped. Check BigQuery access and quota.

## Release smoke checks (cloud sandbox, seed v2)
The cloud sandbox runs seed v2 (officers V01–V21, monitoring officer M01). Ask each question through `/assist/ask` with the `X-Sandbox-User` header. The lines below come from the records (no Gemini call), so they are exact. Expected wording was verified against a local v2 sandbox on 18 Nov 2026.

| # | Officer | Question | Expected (record statements) |
|---|---|---|---|
| 1 | V14 (GAD Secretary) | How has G.O.Ms.No.109/2025 changed over time? | Dated lines: G.O.Ms.No.295/2014 took effect; 381/2016 amended 295; 396/2016 superseded 295 and 381; 109/2025 amended 396. Then "In force on …: G.O.Ms.No.109 …" and "1 further link(s) … await officer review" |
| 2 | V07 (FIN Principal Secretary) | How has G.O.Ms.No.50/2021 changed over time? | 10 order-record lines, starting "11-02-2016: G.O.Ms.No.19, Finance Department … took effect" |
| 3 | V14 | Which other departments refer to G.O.Ms.No.39/2019? | "Finance (FIN01): G.O.Ms.No.39, General Administration Department, dated 26-03-2019 amends G.O.Ms.No.150, Finance Department, dated 08-08-2016." |
| 4 | V07 | Which other departments refer to G.O.Ms.No.150/2016? | "General Administration (GAD01): G.O.Ms.No.39 … amends G.O.Ms.No.150 …" |
| 5 | V21 (ESE Principal Secretary) | Which other departments refer to G.O.Ms.No.20/2025? | "The link records show no record of another department linked to …". No "GAZ" line: a Gazette publication is not a department |
| 6 | V21 | Which notes did B. Suresh Kumar sign? | "60 record(s) name B. Suresh Kumar (Joint Secretary, officer ID V20); the 12 most recent: …" |
| 7 | V21 | Notes signed by V20 | Same statement as 6 |
| 8 | V07 | Which notes did B. Suresh Kumar sign? | No entity statement; status `not_run` (V07 sees no ESE01 file: same as an unknown name) |
| 9 | V21 | How have the orders cited in File No.ESE01-EXAM0EXM/22/2017-EXAMS changed? | "The noting in File No.ESE01-EXAM0EXM/22/2017-EXAMS, written on 21-12-2017, cites G.O.Ms.No.91 … 1 change(s) … after it was written." (and the same for the draft proposal), then 91/2017 took effect, 1/2018 amended it, "In force on …: G.O.Ms.No.91 …, G.O.Ms.No.1 …" |
| 10 | V08 (GAD Section) | How have the orders cited in File No.ESE01-EXAM0EXM/22/2017-EXAMS changed? | No record statement; status `not_run` (the file is outside V08's scope: same as a file that does not exist) |
| 11 | M01 | `GET /assist/monitor?days=14` | 200 with `by_department`, `by_role`, `by_intent`, `topics`, `reasked` |
| 12 | V14 | `GET /assist/monitor?days=14` | 404 |

Seed v1 checks (U01–U08) run only in a local v1 sandbox. Counts that include scanned papers (for example, the 3 records naming Sri K. Venkata Ramana) hold only after the scans are confirmed in OCR review. In a plain sandbox the scanned vigilance note D22 waits in review, so the count is 2. That is correct: an unreviewed scan is not trusted evidence (CLAUDE.md §5.3).
