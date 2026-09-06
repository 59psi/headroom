# Code review — 2026-09-06 (adversarial)

A second whole-project review at `v2.78.0` (`6ca4712`), shipped as **2.79.0**.
The first (`docs/CODE-REVIEW-2026-09.md`) ran the two-axis `/code-review` and
fixed 168 findings by reading, mutation and executing claims. This one was
deliberately **adversarial**: eight sub-agents, each in its own detached repo
copy with its own database and port, booted a live instance, attacked it, and
mutation-probed the code — nothing was accepted on a read-through.

- **STD-A** backend security surface (live gate/traversal/CSRF/DoS attacks + 14 mutation probes)
- **STD-B** backend data/money/workers (280 mutation probes, adversarial inputs, crash-mid-op, hostile env)
- **STD-C** frontend (structural scans, OpenAPI↔TS drift, 59 mutation probes, contrast/tap-target measurement)
- **STD-D** infra/build/CI/supply-chain (real image build + run, every compose combination, Caddy validate)
- **SPEC-A/B/C** claim ledgers (≈570 executable claims across `CLAUDE.md`, README, USAGE, OPERATIONS, CHANGELOG, the review docs)
- **SPEC-D** the live app walked end-to-end in a real browser against USAGE.md, at 390×844 and 1280×800

The method that paid: **execute, then mutate.** The login timing oracle, the
multipart DoS, the placement race, the parameter-leak, the recut spending a
Claude call, the dead-marketplace sweep recorded as success — every one was
invisible to a read and to 88% line coverage, and surfaced from a request or a
reverted constant. Reports and probe manifests are in the session scratchpad.

## Fixed — security

- **Login username-enumeration timing oracle** (`routes/auth.py`) — argon2 skipped for an unknown user, 8× faster; now equal work + a per-IP rate bucket.
- **`multipart/` Content-Type bypassed the body cap** (`limits.py`) — an unauthenticated OOM; the cap is chosen by the endpoint now.
- **Share token leaked into the `error.unhandled` row and log** via SQLAlchemy's bound-parameter rendering (`error_handler.py`, `database.py` `hide_parameters`).
- **Hat-photo upload 500'd on an undecodable file** (`routes/hats.py`, `utils/photo.decoded_image`) — now 400, with a central pixel ceiling; one decoder for the photo and logo routes.
- **`?next=` open redirect** (`LoginPage.tsx`) — whitespace survived the same-origin check; now resolved against the real origin.
- **Session cookie flags** pinned by a test; **no test can reach the network** (`conftest`, both `httpx` and `httpx2`).

## Fixed — data integrity

- **Concurrent placement race** — five hats at one position, one label; `services/locks.loop_lock` + a partial unique index + a boot-time duplicate repair.
- **Unvalidated purchase-import body** — `list[dict]` → `list[PurchaseLine]`; `quantity`/`price`/`order_date` bounded.
- **Money and text validation at the wire** (`schemas/common.py`) — `NaN`/`Infinity`/negative refused, names/notes stripped and capped, dispose price gated to sales, future wear dates refused.
- **Timestamps carry a zone** (`database.UtcDateTime`) — the whole app's `DateTime` columns.
- **Restore into a full case**, **crash between an import hat and its photo**, **deleting a hat orphaning its receipt** — all fixed.

## Fixed — correctness

- **"Redo cutout"** spends no Claude call and preserves owner edits (`finalize_hat_photo(cutout_only=True)`).
- **Dead-marketplace re-pricing sweep** recorded as a failure, not a success; unreached hats not stamped.
- **All-failed colorway harvest** reports the failure; failed categories published.
- **One product-name reading** (`services/naming.py`) across the matcher, pricer and analyzer.
- **Search** matches the printed style label, escapes LIKE wildcards, and keeps a filtered-to-empty filter mounted.
- **Vocabulary tiebreak** counts real rows, not distinct spellings.

## Fixed — reliability & ops

- **Torn scheduled backup** written under `.partial`, renamed only when whole, swept at boot; 60 s stop grace.
- **HTTP/3 on the LE overlay** (UDP 443 published, a Caddyfile with HSTS + compression); both Caddyfiles compress.
- **CA export defeating the backup change-gate** — content hash + `cmp -s` before copy.
- **Env knobs** degrade to default on `nan`/`inf`/zero.
- **Image hardening**: root-owned `/app`, read-only base compose, an image `HEALTHCHECK`, `U2NET_HOME` so the baked model is found, a caching policy by path class.
- **Dependabot** sees the uv pin (`FROM`) and the compose images; CI SHA-pins actions and has timeouts.

## Fixed — documentation

Every FALSE/STALE claim the ledgers found: the lifespan order, the recut
behaviour, `hat_to_read`'s callers, the share-link default, three env-var
shorthands, the body-cap description, the log levels, the Retry card location,
the cache-mount count, the watchdog privileges, the restore recipe's WAL
sidecars, README's comma vs space, and the USAGE label mismatches. New patterns
(UtcDateTime, naming, the placement lock, the wire validators, the network
block, the caching policy) added to `CLAUDE.md`.

## Deliberate non-fixes

- **The 552 KB bundle is not code-split.** The material cost on a Pi is bytes
  on the wire, and that is addressed — Caddy `encode` on every overlay plus
  `GZipMiddleware` for the no-Caddy paths take it to ~155 KB gzip. Lazy-loading
  per route is a larger refactor with test churn for a personal LAN PWA that
  loads once; recorded rather than done.
- **The RGB palette-name metric** stays (measured in the prior review).
- **The 3-cycle matcher blind spot** stays, pinned by its test.
- **`Case.photo_path`** the column stays; dropping it is a destructive migration.
- **The mutation survivors STD-B/STD-C listed on the money/matcher paths** that
  are equivalent (reversed visit order, the `manual`/`comp` branch swap) stay,
  as the prior review recorded.

## What changed about how this repo is reviewed

- **Attack a live instance.** Six of the highest-severity findings were a
  request/response, not a code smell. Every sub-agent booted the app.
- **Mutation over coverage, still** — and now the source-scanning tests cover
  the holes the last ones left: icon-only buttons, `.ts` class literals, a
  `className={'a' + x}` concatenation, single-quoted env reads.
- **The docs are the previous authors' belief.** ≈570 claims were executed;
  the ones that were wrong are corrected in place with a note that they are.
