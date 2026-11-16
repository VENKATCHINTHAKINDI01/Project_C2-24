# ADR-0014: Document preview and download for officers

- **Date:** 2026-11-09
- **Status:** Accepted (owner approval, 9 Nov 2026)
- **Plan sections:** §3.5 (Cloud Storage holds raw source documents), §4.6 (provenance), §5.2 (scope + re-check), §5.4 (indirect leakage), §8.2 (citations), §11 (mock e-Office), §13.3 (leakage matrix)

## Context
Source files are already downloaded (public G.O.s by the collectors; synthetic e-files generated) and, per
plan §3.5, stored in Cloud Storage; extraction reads from those stored copies. Officers can see what C2-24
quotes, but not the document itself. The owner asked for a preview of the actual file and a download
option, so an officer can check a citation against the original page.

Handing over a file is the most direct form of disclosure, so this is a security feature first.

## Decision
Add preview (inline, opened at the cited page) and download of source documents, under these rules:

1. **Same authorization as every other path.** Each preview or download runs `can_access(user, document)`
   at that moment (plan §5.2). A document the officer may not see answers exactly like one that does not
   exist (404, same body). Fail closed on any error.
2. **Private storage, served through the backend.** Buckets stay private. For the PoC the backend streams
   the bytes after the check; no public URLs. Signed URLs are not used in the PoC; if introduced later
   (large files), they are issued only after the check and expire within minutes.
3. **The exact version cited.** Preview serves the stored object the evidence came from (content hash /
   object generation in provenance, plan §4.6), opened at the cited page — never "whatever is latest".
4. **Review-queue items are not served.** A file held by the confidence gate is served only when the
   officer could open it in e-Office; C2-24 never serves unconfirmed extracted text as if it were the file.
5. **Audited.** Every view and download is logged: user, canonical ID, version, action, time, decision —
   IDs only, never content (CLAUDE.md §4.11).
6. **Tested as leakage paths.** "Preview" and "download" join the leakage matrix and the opposite
   scenarios; the pass bar stays zero unauthorised disclosures (CLAUDE.md §9.4).
7. **Behind an interface.** A document-store interface: local files in the sandbox now, Cloud Storage on
   GCP; no core module reads a bucket directly.

## Alternatives considered
| Option | Why not |
|---|---|
| Text-only citations (status quo) | Officers cannot check a quote against the original page |
| Signed URLs straight from the bucket | A URL works for anyone holding it until expiry; harder to audit and to revoke on a permission change |
| Public bucket for public G.O.s | Mixes public and synthetic/restricted material; one rule for all documents is simpler to prove |

## Consequences
- New endpoints (preview, download) and screens in the mock e-Office sandbox; leakage matrix grows by two paths.
- Cloud Run response size limits apply to streamed files; very large scans may need ranged reads (Tier 2).
- Watermarking and download limits are not in the PoC (Tier 2).

## Mentor / department input
None required for the PoC; confirm with the department before any real data is served.

## Implementation note (10 Nov 2026)
Built in the sandbox with ADR-0015 (citation highlights):
- `ingestion/document_store.py`: the `DocumentStore` interface, and `InMemoryDocumentStore` as the
  sandbox stand-in for the bucket. Files are keyed by the ingestion version (sha256 prefix and
  pipeline version), and the media type is read from the content.
- New routes:
  - `GET /assist/documents/{id}` gives the document's details;
  - `…/preview` serves the file inline, for PDF and images only, and answers 415 for anything else;
  - `…/download` serves it as an attachment.
- Every route uses the L0 lookup within scope plus a `can_access` re-check.
- Unknown, hidden, held, malformed and unstored documents all get the same 404, with the body
  "Document not available." (wording replaced by the guiding message of ADR-0016, 11 Nov 2026)
- Files are served with `Cache-Control: private, no-store` and `nosniff`. The file name is built
  from the canonical ID, not the source file name.
- Every request is audited with IDs and the version only.
- Rule 3: preview opens at page 1 until cited paragraphs have page locations (Document AI layout).
- Rule 4: held records are never served in the PoC, which is stricter than the rule requires.
