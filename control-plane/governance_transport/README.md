# Governance transport package

`governance_transport` is the governance repository's private connection and
reliability package. It is not published to PyPI and has no third-party runtime
dependencies.

## Responsibilities

- `client.py` — GitHub REST requests, 30-second timeout, bounded retry and typed errors.
- `retry.py` — HTTP 429, rate-limit 403, 502/503/504 and deterministic backoff policy.
- `audit.py` — JSONL transport audit with recursive secret and payload redaction.
- `idempotency.py` — v3/v4 request identity, canonical UUID validation and SHA-256 fingerprinting.
- `diagnostics.py` — exact repository, Issue and comment readback verification.
- `status.py` — one `governance-machine-status-v1` constructor and renderer.

## Boundary

This package runs only after an OpenAI Action request reaches GitHub. It cannot
control the ChatGPT confirmation UI or repair a request that never reaches the
GitHub API. The OpenAPI schema and GPT instructions continue to manage that
upstream boundary.

## Dependency policy

Production code uses only Python 3.12 standard-library modules. Do not add
`requests`, `httpx`, `tenacity`, `backoff`, `PyGithub`, `Celery`, `RQ`, Redis or
a database client to this package. A new dependency requires a separate design
review, exact version pinning and supply-chain audit.

`control-plane/resilient_http.py` remains a compatibility facade so existing
workflows and recovery scripts keep the same entrypoint while sharing this
package's implementation.
