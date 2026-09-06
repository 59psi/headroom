# Code review — 2026-09-05

Two-axis review (`/code-review max`) of the **whole project** at `v2.77.3`
(`036b769`), shipped as **2.78.0**. **Standards** = conformance to `CLAUDE.md`
plus the Fowler smell baseline. **Spec** = does the code do what the docs
promise. No issue tracker and no PRD, so the Spec axis ran against the
project's own claims — `CLAUDE.md`, README, `docs/`, `CHANGELOG.md` — and
each claim was checked against the code rather than the other way round.

Six sub-agents, two per axis per area (backend services; backend app/routes/
db/tests/infra; frontend), then everything fixed in one pass. **168 findings:
all addressed** — fixed, or recorded below as a deliberate decision with the
reason. Backend suite 997 → **1036**, frontend 253 → **278**.

The method that produced the highest-value findings was not reading: it was
**mutation testing** (change one constant, delete one call, watch the suite
stay green) and **executing the claim** (start the second passkey
registration, POST the traversal payload, run the documented recovery recipe,
resolve `localhost` on a dual-stack host). Most of what follows was invisible
to a read-through and to the line-coverage report, which sat at 88%.

---

## Standards axis — backend services (30)

| # | Finding | Status |
|---|---|---|
| A-1 | **A second passkey registration 500'd.** `exclude_credentials` was passed as dicts; py_webauthn 3.0 reads `.id`/`.type.value`. Executed against the locked library. | Fixed — `PublicKeyCredentialDescriptor` per stored credential; test registers twice. |
| A-2 | Two definitions of a "failed" analysis: the run's `failed` counted `status == "error"`, the card's `failed_count` counted a non-empty `analysis_error`, and the route published both. | Fixed — one predicate, `hat_service.failed_analysis_filters()`, everywhere. |
| A-3 | Bulk import committed the `Hat` row *before* decoding the photo, so a bad file left a photoless hat forever. | Fixed — decode first; the created id is cleaned up on failure. |
| A-4 | `_publish_stage`, the only writer of `analysis_stage`, reached for the module-level session (poisoned under test, so the writes had never once been observed). | Fixed — a session maker bound to the pipeline's own engine; the stage is asserted through the test session. |
| A-5 | `create_job` ran `shutil.copy2` per file on the event loop (100 × 20 MB). | Fixed — `shutil.move` from the spool directory, off-loop. |
| A-6–13 | Docstring after `global` (so `__doc__` was `None`); `clear_construction(to=)` skipping `canonicalize`; `detach_from_case` bypassed by two writers; the inventory report summing disposed hats into the current total; `ebay_listing_count` as `len()` of a 25-row page; the harvest sending `per_page` to an API that reads `perPage`; multi-MB PNG reads synchronous on the loop. | All fixed, each with a test. |
| A-14 | Twelve stale comments, from a lazy-load hazard `CLAUDE.md` had already retracted to a "TOKEN CONTAINMENT" docstring over an `ilike %token%` body. | Fixed — the containment one was a real bug (A-Game Hydro offered HYDROLite colorways); the rest rewritten or deleted. |
| A-15 | British spellings, including a **persisted** status value `cancelled` and the `import.cancelled` activity kind. | Fixed — `canceled` on the wire, `_STATUS_RENAME_DML` rewrites stored rows on every boot, frontend types follow. Data (`"Heather Grey"`) exempt. |
| A-16 | `_product_comp` matched colorways by containment while `is_real_product` used equality — `Camo` priced against `Rain Camo` and `808 Camo`. | Fixed — token-set equality in `_halves_match`. |
| A-17 | Colorway not canonicalized on the PUT path or the matcher's write. | Fixed. |
| A-18 | `_hat_loads()` restated by hand in six modules. | Fixed — public `hat_loads()`, imported. |
| A-19 | Four construction tokenizations. | Fixed — `schemas/hat.CONSTRUCTION_TOKENS`, `constructions_in`, `strip_constructions`. |
| A-20 | Resale-scope string literals everywhere. | Fixed — `models/hat.ResaleScope` (`StrEnum`). |
| A-21 | RGB-nearest palette name vs CIEDE2000 families; palette LAB recomputed per call. | **Measured, not unified.** Over a 512-point grid the metrics disagree on 39% of points and ΔE calls pure blue "purple". RGB kept for the name; palette LAB precomputed; target families computed once per search. The docstring carries the numbers. |
| A-22–26 | Unused `BytesIO` branch; `len(select())` counts; `is_real_product` full-table scan per hat; a private `_fold` import; a dead alias. | All fixed (`func.count`, prefilter, public `fold`). |
| A-27 | The re-pricing scheduler swept the whole shelf on **every boot** — no staleness gate, where the backup loop skips when a recent one exists. | Fixed — `stale_before`, threaded from `_loop` to `reprice_once`; the query excludes hats checked within the interval. |
| A-28 | QR rendering and Kuhn's assignment CPU-bound on the loop. | Fixed — `asyncio.to_thread`. |
| A-29 | `AsyncAnthropic` built per call and never closed; a dead string-payload branch. | Fixed — `async with _anthropic_client(...)`. |
| A-30 | `stop_worker` cleared the factory before cancelling; `advance()` reported 100% during the last unit; a new `AsyncClient` per marketplace page. | Fixed — stop order; `start_unit`/`advance(label=None)`; `shared_client()`. |

