# Source check — fill in during Step 2 (by hand, in your browser)

## GOIR (goir.ap.gov.in) — Finance, G.O.(Ms), 2024, open 3 results
- Department label exactly as shown (e.g. `FIN01 - FINANCE`):
- School Education label / code:
- Section shown? Abstract shown?
- PDF link pattern:

## Internet Archive (archive.org/details/andhra-goir)
- Paste `python tools/test_archive.py` output here
- Paste `python tools/collect_ia.py --probe 5 --dept FIN01` output here
- PDF present? `_djvu.txt` present? Description lists Order Type / Number / Date / Department?

## APUTF (aputf.org/gos/latest-gos)
- Two PDFs downloaded, open OK? Read-list present?

## Surprises
-

## Re-check 11 Nov 2026 (before the fresh full collection)

Output: `~/Documents/c2-24-corpus/logs/source_check_2026-11-11.txt` (`tools/check_robots.py`).

| Source | robots.txt | Change since 18 Oct | Use in this run |
|---|---|---|---|
| GOIR goir.ap.gov.in | **`User-agent: * / Disallow: /`** | **Now disallows all crawling** (was "Allow: /") | **No automated access.** `collect_goir.py` already stops on this. Orders found only on GOIR are hand downloads (`add_manual.py`) or a recorded gap |
| Internet Archive (`andhra-goir` mirror) | allows search + download | unchanged | Main bulk source (`run_batches.sh` → `collect_ia.py`) |
| AP e-Gazette | 404 (no rules) | unchanged | Gazette search as needed |
| AP Finance GOs | 404 (no rules) | unchanged; 27 PDF links | Circular memos (type C) |
| APUTF | crawl-delay 10 s | unchanged; 304 PDF links | Not needed (decision 16 Oct) |
| CAG PAG (A&E) AP | allows the G.O. page | unchanged; 71 PDF links | Pay / DA / pension orders if missing from the mirror |

## Re-check 12 Nov 2026, 21:02 IST (GOIR only)

GOIR robots.txt: HTTP 200, `User-agent:* / Disallow:/`. Both `/` and `/Reports.aspx` are DISALLOWED for our user agent. Unchanged since 11 Nov: still no automated access.
