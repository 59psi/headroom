# Audit history

Several comments in this codebase cite a finding by id — `(R8)`, `(S5/R10)`,
`(S2/R9)`. Those ids came from review passes whose reports were never committed,
so for a long time the references pointed at nothing: a reader could see that a
line existed because of a finding, but not what the finding said. A permanent
citation to a document nobody can open is worse than no citation, because it
implies a rationale exists to be checked.

This file is that document. It records what each cited id actually was, so the
in-code references resolve. It is history, not a plan — nothing here is
outstanding.

## Prefixes

| Prefix | Pass |
|---|---|
| `S` | Security review (Sentinel), first run at v1.3.0 |
| `R` | General code review, same era |

Later passes are recorded in `CHANGELOG.md` under the release that fixed them,
and in `docs/CODE-REVIEW-2026-08.md`. The full 2026-08 archaeology bundle is
generated into `analysis/` (gitignored — regenerate it with
`/code-archaeology` rather than committing it).

## Cited findings

| Id | Finding | Where the fix lives now |
|---|---|---|
| **R8** | The app's rate limiter, passkey challenge store, import queue, token caches and mDNS singleton are all in-memory and process-local, so running more than one worker silently breaks passkey login and halves rate limiting. Nothing shared backs them. | `app.py::_warn_if_multiprocess` — warns loudly at boot when `WEB_CONCURRENCY` / `UVICORN_WORKERS` / `GUNICORN_WORKERS` exceed 1. |
| **R11** | A `Hat` column added to the model but forgotten in `_HAT_COLUMN_DDL` bricks every hat read on an upgraded database, and nothing catches it before deploy. | `tests/test_schema_consistency.py` — turns the CLAUDE.md convention into an enforced invariant. |
| **S2 / R9** | `GET /health/ready` is unauthenticated (the Docker healthcheck calls it) but returned filesystem paths, API-key source and raw error text to anonymous callers. | `routes/health.py` — booleans only for anonymous callers; authenticated ones get full detail plus the import-worker liveness canary. |
| **S4 / S10** | The backup tarball contains the whole database — plaintext keys, tokens, session ids, password hashes — making a download the single highest-value exfiltration artifact, and it was not audited. | `routes/admin/backups.py` — every download writes an `activity_log` row before streaming. |
| **S5 / R10** | First-run `/api/auth/setup` check-then-insert allowed two concurrent requests to create two co-equal owner accounts. | `routes/auth.py` — serialised behind an `app_settings` primary-key sentinel, so the second request loses the insert rather than racing. |
| **S9 / R6** | Bulk import read every uploaded file fully into memory with no ceiling, so 100 × 20 MB could OOM-kill the container on a small Pi. | `routes/import_jobs.py` — files are spooled to disk as they arrive (2.12.0); the byte ceiling now bounds job size rather than RAM. |

## Conventions going forward

Cite a finding only when the reference resolves — add a row here, or write the
reasoning inline instead. An id is a pointer; a pointer to nothing is a
liability, and this repo already fixed the same class of problem once when a
comment described a design the code had moved away from.