## Standards axis — backend app / routes / db / tests / infra (39)

| # | Finding | Status |
|---|---|---|
| B-1 | A module-level `HTTPException` re-raised per request grew its traceback without bound (0 → 30 frames after five anonymous requests), pinning a `Request` and a session per frame. | Fixed — `_not_found()` factories; test raises five times and asserts no module-level exception holds a traceback. |
| B-2 | `upload_logo` unlinked the old logo *before* the size cap and the decode, so a bad upload deleted the logo. | Fixed — decode and resize into a temp file, then replace; test posts oversize and corrupt. |
| B-3 | The harvest's background task imported the module session; only the refused path was tested. | Fixed — `request.app.state.session_factory`; the started path is tested to completion. |
| B-4 | The inline reanalyze path (worker off) was unguarded, so a non-Claude error left a hat `pending` forever. | Fixed — one `_run_inline` guard for all three inline paths. |
| B-5 | A case's detail listed **disposed** hats while its counts excluded them. | Fixed. |
| B-6 | `GET /api/admin/config` reported the env model, not the database-resolved one. | Fixed. |
| B-7 | `docker-compose.http80.yml` proxied to `localhost` — `::1` on a dual-stack host, 502. | Fixed — `127.0.0.1`; the Caddyfile test now greps the compose files. |
| B-8–10 | Tests passing for the wrong reason: a validation test that recorded the poisoned-engine error instead; a labels test with `or "0 labels"`; a source check that read only past the last docstring. | Fixed. |
| B-11 | Fifteen per-endpoint "requires auth" assertions across twelve files, none of which would have caught the `/openapi.json` leak. | Removed; the enumeration test is the guard, and the rule is in `CLAUDE.md`. |
| B-12 | Score/tier assertions in the file whose header forbids them. | Rewritten as outcomes — contended hats where only that tier decides the price. |
| B-13–14 | Tests asserting nothing (`never_raises` ×3, a WAL checkpoint, an `in ("wal", "memory")` that was always memory); fixture state leaking across tests (backup health, sweep progress, the rate limiter, `_session_factory`). | Fixed — real assertions; autouse resets and `try/finally`. |
| B-15 | Thumbnail and export derivation swallowed every exception silently. | Fixed — logged at WARNING, tested with `caplog`. |
| B-16 | ~20 routes returned hand-built dicts with no `response_model` — invisible to the TypeScript types, including one that **writes prices**. | Fixed — schemas for all; `tests/test_api_contract.py` enumerates the OpenAPI document and fails on any 2xx without one. |
| B-17 | Twenty-two stale comments (a "13 fields" that was 23, a CI comment claiming `restart: unless-stopped` acts on health, a Dockerfile comment about a `"*"` that was a subnet, …). | Fixed or deleted. |
| B-18 | Capacity figures typed by hand in four source files and eleven tests. | Fixed — named constants, imported. |
| B-19 | British spellings in prose (data and identifiers exempt). | Fixed. |
| B-20 | Three logo-suffix lists, one drifted (`.jpeg` served to the login page, invisible to Settings, never replaced). | Fixed — `utils/branding.py`. |
| B-21–24 | A duplicated 750 MB cap; the npm pin in three files with no parity; a hand mapper in `routes/search.py`; hand-written `cases`/`hat_colors` migrations. | Fixed — one constant; `test_the_npm_pin_is_one_number_in_three_files`; `SearchResult` `from_attributes`; `_CASE_COLUMN_DDL`/`_HAT_COLOR_COLUMN_DDL`. |
| B-25–37 | `error_handler` falling back to the module session; a blind `except` around `display_id`; a truncation warning on every page; sync upload copy and Pillow on the loop; no EXIF transpose; private cross-module imports; `HatDispose.via` as a bare string; unbounded `limit`s; guest `hat_count` as `len()` of a capped list; passkey exception text echoed to the client; `PLC0415` both selected and ignored; `[ -d .git ]` false in a worktree; `response: Response = None`. | All fixed. `via` is `DisposedVia` (422, not 400). `PLC0415` is now **enforced**, with a prose reason on every surviving `noqa`. |
| B-38 | Tautological and weak tests (`assert x == x`, `sum >= 1`, `getsource` checks, dead helpers, a Claude test mocking the SDK wholesale). | Fixed — each rewritten against an outcome or deleted. |
| B-39 | A docstring describing "colorway doesn't match" for a rule about a colorway *missing*. | Fixed. |

