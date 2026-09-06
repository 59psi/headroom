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
and in `docs/CODE-REVIEW-2026-08.md` / `docs/CODE-REVIEW-2026-09.md`. The full 2026-08 archaeology bundle is
generated into `analysis/` (gitignored — regenerate it with
`/code-archaeology` rather than committing it).

## Cited findings

| Id | Finding | Where the fix lives now |
|---|---|---|
| **R8** | The app's rate limiter, passkey challenge store, import queue, token caches and mDNS singleton are all in-memory and process-local, so running more than one worker silently breaks passkey login and halves rate limiting. Nothing shared backs them. | `app.py::_warn_if_multiprocess` — warns loudly at boot when `WEB_CONCURRENCY` / `UVICORN_WORKERS` / `GUNICORN_WORKERS` exceed 1. |
| **R11** | A `Hat` column added to the model but forgotten in `_HAT_COLUMN_DDL` bricks every hat read on an upgraded database, and nothing catches it before deploy. | `tests/test_schema_consistency.py` — turns the CLAUDE.md convention into an enforced invariant. |
| **S1** | The SPA catch-all joined the requested path onto the `dist` directory without checking the result stayed inside it, so `/%2e%2e/data/headroom.db` could read the database off disk. | `utils/paths.py::safe_join`/`safe_file` — one traversal guard, used by the SPA handler and the share-photo streamer; `tests/test_security.py::test_spa_does_not_serve_files_outside_dist` is the anchor. |
| **S2 / R9** | `GET /health/ready` is unauthenticated (the Docker healthcheck calls it) but returned filesystem paths, API-key source and raw error text to anonymous callers. | `routes/health.py` — booleans only for anonymous callers; authenticated ones get full detail plus the import-worker liveness canary. |
| **S10** | The backup tarball contains the whole database — plaintext keys, tokens, session ids, password hashes — making a download the single highest-value exfiltration artifact, and it was not audited. | `routes/admin/backups.py` — every download writes an `activity_log` row before streaming. |
| **S3** | A password change revoked the other sessions but left the static API token in place, so a stolen token survived the one action a compromised owner takes. | `routes/auth.py::change_password` rotates `api_token` alongside the hash. |
| **S4** | Failed logins were not recorded, so a credential-stuffing run left no trace unless somebody was reading the container log at the time. | `routes/auth.py::login` writes an `auth.login_failed` activity row (committed before the 401 is raised); `tests/test_prod_hardening.py` covers it. S10 is the backup-download half of the same audit finding. |
| **S5 / R10** | First-run `/api/auth/setup` check-then-insert allowed two concurrent requests to create two co-equal owner accounts. | `routes/auth.py` — serialized behind an `app_settings` primary-key sentinel, so the second request loses the insert rather than racing. |
| **S9 / R6** | Bulk import read every uploaded file fully into memory with no ceiling, so 100 × 20 MB could OOM-kill the container on a small Pi. | `routes/import_jobs.py` — files are spooled to disk as they arrive (2.12.0); the byte ceiling now bounds job size rather than RAM. |

## Conventions going forward

Cite a finding only when the reference resolves — add a row here, or write the
reasoning inline instead. An id is a pointer; a pointer to nothing is a
liability, and this repo already fixed the same class of problem once when a
comment described a design the code had moved away from.
