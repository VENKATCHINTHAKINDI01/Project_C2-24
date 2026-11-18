# Security

C2-24 is a proof of concept on **synthetic data**. It holds no real departmental records, and it must not be loaded with any until the department authorises it.

## Reporting a problem

Report suspected vulnerabilities, or anything that discloses a record to an officer who should not see it, privately to the project owner. Do not open a public issue. Include steps to reproduce and the request ID returned in the `X-Request-ID` header.

## Security model (summary)

Below is a summary of the rules the code enforces; the detailed design records are kept by the team outside this repository.

- **Identity:**
  - Cloud deployments sit behind Identity-Aware Proxy. The API verifies IAP's signed assertion itself: signature, issuer, audience and expiry.
  - The verified e-mail is mapped to an e-Office user through a directory.
  - The sandbox sign-in exists only in `sandbox` mode.
- **Authorisation:**
  - Role-based and attribute-based rules are deterministic.
  - `compute_scope` runs before retrieval and is pushed into every rung. `can_access` re-checks every candidate before the evidence package is built.
  - Counts, summaries, citations, cache and memory are all scoped the same way.
- **Fail closed:** when identity, scope or authorisation fails, the request is denied with a neutral message. It never falls back to unscoped results. Inaccessible files are neither confirmed nor denied.
- **The model is not the boundary:**
  - Gemini sees only the authorised evidence package.
  - Retrieved text is treated as untrusted data.
  - Citations are verified, and unsupported claims are withheld.
- **Abuse limits:**
  - per-officer request limits;
  - a request body cap;
  - timeouts on every external call;
  - cross-department alerts for unusual activity.
- **Logs:** IDs, metadata and access decisions only. Document text is never written to general logs.
- **Evidence:** the evaluation harness checks 1,142 access paths for unauthorised disclosure. The pass bar is zero.

## Secrets

Never commit secrets. `.env`, key files and local GCP configuration are git-ignored, and `.env.example` holds placeholder names only. Cloud services use service-account identity. Database access uses IAM authentication.