## Standards axis — frontend (35)

| # | Finding | Status |
|---|---|---|
| C-1 | **`TrustCertCard` never rendered**: its probe went through `apiFetch`, whose `resp.json()` rejects on a PEM, so "no CA" was the answer on every install. The test mocked `apiFetch` resolving `'cert'`, which cannot happen. | Fixed — a plain `fetch` and `resp.ok`; the test mocks a 200 whose `json()` rejects. |
| C-2 | `?next=` was honored only for an already-signed-in visitor; submit and passkey both went to `/`. | Fixed — `assign(next)` on both paths; test. |
| C-3 | The re-pricing card's "press again" hint compared `remaining` against `considered`, but `remaining` had meant "still due" since 2.76. | Fixed — `remaining > 0`. |
| C-4 | A 422's `detail` is an array; the client rendered `[object Object]`. | Fixed — `errorMessage()` flattens it; test. |
| C-5 | Ten Bootstrap-era classes used but styled by nothing (`col-7`, `table-sm`, `form-switch`, `badge bg-danger` with the severity inverted, …). | Fixed — defined or swapped; `styles/classes.test.ts` scans every class literal in TSX against `app.css`. |
| C-6 | `.form-control-sm` at 0.85rem zooms iOS on focus. | Fixed — 16px in the coarse-pointer block. |
| C-7 | **26 form controls with no accessible name** — Login's username and password, every API-key box, the whole Edit-hat form. | Fixed — `id`+`htmlFor` or `aria-label`; `test/accessibleNames.test.ts` scans every control and understands expression-valued ids. |
| C-8 | Mocks not of the real payload shape (untyped `vi.fn` factories defeat `tsc`); a second hand-written case literal. | Fixed — typed factories, `caseFixture()`. |
| C-9 | `navigator.clipboard` used without a secure-context guard — undefined on the http80 overlay, so the copy button threw. | Fixed — `lib/clipboard.copyText` with the `execCommand` fallback, used by all three copy sites; test deletes `navigator.clipboard`. |
| C-10–11 | Edit-hat saves that change a colorway or a manual price left `['admin','shared-prices']` stale; Activity's Refresh missed the sibling retention key. | Fixed. |
| C-12 | Server constants restated by hand (`STAGES`, `DEFAULT_HAT_BASICS`, `MAX_FILES`, the share-expiry seed, a `(default)` label, a placeholder typed as "e.g. 3"). | Fixed — `tests/test_frontend_constants_parity.py`; the default model comes from `ModelStatus.default_model_id`. |
| C-13–14 | Copy claiming analysis fills construction (it never does); "discounted for condition" on a figure used as-is. | Fixed, with tests on the help text. |
| C-15 | Dead effects (a re-sync on a modal that unmounts, a reset on a keyed card) and a dozen orphaned doc comments. | Fixed. |
| C-16 | British spellings, including the wire value `cancelled` (see A-15). | Fixed. |
| C-17 | A failed list fetch rendered as an empty collection with an "Add your first hat" call to action. | Fixed — `role="alert"`, no CTA; test. |
| C-18 | Hand-written `HatRead` literals in two tests. | Fixed — `hatFixture()`. |
| C-19 | **Five write paths outside `useMutation` swallowed their errors** — photo upload, eBay refresh, undispose, passkey removal, share-link revoke: a 413 or a dropped LAN un-pressed the button and said nothing. | Fixed — mutations with `.error` rendered; upload test. |
| C-20 | A per-case capacity override could be set but never cleared (the form omitted the field; the server read `None` as "leave it"). | Fixed — `null` on the wire, `model_fields_set` on the server; test. |
| C-21 | Inline `apiFetch` in two pages. | Fixed — `getColorwayOptions`, `api/share.ts`. |
| C-22 | Eight duplicated pieces: the nav error badge (one copy unlabeled), the two key cards, the ranked hat list (Stats/Valuation, already diverged), the case tile (Cases/Room, the room's had lost the full tag), the hat row, two time formatters with two output styles, two byte formatters, the click-outside effect. | Fixed — `AnalysisErrorBadge`, `KeyCard`, `RankedHatList`, `CaseTile`, `HatRow`, `lib/format`, `useClickOutside`. |
| C-23–25 | A hand-rolled invalidation list beside the helper for it; index keys under removal (Settings cards by `Function.name`, color rows, import files); Settings links with no section; a full-reload `<a href>`. | Fixed — stable keys (a local `rowKey` for colors, `name:size:mtime` for files, roster position for cards); `?tab=` on every link; `<Link>`. |
| C-26 | "Unassigned" meant `case_id == null`, which included every hat kept in a room. | Fixed — `lib/placement` (case / room / none); a third chip; the Duplicates caption. |
| C-27 | `<datalist>` for Model and Colorway (invisible on iOS — the reason `Combobox` exists) and a refetch per keystroke. | Fixed — `Combobox`; `useDebouncedValue` on the model-scoped query. |
| C-28–29 | In-app `<a href>` in charts and the import page; a clickable `<img>` with no role or keyboard path, a clickable `<div>` slide, no `aria-activedescendant`, nested lists in a listbox without `role="group"`, a toggle without `aria-expanded`. | Fixed. |
| C-30 | Edit-case re-seeded on every refetch (the bug Edit-hat had already fixed) and hardcoded room id `1`. | Fixed — seed once per case; no room until the case says. |
| C-31 | Four `var(--x)` tokens that nothing defined (`--hr-pink` on the card whose point was to turn red). | Fixed — real tokens; `styles/tokens.test.ts` scans every `var()` against the stylesheets. |
| C-32–35 | Redundant `uploading` state beside `isPending`; fetching 50 to render 25; `No case matches “”`; "Clear them" on a rename; the Valuation card hidden for a hat whose only figure was its manual price; the Settings test mock missing three exports; `orientation: portrait` locking the iPad; vocabulary keys stale after a save. | Fixed. The Settings mock is now **derived from the real module's exports**, so a new export can no longer fail the section. |

---

## Spec axis — `CLAUDE.md` vs code (19)

| # | Finding | Status |
|---|---|---|
| A-1 | The mDNS bullet ended with the NSEC sidecar as the resolution of the iPhone stall; 2.76.1 had found the real cause (Caddy advertising HTTP/3). | Doc fixed — the bullet says so, and the `127.0.0.1` sentence joined the certificate pattern. |
| A-2 | `_tls_watch_loop` undocumented. | Doc fixed — in the lifespan roster and the `ca_vault` bullet. |
| A-3 | "The harvest can use a BackgroundTask because it claims nothing" — it claims a slot and uses `create_task`; the background task imported the module session. | Doc and code fixed (see B-3). |
| A-4 | "Model matching is TOKEN CONTAINMENT" over an `ilike %token%` body. | Code fixed — set containment (see A-14). |
| A-5–7 | Repricing described as using `_sessions()` (it threads the factory); the share-expiry default described as impossible to express as the constant (it is the constant); `_model_tokens` cached "because scored twice per pair" (once, since Kuhn's). | Docs and comments fixed. |
| A-8–9 | A stale lazy-load comment; "asserts the union covers every card" overstated. | Fixed; the test's real shape is now stated. |
| A-10 | `Case.photo_path` "unread" but served by `CaseRead`. | Code fixed — dropped from the wire (a **wire change**; `HatSummary.photo_path` stays). |
| A-11–14 | `price_audit.py`, `GET /api/admin/config`, the autoheal/rsync overlays, the watchdog, `restore-construction.py`, the recut route, the upload endpoints, `/api/settings/tls`, `_PURCHASE_COLUMN_DDL` — all undocumented. | Docs fixed. |
| A-15–19 | Rosters that rot: the lifespan (missing five things), the Settings cards (19 of 25), what `conftest` disables (3 of 5), the "new tables" list, `GUNICORN_WORKERS`. | Fixed — the lifespan is now stated in code order with a note to update it; the card roster points at `SECTIONS`; the others corrected. |

## Spec axis — README / OPERATIONS / USAGE vs code (24)

| # | Finding | Status |
|---|---|---|
| B-1 | **The documented password-recovery recipe did not work**: `DELETE FROM users` left the `owner_setup_done` sentinel, so `/setup` answered "Setup already completed" forever — on an image with no `sqlite3` binary. Reproduced. | Code fixed — the sentinel is cleared when the users table is empty. Doc fixed — a recipe that borrows `sqlite3` from `alpine`. |
| B-2 | **Compose forwarded almost no `HEADROOM_*` variable to the app.** `HEADROOM_SETUP_TOKEN` in `.env` protected nothing; `HEADROOM_MDNS_HOSTNAME=hats` renamed Caddy's site while the app advertised `headroom.local`. | Code fixed — a passthrough block (`${VAR:-}`), empty treated as unset (`env_ignore_empty`, `env_flag`); `tests/test_env_passthrough.py` parses the compose file against every name the code reads. Docs say so. |
| B-3–5 | "honors X-Forwarded-For from loopback only" on the LE overlay (it is the compose subnet); "token survives password change" (it rotates); "the token is at `GET /api/auth/me`" (it is not, by design). | Docs fixed; the `/me` docstring fixed. |
| B-6–8 | "sold-comparable" eBay (live asks); "Claude's estimate" of retail (looked up first); the re-pricing subsystem — four env vars, three routes, a card — undocumented; "refreshes on every analysis". | Docs fixed in all three files. |
| B-9 | The open-route roster omitted the whole `/api/public/*` prefix and the guest view, and the protected OpenAPI documents. | Doc fixed. |
| B-10 | The watchdog unit's default URL fails every poll on the Let's Encrypt overlay (`:8000` unpublished) → a restart every third minute. | Doc fixed — the `Environment=` line and the script's knobs. |
| B-11 | The `/health/ready` sample lacked `disk` and `workers.expected`; the 503 conditions and the anonymous shape were wrong. | Doc fixed from the route. |
| B-12–16 | Share links "optionally expiring" (30 days); duplicate env rows and `See §6` in a file with no sections; the rsync overlay and its two mounts unnamed; `HTTP_TIMEOUT` "covers eBay" (fixed timeouts); Settings tabs never documented and "This device" throughout. | Docs fixed — the README table deduplicated, linked to OPERATIONS anchors, and given its eight missing rows. |
| B-17–19 | Undocumented cards and flows (construction audit, frozen prices, shared prices, the analysis queue's retry and run logs, the model picker, ✂ Redo cutout, the purchase-import prompt → preview → import flow, the upload caps); operator endpoints; two stale pill labels. | USAGE and OPERATIONS fixed. |
| B-20–24 | 171 vs 179 MB; "three" cache mounts (five); a route roster missing five modules; "an extra field appears" (always shown); "UI always wins" (the upload command doesn't); the fingerprint's CA coverage and the restore recipe's `-f` flags and `caddy-pki` exclude; host networking's UDP 5353. | Docs fixed. |

## Spec axis — CHANGELOG and cross-doc consistency (21)

| # | Finding | Status |
|---|---|---|
| C-3–4 | `CLAUDE.md`'s "168 → 33" conflated two figures the changelog had already separated; `_improve_by_swapping` described as two moves (three) and the visit order as load-bearing (a fast path). | Doc fixed. |
| C-5, 15, 16 | Three false changelog facts: "962 → 971; 240 → 243" (measured 956 → 971; 239 → 243), "fifteen sites" (twelve), "fsyncs the file and its directory before rename" (file → rename → directory). | Corrected in place, each with a note that it is a correction. |
| C-18 | Test comments citing audit ids with no row (`S1`, `S3`, `S4` meaning something else). | `docs/AUDIT-HISTORY.md` gained the rows. |
| C-19 | `[2.24.0]` and `[2.23.1]` never tagged. | Headings annotated. |
| C-21 | Spellings across four docs. | Fixed; lines that quote a misspelling as their subject, and data values, left alone. |
| rest | The remaining ~13 were duplicates of B-axis findings, fixed under those. | Covered above. |

---

## Deliberate non-fixes

- **RGB stays the palette-name metric** (A-21) — measured, documented on `nearest_color_name`.
- **Two mutations legitimately survive** the matcher suite: reversing the purchase visit order (the improvement pass carries the result) and swapping the `manual`/`comp` branches in `valuation.value_hat` (a hat has one scope). Both named in `CLAUDE.md`.
- **The 3-cycle rotation** the local search cannot find is pinned by a test as the known blind spot rather than solved with min-cost max-flow the collection does not need.
- **`"grey"` as a fixture color name** in `tests/test_search.py` is data through the normalizer, not prose.
- **`Case.photo_path` the column** stays — dropping it is a destructive migration and a decision, not a side effect. Only the wire field went.

## What changed about how this repo is reviewed

- **Mutation, not coverage.** `CLAUDE.md` now says how: change one constant, run the suite, and if it stays green the code is covered and unconstrained.
- **Source-scanning parity tests** for the properties that are static — CSS classes, accessible names, design tokens, server constants restated in TSX, the compose passthrough, the OpenAPI contract, the npm pin.
- **Seams are module-attribute calls.** `PLC0415` is enforced; a function that must follow a monkeypatch calls `module.fn(...)`, never `from module import fn`.
- **Rosters that will rot are either derived or pointed at.** The Settings card list points at `SECTIONS`; the Settings test mock is built from the real module's keys; the lifespan roster is stated in code order with the instruction to update it.
