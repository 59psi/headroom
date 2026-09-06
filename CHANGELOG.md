# Changelog

All notable changes are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Internal engineering notes and security-review records are no longer tracked
  in this public repository. `CLAUDE.md`, the `docs/CODE-REVIEW-*.md` files and
  `docs/AUDIT-HISTORY.md` are now local-only and gitignored. Nothing in the
  build, the test suite or CI referenced them, so the project still builds,
  tests and ships from a fresh clone.
- Historical changelog entries have been condensed. Every release still records
  what changed and what to do about it — including each breaking change,
  renamed variable and migration step — but no longer walks through how a
  since-fixed weakness could have been abused. `docs/OPERATIONS.md` and
  `docs/USAGE.md` are unchanged and remain the operator documentation.

## [2.79.0] — 2026-09-06

A whole-project review pass, verified by running a live instance against each
finding rather than by reading the code.

### Security

- Login now performs equal work for known and unknown usernames, and rate
  limiting gained a second per-address bucket alongside the existing one.
- Request body size limits are chosen by the endpoint rather than by the
  client-supplied `Content-Type`; upload routes keep their own larger ceiling.
- Database errors can no longer carry bound query parameters into logs or the
  stored error record.
- The hat-photo route answers 400 rather than 500 for an undecodable upload,
  matching the logo route, and both share one decoder with a central pixel
  ceiling.
- The login page's `?next=` parameter is resolved against the real origin, so
  only same-origin paths are honored.
- Session cookie attributes (`HttpOnly` / `SameSite` / `Secure`) are pinned by
  a test.
- The test suite can no longer reach the network through any HTTP client.

### Data integrity

- Concurrent placement can no longer overfill a case or duplicate a shelf
  label: an in-process lock serializes every placement writer, with a partial
  unique index as the backstop. Concurrent imports of one order file no longer
  duplicate rows.
- The purchase-import body is validated line by line — it was the one request
  body with no schema.
- Money and text are validated at the wire everywhere: non-finite and negative
  prices are refused, names and notes are length-capped and stripped of
  bidirectional and NUL control characters, a dispose price is rejected for a
  non-sale channel, and a wear date cannot be in the future.
- Timestamps carry their zone on the wire — every `DateTime` column is now
  UTC-aware, so browsers stop reading them as local time.
- Restoring a hat into a full case no longer 500s, and a crash between a
  bulk-import hat row and its photo no longer leaves an orphan or a duplicate
  on re-run.
- Deleting a hat returns its receipt to the matching pool.

### Correctness

- "Redo cutout" re-cuts only. It no longer spends a Claude call or overwrites
  analyzer-written fields.
- A re-pricing sweep the marketplace never answered is recorded as a failure,
  and the hats it could not reach are not stamped to the back of the queue.
- A colorway harvest that loses every category reports the failure instead of
  claiming the counts are current.
- One reading of a product name across the catalog matcher, the marketplace
  pricer and the analyzer — they had disagreed, so a quoted or fullwidth name
  could be priceable and unmatchable at once.
- Search matches a style as printed (`A-Game`, not only `a_game`), treats `%`
  and `_` as literal text, and a filtered-to-empty result no longer strands the
  filter that produced it.
- The vocabulary tiebreak counts real rows, so a typed `neon` snaps to the
  spelling most in use.

### Reliability & ops

- A scheduled backup interrupted mid-write no longer leaves a partial archive
  under a real name: it writes under `.partial` and renames only when complete,
  and the app gets a 60 s stop grace period.
- The Let's Encrypt overlay stops advertising HTTP/3 it cannot serve; a
  Caddyfile adds HSTS and compression, and both Caddyfiles compress responses.
- The CA export no longer defeats the backup change-gate — the fingerprint
  hashes content and the sidecar copies only what changed.
- Every `HEADROOM_*` knob degrades to its default on a bad value.
- Image and compose hardening: `/app` is root-owned, the base compose runs the
  app read-only, and the container declares its own healthcheck. The rembg
  model is found at runtime (`U2NET_HOME`) instead of re-downloaded on the
  first analysis. Responses carry a caching policy by path class.
- Dependabot can see the uv pin again (a `FROM` line, not a `COPY --from=`) and
  now tracks the compose overlays' images; CI SHA-pins its actions and carries
  per-job timeouts.

### Breaking

- Stricter validation rejects request bodies that earlier releases stored as
  garbage: non-finite or negative money, a purchase line with `quantity` beyond
  20 or a non-numeric price, a dispose price on a gift/loss, a future wear
  date, a model id that is not `[A-Za-z0-9._:-]`, a tag base URL with no host.
  Correct clients are unaffected. `SharedHat` gains `thumb_url` (additive).

## [2.78.0] — 2026-09-06

The whole project reviewed on both axes and fixed in one pass. Backend tests
997 → **1036**; frontend 253 → **278**.

### Breaking (wire level — no client of this API exists but the SPA, which moved with it)
- **`ImportJob.status` and `ImportJobItem.status` say `canceled`, not
  `cancelled`**, and the activity kind is `import.canceled`. Stored rows are
  rewritten on every boot by three static, idempotent `UPDATE`s, so a
  downgrade-then-upgrade cannot strand one.
- **`CaseRead` no longer carries `photo_path`.** There is no case-photo
  feature; the field was published to every client and read by none.
  `HatSummary.photo_path` — a hat's — is unchanged.
- **`HatDispose.via` is validated** (`DisposedVia`), so an unknown channel is a
  422 rather than a stored typo. `GET /api/settings/model` gained
  `default_model_id` so the card can label the default without a second copy of
  the value in TypeScript.
- **Every route declares a `response_model`.** Around twenty returned
  hand-built dicts and were therefore invisible to the TypeScript types.
  `tests/test_api_contract.py` enumerates the OpenAPI document and fails on any
  2xx without a schema.

### Fixed — things that did not work
- **A second passkey could not be registered.** `exclude_credentials` was
  passed as dicts, which py_webauthn 3.0's `options_to_json` cannot read, so the
  second registration failed on every install. The test now registers twice.
- **The documented password-recovery recipe did not work.** The setup marker
  outlived the users table, so `/api/auth/setup` answered "Setup already
  completed" forever — on an image that ships no `sqlite3`. The marker is now
  cleared when the users table is empty, and the recipe borrows `sqlite3` from
  `alpine`.
- **Compose forwarded almost none of the documented `HEADROOM_*` variables to
  the app.** A `.env` beside the compose file is interpolation for Compose, not
  the container's environment, so the re-pricing knobs, the disk floors, the
  body cap, the SQLite durability setting and the mDNS hostname reached
  nothing. Every knob is now in a passthrough block as `${VAR:-}`, an empty
  string is treated as unset everywhere, and `tests/test_env_passthrough.py`
  parses the compose file against every name the code reads.
- **The Trust-this-device card never rendered.** Its "is there a local CA"
  probe went through the JSON client, which rejects on a PEM. It uses a plain
  `fetch` and `resp.ok` now.
- **Five write paths swallowed their errors.** Photo upload, eBay refresh,
  undispose, passkey removal and share-link revoke were bare `await`s in click
  handlers, so a failure un-pressed the button silently. All are `useMutation`s
  with the error rendered.
- **`?next=` on sign-in was honored only for a visitor already signed in**;
  submitting the form or a passkey went to `/`. A tag tapped with an expired
  session now lands on the hat.
- **A 422 rendered as `[object Object]`.** The `detail` is an array.
- **Bulk import committed the hat row before decoding the photo**, so a bad
  file left a photoless hat forever. Decode first; the created id is cleaned up
  on failure.
- **A per-case capacity override could be set but never cleared**: the form
  omitted an emptied field and the server read `None` as "leave it". The form
  sends `null`; the server reads `model_fields_set`.
- **A case's detail listed its disposed hats** while its counts excluded them.
- **The inventory report summed disposed hats into the current total** when
  asked to include them.
- **`ebay_listing_count` was `len()` of a 25-row page**; the Browse response
  carries `total`.
- **`docker-compose.http80.yml` proxied to `localhost`** — `::1` on a
  dual-stack host, and a 502. Now the v4 loopback, and the test that guards the
  Caddyfile greps the compose file too.
- **The inline reanalyze path was unguarded** when the worker is off, so a
  non-Claude error left the hat `pending` forever. One guard for the three
  inline paths.
- **`upload_logo` deleted the old logo before checking the new one**, so an
  oversize or corrupt upload left no logo at all. Three modules each held their
  own list of what counts as a logo and one lacked `.jpeg`; `utils/branding.py`
  is the one list now.
- **A module-level `HTTPException` re-raised per request grew its traceback
  without bound**, pinning a request and a database session each time.
  Factories now, with a test asserting no module-level exception holds a
  traceback.
- **The re-pricing scheduler swept the whole shelf on every boot.** There was
  no staleness gate; `stale_before` is threaded from the loop to the query.
- **`_publish_stage`, the only writer of the analysis stage, reached for the
  module-level session**, so stage writes had never been observed by a test. It
  now uses a session maker bound to the pipeline's own engine.
- **Ten Bootstrap-era classes were styled by nothing**, **26 form controls had
  no accessible name** (Login, every API-key box, the whole Edit-hat form), and
  **four `var(--x)` tokens were defined nowhere**. All fixed, and each class of
  bug now has a source-scanning test.
- **"Unassigned" meant `case_id == null`**, which included every hat kept
  loose in a room. Three states now (`lib/placement`).
- **Edit-hat's Model and Colorway were `<datalist>`s**, which iOS draws as an
  easily-missed strip above the keyboard, and the colorway lookup refetched on
  every keystroke. Comboboxes, and a debounced query.
- **The harvest's colorway picker matched `hydro` inside `hydrolite`**, so an
  A-Game Hydro hat was offered HYDROLite colorways. Set containment in Python
  behind a cheap prefilter.
- **`_product_comp` matched colorways by containment** while the catalog
  validator used equality, so `Camo` was priced against `Rain Camo`. Equality on
  the colorway half.
- **Colorways were not canonicalized on the edit form's PUT or on the matcher's
  write** — only on the analysis path.
- Edit-case re-seeded the form on every refetch and started with a hardcoded
  room id rather than the flagged default.
- The re-pricing card's "press again" hint compared the wrong two counts.
- Edit-hat saves that change a colorway or a manual price left the shared-price
  report stale; Activity's Refresh missed the sibling retention key; a
  first-time construction or collection did not appear in the next form's
  picker for 30 s.
- The Valuation card was hidden for a hat whose only figure was the resale
  price the owner had just typed.

### Changed
- **`PLC0415` is enforced** (no imports inside functions), with `RUF100` (no
  unused `noqa`). The local-import idiom had spread to ~90 sites and is how
  late-binding test seams break silently; nine tests failed the moment the
  imports were hoisted. A seam that must follow a monkeypatch is now a
  module-attribute call, and every surviving `noqa` carries its reason inline.
- **Constants and enums replace strings and copies.** `ResaleScope`,
  `DisposedVia`, the construction tokenizers (four became one), `PAGE_SIZE`
  shared by the harvest and the pricing client, `MAX_TOTAL_UPLOAD_BYTES`, the
  capacity figures (typed by hand in four source files and eleven tests), and
  `hat_loads()` made public.
- **Frontend duplicates folded into shared components**: the nav's
  failed-analysis badge, the two API-key cards (one `KeyCard` over a
  `KeyProviderSpec`), the ranked "top N" list, the case tile, the hat row, two
  time formatters, two byte formatters, the portalled-list click-outside rule,
  and the clipboard routine (three copies, one with no secure-context
  fallback).
- **Every Settings link names its section** (`?tab=analysis|data|sharing`); a
  chart row and the import page's "view hat" are `<Link>`s rather than full
  reloads; the lightbox thumbnail is a real button opening a dialog Escape
  closes; the home carousel slide is a link; the combobox announces its active
  option; the case picker's groups are groups; the filter toggle says whether
  it is open. The manifest no longer locks the iPad to portrait.
- **Rosters that rot are derived or pointed at.** The Settings test's
  `api/settings` mock is built from the real module's exports, and the lifespan
  roster is stated in code order.
- **Off-loop where it wasn't**: the per-file copy in `create_job`, the logo's
  Pillow work, the upload cap's copy, multi-MB PNG reads for Claude and Vision,
  QR rendering, and Kuhn's assignment. `AsyncAnthropic` is opened with
  `async with` and closed; the marketplace client is shared across pages; EXIF
  orientation is honored on upload.
- **The stored palette name stays RGB-nearest, and that was measured rather
  than tidied**: over a 512-point grid the RGB and CIEDE2000 nearest-name
  answers disagree on 39% of points, and ΔE calls pure blue "purple". Palette
  LAB is precomputed and the target's families computed once per search.
- The Activity card fetches the 25 rows it renders; `LogoCard` reads
  `isPending` instead of shadowing it; the construction audit's button says
  "Change them" on a rename; the case picker's empty state distinguishes no
  query from no match.

### Tests
- **Mutation testing is the documented method** for anything that writes a
  number. The score/tier assertions that had crept into the outcome-only
  matcher suite are outcomes again.
- **Fifteen per-endpoint "requires auth" assertions removed** across twelve
  files; the enumeration test that probes every operation is the guard.
- **Tests that asserted nothing or the wrong thing** were rewritten against an
  outcome or deleted, and fixture state that leaked across tests (backup
  health, sweep progress, the rate limiter, the session factory) is reset by
  autouse fixtures and `try/finally`.
- New parity tests: `test_api_contract`, `test_env_passthrough`,
  `test_frontend_constants_parity`, the npm-pin check, the
  `_CASE_COLUMN_DDL`/`_HAT_COLOR_COLUMN_DDL` coverage checks, and on the
  frontend `styles/classes`, `test/accessibleNames`, `styles/tokens`,
  `lib/format`, `lib/placement`, `lib/clipboard`, `api/client`, `api/settings`.
- Typed mock factories (`vi.fn<typeof fn>`) and a shared `caseFixture()`, so a
  payload that drifts from the real shape fails `tsc`.

### Documentation
- **README / OPERATIONS / USAGE**: the compose passthrough; the working
  password-recovery recipe; `FORWARDED_ALLOW_IPS` on the Let's Encrypt overlay;
  how the API token is actually obtained and rotated; eBay as live asks; retail
  as a lookup; the re-pricing subsystem, its four env rows and its card; the
  guest view and the full open-route roster; the watchdog's URL on the LE
  overlay and its knobs; the real `/health/ready` payload and 503 conditions;
  the 30-day share default; the README env table deduplicated, anchored and
  given its eight missing rows; the rsync overlay named with its two mounts;
  the five Settings tabs and every card USAGE had never mentioned; the
  purchase-import flow as the card actually presents it.
- **CHANGELOG**: three inaccurate statements corrected in place; `[2.24.0]` and
  `[2.23.1]` annotated as never tagged; British spellings across four
  documents.

## [2.77.3] — 2026-09-05

The other three background workers, booted for real under test.

### Fixed
- **Three workers could not be booted under test at all.** `import_service`,
  `analysis_queue` and `backup_service`'s upload hook each reached for the
  module-level session factory directly (twelve sites), so the lifespan could
  start none of them. Each takes `session_factory=` now, resolved at call time
  so existing monkeypatches keep working. Three new boot tests turn each on and
  assert the outcome against the app's database: a crash-stranded import item is
  healed by the boot sweep; a `pending` hat is re-queued and processed; the
  backup scheduler writes its first archive and the upload hook resolves its
  argv through the right database.
- **The lifespan tests were racing on a shared connection.** The suite's
  in-memory engine is a `StaticPool` — one connection for every session — so one
  session's `close()` could discard another's uncommitted work. The lifespan
  module now runs on a file-backed SQLite with the production connect hook
  attached (WAL, busy_timeout, synchronous=FULL), one connection per session as
  on the box. That also made a real assertion possible: after a clean shutdown
  the file's `-wal` sidecar is zero bytes.


## [2.77.2] — 2026-09-05

Two things the suite could not see, made visible: the lifespan, and the SDK
call behind the core feature. Plus the dependency queue, taken properly.

### Fixed
- **No test had ever run the lifespan** — the one function wiring the app
  together (which loops start, which one-time backfills run, what seeds the
  health records, what shutdown cancels and in what order) was the one function
  the suite never executed. It now takes `app.state.session_factory` and
  `app.state.engine`, the seam the auth gate already used, and
  `tests/test_lifespan_wiring.py` boots it for real: the prune runs and records;
  the endpoint serves the record; every backfill flag is stamped once and not
  re-run on a second boot; branding seeds once and never overwrites the owner's
  logo; disabled workers produce `None` not a dead task; shutdown stops workers
  then checkpoints the WAL last on the app's engine; a raising stop step does
  not skip the ones after it.
- **The suite was writing to a real database file on every run.** A bare
  `checkpoint_wal()` opened the module engine, creating an empty `./headroom.db`
  in the working directory. `conftest` now points the module engine at an
  unopenable path so the same slip raises immediately; the guard found a third
  site in production code.
- **The Claude Vision call is now exercised through the real SDK.**
  `tests/test_claude_call_shape.py` drives the real `anthropic` client against
  an in-memory transport: the cached `system` block, the forced `tool_choice`,
  image-then-owner-facts order, the tool-use parse, and the error mapping.
  Written to make the SDK major bump below safe, and it is what proves it was.
- **The zeroconf NSEC notes were out of date.** The owner-name defect described
  there was fixed upstream in 0.150.4; verified against the installed 0.151.2
  that upstream's fix attaches an NSEC only to *address* answers, so a query for
  `HTTPS`/65 or `SRV` at the hostname is still silence and the sidecar responder
  remains the only thing answering it.

### Changed
- **Dependencies, the whole lock, taken on this branch** rather than merging a
  Dependabot PR that moved `requirements.txt` without `uv.lock`.
  `uv lock --upgrade` took everything within `exclude-newer` and regenerated the
  export: `anthropic` 0.122.0 → **1.2.0** (a major; the SDK surface in use was
  checked empirically and is covered by the new call-shape tests;
  `AuthenticationError` now imported from the package root), `zeroconf` 0.150.0
  → 0.151.2, `argon2-cffi-bindings` 25.1.0 → 26.1.0, `pydantic` 2.13.5,
  `pydantic-core` 2.46.5, `ruff` 0.16.5, `scipy` 1.18.1, `protobuf` 7.36.0,
  `websockets` 17.1, `click` 8.5.0, `platformdirs` 4.11.5, `tifffile`
  2026.8.23, `coverage` 7.16.0; `distro` dropped. Frontend Dependabot PR merged
  as is.

### Added
- `app.state.boot_tasks` — the lifespan's one-shot boot work (thumbnail and
  export backfills, mDNS start), published so a test can await it before
  shutting down.
- `claude_analysis._anthropic_client` — the one place an SDK client is built.
- `init_db(bind=, session_factory=)`, `checkpoint_wal(bind=)`,
  `ensure_default_room(session_factory=)`,
  `reattach_orphaned_cases(session_factory=)`,
  `repricing.start_repricing(session_factory=)` — all default to the module
  globals, so production is unchanged.


## [2.77.1] — 2026-09-05

The test suite, measured by what it constrains rather than what it executes.
No user-visible behavior changes; one source comment corrected.

### Fixed
- **The purchase matcher's scoring was covered and unconstrained.** Line and
  branch coverage read 93%, yet zeroing both bonus tiers, deleting the local
  search's only call site, disabling the exact-price tiebreak, collapsing the
  stripped-model tier and dropping `colorway` from the preview each left the
  suite green. `tests/test_matcher_evidence.py` pins each as an **outcome**
  (which receipt links to the hat, which price lands on it), never a score, and
  every test was confirmed to fail under the mutation it names.
- **The `assign_purchases` ordering comment described a mechanism that no
  longer carries the result.** The local-search pass recovers from any starting
  order, so the visit order is a fast path and tiebreak, load-bearing for
  neither. Written down as such.
- A test docstring still carried an overstated claim that the previous release
  had retracted. Fixed at the source.

### Removed
- **Fifteen per-endpoint "requires auth" tests across twelve files.** Each was a
  strict subset of the enumeration test that probes every operation anyway. The
  two that stay cover a mount and the spec itself, which the enumeration cannot
  reach. 988 → 980 tests, strictly more constrained.

### Measured and left alone
- Valuation and pricing were probed the same way and hold: reordering
  `category` above `retail`, ignoring the retention multiplier, and disabling
  the product-first comp each fail — by outcome tests, not only parity checks.
  Swapping the `manual` and `comp` branches survives and correctly so: a hat has
  one scope, so the two are mutually exclusive and the mutant is equivalent.


## [2.77.0] — 2026-09-04

The review backlog, in full. Every fix here is sabotage-checked — the bug
reinstated, the test confirmed to fail with the right symptom.

### Security
- **`GET /api/auth/me` no longer returns the API token.** Reading it is now
  `POST /api/auth/token/reveal` with the current password, and **rotation is
  gated the same way**, since rotate returns the new token.
- **Share links expire in 30 days unless you choose otherwise.** A link is
  unscoped and whole-collection, and "Never" was both the default and invisible.
  The card now offers 7/30/90/365/Never and states each link's expiry.
  `expires_days: null` still means never.
- **Share tokens are redacted everywhere a request path is recorded** — the
  stored error record and the log line beside it, not only the access log. One
  helper owns the rule and all three sinks use it.
- **`HEADROOM_SETUP_TOKEN` gates first-run setup when set.** Opt-in, because
  requiring it always would put a mandatory step between `docker compose up`
  and a working LAN app. A wrong token answers exactly as a claimed box does.
- **A comment credited a destination regex with a guard it does not have.**
  The check that actually rejects flag-shaped input is an explicit one; the
  comment pointed at the wrong guard while making the real one look redundant.
  A test now covers an input the regex accepts and the explicit check refuses.
- **Client-IP behavior on the plain bridge compose is documented** — it may be
  the Docker gateway, which affects per-IP rate limiting and the address
  recorded on login rows. All three LAN overlays use host networking and are
  unaffected.

### Fixed
- **Purchase matching gave a contended hat to the wrong receipt, and the local
  search called it a fixpoint.** The two existing moves could not move the
  *purchase* end of a pair — exactly the shape the augmenting step creates. A
  third move (substitute a held hat's purchase for an unheld one that scores
  higher) closes it; cardinality is untouched, so the maximum-matching guarantee
  still holds. The real remaining limit — a 3-cycle rotation is still missed —
  is now pinned by a test rather than asserted in prose.
- **Whole-collection views silently dropped everything past 1000 hats.**
  `GET /api/hats` caps `limit` at 1000 while the Hats grid, Valuation, Stats and
  the Home carousel all ask for the lot, so a larger collection looked smaller
  and worth less. The server already published the real size in `X-Total-Count`
  and nothing read it. `listAllHats` now pages.
- **The retention prune had no health record** — the only background task with
  none, and the only thing bounding `activity_log` and `auth_sessions`. Now at
  `GET /api/admin/activity-log/retention` and on the Recent Activity card.
- **Per-category isolation in the colorway harvest only caught one error
  type.** The stated property is "one bad category cannot abandon the rest", so
  anything else escaped and killed the whole run.
- **The colorway card re-enabled its button during the window a harvest is
  claimed but not yet running.** `harvest_in_flight()` existed for exactly this
  and had no caller; the card guessed with a local 30-second timer.
- **A comment described the upload-state write in the wrong order.** The code
  does file-fsync → rename → dir-fsync, which is correct; anyone "correcting"
  the code to match the comment would have removed the durability guarantee.
- **The staging directory could be deleted while an import item was still
  reading from it.** The guard against that had zero coverage; it now has both
  halves.
- Documentation fixes: three files cited the wrong operations section for the
  systemd units; `HEADROOM_BACKUP_INCLUDE_CA` was described in prose but missing
  from both env tables; several British spellings.


## [2.76.1] — 2026-09-04

Two Caddyfile fixes found by measuring the live deployment. Both are one-line
config changes and neither needs an image rebuild — the Caddyfile is
bind-mounted, so `docker compose restart caddy` applies them.

### Fixed
- **`https://headroom.local` was slow on the first load after idle, on iPhone
  only — and it was never mDNS.** Caddy advertises HTTP/3 by default, so Safari
  attempts QUIC on every fresh connection and remembers the advertisement for
  thirty days. Measured against the live box, every request negotiated h2 and
  none ever negotiated h3, so the advertisement bought nothing and cost a failed
  attempt before the TCP fallback each time. `servers { protocols h1 h2 }` stops
  offering it.

  It hid for a long time because it is invisible to the usual tools: `curl` and
  Firefox do not attempt h3, and `:8000` sends no `Alt-Svc` — which is exactly
  why "switch to the IP and it's instant" looked like a name-resolution problem.

- **Intermittent 502s from the reverse proxy.** `reverse_proxy localhost:8000`
  resolves to `::1` first on a dual-stack host while uvicorn binds `0.0.0.0`, so
  Caddy dialed the v6 loopback, got `connection refused`, and returned 502
  instead of retrying v4. Now `127.0.0.1:8000`. This also affected the
  Caddyfile's own claim about trusting proxy headers from loopback: `::1` and
  `127.0.0.1` are not the same peer to `FORWARDED_ALLOW_IPS`.

### Internal
- Two tests pin both directives, because deleting either breaks nothing a
  laptop would notice and makes the phone slow again. Both sabotage-checked.
  Backend 971 → **973**.

## [2.76.0] — 2026-09-04

Everything a ten-agent archaeology pass found, fixed. Two of its
recommendations were tested and **rejected** — noted below, because a report is
not a mandate.

The recurring shape across all of it: **this app builds excellent measurements
and connects them to nothing.**

### Fixed — unattended-failure blindness

- **The nav error badge read 0 during a total analysis outage.** It and the
  Settings error list keyed on `analysis_status == "error"`, but when Claude is
  unreachable the pipeline degrades to `fallback` — so in the one situation
  where every hat has failed, the badge was silent and the failures card listed
  the whole collection. Both now key on the failure text.
- **Nothing consumed the container healthcheck.** Docker restart policies fire
  on container *exit*, never on `unhealthy`, so the disk-space floor and
  worker-liveness gate terminated in a `docker ps` string. Two consumers now
  ship: `scripts/headroom-watchdog.sh` with systemd units (no privileges), and
  an opt-in `docker-compose.autoheal.yml`. Autoheal is **not** in the base
  compose because it needs the Docker socket, which is root-equivalent on the
  host.
- **The TLS and CA checks had no caller that was not a request handler**, so a
  long-expired certificate was visible only to someone already looking at the
  page — and the CA check seeds its expected fingerprint on first sighting, so a
  root regenerated before anyone opened that card was recorded as correct. A
  daily lifespan probe now runs both and seeds at boot.
- **A broken off-site destination sat behind a green card.** The argv resolver
  returned `None` both for "nothing configured" and "configured but no longer
  valid". The second case now raises and is recorded; the first stays silent,
  because declining the feature is not a fault.

### Fixed — matching and pricing

- **Purchase assignment maximized link COUNT, not evidence.** Among assignments
  of the same maximum size, which purchase got which hat was decided by
  candidate count and then row order, so a receipt agreeing on colorway, size
  and price to the cent could lose to a line sharing only a model name —
  writing the loser's cost basis onto the hat. Purchases are now visited in
  descending top-score order and a local-search pass runs swaps and relocations
  to fixpoint. Both moves preserve cardinality exactly. Not claimed to be
  globally weight-optimal — that needs min-cost max-flow.
- **`_by_scarcity` is deleted.** It had no call site while its own docstring and
  a test docstring both described it as load-bearing. Kuhn's cardinality is
  order-independent, which is exactly why nothing failed when it rotted.
- **`_product_comp` let a colorway token be satisfied by the model half**, so a
  hat could be priced as a different product. The halves of `<Model> -
  <Colorway>` are now checked separately.
- **The colorway harvest took neither claim nor lock** while the structurally
  identical re-pricing endpoint had both, so two harvests could interleave
  inserts and one would die on a uniqueness violation.
- **Re-pricing's `remaining` never decreased**, so the card could never say
  "done". It counted every eligible hat rather than those actually due.

### Fixed — security

- **`/openapi.json`, `/docs` and `/redoc` are now behind the auth gate**, which
  previously matched on a fixed set of path prefixes that none of the three
  begin with.
- **The open set is pinned by a test.** It enumerates the OpenAPI document,
  probes every operation anonymously, and fails unless each either 401s or
  appears on an explicit allowlist.
- **Share-link tokens are redacted from the access log** by a logging filter;
  existing links keep working.
- **The rate limiter's tracked-key bound is now enforced**, not just declared —
  the only eviction had been an age sweep.
- The off-site backup warning now appears **where the destination is typed**,
  not only inside the archive it warns about, with `rclone crypt` setup in
  OPERATIONS §4. Next-URL normalization handles backslashes; the export sink
  validates hex values; `FORWARDED_ALLOW_IPS` is a pinned CIDR instead of `*`.

### Fixed — claims that were false

- A documented lazy-load hazard does not exist (`Hat.case` is `lazy="selectin"`),
  and the admin router roster omitted two live routers.
- A `# noqa — cycle` annotation in `melin_recap` marked a cycle that is not
  there.
- The NSEC bitmap claimed an AAAA record on IPv4-only hosts — a negative answer
  naming a type we cannot serve, which tells a client to keep waiting.
- `FALLBACK_RETENTION` was module-private on both sides and therefore outside
  the parity check; mutation testing showed swinging it 125% left the suite
  green.
- `test_capacity_parity`'s placeholder guard was scoped to `pages/` only, so it
  silently stopped covering anything that moved out.
- A count in `pyproject.toml` was exactly right when written and 18% stale a
  week later. Removed rather than corrected.

### Rejected after testing

- Dropping the whole-name disjunct in the title ladder. Once a prefix equals the
  hat's *full* model name the comparison really is "listings of this model".
  Four tests pinned it and were right.
- A second module global for the NSEC held-types. Written that way first, it
  leaked across tests within the hour; derived from `_ipv6` instead.

### Added

- `docker-compose.autoheal.yml` and `scripts/headroom-watchdog.sh`.
- `X-Total-Count` on `GET /api/hats`, plus a warning when the cap is reached —
  a ceiling hit silently is a wrong number, not a short page.
- `cryptography`, `starlette`, `numpy` and `pydantic` declared explicitly.

### Internal

- The import worker confirms no item is still live before deleting a job's
  staging directory, rather than trusting a counter a boot recount rewrites.
- `record_upload` fsyncs the file, renames it into place, then fsyncs the
  directory — the order that makes the rename durable.
- Backend 956 → **971**; frontend 239 → **243**. (Measured by checking out the
  tags; the figures first written here, 962 and 240, were a guess.)

## [2.75.3] — 2026-08-30

A second, adversarial review of the same range (2.72.0 → 2.75.2), with both
axes told to assume the code is wrong and to verify by running it. Three of the
findings are defects in 2.75.2 — the release that fixed the first review's
findings — and two of those are in its tests.

### Fixed
- **`is_real_product` leaked in the other direction, and the test could not see
  it.** 2.75.2 pointed colorway containment `catalog ⊆ hat`, which accepts a
  colorway carrying extra words — the exact string the repair it guards
  produces. Single-word colorways are the common case, and every one of them
  validated anything containing it. Whatever survives is written to the hat, and
  a stored colorway vetoes in the purchase matcher, so an invented one ruled the
  hat out of its own receipt. The colorway half is now token-set **equality**,
  which the docstring already promised; the model half keeps its `hat ⊆ catalog`
  asymmetry, which the photo justifies. New test uses one-token fixtures.
- **The scheduled sweep never claimed the full-sweep slot**, so during the
  nightly loop both re-pricing routes asserted a property the code did not have:
  "Re-price all" would start a second full pass and "Re-price now" would skip
  its 409 and block on the lock for the whole run. Every full sweep claims now,
  scheduler included.
- **The regression test named for the sweep race did not test the race.** It
  asserted both presses swept the whole shelf — the opposite of the name on the
  door — and passed identically with the old broken guard restored, because the
  test transport made the two requests strictly sequential. Rewritten to block
  in the only window in which a sweep is claimed but not yet visible, and it now
  asserts it is in that window before pressing again.
- **"Re-price all" could disable itself permanently.** Starlette runs a
  background task only after the response body is sent; if that send fails the
  task never runs, nothing releases the claim, and both routes are dead for the
  life of the process. Scheduled with `asyncio.create_task` now, which the event
  loop runs regardless of the response.
- **The model-name backfill committed the destruction before writing its own
  undo.** It is the one repair that destroys information rather than recomputing
  it, so a crash between the two commits left truncated names durable with no
  record of what they had been. Record and mutation now land in one transaction,
  and the docstring stops implying the undo is permanent — activity rows prune
  at `HEADROOM_ACTIVITY_LOG_RETENTION_DAYS` (default 90).
- **The backfill logged sizes as colorways.** The splitter also takes
  parentheses, which hold `(Small)`, `(S/M)`, `(Classic)` and `(2-Pack)` as
  often as artwork. Stripping them is right either way; the audit field is now
  `dropped`, not `colorway_dropped`.
- **13 British spellings**, six of them inside the system prompt and tool schema
  sent to Claude, plus one in the backup setup steps and one in a test.
- **A documented hazard that does not exist.** `Hat.case` is declared
  `lazy="selectin"`, so `display_id` resolves on a plain `select(Hat)` —
  verified by execution.

### Removed
- `UnclaimedFromPurchases.hat_ids` — shipped over the wire with no reader
  anywhere in the frontend. The two tests that consumed it now assert the
  stronger thing: they run the fill and check which hat actually changed.

### Internal
- `tests/test_repricing.py` gained an autouse fixture that releases the claim
  and drains in-flight sweeps, so a detached sweep cannot outlive its test and
  surface later as an unrelated flake.
- **Sweeps are awaited, not polled for.** The first version of that drain
  yielded to the event loop rather than waiting for I/O, so it reported the
  sweep unfinished — passing locally and failing in CI. `create_task` hands back
  the task, so `_drain_sweeps` awaits it, bounded.
- Backend 953 → **956**; frontend 239.

## [2.75.2] — 2026-08-30

Two-axis code review of 2.72.1 → 2.75.1.

### Fixed
- **`is_real_product` was inverted, and it is the guard the whole
  colorway-writing feature rests on.** It required token containment in *both*
  halves, which meant any **shorter** colorway validated — so it rejected the
  specific readings it existed to keep and accepted the vague ones it existed to
  stop.

  The two halves need **opposite** asymmetries. A `model_name` comes from a
  photo, which cannot show the sub-line, so hat ⊆ catalog. A colorway is *read
  off the hat*, so a correct reading is at least as specific as the catalog's
  name — catalog ⊆ hat.

- **"Re-price all" could start twice.** The guard read a flag set inside the
  sweep, after the lock was taken, and a background task does not start until
  the response has been sent — so two quick presses both started a full
  uncapped pass, serialized by the lock into twice the work. The slot is now
  claimed synchronously in the handler and released in a `finally`. The old test
  pre-called the flag setter, the one arrangement that could not fail; it now
  drives the real endpoint.

- **`POST /api/admin/repricing/run` now 409s during a full sweep** instead of
  blocking on the lock for minutes — the multi-minute request, dead spinner and
  proxy timeout that route's own cap exists to prevent.

- **The "unclaimed colorways" offer went stale after the button that consumes
  it.** Import, re-run matching and unlink-all invalidated only one of two
  sibling keys, so the offer went on advertising work that had just been done. A
  new `invalidatePurchaseDerived()` helper covers both from all three call
  sites.

- **The model-name backfill destroyed information silently.** It runs once,
  unattended, with no dry run, and its change cannot be re-derived. It now
  writes every change to the activity log with the original name and the dropped
  half, so the log **is** the undo.

### Changed
- `_apply_analysis` no longer writes back into its `analysis` argument. It
  returns the leaked colorway, which the caller passes on explicitly.
- The `unclaimed` query carries a `staleTime`: answering it runs the whole
  matcher, so it is not a free read to repeat on every mount.
- `MAX_UNREMARKABLE`'s comment said "one or two hats sharing a number is
  ordinary" while the code treats three as ordinary too.

## [2.75.1] — 2026-08-30

### Changed
- **The LAN Discovery card now looks like it was designed rather than
  accumulated.** It reads as three facts — a state, the name devices resolve,
  and the addresses behind it — and was being forced through a two-slot metric
  component, which fused the state and the IPv4 into a single label and bolted
  the IPv6 underneath at a different size and color.

  Now: a state line with a live dot (green and glowing only when actually
  advertising, so the color carries the state and not just the words), the URL
  as the one thing you click, and IPv4/IPv6 as an aligned pair below a divider.
  A missing IPv6 still occupies its row, italic and muted, because its
  **absence is the diagnosis**: with no IPv6 record every lookup of the name
  stalls for the client's full resolver timeout, which reads as a slow or dead
  site rather than a missing record.

  The card had no tests; it has four now.

## [2.75.0] — 2026-08-30

### Added
- **"Re-price all" — the whole shelf, in the background.**

  `POST /api/admin/repricing/run` is bounded, and that bound is right for it: it
  runs inline because the caller wants the number back, and uncapped it is a
  multi-minute request against somebody else's public API — a dead spinner on a
  phone, then a proxy timeout, after which the result is discarded.

  The mistake was that blocking was the **only** option, so re-pricing the
  collection meant pressing a button repeatedly or waiting up to 24 hours for
  the scheduler.

  `POST /api/admin/repricing/run-all` answers **202** and sweeps uncapped in the
  background, exactly like the colorway harvest. Progress was already observable
  and drawn by the shared progress bar, so the card needed no new machinery.

  * It **refuses to start a second sweep** while one is in flight. `started` and
    `already_running` are separate booleans because "not started" has two
    meanings and only one is a problem.
  * A failure is **recorded, not swallowed** — nobody is watching a background
    sweep.
  * A manual full sweep does not clear a standing scheduler failure: a button
    press proves the code works, not that the background loop is alive.
  * The card invalidates hat views on the **true → false edge** of `running`,
    not in the mutation's `onSuccess` — a 202 arrives long before any price
    changes, and that edge is also reached when the scheduled sweep finishes.

## [2.74.1] — 2026-08-30

### Fixed
- **The Synology setup steps demanded a module you do not need, and
  contradicted themselves doing it.**

  Step 1 correctly said DSM exposes your **shared folders** as modules and told
  you to discover the real list. The steps below it then insisted `NetBackup`
  was the thing to enable, and closed by claiming the double colon selects the
  network backup service rather than SSH.

  Both are wrong. Confirmed against a real NAS: any shared folder the daemon
  lists works as a module, and `NetBackup` is simply one *more* module that the
  "Enable network backup service" checkbox adds. The double colon is about
  **transport**: it makes rsync talk to the daemon on port 873 instead of
  tunneling over SSH, and makes the first segment a module name.

  The example destination no longer names `NetBackup` either — the example is
  the part people copy. `docs/OPERATIONS.md` is corrected to match.

## [2.74.0] — 2026-08-30

### Fixed
- **The analyzer had nowhere to put a colorway, so it put it in the model
  name — and the model name is the field every match gates on.**

  melin names its goods `<Model> - <Colorway>`. The Claude tool schema carried
  `model_name` and **no `colorway` field**, so a colorway plainly readable off
  the hat was appended to `model_name`: `Trenches Hydro — Hawaii 808 Camo`,
  `Odysea Rope Hydro (WATERCOLOR)`.

  That field is the gate for **both** purchase matching and product pricing. One
  foreign word — `camo`, `808`, `watercolor` — makes a hat unmatchable against
  its own receipt and unpriceable against its own product. This is the root of
  the "bad matching": the matcher is provably optimal under its gate, and the
  gate was being fed corrupted input.

  Measured against the 568 real products harvested from the marketplace: **89 of
  235** stored model names matched no melin product at all, and 35 carried a
  literal separator.

  Four parts to the fix:
  * `colorway` is now a **required** field on the tool schema (null is a valid
    answer), described as the colorway half of melin's naming, to be read off
    the hat and never inferred from its colors.
  * The system prompt states the `<Model> - <Colorway>` convention and forbids a
    dash, em-dash or parentheses in `model_name`.
  * A stored name is split on an explicit separator. **Only a spaced separator
    counts** — `A-Game` is a melin line and the most common one in the
    collection, so a naive split on `-` would break every A-Game hat.
  * A one-time repair runs from lifespan behind `model_names_split_v1`, since
    fixing the schema alone would leave a hat's name depending on *when* it was
    analyzed. Splitting alone takes usable names from **146 to 174 of 235**,
    with no API call.

### Added
- **An analyzer-read colorway is validated before it is believed.**
  `catalog_service.is_real_product()` checks `<model> - <colorway>` against the
  harvested catalog. Deliberately **not** done by handing Claude a candidate
  list — a menu invites a forced choice and a wrong pick is indistinguishable
  from a right one, where a validator applied afterwards can only ever reject. A
  colorway already on the hat is never overwritten: that came from a matched
  receipt or from the owner, and both outrank a photo.

  The leaked halves recovered from existing names are deliberately **dropped
  rather than stored** — measured against the live catalog, none of them
  validate. They are collab and limited-run drops that no longer appear on the
  resale market.

## [2.73.0] — 2026-08-30

### Added
- **The colorways sitting unclaimed in your own order history are now offered,
  with a button.** Measured against the live collection: **17 colorways and 16
  purchase prices** were already in the database, in orders imported weeks ago,
  waiting on a match that nothing was ever going to run.

  Purchase→hat matching happens at the end of an **import** and nowhere else. So
  every improvement to the matcher, and every re-analysis that finally gives a
  hat the `model_name` that would have paired it, creates matchable pairs that
  nothing looks at again.

  `GET /api/admin/purchases/unclaimed` reports what a re-run would fill, and the
  shared-price card offers it — derived from the matcher's own dry run rather
  than restating its rule. Ambiguous matches are counted and stated rather than
  hidden.

### Fixed
- **The shared-price card claimed a colorway was the one thing only the owner
  could supply.** That was false for 17 of the 82 colorway-less hats: the app
  already held the answer in its own purchase table. The card now offers those
  first and asks for the rest.

## [2.72.1] — 2026-08-29

Two-axis code review of 2.72.0. Both axes independently found the same
mislabeling bug, from different directions.

### Fixed
- **The shared-price report could hide the very cluster it exists to reveal.**
  It grouped on the source sentence verbatim, and that sentence quotes how many
  listings were live at the moment each hat was priced. Re-pricing is
  sequential, paced and resumable, so hats priced against one line routinely
  carry different counts — and one cluster therefore split into fragments that
  each fell under the threshold and disappeared. Grouping now runs on a cleaned
  key that neutralizes that one integer, and the sentence is still displayed
  verbatim. Deliberately narrow: the size and condition qualifiers mark
  genuinely different comparisons, so they still separate.
- **A link in the report could point at the wrong hat.** Ids and shelf labels
  were two parallel arrays, and a hat with no case contributed an id but no
  label, so every later label slid up one. Each hat now carries its own label on
  one object. It was invisible in tests because every fixture hat was caseless;
  there is now a test with both kinds in one group.
- **The report went stale after the two mutations that change it.** Re-pricing
  and releasing a manual price both make hats newly eligible for it, and neither
  invalidated the report's sibling query key.

### Changed
- **The missing-colorway hats are now reachable, not just counted.** They sort
  to the front of each group, and they link to the hat's **edit form** — where a
  colorway is actually entered — rather than to its read-only page.
- `SHARED_THRESHOLD = 3` compared with `>` read as "three or more" and meant
  four or more; it is now `MAX_UNREMARKABLE`, named for what it bounds.
- The service dataclass is `PriceCluster`, no longer a second, differently
  shaped type beside the schema of that name.
- The `/prices/shared` handler maps through a row helper instead of inlining the
  field list.

## [2.72.0] — 2026-08-29

### Added
- **A report of which prices describe a LINE rather than the hat beside them**
  (Settings → Data → "Prices shared by many hats").

  The original complaint was that resale values "are all very wrong". They were
  not individually implausible — they were *identical*, and **nothing in the app
  said so**: each hat's page shows its own figure with its own source sentence,
  and only a query across the whole collection reveals that 54 of them share
  one. The card groups active hats by the price and source they carry, biggest
  group first, and names how many of each group are missing a colorway.

  **Measured, and why this is a report rather than a fix.** 2.71.0 made pricing
  prefer melin's own product, which splits a line into its real goods — but only
  for hats whose product can be identified. Four ways to identify the rest were
  tried and measured against the real collection:

  * **Purchase history.** 152 of 153 existing colorways came from a matched
    purchase, but **59 of the 82** colorway-less hats have no eligible purchase
    at all.
  * **The marketplace product list.** **47 of 76** have *no candidate product* —
    their model is not currently listed, so there is nothing to pick even by
    hand.
  * **Inferring a colorway from the photo's extracted colors.** Validated
    against the 153 hats whose colorway is known: **12% precision** (4 right, 28
    wrong), 56% ambiguous. Guessing would confidently price 28 hats off somebody
    else's product — strictly worse than leaving it blank.
  * Which leaves the owner. Entering a colorway on the Edit Hat form already
    lets that hat be priced against its own product.

  `manual` prices are excluded — a number the owner typed is theirs. Grouping is
  on (price, source) together: two lines that happen to sit at the same median
  are two facts, not one.

## [2.71.1] — 2026-08-29

An adversarial review of 2.70.1–2.71.0. Two of the three hard findings are
defects that 2.71.0 shipped, and one of them made the feature it shipped
actively worse.

### Fixed
- **The construction veto was inverted: it rejected a hat from its OWN
  product.** `Denim`, `Canvas`, `Suede`, `Linen` and `Corduroy` are
  constructions *and* common colorway words, and melin names products
  `<Model> - <Colorway>` — so reading the whole string made a HYDRO hat look
  like a Denim product and vetoed it from its own item, meaning a **correctly
  recorded construction made pricing worse than leaving it blank**. Only the
  model half is read now, and the veto fires on contradiction rather than on
  absence.

- **A canceled sweep reported itself as running forever.** 2.71.0 replaced
  `try/finally` with `try/except Exception`, and `CancelledError` is a
  `BaseException`. "Re-price now" is a long blocking POST, so a phone
  disconnecting mid-sweep left the progress record permanently in flight with
  the card polling a phantom sweep.

- The source sentence named products that had not priced the hat: the product
  set was computed *before* the condition/size narrowing.

### Changed
- Removed `Listing.color`. It was captured, documented as "the important
  addition", and read by nothing — the product name already ends in the colorway
  on 990 of 995 listings.
- Finished the `Listing` NamedTuple refactor; the ladder still indexed it
  positionally.

### Corrected
- **2.71.0's release note overstated its own result.** It said "from 5 distinct
  prices covering 168 of 235 hats to 33", which compares a coverage count with a
  cardinality. Measured properly over the whole collection, the top five prices
  covered **168 hats before and 135 after** — a real improvement, and a smaller
  one than the note implied. The largest cluster, **54 hats at $85.00, is
  unchanged**: those hats have no colorway recorded, so there is no product to
  identify. Only 48 of 235 hats reach the product matcher at all.

## [2.71.0] — 2026-08-29

### Fixed
- **Hats are priced against melin's own PRODUCT now, not the line they belong
  to.** 2.69.0 fixed the sample and the labeling but not the symptom: measured
  across the real collection afterwards, **168 of 235 hats still shared just
  five prices**. The scope read `model`, but `Trenches Hydro` matches 76
  different hats.

  The cause was that pricing token-matched the freeform listing `title` and
  ignored the structured product identity every listing already carries.
  Measured on the live marketplace: **986 of 986 listings publish
  `shopifyProductName`** and a structured variant color, across **510 distinct
  products**.

  melin names a product `<Model> - <Colorway>`, which is exactly the two columns
  a hat already carries. Matching those first gives a hat the price of *its own
  item*: on the real collection this takes 5 distinct prices to **33**, and
  moves 46 hats off the shared numbers.

  **A colorway is required.** Without one there is no product to identify, only
  a line — and calling that a product match is how "Odysea Hydro" came to match
  319 listings across 131 products. Matching more than `_MAX_PRODUCTS` is
  likewise treated as a line, not an item.

  **No minimum sample for a product match.** On a fixed-price marketplace one
  live listing of *this* product is a better answer than the median of a line it
  merely belongs to, and `count` is published so a thin sample is visible rather
  than disguised.

  **A stated construction vetoes a rival product**, because melin sells
  `Trenches Icon Hydro` and `Trenches Icon Thermal` as different goods at
  different prices. A *blank* construction vetoes nothing: it means nobody has
  looked.

  Sold history is not available — the API ignores `states=closed` and returns
  the same open listings — so live asks remain the only signal.

### Changed
- `_listing_facts` returns a `Listing` NamedTuple rather than a bare 4-tuple. It
  had grown to six fields and every call site indexed it positionally.

## [2.70.1] — 2026-08-29

Everything here came out of a two-axis review of 2.66.0–2.70.0. Both axes
independently found the same defect, and it is the one 2.70.0 shipped to
prevent.

### Fixed
- **A failed sweep could not report that it had failed.** `SweepProgress.error`
  was never set by anything, so a crashed re-pricing sweep or colorway harvest
  reported clean. The card's "Last run failed" branch was unreachable, and two
  frontend tests passed by mocking a state the server could not emit. The
  harvest case was the worse one: it runs behind a 202 with nobody watching, so
  a marketplace rejection rendered as an idle card.

- **"Re-price now" showed no progress bar at all.** The poll only started once
  `running` was already true, but that flag is not set until the sweep has taken
  its lock and run its query — so the status fetch issued on click answered
  `running: false` and polling stopped. It now uses the same grace window the
  colorway card already had, and a test drives the real click → bar sequence.

- `['admin','analysis-job', id]` was not invalidated after a retry, so a run log
  left open described a set the retry had just re-tagged.

### Changed
- The `SweepProgress` fixture is now shared from `src/test/fixtures.ts`. Two
  byte-identical copies had appeared in two card tests.
- Dropped `SweepProgress.name` and the `new()` helper that existed only to set
  it — the field appeared in neither the API payload nor any log.

## [2.70.0] — 2026-08-28

### Added
- **The two buttons that start minutes of work now show what they are doing.**
  "Re-price now" and the colorway "Refresh from Melin Recap" each kick off
  hundreds of sequential external calls and then said nothing at all.

  The harvest was the worse of the two: it answers **202** and runs as a
  background task, so its only trace was a log line. From the Settings page a
  working harvest and a button that did nothing looked identical.

  Both now report a live bar with counts **and what they are working on right
  now** — the hat being re-priced, the category being harvested. A count says
  the sweep is alive; the label says it is not wedged on one item.

  Also visible for the first time: the **scheduled** re-pricing sweep, which
  starts at boot and runs for minutes. The fields beside it describe the last
  run that *finished*, so until now a sweep in flight was indistinguishable from
  nothing happening.

  One `SweepProgress` type serves both, rather than two counters that drift. The
  analysis queue is deliberately not folded in: its progress is derived from a
  hat column and survives a restart, because that worker's work outlives the
  request. These two sweeps run inside the process and die with it, so they are
  process-local.

  `pct` is computed server-side so the two cards cannot disagree about how it
  rounds, `done` is capped at `total`, and an error **outlives** `running` going
  false — nobody is watching at the moment a background sweep fails.

  Each sweep wraps its body in `try/finally`, because one that raises and leaves
  `running` true reads as permanently in flight.

### Fixed
- `RepricingCard`'s test fixture was cast with `as RepricingStatus`, so adding a
  required field to that type left the fixture silently incomplete with
  typecheck still green. The cast is gone and the object is complete.

## [2.69.1] — 2026-08-28

### Fixed
- **`httpx` was imported directly by three services and declared by none of
  them.** `ebay_service`, `google_vision` and `melin_recap` all import it, but
  it reached the environment only as a transitive dependency of `anthropic`.
  That held by luck: a routine `uv lock --upgrade` resolves `anthropic` to a
  version that no longer pulls httpx, and the lock duly removed it — leaving
  three services that fail at import with nothing in `pyproject.toml` to explain
  why. Now declared explicitly.

### Notes
- **A Dependabot PR bumping `pydantic-core` is correctly blocked and was left
  alone.** It edits `requirements.txt` only, which is *derived* from `uv.lock`,
  and `[tool.uv] exclude-newer = "7 days"` deliberately holds that version back
  — so the PR asks the derived file to move ahead of its source.
  `tests/test_requirements_export.py` catches exactly that. The guard working is
  not a bug to fix.
- **`anthropic` 1.0.0 is available and deliberately not taken here.** It is a
  major version affecting the Vision tool-use call, which the test suite stubs —
  so a green suite would prove nothing about it. It wants its own change with a
  real call verified against the API.

## [2.69.0] — 2026-08-28

### Fixed
- **Resale values were wrong across the collection — three separate defects,
  all of which made a hat look appraised when it had barely been looked at.**

  **1. One page of the market was being read and called the market.** The query
  sent a single request and took what came back. The `odysea` category holds
  **436** listings; that read **100** of them, so every Odysea was priced off
  whichever quarter the API happened to return first. The total was in every
  response and discarded. Correcting the sample alone moves the Odysea median
  from **$100 to $79**.

  **2. Punctuation made a model unmatchable.** Tokens were split on whitespace
  only, so a hat named `Odysea Hydro "Have More Fun"` demanded tokens that
  appear in no listing title. The model tier matched nothing and the hat fell
  silently to a category median.

  **3. There was no rung between "this exact design" and "the entire
  category".** melin titles read `<line> <construction> - <colorway>` and
  `model_name` comes from Claude reading a *photo*, so it lands on the line plus
  whatever artwork was visible. When that exact string had no listings, pricing
  jumped straight to the median of the whole category — which is how **28
  different hats all sat at exactly $115.00**, and 26 more at exactly $85.00.

  Model specificity is now surrendered one token at a time, and entirely, before
  condition or size are given up at all. Measured live on the real collection,
  **11 of 14** previously category-priced hats now price against a named line.

  A prefix counts as a model match only if it matched the whole name **or
  actually narrowed the field** — token count cannot decide it.

  The source label now **names the line compared against** (`median of 18 live
  classic new-with-tags Odysea Rope Hydro listings`) instead of leaving which
  model unstated.

## [2.68.0] — 2026-08-28

### Fixed
- **`headroom.local` still stalled on iPhone, and 2.61.0 did not fix it.**
  Advertising both address families fixed AAAA and nothing else, because the
  defect was never about addresses: zeroconf answers a query for a record type
  it does not hold at our hostname with **silence**, and a resolver that gets
  silence from a name it believes exists waits out its full timeout.

  Probing the live advertisement, one record type at a time:

  ```
  A           answered in 0.002s
  AAAA        answered in 0.001s   ← what 2.61.0 fixed
  HTTPS/SVCB  NO ANSWER in 4.0s
  SRV         NO ANSWER in 4.0s
  ```

  **iOS Safari queries the HTTPS record (type 65) before connecting**, so every
  navigation paid that timeout — while `curl` and `getaddrinfo`, which only ever
  ask for A and AAAA, measured 3ms and made it look fixed.

  RFC 6762 §6.1 requires a responder that owns a name to answer an absent type
  with an **NSEC** record asserting which types do exist there. The app now
  sends one, from a small responder that binds 5353 alongside zeroconf
  (`SO_REUSEPORT`) and answers **only** for our own hostname, and **only** for
  types zeroconf has no answer for. It can never contradict or race the real
  advertisement.

  This fixes the whole class, not just type 65 — SRV was stalling identically.

  Upstream is still unfixable from outside: zeroconf 0.150.0 is the current
  release, it builds its NSEC with the service-instance name instead of the
  host, and it ships compiled Cython so the method cannot be overridden. A test
  reproduces that exact mis-naming and fails on it.

## [2.67.0] — 2026-08-28

### Added
- **"Recent runs" entries are clickable, and open that run's log.** The card
  listed five runs as bare text with no way to find out which hats a run covered
  or what its failures actually said. Each row is now a button that expands into
  the run's own log: every hat still attributed to it, its analysis status, and
  its **verbatim, untruncated** error.

  Verbatim on purpose. The "Why analysis is failing" card groups on a *cleaned*
  key so that one problem reads as one problem; a single hat's log is the
  opposite case, where the whole string is what you came for.

  Backed by `GET /api/admin/analysis/jobs/{job_id}`. There is no separate log
  store and deliberately isn't one — a run's record *is* the hats it tagged — so
  this reads them back. Failures sort first. The request only fires when a row
  is opened.

- **A run says when its hats have moved on, instead of looking empty.**
  `hats.analysis_job_id` is a single column that every later run overwrites, so
  an older run legitimately ends up with nothing attributed to it. The detail
  publishes `still_tagged` alongside the run's original `total`. Both it and
  `failed_count` are SQL `COUNT`s, never `len()` of the capped list — and when
  the list is truncated the view says so.

## [2.66.0] — 2026-08-26

### Added
- **Retry just the hats that failed, instead of re-analyzing all 234.** A
  transient overload from Anthropic takes out a scattering of hats mid-run.
  Until now the only repair was "Re-analyze every hat", which spends a Claude
  call on the 213 that were already correct in order to fix the 21 that were
  not.

  `POST /api/admin/analysis/retry-failed` covers the failures only. The "Why
  analysis is failing" card now carries a **Retry** button per failure group,
  plus one "Retry all N failed hats" when there is more than one group.

  Per group rather than one button for the card, because the groups are not
  interchangeable: an overload wants retrying immediately, while a response the
  parser choked on will choke again and is a bug report. Matching a group
  re-uses the same cleaned reason key the grouping does.

- **The card now says how many of a group can actually be retried.** A hat can
  carry a failure string and have no photo left to analyze — a real failure,
  worth seeing, and one no retry can fix. `retryable_count` is derived from the
  very query the retry route calls rather than restating its rule, so a button
  labeled "Retry 21" queues 21 by construction.

### Fixed
- **The failures list went stale after any re-analysis.** Both runs move hats to
  `pending` and clear their failure text, but neither invalidated the failures
  key — so the card went on listing failures the run had just wiped, for the
  full 30s `staleTime`.

### Changed
- The failures list moved **above** the re-analyze-everything button in the
  Analysis Queue card. While the expensive button was the only one on the card,
  it was the one people reached for.

## [2.65.0] — 2026-08-26

Everything here came out of an adversarial review of 2.61.0–2.64.0. Two of the
findings were bugs that defeated the fixes they shipped inside.

### Fixed
- **The off-site backup counters were still being wiped on every restart — by
  the very release that claimed to fix it.** The persisted record was restored
  only when something *read* it, but the write path never reads. So the first
  nightly upload after a reboot incremented an empty record and overwrote the
  file, discarding the history.

  Every test passed because each one happened to read before writing. The
  unattended sequence — boot, then upload, with nobody having opened the page —
  was the one nobody exercised. There is now a test that deliberately does not
  read first.

- **Re-pricing: pressing "Re-price now" could hide a dead scheduler.** A manual
  run cleared the error and zeroed the failure count, so a sweep that had been
  failing nightly for a month would read "swept just now, 0 failures" after one
  click. Only a scheduled success now clears the alarm, and a manual run that
  *fails* is recorded too.

- **Re-pricing could never get past hats it cannot price.** Hats with no
  listings — or a non-melin brand — kept an empty "last checked" timestamp, and
  since the sweep does the least-recently-checked first, those hats owned the
  front of the queue permanently. Every attempt is now timestamped, whether or
  not it found a price.

- **"Re-price now" no longer blocks for minutes.** It was an uncapped inline
  request — roughly four minutes for a full collection, which on a phone is a
  dead spinner followed by a timeout. It now sweeps a bounded batch, stalest
  first, and tells you how many remain so you can press again.

- **Two sweeps can no longer run at once.** The scheduled loop and the button
  were separate doors into the same few hundred calls against a public API the
  code otherwise takes care to pace.

- **The colorway picker still showed nothing for many hats.** The 25-item cap
  was fixed in 2.62.0, but the lookup still demanded an exact model-name match,
  and a hat's model name comes from a photo that cannot show the sub-line.
  Matching already solved this for purchases; the picker now does the same.

- British spellings of "catalog" in the changelog, docs and tests.

## [2.64.0] — 2026-08-26

### Added
- **Appraisals now refresh on their own.** They never did. A hat's resale value
  moved only when that hat was *analyzed*, and nothing re-checked prices on a
  schedule — so every value sat frozen at the date of the last bulk re-analysis,
  and the only way to move them was to re-analyze the entire collection: a
  Claude vision call per hat, to fetch a marketplace median that needs no Claude
  at all.

  That coupling chained two unrelated failures together. When the Anthropic
  balance ran out, the analysis call raised, the pipeline fell back and returned
  early, and the price refresh below it never ran. **Prices stopped because
  identification stopped**, though pricing never depended on it.

  Re-pricing is now its own scheduled sweep, independent of analysis: the
  marketplace lookup keys on details already stored on the hat, so it needs no
  photo, no API key and no vision call.

  - **Prices you entered yourself are never touched** — excluded from the query
    outright, so a protected hat doesn't even cost a lookup.
  - Disposed hats are skipped; they've left the collection.
  - Oldest-checked-first, so a sweep interrupted by a restart makes progress on
    the stalest prices rather than re-doing the freshest.
  - One unreachable listing doesn't stop the other 234.
  - A new **Re-pricing** card under Settings → Data shows when the last sweep
    ran and how many prices actually *changed* — not how many hats were visited,
    because a flat market is a working sweep. It also has a "Re-price now"
    button, which works even with the schedule turned off.

  Tunable with `HEADROOM_REPRICING_ENABLED`, `_INTERVAL_HOURS` (default 24),
  `_DELAY_SECONDS` (default 1, spacing between calls to a public API that isn't
  ours) and `_BATCH_LIMIT`.

## [2.63.0] — 2026-08-26

### Added
- **Purchase History can now tell you how to get the JSON it wants.** The card
  has always had an "Import JSON…" button and no answer to the obvious question
  — where does that file come from? The data is sitting in your email, and
  nothing in the app produced it.

  There's now a collapsed "No JSON yet? Get one from your email" section with a
  ready-made prompt and a copy button. Paste it into Claude or ChatGPT with
  access to your mail; it reads your melin receipts and returns exactly the JSON
  this card imports.

  The prompt is a schema written in prose describing a Python parser, so a test
  parses the field list back out of it and fails if any name isn't one the
  importer actually reads. That check earns its keep: the first draft said
  `purchased_at` where the parser reads `order_date`, which would have imported
  cleanly with every order date silently discarded.

## [2.62.0] — 2026-08-26

### Fixed
- **The colorway picker showed 25 of 188 colorways.** The catalog was not
  missing anything — 550 entries across 160 models, harvested the same day. The
  feed called its helper without a limit and silently took the default of 25.
  Typing couldn't reach the rest either: the edit page fetches that feed without
  a query and filters client-side.

  This is the second time that same cap has been mistaken for a small catalog.
  **A truncated list is invisible: it looks exactly like a short catalog.** The
  feed now takes an explicit limit defaulting high enough to serve the whole
  catalog, and a test asserts the *tail* is reachable.

- **Off-site backup reported "nothing has been uploaded yet this run" forever,
  on a box that was uploading successfully every night.** The upload record was
  held in memory. The scheduler checks every 24 hours, skips the startup backup
  when a recent one exists, and only writes when data changed — so after any
  restart there was a day-long window with no upload, and the card fell back to
  claiming nothing had ever left the machine.

  The upload record is now persisted beside the backups, and the card states
  **when** the last upload happened and **which archive** it shipped. A failure
  is reported as a failure with its reason, and "never" now means never.

  Deliberately not stored in the database: the change-gate fingerprints the DB,
  so writing upload status there would make every cycle see a change and turn
  change-gating into an unconditional daily backup.

## [2.61.0] — 2026-08-26

### Fixed
- **`https://headroom.local` took over a minute to load, and often never did.
  It was never the TLS handshake — that measured 46ms.** The entire delay was
  name resolution: every lookup of `headroom.local` stalled for the client's
  full mDNS resolver timeout (5s on macOS; far worse on iOS, where Safari fires
  many parallel requests and each one pays it).

  We advertised an IPv4 address and nothing else. A responder that owns a name
  but has no AAAA is supposed to answer an AAAA question with an **NSEC** record
  (RFC 6762 §6.1), which is what lets a client give up instantly. python-zeroconf
  0.150.0 builds that record with the wrong owner name — the service instance
  where it must use the host — and an NSEC only asserts non-existence for the
  name it carries, so clients correctly ignored it and kept waiting. **A
  mis-named NSEC and total silence look identical to the querier.**

  Confirmed from four independent angles: a `curl` timing split, `avahi-resolve
  -6` timing out on the server's own box while `-4` answered instantly, a full
  mDNS packet dump showing the mis-named record, and a local reproduction.

  Headroom now advertises every address family the host actually has. With
  nothing missing there is no NSEC to get wrong. 0.150.0 is the current release,
  so there was no upgrade to take, and the defect cannot be patched from outside
  — zeroconf ships compiled Cython. Reported upstream.

  Hosts with no global IPv6 are unaffected and still bind IPv4 only.

### Added
- Settings → LAN Discovery now shows the advertised IPv6 address, or says
  plainly that the host has none — its absence is the diagnosis for a slow
  `.local` name.

## [2.60.0] — 2026-08-26

### Added
- **Settings → Analysis now says why analysis is failing.** Distinct failures,
  grouped, worst first, with the actual error text and a few hat ids.

  It was visible nowhere. A failure lived on one hat's own page, where the
  banner printed generic advice instead of the reason — so when the Anthropic
  **account ran out of credit**, all 235 hats read "add a Claude API key" on a
  key that was set, valid, and had been working minutes earlier. Three days.

  Grouped, because 235 hats failing for one reason is **one** problem. The
  per-call request id is stripped before grouping or every call looks like its
  own unique fault. A billing/quota refusal is flagged explicitly — it is the
  one failure that masquerades as a missing key.


## [2.59.0] — 2026-08-26

Measured against the real 294-line order history throughout: **144 → 152
matched, which is now the provable maximum** rather than whatever a heuristic
happened to reach.

### Fixed
- **A construction word in the colorway half no longer rules a hat out.** melin
  model names read `<line> <construction>`, but a receipt is free to put that
  word in either half of the title, and the gate only compares the model half.
  Real miss: hat `Eagle Denim` against `Eagle Mill Union - Hickory Denim`. The
  gate now retries with the construction stripped from both sides. Narrower than
  widening it to the whole title, which was tried and rejected.
- **A construction that CONTRADICTS the title now vetoes**, which the above
  makes necessary: stripped, `A-Game Thermal` and `A-Game Hydro` both reduce to
  the same tokens.
- **A price typed off the receipt outweighs a colorway typo.** Two stated
  colorways that disagree normally rule a hat out. That is right when the
  colorway is all you have and wrong when the owner entered the purchase price
  from the same order confirmation — "Navy Denium" against "Hickory Denim" is
  someone's words for a color; **$200.00 against $200.00 is corroboration**.
- **The Claude fallback banner stopped telling you to add a key you already
  have.** When the account ran out of credit, every hat displayed "Add a Claude
  API key in Settings". The real reason sat in `analysis_error`, which only the
  `error` status ever rendered. `fallback` now shows it too.

### Changed
- **Assignment is maximum bipartite matching, not greedy.** `assign_purchases`
  (Kuhn's augmenting paths) replaces "each purchase takes its best free hat,
  scarcest first". That heuristic was measured leaving **3 real matches
  unclaimed** the moment scoring changed. Candidates are visited in descending
  score order, so among maximum-size assignments the better-evidenced pairings
  win. Keyed on object identity rather than the primary key, since the preview
  scores transient rows. Shared by the importer and the preview.

### Added
- **Settings → Data → Frozen prices.** 2.58.0 shipped the endpoints with no UI,
  which meant the only way to repair the affected hats was curl. Now a list with
  checkboxes, flagging the ones carrying marketplace provenance under a manual
  stamp.


## [2.58.0] — 2026-08-26

The six things 2.57.2 listed as "not fixed". They are fixed.

### Fixed
- **Color search returned the wrong hats, and now it doesn't.** Searching
  **olive returned the cream hats** — ΔE 40.0 apart, across families the module
  swears it never crosses. Also olive→beige, tan→cream, gold→beige.

  The hue fallback exists because ΔE is dominated by lightness, so a DARKENED
  color lands on a neutral name. It only ever tested chroma and hue, so pale
  tints walked through in the opposite direction. **Chroma is bounded by
  lightness**: at L=95 a low chroma is the most a color can have, not evidence
  of desaturation, so the chroma ratio against a mid-lightness target compares
  two different ceilings.

  The fallback now applies only to swatches **darker than the target**. Not a
  fourth tuned constant — the three before it (30 → 22 → 26) are why. Measured
  over the full palette cross-product: **4 cross-family matches → 0**, the
  dark-teal case it exists for still works, all 6 darkened-swatch rescues kept,
  0 regressions. The test now asserts zero cross-family matches over **every
  ordered palette pair**.

- **An analysis job never closed if one of its hats was deleted mid-run.**
  `total` is frozen at creation while the counts are over surviving rows, so
  `done` stayed one short forever — the run reported itself in flight
  permanently, across restarts. Now gated on "nothing is left PENDING", which is
  what the docstring always claimed.

- **An oversize chunked body returned 500, not 413** — and wrote a durable error
  row each time. The counted-bytes path signalled a disconnect, which Starlette
  turns into an exception inside the route where nothing catches it.

### Security
- Rate-limited logins are now audited once per lockout window rather than once
  per attempt; the log line still fires every time.
- The login rate limiter now sweeps its tracked keys periodically instead of
  pruning only the key handed to it.
- The passkey challenge store is now bounded, evicting oldest-first so a flood
  evicts its own entries rather than a real ceremony's.

### Added
- **`GET /api/admin/prices/frozen` and `POST /api/admin/prices/release`** — the
  repair 2.57.0 needed and did not have. Its fix stopped the Edit form freezing
  prices as `manual`; every hat already stamped stayed frozen forever.

  Nothing records whether a `manual` stamp came from a person or from the form
  resending a value it had seeded, and the numbers are identical either way — so
  this reports and lets you choose, never guessing in a backfill. `dry_run`
  defaults to **true**, releasing keeps the price VALUE and clears only the
  scope, and `market_priced_only` narrows to hats carrying marketplace
  provenance.


## [2.57.2] — 2026-08-26

A second whole-codebase review, run adversarially. Most of what it found was in
**2.57.0 itself** — written and self-reviewed in one sitting, merged an hour
later. That is the finding worth keeping.

### Fixed — regressions introduced by 2.57.0
- **`aria-labelledby` had been renamed to `aria-labeledby`.** The
  American-spelling sweep used unanchored regex and ate the `l` in a W3C
  attribute name. React passes unknown `aria-*` through verbatim, so nothing
  errored and no test failed, while the Settings tabpanel lost its accessible
  name.
- **`resize: vertical` and `field-sizing: content` were shipped together and are
  mutually destructive.** Dragging the grabber writes an inline `height` that
  later changes do not reset, so one drag permanently killed auto-growth.
  `field-sizing` now applies only inside `@supports`, *instead* of the drag
  handle.
- **The textarea ceiling was smaller than its own floor on a phone.**
  `max-height: 40vh` is ~157px on an iPhone in landscape against a 146px
  `min-height`, and `vh` is the *large* viewport and does not shrink for the
  soft keyboard. Now expressed in lines.
- **"Press ⌘/Ctrl + Enter" was shown on a phone.** Neither key is on an iOS
  soft keyboard. Hidden under `@media (pointer: coarse)`.
- **The price guard could be defeated by a background refetch.** It compared the
  box against the *live* row while seeding is frozen per hat, so a fresher price
  landing between open and save wrote the stale value and stamped it `manual`.
  Now compared against the value as seeded.
- **A price could be silently cleared by a typo.** `type="number"` reports
  `value === ""` both when you clear it and when it rejects what you typed, and
  this form reads an empty box as "clear this price". `validity.badInput`
  separates them.
- **`HatNotesCard` leaked mutation state between hats** — the card is at a fixed
  position, so one failed save left a red "Couldn't save" under the next three
  hats' untouched boxes. Keyed on the hat id.
- **`undispose_hat` still un-roomed a hat**, and 2.57.0's beanie change made it
  routine. `delete_case` was taught to keep hats in the room; the *other* detach
  site was not. `Hat.detach_from_case()` is now the one definition.
- **`delete_case` filed DISPOSED hats into the room** and counted them in the
  audit line, which still read "unassigned".
- **`delete_case` wrote a room id it never validated** — the only such writer.
- **`uploads/cases` was still created** by `Dockerfile` and `setup.sh`, so
  2.57.0's "no longer created on every boot" was false on every build.

### Fixed — older bugs
- **A re-analysis erased `estimated_new_price` for most of the collection.**
  The retail resolver returned nothing when the table had no entry *and* Claude
  declined, and the apply step assigned unconditionally. That is 12 of 16 styles
  and 9 of 11 constructions, and "re-analyze all" covers every hat with a photo.
  It now keeps the stored value — the rule already applied to brand, model and
  series 75 lines above.
- **`POST /share` had no total-batch cap and ran on the event loop**, with a
  fourth private copy of the chunk loop. It now uses the shared helper,
  off-thread, under the same ceiling bulk import has always had.
- **The "full" badge, the Settings census, and the CI probe** — see below.

### Fixed — tests that could not fail
- **`test_multipart_is_exempt` asserted a tautology** and then posted a payload
  far below the cap it was checking. Now sabotage-verified.
- **The path-traversal canary added in 2.57.0 was itself wrong** — it probed a
  path served by a mount bound at app creation, so it answered even with the
  request-time guard unpatched. Moved to a file that goes through the real
  guard, and verified by reinstating the original bug.
- **`POST /share`'s auth was untested** — a two-line special case with both
  existing callers authenticated, so deleting it left the suite green.
- **The Settings census counted a literal.** It asserted a length beside a
  roster that had grown past it, so a card could be deleted outright with every
  test passing. It now derives from the exported `SECTIONS`.
- **`test_upload_caps` asserted a false statement** — added in 2.57.0, claiming
  "one definition, used by all" while a third copy existed. It now asserts the
  call sites and fails if any route grows a private chunk loop.

### Documentation
- Internal notes still said beanies pack "3-to-a-case instead of **8**" one line
  above the sentence 2.57.0 corrected to 6.
- **"semgrep-enforced" is now accurate in both directions**: the rules are not
  in this repo *and* the check is **not required** — `main` has no branch
  protection and no rulesets, so it reports and does not block.
- The Dependabot note said "Two failure modes" above three.
- 2.57.0's changelog miscounted the admin submodules and mis-stated what
  `delete_room` says.
- The CI container probe curled `/health` (a static 200) while production's
  healthcheck uses `/health/ready` (disk floor + worker liveness), so a
  readiness regression shipped green.
- rembg's model size was given three different ways; measured, it is ~179 MB.
- Sweep misses: "artefact", "modelled". `USAGE.md` implied beanies get the
  one-hat overfill allowance they have never had.

## [2.57.1] — 2026-08-26

### Changed
- `uvicorn` 0.52.3 → 0.52.4, as one coherent `uv lock --upgrade`.

### Documentation
- **A third Dependabot failure mode recorded, and it is the sharpest one:** a PR
  proposing a transitive version that is *impossible*. Observed with
  `pydantic-core` 2.46.4 → 2.48.0 — `pydantic` 2.13.4 requires
  `pydantic-core==2.46.4` **exactly**, so the PR would have written into
  `requirements.txt` a set no resolver can satisfy. That is why the Docker build
  failed alongside the export test, rather than the export test alone.

  `uv lock --upgrade` correctly declines to move it. The note in
  `.github/dependabot.yml` now says so, and says not to "help" by editing the
  pin.

## [2.57.0] — 2026-08-26

A whole-codebase two-axis review, plus two changes asked for directly. The
headline finding is that the **code** is in good shape and the
**documentation had drifted** — but it also turned up four real bugs, one of
which was quietly rewriting prices.

### Changed
- **A case now holds 6 beanies, not 8.** `MAX_BEANIE` is the owner's number for
  how many belong in a case, so it gets no overfill allowance — the same rule a
  per-case `capacity` override has always had: a stated number is exact.

  The figure has now moved twice (3 → 8 → 6), which is why **it is never
  restated by hand**. `services/capacity.py::MAX_BEANIE` is the value,
  `frontend/src/lib/capacity.ts` carries only the *default* for the create/edit
  placeholder, and `tests/test_capacity_parity.py` fails if they drift.

  **A case already holding 7 or 8 beanies is not broken** — it reports
  `overfull` and refuses more, exactly as an over-crammed hat case does.

- **The notes box is a designed field instead of a browser default.** There was
  no `textarea` rule in the stylesheet at all: every multi-line field borrowed
  `.form-control`, which is built for one line and got four things wrong the
  moment there were two — a single-touch-target `min-height`, no `line-height`,
  `resize: both` (draggable sideways out of a card whose `overflow: hidden` then
  clips it), and a baseline alignment that left a descender gap.

  Fixed at the mechanism, so Design Notes and the disposal notes get it too.
  Your notes additionally get room to write in, an explicit *Unsaved changes*
  state, and ⌘/Ctrl+Enter to save — Enter inserts a newline in a textarea, so
  the usual submit gesture was unavailable on a field with its own Save button.

### Fixed
- **Editing any field silently froze a hat's prices and relabeled them as
  yours.** The Edit page seeds both price boxes from the loaded hat and sent
  them on *every* save, and the update service reads a sent key as "a person
  typed this number" and stamps the price `manual`. So changing a colorway
  turned a scraped marketplace median into *"Price you entered — used as
  given"* and made it permanent. Same number on screen, different meaning. The
  keys are now sent only when the value actually changed; clearing one still
  sends `null`, which hands the hat back to the live market feed.
- **Deleting a case took its hats out of the room with it.** `delete_case`
  cleared `case_id` but never set `direct_room_id`, so since 2.33 the hats
  became reachable from nowhere but the Hats list and search. The shelf appeared
  to empty itself.
- **The "full" badge never appeared on a case holding regular hats.** Cases are
  type-exclusive, so the unused type's free count sits at its full nominal
  figure forever, and the grid tested the sum of both. Asked of the type the
  case actually holds now.
- **Container mutations left the views they changed stale for 30s.** Creating or
  moving a case invalidated only `['cases']` — never the room's `case_count` or
  its contents — and room rename/delete never touched `['hats']`, so hat cards
  kept printing the old room name. All four now go through `invalidateHatViews`.
  The room-delete confirmation also names the loose hats that move.
- **First-run setup hashed argon2 on the event loop.** `create_user` was the one
  remaining synchronous hash call — a few hundred milliseconds of fully frozen
  process on a Pi, health check included.
- **`GET /api/admin/backups` returned a naive timestamp** while the health
  endpoint reads the same mtime as UTC, so the file list and the health card
  disagreed by the host's offset.
- **Search rendered full-resolution cutouts into 72px rows**, ignoring the
  thumbnail path the projection already carries.

### Security
- **The path-traversal regression test could not fail.** Its fixture restored a
  module global before returning the client, and the guard reads that global per
  request — so every request was served from the real bundle and the planted
  file was unreachable whatever the guard did. It now uses `monkeypatch`,
  asserts up front that the app is really serving the temp bundle, and **fails
  when the containment check is removed** (verified by sabotage).

### Removed
- **`read_capped` is gone**, replaced by `copy_upload_truncating`. It had *zero*
  production callers: the import route carried a private spool that streamed to
  disk instead of buffering in memory — strictly better, so nothing ever failed
  and only the "one definition, used by all four" claim was wrong. Promoted the
  copy, deleted the original, and a test now pins that the route uses the shared
  helper.
- **`uploads/cases` is no longer created on every boot** — a leftover from the
  removed case-photo feature, written to by nothing since.

### Documentation
- Internal notes corrected: `['hats','disposed']` is **covered** by `['hats']`
  (TanStack matches array keys element-wise by prefix — the genuine sibling
  traps are `['room']`/`['rooms']` and `recent-errors`/`-count`); `read_capped`
  no longer guards bulk import; two symbols were documented in the wrong module;
  the admin submodule count was wrong; `CONDITION_IN_SENTENCE` is module-private,
  not exported; `frontend/src/lib/capacity.ts` exists and is reconciled by a
  parity test, which the "ONE rule" entry had denied.
- **Counts that had already gone stale are no longer quoted** — the Settings
  card roster and the `.card`-on-an-anchor tally, both of which had drifted
  within two releases.
- **"semgrep-enforced" now says where the rules are.** They are not in this repo
  — the scan is a check supplied by the Semgrep Cloud Platform app, so grepping
  for a config finds nothing.
- **Two commands that could not work as written**: the CA-export `docker compose
  cp` in README omitted the overlay that defines the `caddy` service, and
  OPERATIONS named the wrong DSM checkbox for Synology — the other one yields
  `@ERROR: Unknown module`, which reads like a broken NAS.
- American spelling swept across code, comments, tests, docs and UI (~48 sites
  in 39 files). `"Heather Grey"` is real melin catalog data and is untouched;
  `"cancelled"` as a persisted status value is data, not prose, and stays.

## [2.56.0] — 2026-08-26

Five Dependabot PRs had piled up; three of them could never have gone green.

### Changed
- **Backend dependencies updated as one coherent resolution.** Notably
  `websockets` 16.1.1 → 17.0.1, `starlette` 1.3.1 → 1.6.0, `uvicorn` 0.51.0 →
  0.52.3, `rembg` 2.0.78 → 2.0.81, `sqlalchemy` 2.0.51 → 2.0.52, plus the
  minor/patch group. One `uv lock --upgrade`, one export, one review.

  This replaces three Dependabot PRs that were **internally inconsistent**, and
  the reason is worth recording. `requirements.txt` is a *generated* artifact
  (`uv export`) that the Docker image installs from — worth 490s of an 873s Pi
  rebuild, and byte-identical across a version bump so a release does not bust
  that layer. Dependabot cannot see that it is derived from `uv.lock`, and
  treats it as a manifest in its own right. Two distinct failures resulted:

  - One PR bumped **only** `requirements.txt` — a transitive dependency that is
    not in `pyproject.toml` at all — so `uv.lock` never moved and the two
    disagreed by construction.
  - Another bumped **both, independently, to different resolutions**: its
    `uv.lock` said `annotated-types 0.7.0` while its own `requirements.txt` said
    `0.8.0`, and `cbor2` appeared in one and not the other. The image would have
    installed a different dependency set than the tests ran against.

  `tests/test_requirements_export.py` caught both. Regenerating on the
  Dependabot branch is **not** the fix for the second case: it silently discards
  half the update.

- **`.github/dependabot.yml` now says all of this at the point of use**,
  including the one-command recipe.

  There is deliberately **no workflow auto-regenerating the file** on those
  branches. Doing so requires `pull_request_target` with a writable token plus a
  checkout of the PR branch — the pwn-request pattern this repo's own semgrep
  scan rejects.

**799 backend + 192 frontend tests pass.**

## [2.55.0] — 2026-08-26

Found on the real deployment: certificates were being issued for **six days**
against a configured 820, and the app's own warning pointed at the wrong fix.

### Fixed
- **A leaf cut short by its issuer is now diagnosed as such.** Caddy was logging
  `cert lifetime would exceed issuer NotAfter, clamping lifetime` — 820 days
  requested, ~6 granted — because the **intermediate** had seven days left and a
  certificate cannot outlive what signs it.

  The card correctly reported a certificate about to expire and then advised
  restarting Caddy, which reissues *another* six-day certificate. Same symptom
  on the certificate, opposite fix: renewal repairs an old leaf and can never
  repair a clamped one.

  `ca_vault.clamped_by_issuer()` tells them apart — Caddy mints leaf and issuer
  in one operation, so a clamped expiry matches the issuer's to the second —
  reported as `clamped_by_issuer` / `issuer_not_after` on
  `GET /api/settings/tls`. Settings → Trust this device now names the
  intermediate and gives the command that actually works, including the note
  that **the root is untouched so no device has to be re-trusted**.

  The intermediate is read from the exported PKI rather than the served chain,
  because the peer certificate is the leaf alone.

- **The trap that caused it is documented.** Shipping `intermediate_lifetime
  3000d` in 2.48.0 did **not** fix existing installs and failed silently: Caddy
  loads the intermediate it already has and only regenerates one when it is
  expiring, so any box that ran the LAN-HTTPS overlay before that release kept a
  seven-day intermediate and quietly clamped every leaf. The runbook now has the
  symptom, the cause and the repair — which must delete the issued leaves along
  with the intermediate, since they are signed by it.

### Added
- **Denim is offered as a material.** Joins the curated `KNOWN_CONSTRUCTIONS`
  vocabulary, so it is suggested on an empty collection rather than only after
  some hat already uses it, and a typed "denim" snaps to that spelling. No
  frontend change — `GET /api/meta/constructions` merges curated with in-use.

**799 backend + 192 frontend tests pass.**

## [2.54.0] — 2026-08-24

Closes the gap 2.53.0 recorded and left open: Caddy's certificate authority —
the artifact that actually died in the long HTTPS outage — was in no backup, and
nothing noticed when it was replaced.

### Added
- **Caddy's local CA is now part of the backup.** A leaf certificate expiring is
  a non-event; Caddy issues another. The **root** is the expensive one: every
  device that browses the site installed it by hand through iOS Settings or
  macOS Keychain, and a root is self-signed, so nothing can vouch for a
  replacement. Losing it means visiting every phone, tablet and laptop.

  It lived only inside Caddy's own volume — on the same SD card whose unclean
  shutdown started the outage — and the backup fingerprint measured only the
  database and the uploads tree. The export sidecar now copies the whole
  authority to `/caddy-ca/pki` (**0700, uid 1000**, alongside the 0644
  `root.crt` the app already serves publicly — two destinations with
  deliberately different permissions), and backups carry it under
  `data/caddy-pki/`.

  The file list is **explicit, never globbed**: these are private keys, so what
  leaves the box is an inspected decision. The CA also joins the backup
  change-gate, or a regenerated authority would not itself trigger a backup and
  the archive holding the *old* root would age out while the new one was never
  captured — losing both.

  **The tradeoff is stated rather than assumed.** A trusted root's key can sign
  for *any* hostname those devices trust, which is broader than anything else in
  the archive, and the post-backup hook may be uploading it to a NAS or cloud. A
  `READ-ME-CA-KEYS.txt` travels *inside* the archive saying so.
  `HEADROOM_BACKUP_INCLUDE_CA=false` opts out.

- **A replaced certificate authority is now reported.** Nothing noticed when the
  served root changed, and it is close to invisible: Caddy names every root
  `Caddy Local Authority - <year> ECC Root`, so a regenerated CA has the same
  name, the same issuer string and a completely different key. The first symptom
  is a device reporting an invalid signature on a chain that verifies perfectly
  at the server.

  The fingerprint is recorded on first sight and compared on every reading;
  `GET /api/settings/tls` gained `ca_changed` and `ca_expected_sha256`, and
  Settings → Trust this device shows both fingerprints with the fix. It is
  ranked **above** the expiry warning and worded differently on purpose. The
  check deliberately **never self-heals** — overwriting the stored fingerprint
  on a mismatch would silence the alarm on the next poll while every device
  stayed broken.

  Restoring `caddy-pki/` from a backup taken before the change puts the original
  authority back, which is the reason the two halves of this release ship
  together.

### Fixed
- **Touch targets on small controls.** `.btn-sm`, `.form-select-sm` and
  `.form-control-sm` were 36px against a documented 44px minimum — and on a
  phone these are the destructive buttons sitting in a row beside their
  neighbors. Now 44px under `@media (pointer: coarse)`, keyed on what is doing
  the pointing rather than a width breakpoint. Padding is unchanged, so nothing
  reflows.

- **`PurchasesCard` reached past the API layer.** It held its own interfaces and
  four URL literals, against the convention that API functions live in
  `frontend/src/api/` and types in `frontend/src/types/`. Now
  `api/purchases.ts`, with the shapes in `types/index.ts`.

**Durability itself remains Caddy's.** It decides when to fsync its own files
and this app cannot reach inside it, so a durable *copy* is the only mitigation
available.

**793 backend + 191 frontend tests pass.**

## [2.53.0] — 2026-08-24

A code review of 2.52.0 found that the purchase-import preview — the whole
safety story for a feature with no undo — was describing a smaller operation
than the button performed.

### Fixed
- **The import preview under-reported what importing would do, by a factor of
  144.** Importing runs the matcher over **every** purchase with no hat linked,
  not just the lines in the file being imported, and the preview only ever
  considered the file. Against the real collection the gap was not subtle:

  ```
  PREVIEW shown to the user: would_import=1  would_match=0
  IMPORT actually did:       imported=1      matched=144
                             +144 hat prices written by that one click
  ```

  The preview now matches the file's lines **together with the existing
  backlog**, in the same order the import uses, and reports `would_match` (the
  file's own lines), `would_match_backlog` and `would_match_total` separately.
  The backlog is called out in the UI in **hats**, because hats are what
  changes. A test pins it and fails if the backlog is dropped again.

- **The purchase-import file picker had no `aria-label`.** The visible labels in
  this app carry no `htmlFor`, so nothing else associates them — an
  accessibility requirement first. Its own test proved the cost by reaching past
  it with a raw DOM query; the test now selects by label.

- **British spellings.** `initialised` in `OffsiteBackupCard`, `catalogued` in
  the 2.52.0 notes, and two older ones that predated the sweep.

### Changed
- **2.52.0 overstated the matching result, and the claim is now checkable.** It
  said 144 matches was "the maximum possible" and that "the ceiling moves when
  more hats are cataloged, not when the matcher is tuned". The first half was
  measured in a throwaway script that was never committed — a number nobody can
  reproduce is a rumor. The second half was false as written: the optimum is
  relative to which pairs are *eligible*, and the gate is a deliberate choice,
  not a law.

  `test_matching_achieves_the_maximum_possible` now computes a maximum bipartite
  matching with a second, independent implementation and fails if the matcher
  falls short. It is **sabotage-checked**. The 2.52.0 entry has been corrected in
  place, and states plainly that the target was 90% and the delivered figure is
  68%.

- `_matchable_hats()` is now the single query behind both the preview and the
  import, and the score weights are named constants beside the model tiers — the
  gap that keeps an exact model hit above a contained one is load-bearing and
  was previously two bare literals.

- `test_the_module_host_is_parsed_from_the_destination` exercised nothing: it
  read the function's source text and grepped for a string, which passes just as
  happily when the string sits in a comment. It now runs the real call, asserts
  the dialed URL, and that no credential appears in argv or the environment.

**777 backend + 189 frontend tests pass.**

## [2.52.0] — 2026-08-24

### Fixed
- **SQLite committed transactions were not durable.** `PRAGMA synchronous` was
  `NORMAL` — SQLite's own recommendation for WAL, and safe from *corruption*,
  which is what most guidance means by "safe". It is not safe from *loss*: the
  WAL is synced at a checkpoint rather than at commit, so a committed
  transaction "might roll back following a power loss", and the default
  1000-page threshold means what is at risk is **every write since the last
  checkpoint**.

  This is not theoretical here. An unclean shutdown on the deployment destroyed
  Caddy's stored private key and a lock file on the same SD card — written,
  never fsynced, gone — and broke HTTPS for weeks. The database sits on that
  card, under the same power, with durability switched off.

  Now `FULL`, which fsyncs the WAL on every commit. It costs one fsync per
  commit; for a personal inventory doing a handful of writes per interaction
  that is not a close call. `HEADROOM_SQLITE_SYNCHRONOUS` overrides it, and
  anything outside the accepted set falls back to `FULL` rather than through —
  the value is spliced into a PRAGMA, which cannot take a bound parameter, so a
  typo must not quietly disable durability. `checkpoint_wal()` also truncates the
  WAL on graceful shutdown, and runs **last**, because the workers above it still
  commit as they stop.

- **The off-site backup card showed the wrong provider's instructions.** The
  dropdown was hardcoded to rclone and never synced to the saved provider — so
  after configuring Synology, reopening Settings showed rclone selected with
  rclone's setup steps. The Synology instructions were in the payload but
  unreachable, which reads exactly like they had been removed.

- **Purchase matching missed over half of what it could match.** Model names had
  to be string-equal, and that fails structurally: a hat's `model_name` comes
  from Claude Vision reading a **photo**, which cannot show the sub-line, so it
  lands on the generic family. The order email states the full product. None of
  those meet under equality.

  A hat now also matches when its model tokens are a **subset** of the
  purchase's — the photo saw less than the receipt knew. Scored well below an
  exact hit, and deliberately asymmetric: a hat named *more* specifically than
  the receipt does not match, because that would let one generic line claim any
  specific hat in the family.

  Two further signals, both scored rather than gating. **Owner-stated fields** —
  `artist_series` and `construction` are typed in by the person who owns the
  hat, and matching on `model_name` alone threw them away. They are compared
  against the *whole* title, because melin puts the series in either half. And
  the **colors the analyzer read off the hat's own photo**, against the colorway
  the receipt names.

  Both are bonuses and never vetoes: 102 hats have no series recorded, and
  absence is not disagreement. Putting them in the *gate* was tried and was
  measurably worse (143 → 105).

  **Assignment order turned out to matter more than any of the scoring.**
  Matching is greedy, so in file order a line with fifty candidates can take the
  one hat that the next line's only candidate was. Purchases are now served
  **most-constrained first**. The preview shares that ordering.

  Measured against a real 294-unit order history: **matched units went 41 → 144
  (19% → 68% of hat units)**, and `test_matching_achieves_the_maximum_possible`
  pins it against a second, independent implementation.

  Stated precisely: the optimum is relative to which pairs are *eligible* at
  all. Most of the remaining gap is genuine contention — 73 `Trenches Icon
  Hydro` purchases against 36 such hats, plus 78 travel-case lines that
  correctly never match a hat. **The target was 90%; this delivers 68%**, and
  the shortfall is contention plus deliberate strictness — not something a
  better algorithm reaches.

### Added
- **Purchase history can be imported from Settings.** There was no UI path at
  all — an order history sat unusable unless someone opened a terminal. Settings
  → Data → Purchase History now takes a JSON file, and **previews before it
  writes**: how many lines are new, how many are already on record, how many
  would match a hat, and how many are ambiguous. Nothing is written until the
  preview is confirmed. **Unlink all** is beside it, since that is the only
  undo.

- **The app enumerates rsync modules instead of telling you to.** An
  `@ERROR: Unknown module` failure now lists what the daemon actually offers,
  because DSM derives modules from your shared folders and the real list is
  install-specific.

**775 backend + 187 frontend tests pass.**

## [2.51.0] — 2026-08-23

Reported from a real NAS: `@ERROR: Unknown module 'NetBackup'`. The setup steps
were wrong, and the app relayed rsync's message without explaining it.

### Fixed
- **The Synology setup steps asserted a module name that often doesn't exist.**
  They said to tick *"Enable rsync service"* and that DSM creates a `NetBackup`
  shared folder. Both halves misled: that checkbox is rsync **over SSH** and
  defines no modules at all, and `NetBackup` only exists if you separately
  enable **network backup service** — a different checkbox on the same page.

  Worse, the steps told you a module name instead of telling you to look one up.
  DSM exposes your **shared folders** as modules, and the name varies per NAS.
  The steps now lead with `rsync rsync://HOST/` to enumerate them.

- **macOS can't run that check.** `rsync` on macOS 15+ is **openrsync**, which
  does not parse `user@host::module` and reports the whole string as an
  unresolvable hostname — which reads like a DNS or NAS fault and is neither.
  The steps now say to use GNU rsync, and note the container has 3.4.1.

### Added
- **Upload failures whose cause is somewhere else now explain themselves.**
  Relaying rsync's own words is correct but not always enough: an operator
  reading *"Unknown module"* has no way to know DSM has two rsync checkboxes, or
  that module names resolve **before** the password. `Test now` appends guidance
  for unknown-module, auth-failed, connection-refused and permission-denied, and
  passes anything unrecognized through untouched, because no hint beats a wrong
  hint.

**748 backend + 180 frontend tests pass.**

## [2.50.0] — 2026-08-23

A two-axis review of 2.44–2.49, and the two shipped bugs it found. Both were
features that reported themselves as working.

### Fixed
- **Off-site backups to a Synology could never authenticate — that provider has
  not worked since it shipped in 2.46.** `docker-compose.yml` carried no
  passthrough for `HEADROOM_BACKUP_RSYNC_PASSWORD`, and Compose's `.env` file
  feeds variable **interpolation only**: it does not become the container's
  environment. So the documented instruction — "put it in `.env`" — was true of
  the file and false of the process. Inside the container rsync found no
  credential and prompted; on a non-tty an unattended prompt is a **hang, not an
  error**, so every scheduled upload sat there until the timeout killed it.

  The tests could not have caught it. They set environment variables in-process,
  where there is no container boundary to cross. `docker-compose.yml` now
  forwards the variable explicitly with an empty default, and it is in the
  environment table in `docs/OPERATIONS.md` as well.

- **The certificate card called a valid certificate broken, on exactly the setup
  2.49 exists to enable.** The coverage check consulted only DNS SANs. Serving
  on a bare address — the whole point of `HEADROOM_SITE_ADDRESSES` — makes Caddy
  sign that address in as an **IP** SAN, so the card announced that the
  certificate does not cover the host, about a certificate the browser in front
  of it had just accepted.

  An IP host is now matched against IP SANs and a DNS host against DNS SANs,
  which is what browsers do. Both directions are tested, including a DNS-only
  certificate still failing an IP host, so the fix is not "always true".

- **25 British spellings, reintroduced by the very range that swept them out.**
  Not all of them were comments — `"Authorise it on the destination: "` is a
  **rendered numbered step** in the off-site backup card. Swept again across
  every form. `"Heather Grey"` deliberately survives: it is a melin colorway
  from catalog data, and correcting it would stop it matching the orders it came
  from. Three over-corrections went back the other way too — `analyses` is the
  plural of *analysis* in both dialects.

- **The changelog's dates ran backwards.** 2.48.0 was dated 2026-08-24 sitting
  above a 2.47.0 dated 2026-08-23. All three of 2.47–2.49 now read 2026-08-23.

- **The backup card's "the binary arrives by a bind mount" advice was true of
  one provider.** `rsync` and `openssh-client` have shipped **in the image**
  since 2.46; only rclone is bind-mounted. The message now names the right
  remedy per binary.

- **A redundant second clamp on the home carousel.** `visibleCount` is already
  bounded by the number of hats with photos, so the extra `Math.min` restated
  that rule in a second place.

### Changed
- **One definition of "is this binary present":**
  `backup_service.binary_available()`. The upload-test endpoint re-derived it
  with its own lookup, so two code paths could disagree about whether an upload
  could possibly run. The duplicated "Unknown provider" rejection is gone for
  the same reason.
- `['settings', 'tls']` added to the documented query-key list, which had missed
  the one 2.46 added.

### Added
- **A field-parity test between `TlsStatus` and `TlsStatusRead`.** The route
  builds the response by splatting the dataclass, and pydantic's default
  `extra='ignore'` drops unknown keys **silently** — add a field to the
  dataclass, forget the schema, and the API just stops reporting it with nothing
  red in CI.
- **A tautological test replaced with one that measures something.** Asserting a
  field is a `bool` proved only that pydantic works. It now drives the real
  lookup to both answers and checks each one reaches the payload.

### Known
- `tls_health.ca_fingerprint()` imports a constant from a route module — a
  service reaching into a route, which inverts the layering the rest of the
  backend follows. Left alone deliberately: it is a judgment call rather than a
  breach of a documented standard, and moving the constant touches 5 source and
  12 test sites. Recorded here so it stays a decision rather than an oversight.

## [2.49.0] — 2026-08-23

The LAN HTTPS front door can answer on more than the `.local` name, so the app
is reachable over a VPN instead of looking like it is down.

### Fixed
- **Over a VPN the app was unreachable in a way that read as an outage, and the
  server was fine the whole time.** Three separate causes stacked up, each of
  which alone is enough to break it:

  1. **`headroom.local` is mDNS, and mDNS is link-local multicast.** It cannot
     cross a VPN, a tunnel, or a routed subnet. The name simply does not
     resolve, and there is nothing to fix in DNS because no DNS is involved.
  2. **Connecting by IP failed the TLS handshake outright.** Caddy rejects a
     connection whose SNI matches no configured site, and only `headroom.local`
     was configured. `curl --resolve headroom.local:443:<ip> https://headroom.local/`
     returns **HTTP 200**, while `curl https://<ip>/` returns **HTTP 000** — no
     response at all — even with `-k`.
  3. **Even had it matched, the certificate would not have.** It carries
     `DNS:headroom.local` and no IP SAN.

  What turned this from "does not work" into "the server is down" is Caddy's
  automatic HTTP→HTTPS redirect: `http://<ip>/` answers with a **308 to
  `https://<ip>/`**, which is precisely the address that cannot complete a
  handshake.

  The site address list is now **configurable** — `HEADROOM_SITE_ADDRESSES`,
  comma-separated — and defaults to `{HEADROOM_MDNS_HOSTNAME}.local`, so
  existing installs are byte-identical to what they served before. Adding the
  LAN IP (or a Tailscale/WireGuard name) makes Caddy serve it *and* puts it in
  the certificate as an IP SAN signed by **the same root**, so devices that
  already trust the CA need no reinstall:

  ```bash
  HEADROOM_SITE_ADDRESSES="headroom.local, 10.0.111.4" \
    docker compose -f docker-compose.yml -f docker-compose.https-lan.yml up -d
  ```

  **Passkeys still only work on the origin in `HEADROOM_ORIGIN`.** WebAuthn
  credentials are bound to an origin. That is WebAuthn working correctly, not a
  misconfiguration, and it is not something a certificate can fix. Password
  login works on both.

  **There is also a zero-config remote path that needed none of this:**
  `http://<ip>:8000` reaches uvicorn directly, bypassing Caddy entirely. It is
  plain HTTP, so it is not a secure context and passkeys are unavailable there
  either.

### Added
- `HEADROOM_SITE_ADDRESSES` documented in the operations environment table and
  in the README's HTTPS section, with a troubleshooting entry for the exact
  presentation — *works on the LAN, dead over the VPN*.
- A test asserting the Caddyfile's site line is env-driven and still defaults to
  a `.local` name. It reads the Caddyfile, because a constant in this repo would
  agree with itself while the deployed configuration said something else.

## [2.48.0] — 2026-08-23

The LAN HTTPS certificate now lasts 820 days instead of twelve hours.

### Fixed
- **`https://headroom.local` served a certificate that had expired weeks
  earlier, and Caddy spent every one of those days trying to fix it.** Caddy's
  internal CA issues **twelve-hour** leaf certificates by default. Twelve hours
  is a good default *if renewal always works*. Here renewal stopped: an unclean
  shutdown destroyed Caddy's stored leaf private key, and with no key to sign
  against, the renewal it queued every ten minutes could never complete.

  Leaf certificates are now issued for **820 days**. A certificate that outlives
  the gap between something breaking and somebody noticing is worth more on a
  LAN than a short blast radius, and 2.46's `tls_health` check exists precisely
  because nothing here notices quickly.

  **820 is a ceiling, not a preference.** Safari — and therefore every iPhone in
  the house — rejects a TLS server certificate whose validity exceeds **825
  days**, even when it chains to a manually installed root. The widely-quoted
  398-day cap is a different rule that applies only to Apple's *preinstalled*
  roots; user-added roots get 825, verified by binary search. Chrome and Firefox
  impose no limit here at all, which is exactly the trap: "make it ten years"
  produces a setup that works on the laptop you test it from and fails on every
  phone.

  **The root is untouched and still lasts ten years**, so nothing needs
  reinstalling. Raising `intermediate_lifetime` regenerates the *intermediate*,
  which is presented during the handshake; the root is the self-signed trust
  anchor sitting in each device's keychain.

  **This does not repair a device that currently refuses to trust the CA.**
  Deploying this release changes what is served, not what is trusted.

### Changed
- **The Caddy sidecar runs from a `Caddyfile` instead of `caddy
  reverse-proxy`.** The CLI form cannot express PKI options at all, so the
  twelve-hour default was not something the old configuration could have
  overridden. New `./Caddyfile`, bind mounted read-only, setting
  `pki { ca local { intermediate_lifetime 3000d } }` and
  `tls { issuer internal { lifetime 820d } }`. Caddy requires the issued
  lifetime to sit under `renewal_window_ratio` × the intermediate's, so an
  820-day leaf needs an intermediate of at least ~2460 days; 3000d clears that
  and still sits below the 3600d root.

  `docker-compose.https.yml` — the internet-facing overlay — deliberately keeps
  the CLI form. Its certificates come from Let's Encrypt, which sets its own
  90-day lifetime.

- **`tls_health.RENEWAL_GRACE_DAYS` 2 → 30.** Two days was generous against a
  twelve-hour certificate. Against an 820-day one it is a fire alarm that rings
  as the roof falls in.

- The **Trust this device** card and the README's HTTPS troubleshooting both
  said the certificate "lives twelve hours", and the card's warning read
  *expires within hours*. The card now names the real number of days remaining,
  and says *ran out* versus *runs out* correctly.

### Added
- Two tests guarding the ceiling, because the failure mode is invisible on the
  machine you would test it from. One fails if the Caddyfile's leaf lifetime
  reaches 825 days; the other checks Caddy's own constraint, which otherwise
  surfaces as a sidecar that refuses to start after a deploy.

## [2.47.0] — 2026-08-23

Build speed. Nothing about the running app changed.

### Changed
- **A release rebuild on the Pi took 873s, and 490s of it was reinstalling
  dependencies that had not changed.** Cutting a release edits the `version`
  field in `pyproject.toml` — and `pyproject.toml` was the file gating the
  dependency layer. So the copy busted on every release, `uv sync` re-ran
  (237s), and the rembg model layer sitting downstream of it fell with it
  (149s).

  Dependencies now install from `requirements.txt`, generated by
  `uv export --frozen --no-dev --no-emit-project --format requirements-txt`.
  `--no-emit-project` leaves the project — and therefore its version — out, so
  the file is byte-identical across a version bump and the layer survives one.
  `--require-hashes` keeps the supply-chain guarantee `--frozen` gave here:
  every artifact must match the digest recorded in `uv.lock`.

  The version-bearing `COPY pyproject.toml uv.lock*` moved to **after** the
  dependency install. It is still `uv sync --frozen` with no fallback, and it
  still busts on every release — but installing the project alone against a venv
  that already satisfies the lock costs 6.5s.

  `npm ci` also gained `--no-audit --no-fund`. Deliberately **not**
  `--ignore-scripts`: rolldown and esbuild fetch their platform binary in a
  postinstall, so skipping scripts produces a build that fails later and further
  away.

  Measured A/B on the Pi this deploys to:

  | Step | Before | After |
  |---|---|---|
  | `uv sync` (dependencies) | 237s | **cached** |
  | rembg model layer | 149s | **cached** |
  | `npm ci` | 104s | 53s |
  | image export | 276s | 259s |
  | **Total** | **873s** | **531s** |

  A 39% reduction, with cached steps going from 7 to 10. The export line is
  unchanged because it is SD-card write throughput.

  **The first build after upgrading is slower — measured at 1106s.** The layer
  shape changed, so its cache is cold and everything rebuilds once.

### Added
- `tests/test_requirements_export.py`, because the two ways this silently
  reverts both leave a green build: a bump can land in `uv.lock` without
  `requirements.txt` being regenerated, and the image then quietly installs the
  **old** set while every test passes against the new one. The other is anyone
  moving `COPY pyproject.toml` back above the dependency install. Four tests pin
  both, plus the hash-pinning and the project's absence from the export.

## [2.46.0] — 2026-08-23

### Added
- **The app now watches its own HTTPS certificate.** `GET /api/settings/tls`
  opens a TLS connection to the app's own origin and reports what is actually
  being **served** — expiry, days remaining, whether the certificate covers the
  name it is served under, and the SHA-256 of the CA this install hands out.
  Surfaced in **Settings → This device → Trust this device**.

  Written because the real deployment served a long-expired certificate and
  nothing noticed. Caddy's stored leaf key had vanished, so its renewal queued
  every ten minutes and never completed. The container was healthy, the app
  answered, backups ran — every signal was green, because nothing here had ever
  looked at the certificate in front of it.

  It measures the served chain rather than reading Caddy's storage, because
  those disagree: that failure had a valid certificate **on disk** and an
  expired one in Caddy's memory.

  It is reported, never enforced. The certificate belongs to Caddy, so failing
  readiness on it would restart-loop the app without fixing anything.

- **The CA fingerprint is published**, because a name is not an identity. Caddy
  names every root `Caddy Local Authority - <year> ECC Root`, so two installs
  produce two **different** roots with the **same** name, and a browser matching
  by name reports an invalid signature on a chain that verifies perfectly at the
  server. The card now shows the fingerprint and the command to list what a Mac
  actually trusts.

- **Off-site backups to rsync and Synology.** Three providers now, each a single
  frozen record driving the argv, the validation, the UI copy and the preflight
  check — so adding a transport is one entry rather than four edits that can
  disagree.

  | Provider | Destination | Needs |
  |---|---|---|
  | Cloud storage (rclone) | `box:Headroom-Backups` | `rclone config` + the rclone overlay |
  | rsync over SSH | `pi@nas.local:/volume1/backups/headroom` | an SSH key + the rsync overlay |
  | Synology NAS (rsync service) | `backup@nas.local::NetBackup/headroom` | DSM's rsync service + `HEADROOM_BACKUP_RSYNC_PASSWORD` |

  The two rsync destinations differ by **one colon, and that is the whole
  transport**: `host:/path` is rsync over SSH, `host::module/path` connects
  straight to a daemon on port 873 and reads the first segment as a module name.
  Validation is per provider so a typo cannot silently switch transport and fail
  with credentials nobody configured, looking like a broken NAS.

  `rsync` and `openssh-client` now ship **in the image** (~3 MB). rclone is
  ~50 MB and stays a bind mount.

- **The off-site backup card explains how to finish setting up.** Each provider
  carries its host-side steps, its destination shape, an example, and whether
  its binary is actually present in the container. "Configured" and "working"
  are different states. **Test now** also says outright when the binary is
  missing, instead of surfacing a subprocess's "No such file or directory".

### Fixed
- **The macOS trust instructions**, which stopped at "double-click the file".
  That lands it in whichever keychain Keychain Access last had selected; the
  **iCloud** keychain cannot hold certificates and rejects the import with
  `Error: -26276`, which reads like a bad file rather than a wrong destination.
  Both the card and the README now lead with `security add-trusted-cert`, and
  note that a browser's own export button always hands you the leaf or the
  intermediate and **never** the root.

## [2.45.0] — 2026-08-23

### Fixed
- **`GET /api/public/ca-certificate` returned 404 on every install that ever ran
  the LAN-HTTPS overlay.** The endpoint exists so a phone can trust
  `https://headroom.local` by opening a URL; instead it reported that no local
  CA exists, to operators who were looking directly at Caddy serving
  certificates.

  The route read Caddy's PKI in place. Caddy creates that tree `0700 root`, and
  this app's container runs as a non-root user by policy, so the traversal
  failed — and `Path.is_file()` reports a permission failure as plain `False`,
  which made **"mounted but unreadable" indistinguishable from "not
  installed"**. It had never worked, on any release, on any deployment.

  The overlay now runs a `caddy-ca-export` sidecar that copies the public root
  out to its own volume, world-readable, and the app mounts *that* instead of
  the PKI. Copying one file rather than loosening permissions also means the app
  container has no key material in view at all. It polls rather than copying
  once, since Caddy mints the CA a moment after startup on a first boot and
  rotates its intermediate periodically after that.

  `_unavailable_detail()` now tells the two failures apart, so a still-broken
  install is told what is actually wrong.

  **Upgrading:** recreate the stack (`docker compose -f docker-compose.yml -f
  docker-compose.https-lan.yml up -d --build`) to pick up the new service.

- **README's macOS trust step.** It said to double-click the certificate, which
  lands it in whichever keychain Keychain Access last had selected; the
  **iCloud** keychain cannot hold certificates and refuses with `Error: -26276`.
  The step now leads with `security add-trusted-cert`.

### Changed
- **The home carousel shows two hats side by side on a desktop**, one on a
  phone. The breakpoint is 992px — the width this app already treats as desktop
  — so it is not a new number to keep in step.

  The count is decided in JavaScript rather than by hiding a second slide in
  CSS, so a phone never downloads a photo it will not display.
  `useSyncExternalStore` rather than `useState` + an effect: the effect version
  renders one frame at the wrong size and visibly pops on every mount.

  Two details are pinned by tests: the visible count is clamped to the number of
  hats that actually have photos, and the arrows now hide when everything is
  already on screen.

## [2.44.0] — 2026-08-23

### Added
- **An off-site backup card in Settings.** The feature has existed since 2.38
  and was configurable only by editing `.env` and restarting, with no way to
  learn whether it had ever actually run short of reading container logs. That
  is the wrong shape for the one thing standing between a dead SD card and
  losing the collection.

  The card answers three questions: is a copy configured, did the last one work,
  and does it work *right now* — the last via a **Test now** button that
  performs the real upload against your newest backup. A dry run would only
  prove the form had been filled in.

  **The form does not accept a command, deliberately.** The browser sends a
  provider name and a destination; the argv is assembled from a template the
  server owns, and the destination must match `remote:path`.

  `HEADROOM_BACKUP_UPLOAD_CMD` still works and now **wins** over anything set in
  the UI, which is the opposite precedence to the API keys. That variable is
  settable only with host access. When it is set, the card goes read-only and
  says so.

- **Upload outcomes are recorded** — last attempt, whether it succeeded, the
  error, and running success/failure counts — separately from the backup's own
  health. The two fail independently: a local backup can succeed every night
  while the off-box copy has been failing for a month.

## [2.43.0] — 2026-08-23

A test-coverage audit, and the bug it found.

### Fixed
- **Bulk import failed every single item.** `_process_item` reads
  `item.filename` a few lines after calling `create_hat` — and `create_hat` ends
  in a reload that calls `db.expire_all()`. That expires every object in the
  session, the import item included, so the next attribute read triggered a lazy
  refresh through synchronous attribute access, which an async session cannot
  service. The per-item handler caught it and recorded an error, so the feature
  failed completely while presenting as a batch of bad files.

  Found by writing the first test that ever ran the worker. It reads what it
  needs into plain locals before `create_hat` now.

### Added
- **Coverage measurement**, as `pytest --cov` with **branch** coverage. Branch
  rather than statement because this codebase's risk lives in degradation paths
  — Claude unconfigured, rembg failed, worker dead — which are branches, and a
  statement-only number counts them covered the moment the happy path runs once.
- **58 new tests** against what the audit found was least covered, which was not
  random: the modules with the strongest docstring promises had the weakest
  coverage.
  - `import_service` **46% → 87%** — the durability claims were prose, not
    tests.
  - `utils/upload` — the 413 cap, whose own docstring says an untestable limit
    "is how the last one went missing".
  - `report_service` **53% → 97%** — the document that goes to an insurer.
  - `claude_analysis` **57% → 84%** — request shape and failure translation.
  - `ebay_service` **53% → 73%**, `melin_recap` **69% → 83%**, `google_vision`
    **72% → 84%** — the degrade-don't-fail paths, which on a Pi talking to four
    third parties are not edge cases.

## [2.42.0] — 2026-08-23

The remainder of the archaeology report, plus build-time work.

### Added
- **`GET /api/admin/config`** — what this deployment is *effectively* configured
  to do. Every toggle is an env var read live, and a typo degrades to the
  default rather than crashing, so a misconfigured box looked identical to a
  correct one from outside. Reports worker expected-vs-alive, backup interval
  and keep-count, whether an off-box upload is configured at all, the body and
  disk limits, and free space. No secrets.
- **`analysis_stage_at`** — a stage alone can't distinguish a pipeline that is
  working from one that is wedged; both read "identifying". Stamped by the same
  `UPDATE` that sets the stage, so the two can never disagree.
- **ruff**, inside the existing backend CI job rather than a new one. It
  immediately found **16 dead imports** and a genuine forward reference that
  worked only because annotations are deferred. 58 `noqa` codes had been written
  to an authority that was never installed.

### Fixed
- **The Settings tabs fit a phone, on one line.** As a horizontal scroller the
  tabs past the fold were invisible — no scrollbar on touch, last pill flush
  with the gutter. The real constraint turned out to be the LABELS, not the
  layout: five names have to share ~320px. They are **Data**, **Device** and
  **Upkeep** now, in five equal columns, one row, no scrolling and no ellipsis.
- **Stats, Valuation and Home gate on `isError`.** `?? []` turned a failed fetch
  into "$0 across 0 hats" — a confident wrong answer.
- **The nav error badge is labeled.** A bare red dot is unreadable to a screen
  reader; it counts hats whose *analysis* failed, not errors in general.
- **`melin_recap` logs.** A network service with a declared, never-used logger,
  whose documented failure mode presents as the entire collection quietly losing
  its resale prices.
- **One correlation token.** `hat=%s` everywhere, so `grep 'hat=42'` is a
  complete trace of one run instead of five formats.
- **The Claude prompt stopped teaching a discarded answer.** `construction` is
  owner-only, but the schema demanded it and spent ~200 tokens per analysis on
  guidance that ended with a false claim. Trimmed and dropped from `required`.
  The **stitching falsifier stays**, reframed around what it actually protects:
  `model_name`, which *is* stored and *is* the name a person reads.

### Changed
- **Docker builds cache their layers in CI.** The image job rebuilt apt,
  `uv sync`, `npm ci` and a full SPA build from scratch on every run.
- **`npm ci` caches on the Pi.** Cutting a release edits
  `frontend/package.json`, which busts that layer — so every upgrade
  re-downloaded the entire dependency tree over the Pi's own network. A cache
  mount survives the invalidation, and `--prefer-offline` stops it revalidating
  each tarball.
- **A docs-only commit no longer re-runs CI on `main`.** Excluded on `push`
  only — `pull_request` still gates every change.

## [2.41.0] — 2026-08-23

### Fixed
- **Color search returned most of the collection whatever you asked for.** It
  ranked hats by CIEDE2000 distance and kept everything under a cutoff of 26 —
  and ΔE 26 is an enormous distance. At that threshold **51 pairs of curated
  palette colors matched each other**: black with navy, silver with beige, white
  with cream. Three releases were spent moving that number (30, then 22, then
  26) and the file's own comment already had the answer: a distance threshold
  cannot answer "is this hat purple?"

  The measurement that ends the argument: within-family distances run up to **ΔE
  55.8** (light blue to navy, both plainly blue) while cross-family ones start at
  **15.4** (black to navy). The ranges do not overlap, they *invert* — so no
  threshold exists that separates them.

  Membership is now categorical, decided on the curated palette names where the
  question has an exact answer. Distance keeps the job it is good at: ordering
  hats that are already the right color.

  Two refinements earn their place. A swatch too muted for its name to be
  trustworthy is classified by **hue angle** instead — a dark teal sits nearest
  *charcoal* by ΔE because it is dark, but its hue is 197°, the same as a mid
  teal's — with the existing chroma-*ratio* guard separating the case that must
  match from the one that must not. And blue/purple can never be bridged by hue
  at all, because CIELAB's hue angle is non-linear through the blue region.

  A color chip now honors major colors the same way a typed color term has since
  2.39, with a per-rank distance budget so "the hat with the pink brim" still
  works but a pinkish logo no longer counts as a pink hat.

- **The collection export took longer than a full backup and produced nothing.**
  It generated every hat's 800px derivative inline, in the card-rendering loop,
  **on the event loop** — a full-resolution decode and a slow WebP encode each. A
  few hundred hats is minutes during which the app answers no request at all.

  Derivatives are now written when the photo is processed, swept in at boot for
  hats that predate the change, and whatever is left resolves on a worker thread
  with progress logging.

- **A legacy hydro/hydrolite flag was dropped when sent with another field.**
  The branch handling pre-2.11 clients hung off the wrong test, so a flag sent
  *alongside* an artist series was silently ignored while one sent alone worked.

- **The purchase importer disagreed with its own preview.** The importer adds a
  row per unit as it walks a batch, and the dedupe query autoflushed those
  pending rows — so units the batch had just staged were counted twice. The
  preview writes nothing, so it had nothing to flush and stayed correct.

- **The case forms advertised the wrong capacity, in both digits.** They read
  "Default: 4 regular / 6 beanies"; a default case is **3 regular (4 at a
  squeeze) / 8 beanies**. Now built from the constants and pinned by a parity
  test.

## [2.40.0] — 2026-08-23

The three failures this deployment was structurally unable to notice, plus
backups that stop restating themselves.

### Changed
- **Backups are written only when the data has changed**, and retention is now a
  **count** (`HEADROOM_BACKUP_KEEP`, default 5) rather than an age. On an
  untouched collection a daily tarball re-read every photo, wore the SD card,
  and evicted a genuine historical snapshot to store a restatement of the newest
  one.

  The two changes are one change. Age-based pruning combined with change-gating
  has a steady state of **zero backups** on an idle system. Counting cannot do
  that. `HEADROOM_BACKUP_RETENTION_DAYS` is still read — as a count — so an
  existing `.env` keeps meaning something.

  Change is judged from the size and mtime of the database, **its WAL sidecar**
  (a commit in WAL mode can leave the main file untouched), and every file under
  uploads. The marker recording the last backed-up state is a file in `backups/`
  and deliberately not a row in the database — the database is part of what it
  measures.

### Added
- **The app can see the disk filling up.** There was no free-space check
  anywhere, and readiness proved the volume was writable by writing two bytes —
  which succeeds with 8 KB free, while the next backup tarball fails. Two
  thresholds: a warning in the log below 15%, and readiness failure below a hard
  floor of 500 MB. The floor is an absolute size rather than a percentage
  because what matters is whether the next backup fits.
- **Readiness fails when a background worker has died.** The Docker healthcheck
  is anonymous and worker liveness was authenticated-only detail, so the
  container could not go unhealthy for a dead analysis or import worker. Gated
  on whether the worker is *expected* to be running, so a deliberately disabled
  one is not reported as a fault.
- **The Backups card now says whether the scheduler is working.** The endpoint
  that answers this shipped in 2.26 and nothing ever rendered it. It
  distinguishes running-and-idle-because-nothing-changed from failing from not
  running at all.
- **Unhandled errors become activity-log rows.** A 500 previously left exactly
  one trace: a stack trace on stdout, inside a container, on a Pi. The traceback
  still reaches the log — the row joins it rather than replacing it.

### Fixed
- **Security headers were missing from every 401.** `add_middleware` prepends,
  so the last one added is outermost — and the header middleware was added
  first, which put it behind the auth gate. The test named for this invariant
  asserted against `/health`, the one path where it already held.
- **`last_success_at` no longer forgets on restart.** The health record is
  process-local, and on this deployment restarts are routine, so the endpoint
  named *health* was the one that forgot — and `null` reads as "never
  succeeded". It falls back to the newest backup's mtime, flagged as derived.
- **Large non-multipart request bodies are refused early.** Every upload path
  was careful; nothing else was. Bodies over 2 MB are now refused with 413
  before the auth gate spends a database lookup on them. Multipart is exempt —
  those routes stream to disk under their own, much larger, deliberate caps.
- **A rejected password is no longer echoed back in the 422.** Pydantic puts the
  offending `input` into every validation error and FastAPI serializes the list
  straight into the response body. The field and the reason stay; the value was
  the one part the caller already had.
- **The Google Vision API key is no longer printed to the container log.** It
  traveled as a query parameter, and httpx logs the full request URL at INFO on
  every call. It goes in the `X-Goog-Api-Key` header now, which is what Google
  documents it for.
- **A bulk import with no worker running says so at ERROR**, and the check is
  now on the worker rather than on the queue object — a queue with nothing
  draining it accepts work silently. `stop_worker` clears the queue to match
  `analysis_queue`. Scheduled-backup and upload-hook failures were promoted to
  ERROR as well: nothing in 75 logging call sites was ever logged at ERROR.

## [2.39.0] — 2026-08-22

### Fixed
- **The guest grid's tiles were broken, and it was `.card` on an anchor.**
  `.card` never declared a `display`, which was invisible while every card was a
  `<div>`. 2.37 made the guest tiles links, and an `<a>` is `display: inline` —
  so `h-100` was ignored outright and the border broke across line boxes.
  `.card` now says `display: block`. This was latent in five other places.

- **A hat is not "pink" because its logo is.** Color terms matched ANY row in
  `hat_colors`, so searching "pink" returned every black cap with a pink
  embroidered mark. On this collection that made color search close to useless:
  a melin hat is a dark crown with a bright logo. Color terms now match **major
  colors only** by default — dominance rank 1–2.

- **The guest search didn't survive going to a hat and back.** The term lived in
  component state, which a re-mount discards. It lives in the URL now
  (`/guest?q=…`), and the results are cached long enough that the page is its
  full height when the browser restores your scroll position.

### Added
- **A color-match toggle: Main colors / Accents only / Any.** "Accents only" is
  its own question rather than the leftovers of the default — *which of my hats
  has pink on it somewhere* is how you look for a collab mark or a contrast
  underbrim. On the Search page and the guest page; on the latter it is in the
  URL too. An unrecognized value falls back to the default, because it arrives
  from a query string and the safe reading of a typo is not a wider search.

## [2.38.0] — 2026-08-22

### Added
- **The server hands you the certificate to trust.**
  `GET /api/public/ca-certificate` serves Caddy's **root** CA, linked from
  **Settings → This device → Trust this device** (which appears only when a
  local CA exists). Open it on the phone and iOS offers to install it — no
  `docker compose cp` on the Pi and no AirDrop.

  Served as `application/x-x509-ca-cert`, because as `text/plain` a perfectly
  good certificate is displayed rather than installed.

  **Only `root.crt` is served, and the filename is hardcoded.** The handler
  takes no path, no filename and no parameter of any kind. The overlay mounts
  Caddy's volume read-only.

### Documentation
- **The intermediate is the trap, and now the docs say so.** `root.crt` and
  `intermediate.crt` sit side by side and only the root is a trust anchor: a
  root is self-signed and installed out of band, whereas an intermediate is
  presented by the server during the handshake and means nothing until its
  issuer is already trusted. Installing one therefore *appears to succeed and
  changes nothing*. Called out in the README's step 2 and added to its
  troubleshooting list.

## [2.37.0] — 2026-08-22

### Added
- **Guests can open a hat.** Tiles in the guest view are now links to
  `/guest/hat/:id`, showing the photo, name, style, colors and — given the most
  room, because it is the question a guest actually has — **which room and which
  case** it lives in. A caseless hat says so and still names its room.

  A real endpoint rather than a detail rendered from the listing payload, so the
  link survives being sent to somebody. It returns **exactly** the `SharedHat`
  projection the grid already used, and a test pins the response's key set.

### Fixed
- **`shared_hat` required a photo**, because its only caller was the photo
  endpoint. A hat plainly listed on the page you clicked from would have 404ed
  when you clicked it. It now answers "may an outsider see this hat", which is a
  different question from "does it have a photo to serve".
- **`shared_hat` used `db.get`**, returning a bare instance, so the projection's
  room lookup raised rather than lazy-loading under asyncio. It now eager-loads
  what the projection reads.

## [2.36.2] — 2026-08-22

Findings from a two-axis review of 2.34–2.36.1.

### Security
- **Guest search matched on fields the guest projection withholds.**
  `SharedHat` deliberately omits condition, size, collection and construction,
  but guest search delegated to the owner's search, which matches on all four.
  `search_hats(public_fields_only=True)` now drops those clauses **and the
  hydro/hydrolite flags derived from construction**. The owner's own search is
  unchanged.

- **`/api/auth/status` no longer tells anonymous callers that guest view
  exists.** It returned `guest_view_enabled: false`, which is precisely the fact
  the guest routes' 404-rather-than-403 was written to keep private. The field
  is now absent when off.

### Fixed
- **Guest search reported a capped count.** The response's `hat_count` is its
  own length, and search was bounded to 50 — so a search matching 200 said "50
  hats". The third instance of the same `len()`-of-a-capped-list mistake. Guest
  search uses its own, higher bound.
- **The case-valuation rule was stated a third time**, inside `report_service`,
  where the parity test cannot see it — and it had already drifted. Moved to
  `services/valuation.value_cases()` beside the hat rule, with a parity test.
- **Home and Stats showed a Cases tile beside a hats-only total.** Both now
  carry a combined figure, as the Valuation page and the report already did.

### Changed
- One projection *mapper*, not just one projection type. The share-link and
  guest routes each built `SharedHat` field by field, so a field added to the
  projection would be filled in at whichever site the author was looking at, and
  the copy that fell behind would be the one exposed to strangers.
- Guest fetching moved into `frontend/src/api/guest.ts`, per the convention that
  API functions live in `api/`.

## [2.36.1] — 2026-08-22

### Fixed
- **"Re-analyze every hat" was re-analyzing a fraction of them** — 45 of 234 in
  a real collection.

  A checkbox above the button read *"Leave hand-entered prices alone"* and was
  **on by default**. It mapped to a server filter restricting the run to hats
  whose price source was Claude Vision.

  Before 2.27 that was very nearly every hat. **2.27 moved the majority onto the
  retail table**, and the same filter then matched only the remainder Claude
  still prices. Nothing announced the change in meaning; the button still said
  "every hat".

  The filter was **redundant from the start**. A Manual price is protected
  unconditionally, so it never spared anything that wasn't already safe — it
  only shrank the run.

  Removed. Re-analysis now covers **every hat with a photo**; disposed hats
  remain the only exclusion.

- **The queue's "waiting" count was capped at 50.** `pending_count` was `len()`
  over a list deliberately bounded to 50 for display, so a deeper backlog always
  reported 50. The list stays bounded; the count is now a `COUNT`.

## [2.36.0] — 2026-08-22

### Added
- **Guest browsing.** A "browse the collection as a guest" link on the login
  screen, letting anyone who can reach Headroom look through the collection and
  search it without an account. Useful on a LAN when people in the house should
  be able to look but shouldn't have a login.

  **Off by default.** Unauthenticated read access to somebody's whole collection
  is not a thing anyone should acquire by upgrading — it is a switch in
  **Settings → Sharing → Guest browsing**, and until it is thrown the endpoints
  behave exactly as if they did not exist.

  **404, not 403, when off.** A 403 confirms the feature is there and merely
  switched off, which is a fact about a private install a stranger has no reason
  to learn. The login screen omits the link entirely rather than disabling it.

  **No pricing, and not by hiding it.** Guests get the same `SharedHat`
  projection share links use: photos, brand, model, style, colors and where a
  hat lives. Prices, purchase history, disposition, wear counts, analysis state
  and owner notes are *never sent* — returning the full model and trusting the
  frontend not to render the rest is exactly how that leaks. Disposed hats are
  excluded too.

  Search is delegated to the real search service rather than reimplemented. A
  guest-only copy would quietly stop matching what the owner's search matches.
  Only a submitted term hits the server.

  Read-only by construction: there are no non-GET routes in the module, and a
  test fails if one is ever added. Turning guest view on does not weaken the
  gate on anything else, which is also tested.

  Flipping the switch is written to the activity log both ways.

## [2.35.0] — 2026-08-22

### Added
- **Rooms are viewable, and loose hats come first.** There was no room view at
  all: `/rooms` listed names with rename and delete, and rooms weren't
  clickable. So the room-stored hats added in 2.33 had **nowhere to be seen**.

  `/rooms/:id` shows what's actually in a room, with the loose hats **above**
  the cases. That ordering is the point: a cased hat is findable three other
  ways, a loose one is findable here and in search. It also matches a physical
  room — the things sitting out are what you see when you walk in.

  The rooms list gains a loose count too, since a room holding three hats and no
  cases previously read as empty.

  `GET /api/rooms/{id}` now returns `RoomDetail` (loose hats + cases); loose
  hats are newest-first.

### Fixed
- **`invalidateHatViews` now covers `['room']`.** It is a *sibling* of
  `['rooms']`, not a prefix match — TanStack matches by prefix and "rooms" is not
  a prefix of "room". Without it, moving a hat into or out of a room left the
  room view showing it where it used to be for the full 30s `staleTime`.

## [2.34.0] — 2026-08-22

### Fixed
- **The cases were in no total at all.** `CaseRead.retail_price` had been served
  since 2.27 and was read by *nothing* — it existed only in the TypeScript type.
  So "collection value" excluded dozens of $49 travel cases, understating the
  thing it names by four figures, and silently.

  They now appear on the Home summary, the Stats "Money" card, the Valuation
  page and the printable inventory report — which matters most, since that is
  the document that goes to an insurer.

  **Reported on their own line, never folded into the hat figures.** Two
  reasons, and both would have been invisible if ignored:

  - A case is not a hat. Quietly adding a couple of thousand to a number labeled
    *market value* would make every comparison on the page — retail retention,
    unrealized gain, cost per hat — wrong in a way nobody could see.
  - The two are different *kinds* of number. Hats are valued from live
    comparable listings; cases have no resale market at all, so $49 is
    replacement cost. The Valuation page adds an "Everything, together" line.

  `valueCases()` sums each case's **served** `retail_price` rather than
  multiplying by a constant declared in TypeScript.

## [2.33.0] — 2026-08-22

### Added
- **A hat can live in a room with no case.** Rooms contain Cases contain Hats
  was the whole model, so a caseless hat reported no room at all — it was
  *nowhere*. That is not how a collection sits: Caddies and Aviators don't fit a
  three-hat travel case, special editions get displayed rather than packed, and
  plenty of hats are simply out on a shelf.

  Any hat can be placed this way; nothing is restricted by style. A case and a
  direct room are **mutually exclusive** — `assign_hat` clears one when it sets
  the other, because a cased hat's room *is* its case's room. `room_id` still
  resolves either, so nothing reading it had to change.

  Deleting a room moves its caseless hats to the default room alongside its
  cases. Left behind they'd point at a room that no longer exists.

- **Limited edition** checkbox on the hat form. Nothing can derive this: a hat
  is limited because the drop was.

### Changed
- **Beanie case capacity is 8, up from 6**, and 8 is a *hard* ceiling. They have
  no brim and squash flat, so far more fit in the same shell than the three the
  case is named for. Beanies get **no overfill allowance**: the regular one
  exists because 3 is melin's *name* for the case and a fourth demonstrably
  fits. 8 is the opposite — it is what fits, counted by packing it.

### Fixed
- **Search by room could not see room-stored hats** — caught by review before
  release. The API filter went through the case, which is NULL for a caseless
  hat, while the Hats page filters client-side on the resolved room and kept
  showing them. `search_service._in_room()` is now the one disjunction both call
  sites use.
- **Creating a hat in a nonexistent room was accepted.** `assign_hat` checked;
  `create_hat` didn't. The migration adds `direct_room_id` without a foreign key
  (SQLite cannot add one to an existing table), so the bad id persisted.
- **The case detail page showed the wrong capacity, twice.** It computed its own
  fallbacks — a second copy of a rule `services/capacity.py` owns. `4` is the
  *overfill limit* rather than nominal, so a full three-hat case displayed
  **"3/4"**. `CaseRead` now publishes `nominal_regular` and `nominal_beanie` so
  no client restates either.

## [2.32.0] — 2026-08-22

### Breaking
- **Analysis no longer decides construction. At all.** It never overwrote a
  stated value, but it filled the field whenever it was *empty* — and the
  function's own docstring already explained why that was unsafe: Claude reads
  HYDRO vs HYDROLite off a photo unreliably, because the tells are bonded seams,
  a gel-welded logo and a sweatband, none of which survive a front-on shot.

  Two later changes turned a cosmetic guess into an expensive one:

  - **It moved money.** `retail_pricing` prices HYDRO at $79 and HYDROLite at
    $99, so a guess skewing HYDROLite over-priced the hat by $20.
  - **It hid hats.** 2.29 made construction a filter, so a mislabeled hat is
    absent from a filtered view rather than merely wrong in a detail pane.

  A blank construction is an honest *"nobody has looked yet"*. A guessed one is
  indistinguishable from one you typed. **Construction is now owner-only.**

- **A model name may not assert a construction nobody stated.** melin names read
  `<line> <construction>`, so "A-Game HYDROLite" carries the same guess in the
  field a person actually reads — and the stripper returned early when no
  construction was stated, so a blank protected nothing. With none stated, every
  construction is now stripped from the name. Removed, not rewritten: "A-Game
  Thermal" would be an invented product name, where "A-Game" is less specific
  and true.

### Added
- **Construction audit** (Settings → Construction audit), for undoing what
  analysis already wrote. Nothing in the database records which values came from
  a person, so this deliberately is *not* a startup backfill: it lists every
  construction on record with how many hats are priced from it, previews exactly
  what clearing one would do, and acts only on an explicit confirmation.

  Clearing a construction also clears what was derived from it — the
  construction word in `model_name`, and a retail price that came from the price
  table. **A price you entered manually is never touched.**

  It **reassigns** rather than only clearing: `to=HYDRO` writes the right
  answer, because the common case is not "I don't know" but "these are all
  actually HYDRO". The price is then re-looked-up from the new value.

  And it **leaves your own values alone**: an audit row naming `construction`
  among the fields a client PUT changed is proof a person typed it, so those
  hats are skipped and the count is reported. This is a proof of ownership, not
  a complete one — audit rows prune after 90 days — so it can say "this one is
  definitely yours", never "this one is definitely not". That asymmetry is the
  right way round: it only ever protects more.

  `GET /api/admin/constructions/audit`, `POST /api/admin/constructions/clear`
  (`dry_run=true` and `skip_owner_set=true` by default).

- **The analyzer now knows the one HYDROLite tell that a photo can show.**
  HYDROLite seams are bonded and show no thread, so **visible stitching on the
  panel or crown seams rules HYDROLite out**. That is a falsifier rather than an
  identification, which is what makes it worth having: it can be checked against
  what the photo actually shows. Stated as a hard exclusion in both the system
  prompt and the tool schema.

### Changed
- **Settings is five sections instead of nineteen cards in a row.** It had grown
  by accretion, ordered by the sequence things were built in, so finding
  anything meant scrolling past everything — which on a phone is most of a
  minute.

  Grouped by **errand**, not by subsystem: *Analysis* spans two API keys, a
  worker queue and an error list, and that is fine because it is one thing you
  came to do. Then *Collection data*, *Sharing*, *This device*, *Maintenance*.

  The section lives in the URL (`/settings?tab=data`), so it survives a reload
  and can be linked to. The tab strip scrolls horizontally rather than wrapping.

  Side effect worth having: only the open section is mounted, so opening
  Settings no longer fires every card's queries at once.

## [2.31.1] — 2026-08-22

### Fixed
- **Typing a known value showed the whole list instead of the match.** Typing
  `Links` into Collection offered every option, alphabetically, which reads as
  the box being ignored. The filter skipped itself whenever the typed text
  exactly matched an option, on the theory that "value equals an option" meant
  "the user picked it". It cannot: typing a known value out in full is the
  normal case. The Combobox now tracks whether the value was **typed** or
  **picked**. Affects both Construction and Collection.

- **Matches are ranked exact → prefix → substring.** The list is capped by
  screen height on a phone and a plain filter is alphabetical, so typing "Links"
  put "Cypress Links" above "Links".

- **The list could not be reopened after picking.** Options call
  `preventDefault` on mousedown so the field keeps focus through a pick; that
  leaves the input focused with the list closed, and tapping it fires no focus
  event. Fixed in **both** the Combobox and the case picker.

## [2.31.0] — 2026-08-22

### Added
- **melin's beanie shapes are now models, not one bucket.** Journey, Destination
  and All Day are named and sold like any other melin model, so they are
  `HatStyle` members. `beanie` remains as **"Beanie (unspecified)"** — existing
  hats use it, and a shape you haven't identified is a real state.

  Prices come from the order history: **Journey $79** and **Destination $79**.

  **All Day is deliberately unpriced.** It appears in the order history exactly
  once, at **$0.00** — a "free with purchase" promo — and a giveaway is not a
  retail price. It falls through to Claude's estimate rather than inheriting the
  $79 that the other two establish.

### Changed
- **`is_beanie` now has exactly one definition.** It is a real column — search
  filters query it and case capacity depends on it — but it is *derived* from
  style, and that derivation was written out separately at each write site.
  `schemas/hat.BEANIE_STYLES` + `is_beanie_style()` is now the single source.

  A beanie shape missing from that set would pack 3-to-a-case, disappear from
  the Beanies filter, and make the case picker offer cases the save then rejects
  with a 409 — none of which looks like a bug from the outside.

- **`GET /api/meta/styles` publishes `is_beanie` per option.** The frontend used
  a literal style comparison to decide case availability; with several beanie
  shapes that would have become a hardcoded TypeScript list. The flag is served
  instead.

## [2.30.0] — 2026-08-22

### Added
- **The analyzer now learns your series.** Entering a collaboration or artist
  series taught the *typing* autocomplete, but it never reached Claude — so
  every analysis was asked to recall a collab from a photo unaided.

  That is the wrong thing to ask. A series is rarely legible in a photo — it is
  usually a small woven label or an embroidery style — so most were simply
  missed. The names already on record are now sent with the image, turning
  recall into recognition.

  The framing is deliberately careful, because a candidate list invites a forced
  choice and a wrong series looks exactly like a right one. It is stated as a
  record of what the collection contains, **not** a list to choose from, with an
  explicit instruction that `null` beats a wrong match. If the list is ever long
  enough to be truncated the prompt says so.

### Fixed
- **Analysis-written free text was never canonicalized.** `vocabulary.canonicalize`
  ran on the client write path but not the analysis path, so Claude returning
  `skye walker` created a second entry beside your `Skye Walker`. Nothing looked
  wrong afterwards — both hats had *a* series — and the split surfaced only as
  two near-identical rows in the autocomplete, the Stats collab chart, and the
  filters. Both paths canonicalize now, covering `artist_series` and a
  construction Claude filled in. Construction goes through `set_construction` so
  the derived flags cannot drift.

  This is what made the feature above safe to ship: feeding known names into the
  prompt without it would have multiplied the very duplicates it exists to
  prevent.

### Note
Existing hats are not retroactively re-identified — nothing in the database can
invent a series that was never captured. **Settings → Analysis Queue →
re-analyze** picks them up, and a re-analysis never erases a series you typed.

## [2.29.0] — 2026-08-22

### Added
- **Filter hats by construction.** The Hats and Search pages share one filter
  bar, so both gained a **Construction** select — populated from
  `GET /api/meta/constructions`, which merges the curated list with every value
  actually in use, so a specialty fabric typed once is filterable from then on
  without shipping a migration. Seeds from the URL like the others
  (`/hats?construction=HYDROLite`).

  Matching is **full equality, never substring** — "hydro" is a literal
  substring of "hydrolite", and those are different products at different prices
  ($79 vs $99), so a `contains()` check would silently fold the two together in
  every filtered view. Casing is ignored, only to tolerate rows written before
  canonicalization began snapping values to one spelling on write.

  There is also a **"Not recorded"** option. The field is nullable by design, so
  "which hats still need this?" is a real question that previously had no way to
  be asked.

### Fixed
- `SearchResult` now carries `construction`. The Search page applies the shared
  predicate client-side to whatever the API returns, so a field the filter reads
  but the projection omitted would have rendered a fully populated dropdown that
  silently matched nothing.

## [2.28.0] — 2026-08-22

### Added
- **QR stickers and NFC tags for hats and cases.** A tag carries one URL and
  nothing else, so both formats are the same feature: print the QR, or write the
  identical URL to an NFC sticker with any tag writer. No app support is needed
  beyond the URL — iOS reads NFC URI records from the lock screen with nothing
  installed.

  Tapping a **hat** tag opens a one-tap *"Wore it today"* screen: photo, name,
  and a single oversized button. That is the whole point. Wear logging only ever
  happens at one moment — hat in one hand, phone in the other — and the full hat
  page puts its wear button a scroll below several cards.

  Tapping a **case** tag opens that case's contents.

  New printable sheet at `GET /api/admin/hat-labels`, with `?case=AH-01` to
  narrow it to one case. Every label prints its URL as text underneath, because
  writing an NFC tag means pasting that URL somewhere.

  Three decisions are load-bearing, all from one fact — **you cannot rewrite a
  sticker that is already on a hat**:

  - **Hat tags key on the immutable `hat.id`, not `display_id`.** A display id
    is derived from case + position, so it changes the moment a hat is
    reshuffled, and is `None` for an unassigned hat — precisely the state a hat
    is in while you are tagging it. A sticker printed with one would keep
    scanning and silently resolve to a *different* hat. Cases are the opposite
    and key on `display_id`: it is painted on the physical case.
  - **Tags point at `/t/...`, not at the real page.** One level of indirection
    that costs nothing now and cannot be added later.
  - **The host is configurable** (Settings → Tags & labels), defaulting to
    whatever you are browsing on. Browse to the Pi by IP once and every tag
    written that afternoon names a DHCP lease. A base without an `http(s)`
    scheme is rejected — an NDEF URI record needs one, and a QR without one is
    read as plain text, so it looks obviously right and produces tags that do
    nothing.

- **Login returns you where you were** (`?next=`), which physical tags need:
  tapping a tag with an expired session previously dropped you on the home page,
  losing the one piece of information the tap carried. Only same-origin paths
  are honored.

### Fixed
- **Case labels printed the wrong occupancy, onto adhesive.** The sheet computed
  capacity itself — a third copy of the rule `services/capacity.py` exists to
  centralize, and wrong two ways. `4` is the *overfill limit*, not nominal
  capacity, so a full three-hat case printed **"3/4"**. And the count included
  **disposed** hats, which have already freed their slot. It now defers to
  `capacity.evaluate`.

### Changed
- The copy-to-clipboard control falls back to `execCommand` outside a secure
  context. `navigator.clipboard` is `undefined` on plain HTTP, which is exactly
  how Headroom is served on a LAN by the port-80 overlay — so without the
  fallback the button would appear to work and copy nothing.
- Frontend tests share one `HatRead` fixture (`src/test/fixtures.ts`) instead of
  each file writing out all ~50 fields, and `renderWithProviders` accepts an
  initial route for components that read `useParams` / `useSearchParams`.

## [2.27.0] — 2026-08-22

### Fixed
- **Base retail prices were wrong for the entire collection, and a comment was
  the cause.** `estimated_new_price` came entirely from Claude Vision, steered by
  a block of price anchors in the analysis prompt. A photo cannot show a price,
  so those anchors *were* the answer — and they read **"HYDRO caps — $69 is the
  common price"** long after the band had moved. Every hat inherited it, and so
  did valuation's retail-share fallback.

  melin prices are now **looked up**, from a table cross-checked against 223
  real order lines:

  | item | table | order history |
  |---|---|---|
  | HYDRO | **$79** | $89×67, $69×30, $79×29 — the band moved over the years |
  | HYDROLite | **$99** | $99×16, $89×1 — unambiguous |
  | Beanie | **$79** | $79×3 (Destination, Journey) |
  | 3 Hat Travel Case | **$49** | $49×34, $39×15 |
  | Aviator | **$99** floor | $179 Scout Thermal, $139 Infinite Thermal |

  What the table deliberately does **not** do is invent the numbers it cannot
  know. Thermal is $79/$89/$99 on caps but $139/$179 on Aviators, and the Mill
  straw line runs $99–$180 — so those fall through to Claude's estimate, which
  is still labeled as a guess. And the table never pulls a *higher* estimate
  down: the base is what a plain example costs, and collabs, artist series and
  premium colorways genuinely exceed it.

- **An entered retail price is now permanent.** Typing one marks it `Manual`,
  and no analysis, re-analysis or backfill may overwrite it — the same
  protection `resale_price` has had since 2.19.

- **Existing hats are re-priced once on upgrade** (`retail_prices_v2`). Fixing
  the code alone would have left a collection where a hat's price depended on
  *when* it happened to be photographed.

- **A test was pinning the wrong price.** It asserted `$69` stayed in the prompt
  — enshrining the stale anchor as a requirement. It now asserts the prompt and
  the table *agree*.

### Changed
- **The analysis prompt stops guessing melin prices** and is told the table will
  override it. Its remaining job is the exceptions the table cannot see —
  collabs, artist series, Mill straw, Thermal Aviators.
- **Cases publish their retail price** (`CaseRead.retail_price`). Not a column:
  every case is the same product at the same price, so a per-row copy would be
  forty duplicates of one number waiting to disagree.

## [2.26.0] — 2026-08-19

### Fixed
- **Case photos are actually gone.** "Cases show a collage of their hats, not a
  case photo" had been true of exactly one of three surfaces. The grid got the
  collage; the **detail page**, the **edit form** and `POST /api/cases/{id}/photo`
  all kept the feature — so a case with three hats in it rendered a
  screen-filling **"NO PHOTO"** placeholder above its own contents. All three
  removed; the detail page now shows the same collage the grid does, and a test
  asserts the route returns 405. `Case.photo_path` and any files on disk are
  left alone — dropping those is destructive and should be a decision.

- **The backup health endpoint was reporting success when the backup failed.**
  `write_scheduled_backup` catches its own exception and returns `None`, and the
  loop called `record_success()` without checking. A backup failing *every*
  cycle reported a fresh success and zero failures. An existing test concealed
  it: its stub returned `None` on its **success** path.

- **The Android share target was broken, not merely uncapped.** `POST /share`
  read whole files into memory and passed the job creator **bytes** — but that
  function takes **paths**, so every share raised `AttributeError` on the first
  file. Nothing covered the handler. It now spools to a temp dir in capped
  chunks and passes paths, like the bulk-import route it was always meant to
  mirror.

- **Tests could make real, billable API calls.** `conftest` neutralized the
  marketplace seam only, while `config.py` reads the Anthropic and Google Vision
  keys at import and the key resolver falls back to the environment. The claim
  "tests never call the Anthropic, Google, eBay, or Sharetribe APIs" held only
  by accident of one machine's shell.

### Added
- **Two hat styles: The Shore and Aviator.** Both confirmed against reality
  rather than guessed — The Shore from 953 live marketplace listings, Aviator
  from the order history. Aviator is seasonal, which is why the resale market
  carries none and no catalog sweep would ever have found it. Neither is mapped
  into the category table: the marketplace has no such category, so mapping them
  would sweep an empty one and return no comps.

### Changed
- **Internal documentation audited end to end and 15 claims corrected.** The
  case-photo line was not an isolated slip. Also wrong: the rank-penalty
  budgets, "three single-file photo routes" (two), the path-traversal
  description (one shared helper now, not two copies), the flicker animation
  (~5s, not 18s), `protected_namespaces`, a retention constant that does not
  exist, the lifespan list (omitted the analysis worker), the middleware roster,
  three undocumented services, the components tree, and the query-key list.

## [2.25.0] — 2026-08-19

### Fixed
- **"25 models known" was never the catalog's size.** The Settings card read the
  length of the *autocomplete* feed, which caps at its own default of 25. The
  figure would have said 25 with 1,000 models harvested, which is
  indistinguishable from a harvest that found 25.
  `GET /api/admin/colorways/status` now reports the real totals.

- **One transient marketplace error abandoned the whole colorway harvest.** The
  listing query raises on any non-200 and the only handler was at the very top.
  The sweep is sequential and commits per page, and the endpoint had already
  returned `202 started`, so a single blip left a silently partial catalog that
  looked exactly like a complete one. Pages now retry with backoff, each
  category is isolated, and any that still fails is reported in
  `failed_categories`. For scale: a full sweep is **988 listings across 146
  models**.

- **Replacing a hat's photo leaked its export image.** The cleanup loop deletes
  everything named by a Hat column, but 2.24.0's export derivative is named
  after the canonical photo's *filename*, so it was invisible to that loop.
  `utils/photo.export_derivative_path` is now the single definition of where
  that file lives, so the code that writes it and the code that deletes it
  cannot drift apart.

- **Two query invalidations bypassed `invalidateHatViews`.** Bulk import
  refreshed only `['hats']` and `['cases']` despite creating hats *into* a case,
  and deleting a case refreshed only `['cases']` despite unassigning every hat
  in it.

### Changed
- **`hat.case.room` is no longer walked outside the model.** Five call sites
  rebuilt what `Hat.room_name` / `Hat.case_display_id` / `Hat.display_id` already
  provide.
- **Three unlabeled `<select>`s got their `aria-label`** — Case Type,
  Disposition Type, and color Tier.
- **The purchase-import dedupe is defined once.** Import and preview each had a
  byte-identical copy, so "the preview predicts the import exactly" was a claim
  maintained by hand.
- **`CONDITION_LABEL` is no longer declared three times.** Two of the copies were
  identical and differed only by a trailing `s` in the name; the third is
  genuinely different (lowercase, for use inside a sentence) and is now named
  `CONDITION_IN_SENTENCE`.
- **The payout constants have one home again.** `melin_recap.py` defined them a
  third time, unused by anything and outside the reach of the parity test.
- **README and USAGE now document the zip export and per-hat notes.**

## [2.24.0] — 2026-08-19 *(never tagged; shipped inside v2.25.0)*

### Added
- **Download the collection as a zip.** `index.html` plus an `images/` folder:
  open it in any browser, works offline, nothing to host, no login. Every hat
  gets its photo, colors, where it lives, and your notes.

  A zip rather than one self-contained HTML file with base64 images — that is
  neat until it is several MB of base64 no mail client will preview.
  Deliberately a **showcase**, not the inventory report: prices are opt-in and
  off by default, matching what share links already withhold.

  This exists because share links, which are the better answer, only work if the
  recipient can reach the app — and `headroom.local` resolves for nobody off
  your LAN.

  Images are **re-encoded to 800px WebP** from the canonical photo rather than
  copied from the 320px grid thumbnail, which looked soft the moment anyone
  opened the zip on a laptop. The alternatives were measured, not assumed:
  lossless PNG is 137 KB an image, 256-color PNG is 26 KB but softens the
  cutout's anti-aliased edge, and JPEG is 31 KB with **no alpha at all**. AVIF
  came in at 13.5 KB against WebP's 13.9 on photographic content, so it buys
  nothing worth a Safari 16.4 floor. Derivatives are cached on disk and
  invalidated by modification time. The whole zip build runs off the event loop.

- **Notes of your own, on every hat.** The only free-text field no automated
  path ever writes — not analysis, not a refresh, not a bulk re-analyze. Every
  other prose field on a hat is derived and gets rewritten, so the card says
  outright that this one survives.

## [2.23.1] — 2026-08-18 *(never tagged; shipped inside v2.25.0)*

### Fixed
- **The case part of a hat's ID is now a link back to that case.** `A-029-01`
  reads as "hat 01 of case A-029" and sits at the very top of the page, so it
  looks like a breadcrumb and gets tapped like one. It wasn't one. The "View
  Case" button did already exist, but below the identification card, the photo
  and the specs.

  Only the case portion links; the `-01` stays plain text, so which part is
  navigation is visible rather than guessed. A hat with no case still renders
  `Hat #12` as plain text.

### Documentation
- **A diagram of what happens when you add a hat.** The README now carries a
  Mermaid flowchart of the upload → queue → cutout → Claude → price-lookup path,
  including the branches that matter: the upload returning before any of it
  runs, the inline fallback when no worker is draining the queue, and the fact
  that **eBay and melinrecap only run after Claude succeeds**.
- **The color-search description was two releases stale**, still describing plain
  "ΔE in LAB space" after 2.20 moved to CIEDE2000.

## [2.23.0] — 2026-08-18

### Fixed
- **Color search: a gray hat is no longer a purple hat.** Searching purple
  returned **22 of 22** hats, every one matched on a gray swatch at Δ13–19.
  2.22.0 did not fix this and neither would a third attempt at the same
  approach.

  **A distance threshold cannot answer "is this hat purple?"** CIEDE2000 divides
  the chroma difference by a factor that is correct for judging whether two
  nearly-identical samples of a dye match, and wrong for this. A mid gray and a
  saturated purple differ by **55 units of chroma**; that divisor compresses the
  gap to ~22, and when their lightness happens to agree the pair scores **~17**.
  Two genuinely different purples score ~33.

  The hue question is now answered **before** distance, not with it. A swatch
  with essentially no hue is never matched against a color with plenty of one,
  at any distance.

  Deliberately **not** a general penalty on the chroma gap — that was tried first
  and it killed `navy`/`blue` and `red`/`maroon` along with the bug. Those are
  the dark and bright versions of one hue and must keep matching. What makes
  gray different isn't the size of the gap but that it has no hue to be a darker
  version *of*.

  The test is a **ratio** rather than an absolute chroma floor, because how much
  color counts as *some* color depends on the color. Teal is itself only C=27
  where red is C=73, so a slate teal at C=10.5 holds **39%** of teal's chroma and
  is a teal, while the blue-gray that must not match purple holds **20%** of its
  C=59.

  Worth knowing: the guard is strong for emphatic targets like purple and
  inherently weaker for muted ones. Purple now returns **3** hats instead of 22.

### Changed
- **The cutoff relaxes back to 26**, because it no longer has a second job. It
  had been tightened to 22 to suppress the neutral blowout, which cost real
  matches — `navy`/`blue` and `charcoal`/`gray` were both casualties. With the
  hue guard doing that work properly, 26 is the first value that keeps all 17
  same-family palette pairs; 28 would start admitting `navy`/`maroon`.

## [2.22.0] — 2026-08-18

### Fixed
- **Color search stops returning the whole collection.** Searching a color came
  back with everything, bunched at near-identical distances. Two causes:

  **A hat was scored on the closest of ALL its swatches, with nothing weighting
  them.** A logo counted exactly as much as the crown, and a hat with four
  colors got four chances to match anything. Every melin hat is a dark neutral
  crown with a bright accent, so searching pink ranked a green hat with a pink
  logo **equal first** — identical to a hat that is actually pink.

  A hat now scores on `distance + penalty(dominance_rank)`: +0 for its main
  color, +8 for its secondary, +14 for anything deeper. Additive, because a
  multiplier leaves an exact accent match at 0.00 and breaks no tie. Accent
  matches still surface, but they never outrank a hat that IS the color, and the
  penalty doubles as a budget.

  **The Δ30 cutoff was calibrated against the wrong distribution.** It was
  measured on the 26-color palette, whose entries are deliberately spread around
  the wheel. A hat collection is not: these are overwhelmingly black, charcoal,
  navy and gray, and CIEDE2000 places a low-chroma neutral moderately near
  *everything*. At 30, gray was a "match" for **17 of the other 25 palette
  colors**. Every hat owns a gray swatch, so every search returned every hat.

  Re-calibrated on the neutrals, where the problem lives, to **22**:

  | target   | within 30 | within 22 |
  |----------|-----------|-----------|
  | gray     | 17        | 4         |
  | charcoal | 11        | 5         |
  | pink     | 4         | 1         |
  | red      | 6         | 1         |

  Saturated searches barely notice. Shades of one color still match comfortably:
  a real gray crown is 8.0 from the gray chip.

### Added
- **Results say which swatch they matched.** A hat matched on its accent is
  labeled as such, so a row reading "Δ0 · accent" sitting below a row reading
  "Δ5" is legible rather than looking broken. `ColorSearchResult` gains
  `matched_rank`; `distance` keeps its meaning and is deliberately **not** the
  sort key.

## [2.21.0] — 2026-08-18

### Changed
- **Resale values are now real comparables, and they go UP.** Two invented
  numbers are gone: a 15% "ask-to-sold" haircut and a guessed condition
  multiplier.

  The haircut was modeling a negotiation that doesn't happen. melinrecap is a
  fixed-price Treet marketplace with automatic drops — a buyer clicks buy at the
  number shown — so **the listed price is the sale price**.

  The multiplier was unnecessary. Every listing carries its own `condition` and
  `size` in the feed, and the code ignored both. Measured against 706 live
  listings those guesses were also wrong — new-without-tags sells at 95% of
  new-with-tags (not 92%), worn at 82% (not 78%).

  Comparability now comes from **filtering, not arithmetic**. A hat is priced
  against listings matching its own model, condition and size, widening only
  when the market has too few of the exact thing, and the source line says
  which.

  Effect on a real hat, a Classic Trenches Icon Hydro, against live data:
  new-with-tags $59.50 → **$77.00**, new $54.74 → **$75.00**, worn $46.41 →
  **$63.00**. Roughly +30%, and each from 5–11 genuinely comparable listings.

### Added
- **What you'd actually receive.** Every listing carries `payoutInfo`: the
  marketplace pays a seller **80% in cash or 110% in brand credit**. Valuation
  reported only the gross figure — the one number that never reaches you.
  There's now a card showing market value, cash, credit, and what choosing
  credit is worth over cash.

389 backend + 82 frontend tests.

## [2.20.0] — 2026-08-18

### Changed
- **A case is full at 3 hats, not 4.** The physical article is a three-hat case
  — melin's own order lines call it a "3 Hat Travel Case". A 4th still fits, so
  it is accepted and the case is reported **overfull** rather than refused or
  passed off as normal. One over is the whole allowance; the 5th is refused, and
  the 409 quotes the ceiling actually enforced.

  Cases hold their hats either way — nothing moves and nothing is rejected on
  upgrade. Any case you already have with 4 hats simply starts saying
  *overfull*.

  A per-case `capacity` you set yourself gets **no** overfill latitude. That
  field exists for a case you don't want to cram.

- **Color search is much tighter.** Two separate problems:

  *No cutoff.* Only the result limit bounded it, so every hat was ranked and the
  nearest 30 came back however far away they were. A list that always fills to
  the same length says nothing about whether anything matched. Now capped,
  calibrated against the curated palette. An empty result is now possible and
  the page says "no hats are close to that color".

  *Crude metric.* Distance was plain Euclidean in LAB, which is least uniform
  among saturated blues, i.e. most of this collection. Now CIEDE2000, verified
  against all 34 published reference pairs.

  Expect a light-blue search to stop returning navies. That is the fix.

### Fixed
- **The hat spec sheet showed the wrong things.** "Type" reported Beanie or
  Regular, which is derived entirely from Style directly above it. Meanwhile
  **construction** appeared only as a badge beside the title, and **colorway**
  appeared nowhere on the hat page at all. Specs now lists Style, Size,
  Construction, Colorway, Collection and Last Worn.

384 backend + 81 frontend tests.

## [2.19.0] — 2026-08-17

### Added
- **Stats page (`/stats`).** Everything the collection is, as numbers and
  charts: totals, condition/style/size/brand/construction/colorway splits, color
  distribution, hats and value by room, case fill levels, acquisitions and spend
  over time, and leaderboards for most valuable, most expensive, most worn and
  best cost-per-wear. Charts are hand-rolled SVG/CSS for the same reason this
  app has no UI framework.
- **Price-paid tracking end to end.** `purchase_price` and `purchased_at` are
  now settable when you *add* a hat, not only when editing one — the receipt is
  in hand at that moment. Valuation gained a "What you've paid" card with
  totals, coverage, average, and a list of hats still missing a price.
- **Home page counts are links.** Hats, Cases and Rooms go to their lists;
  Archive and Daily deep-link into the Cases page's own type filter. The Cases
  type filter now lives in the URL, the hat filters seed from query params, and
  Search accepts `?q=` and `?color=`.

### Changed
- **The valuation math, substantially — read this one.** Previous totals were
  overstated. Both price feeds report *asking* prices and both were being summed
  at face value. Worse, whenever a market price existed, condition was ignored
  entirely: every copy of a model got the same number whether it was tagged or
  beaten. Market signals are now discounted 15% for the gap between ask and sale
  and then adjusted for the hat's actual condition, so headline figures will
  **drop**. They were wrong before, not now.
- **The home page caption said something the code no longer did.** It named
  condition multipliers long after `resale_price` had become an automatic feed.
  Valuation now carries a "How the sale estimate is worked out" card that states
  the method and shows how many hats rest on each kind of signal.
- **One valuation rule instead of three.** It was implemented separately in the
  home page, the valuation page and the server's inventory report, and had
  drifted in all three. It now lives in `frontend/src/lib/valuation.ts`, with
  `src/headroom/services/valuation.py` mirroring it for the server-rendered
  report and `tests/test_valuation_parity.py` failing the build if the two ever
  disagree.
- **Home page stats are one panel, not five buttons.** Each was a bordered card
  with a gradient bar — the same recipe this stylesheet uses for a primary
  button — so they read as buttons containing numbers and took nearly half the
  first screen.
- **The home carousel no longer glows.** It now uses the same border, surface
  and shadow as every other card.
- **Hat page pricing tiles** are two-up rather than three-across, label the feeds
  as *asks*, show what you paid, and show the estimated sale value with a
  plain-English note on how it was reached.

### Fixed
- **The app's own CSP had been blocking its own fonts since 2.12.0.** The
  security headers set `style-src 'self'` and `font-src 'self'` while
  `tokens.css` still pulled its four families from Google Fonts, so the entire
  type system was stripped and everything rendered in system-ui. It stayed
  invisible because anyone who had used Headroom before 2.12.0 had the fonts
  cached. The fonts are now bundled from `@fontsource*` packages, which also
  means the design no longer depends on a Google CDN being reachable.
- **A hand-entered resale price no longer survives only by luck.** Every
  analysis of a Melin hat reset the price to null and relied on the live feed
  putting a number back; when the marketplace API was unreachable it didn't — on
  a path that also runs unattended from the bulk re-analyze queue. Prices you
  enter are now marked as yours, used as given, and never overwritten.
- **Cost per wear used the retail estimate** when no purchase price was
  recorded, so a hat bought on sale showed a cost per wear it never had.
- **Unpriced hats are excluded from totals rather than counted as $0**, and the
  count of them is shown. "Retention %" is computed only across hats present in
  both totals.
- The deprecated `apple-mobile-web-app-capable` meta tag warned on every page
  load; the standard `mobile-web-app-capable` now sits beside it.

### Added — purchase import
- **Order-history import understands size.** Order emails have always carried it
  and the importer dropped it, so matching went on model name alone and bound a
  purchase to whichever hat came back from the database first. Matching now
  scores candidates — size outranks colorway, a stated field that disagrees
  rules a hat out, and a genuine tie is reported rather than resolved by coin
  flip.
- **A multi-buy line now prices every hat it bought.** "× 2" is two hats and a
  purchase matches one hat, so one row per line meant the second hat of every
  multi-buy silently never got a cost basis — nearly 40% of lines in a real
  order history. Import writes one row per unit, and dedupe counts rows instead
  of testing existence.
- **`?dry_run=true` on `/api/admin/purchases/{import,match}`** reports exactly
  what would be imported and which hat each purchase would attach to, writing
  nothing. Importing mutates hats and there is no undo for "every price on the
  shelf is now slightly wrong".
- An explicit `colorway` in the payload now beats one parsed out of the title.
- **Matching can be undone.** `POST /api/admin/purchases/{id}/unmatch` breaks one
  link and `POST /api/admin/purchases/unmatch-all` breaks every link. Previously
  there was no undo of any kind: matching mutates hats, runs over years of order
  history in a single call, and only ever reconsiders purchases with no hat — so
  a wrong link was permanent *and* invisible, because the hat still came out
  with a price and a colorway, just the wrong ones.

  Reverting clears `purchase_price`, `purchased_at` and `colorway` only where
  they still hold the value that match wrote. Anything edited since belongs to
  whoever edited it. The purchase rows themselves survive `unmatch-all`:
  re-importing years of orders is the expensive part. Both are audited.

### Added (schema)
- `hats.resale_price_scope` — `manual` | `model` | `category`, recording what
  `resale_price` is a price *of*. A category median is the going rate for a
  whole style rather than a valuation of one hat, and valuation needs to tell
  those apart without parsing a display string.
- `purchases.size` — the size on the order line, normalized to the app's
  vocabulary. Also now part of the import dedupe key: one real order bought the
  same model at the same price in Classic ×2 *and* Small ×1, and a key without
  size collapsed the Small.

340 backend + 81 frontend tests.

## [2.18.2] — 2026-08-17

### Fixed
- **`setup.sh` now verifies the npm upgrade actually took.** It only checked
  whether `npm install -g` exited cleanly, which it can do while changing
  nothing you will run — so a setup that printed no error still left npm 11
  building the SPA against an image pinned to 12. It now re-checks the version
  afterwards and reports the mismatch immediately.

  On a Homebrew node it says so specifically: the formula owns the `npm` symlink
  into its Cellar, so a global upgrade is undone by the next `brew upgrade node`
  and cannot be made to stick. This is cosmetic for Docker deploys — the image
  installs its own pinned npm in the build stage — and only matters when
  building the SPA locally for a bare-metal deploy.

307 backend + 66 frontend tests.

## [2.18.1] — 2026-08-17

### Fixed
- **`BUILD_SHA` works again as a name for the build stamp.** v2.0.0 renamed the
  build arg to `HEADROOM_BUILD_SHA` and listed it as breaking — but a build arg
  that doesn't match simply arrives empty, with no warning, so a command using
  the old name kept working and silently stopped stamping. The old name is
  accepted as a fallback.

- **Docs: upgrading with an overlay.** `## Upgrades` said
  `docker compose up --build -d`, which on a host running an overlay is not an
  upgrade — compose applies only the files named, so the sidecar never starts and
  the app drops back to `:8000`. Now states plainly that upgrades must repeat the
  same `-f` flags, with a worked example.

- **Docs: the build stamp was undocumented.** Neither README nor OPERATIONS
  explained why the footer shows no build or how to make it. OPERATIONS §5 now
  covers it, including that a dirty tree is stamped `-dirty` and that no stamp is
  not an error.

### Changed
- `scripts/stamp-build.sh --install-hooks` installs the git hooks on its own, so
  a running deployment can pick them up without re-running `setup.sh`.

307 backend + 66 frontend tests.

## [2.18.0] — 2026-08-17 — _seen it twice_

### Added
- **Find duplicates** (`/duplicates`, linked from Search). Bulk import from a
  camera roll is how this happens: two photos of one hat become two rows that
  both analyze plausibly, and at two hundred hats you don't notice — the
  collection quietly reports more than you own, which flows into the valuation.

  Grouped on identity fields, never pixels: two shots of one hat look different
  enough to defeat image comparison, and two genuinely different hats in the
  same colorway look nearly identical. `exact` means every identity field
  agrees; `likely` means same model and size with the colorway missing on one
  side.

  Colorways that actively **disagree** are never grouped — "Trenches Black" and
  "Trenches Navy" are two hats somebody deliberately owns, and reporting every
  normal shelf as a mistake is the fastest way to make a report like this get
  ignored. Reports only: nothing is deleted or merged.

- **The three most recently created cases are pinned to the top** of the case
  picker. A hat you're adding now usually belongs in a case you made minutes
  ago. Hidden once you start typing.

- **Cases show a collage of the hats inside**, not a photo of the case. Every
  case looks identical from the outside, so that picture carried no information
  at the moment you were scanning for one. The layout follows the count rather
  than letterboxing a single hat into a quarter of a forced 2x2.

### Fixed
- **Dropdown lists were being clipped by the card they sat in.** `.card` sets
  `overflow: hidden`, so options past its edge were cut off mid-row and the ones
  below unreachable — no z-index could fix that, because the pixels were never
  drawn. The lists now render into `<body>` via the existing portal helper,
  positioned against their input. That also clears the two other ancestor traps.

- **The bottom nav no longer jumps to the middle of the screen.** iOS positions
  `fixed` elements against the *visual* viewport, so the nav is lifted with the
  keyboard and lands on top of whatever you're typing into. 2.14.0 hid it while
  a combobox was open, which missed the actual cause: it happens for every
  focused input. Now tracked app-wide via `visualViewport` — the only API that
  reports a keyboard.

- **Picker lists no longer run off the bottom of the screen.** They were sized
  against the layout viewport; with the keyboard up that's roughly double the
  visible area. Sized in `dvh` now.

- **The footer shows the build again.** `.dockerignore` excludes `.git` and the
  frontend build stage only receives `frontend/`, so nothing inside the image
  could ever learn the commit — and the compose build arg defaulted to empty.
  `scripts/stamp-build.sh` writes it to the `.env` compose already reads, and
  `setup.sh` installs git hooks so a `git pull` keeps it current. A working tree
  with uncommitted changes is marked `-dirty`.

- Search results now carry `thumb_path`, so the results grid loads thumbnails
  instead of full-size transparent PNGs.

307 backend + 63 frontend tests.

## [2.17.0] — 2026-08-17 — _it already knows_

### Fixed
- **Your construction is now sent to Claude as ground truth.** 2.12 stopped
  analysis *overwriting* a construction you had stated, but never told it what
  you'd said — so a hat you recorded as Thermal still came back named "A-Game
  HYDROLite". The construction field was right and the name you actually read
  was wrong, which reads as the app overruling you.

  The prompt now states both the model line and the construction as facts from
  someone holding the hat, and binds `model_name` to agree with them. HYDRO vs
  HYDROLite vs Thermal turns on bonded seams, a gel-welded logo and the
  sweatband — none reliably legible in one photo — so a guess there is weak
  evidence against your direct observation.

- **A full rescan repairs the hats that already got this wrong.** melin names
  read "&lt;line&gt; &lt;construction&gt;", so a model name asserts a build by
  itself. Any name that contradicts the hat's recorded construction now has the
  wrong build removed on every analysis.

  Removed, not rewritten: "A-Game Thermal" would be inventing a product name,
  where "A-Game" is merely less specific and true.

299 backend + 63 frontend tests.

## [2.16.0] — 2026-08-17 — _one Piña_

### Changed
- **Accents fold too.** 2.15.0 deliberately kept "Piña" and "Pina" apart, on the
  theory that two names differing only by a diacritic might genuinely be
  different collections. In this collection they aren't — they are one drop
  typed with and without a long-press on a phone keyboard, and the concrete harm
  is three entries that never find each other in search. `Piña`, `Pina` and
  `PINA` are now one collection.

  When variants disagree the **accented** spelling wins: adding an accent is a
  deliberate act, while dropping one is what happens when you type quickly.

  On write, the value already on record still wins a *tie* — otherwise typing
  `NEON` once would rename a collection recorded as `Neon`.

### Fixed
- Matching moved from SQL to Python. It was a `WHERE lower(col) = lower(?)`, and
  SQLite's `lower()` is ASCII-only: it cannot fold accents, so `Piña` and `PIÑA`
  did not even match *each other*. The candidate set is a few dozen short
  strings, so comparing in Python costs nothing and is actually correct.

296 backend + 63 frontend tests.

## [2.15.0] — 2026-08-17 — _one Neon_

### Changed
- **The collection field autocompletes**, like construction — suggestions come
  from `GET /api/meta/collections`, the names already in use. No curated list:
  melin names these for the partner or the drop, so any fixed list is wrong by
  the next release.

- **Typing past a suggestion no longer creates a duplicate.** A value that
  case-insensitively matches something already recorded is now stored with the
  existing spelling, so "Neon", "NEON" and "neon" converge on one collection
  instead of three that never find each other in search. Applies to
  `construction` too, where the curated list wins.

  Case and whitespace only. "Piña" and "Pina" stay distinct: collapsing accents
  would be guessing.

### Added
- **A one-time merge for variants that already exist.** Canonicalization covers
  writes, so anything recorded before it keeps whatever was typed. Runs once on
  boot behind `vocabulary_merged_v1`, keeping the curated spelling where there is
  one and otherwise the most *common* variant.

294 backend + 63 frontend tests.

## [2.14.0] — 2026-08-17 — _sixty cases_

### Changed
- **The case selector is a searchable picker.** A native `<select>` is fine at
  six cases and unusable at sixty: iOS renders it as a picker wheel with no
  search. Type to filter on case id, room name or type; cases are grouped under
  their room with occupancy shown.

- **It won't let you pick a case the save would reject.** Cases are
  type-exclusive and capacity-limited, so the old dropdown happily offered a case
  that came back `409`. Full and wrong-type cases now render dimmed and
  unselectable with the reason ("full", "holds beanies"), rather than hidden: a
  case you expected to see silently missing is its own puzzle.

  Availability is computed server-side in `services/capacity`, the same module
  the write validator uses, so the picker cannot disagree with what a save will
  accept.

### Fixed
- **The bottom nav no longer covers an open picker.** It is `position: fixed` at
  `z-index: 100`, above the list — and once the iOS keyboard opens, fixed
  elements are positioned against the visual viewport, so the nav rode up to
  mid-screen. The nav is now hidden while a picker is open.

- **Case occupancy counted disposed hats.** A disposed hat stays in the database
  but frees its slot — the write validator has always filtered them, but the read
  model did not, so a case could display as fuller than the validator considered
  it.

283 backend + 63 frontend tests.

## [2.13.0] — 2026-08-17 — _one place for each thing_

The layering and traceability findings the 2.12.0 release deliberately left,
plus the test gap that let the crash class stay invisible.

### Changed — the layering

- **`share_links.py` has a service layer.** It was the only feature that lived
  entirely in the transport layer — hand-rolled persistence, token-expiry rules,
  and a second copy of the path containment check `app.py` already had. Now
  `services/share_link_service.py` owns token validity and what a token may see;
  the route is transport only.
- **One definition of path containment.** `utils/paths.py::safe_join` is now the
  single implementation, used by the SPA fallback and the share-photo streamer.
  Both copies were correct — which is the problem: two correct copies of a
  security check are two places that must both be fixed when it is wrong.
- **No more hand-built dict responses.** `schemas/share.py`,
  `schemas/import_job.py` and `PurchaseRead` replace them, so the public share
  view and the purchase list have declared shapes and appear in the OpenAPI
  document. The shared-collection payload is deliberately a projection, not
  `HatRead` — prices, purchase history, disposition and analysis state are the
  owner's business.
- **`schemas/auth.py`** holds the five models `routes/auth.py` declared inline —
  the request bodies on the unauthenticated surface, whose validation rules
  should be readable without opening the transport layer.
- **Admin routes go through `hat_service`** rather than querying models
  directly.
- **`Purchase.hat` is a real relationship**, not a bare foreign key every caller
  had to navigate by hand.
- **The colorway harvest runs in the background** and returns `202`. It is up to
  9 categories × 50 pages of sequential external calls — minutes of work inside a
  request, long enough for any reverse proxy in front of it to time out first.
- The three analysis/queue response types moved to `types/index.ts` with every
  other API shape.

### Added — tests for what the stub was hiding

`tests/test_memory_bounds.py`. The suite stubs `remove_background` out entirely
— rembg's model is 179MB — and that stub is why the crash class stayed
invisible: every precondition sat in the code, green, for releases. The bounds
are plain control flow, so they can be tested without the model. Removing the
semaphore now fails with *"4 inferences ran at once; the bound is 1"*.

Covers the inference bound and its env override, a bad config value falling back
rather than deadlocking, all photo routes rejecting oversize input before Pillow
decodes anything, a normal photo still working, and bulk import handing the
worker paths rather than bytes.

### Fixed

- `copy_upload_capped` bound its limit at import time, so it could never be
  changed — and an untestable limit is how the last one went missing.
- Ten of twelve in-code citations pointed at review documents that were never
  committed; a permanent reference to something nobody can open is worse than
  none, because it implies a rationale exists to be checked. Those citations are
  gone.

### Fixed — the memory limit was being ignored on Pi

Raspberry Pi OS ships with the memory cgroup disabled, so Docker printed *"Your
kernel does not support memory limit capabilities ... Limitation discarded"* and
dropped 2.12.0's `mem_limit` on the floor. The in-app bounds were unaffected,
but the container ceiling — the thing that turns a system-wide OOM kill into a
diagnosable `OOMKilled=true` — was not actually in force.

`docs/OPERATIONS.md` §7 now has the one-time fix (`cgroup_enable=memory
cgroup_memory=1` in `cmdline.txt`, reboot), how to verify it took, and how to
tell a memory kill from a Pi brown-out — undervoltage and thermal throttling
during rembg's CPU burst produce an identical sudden death with no logs.

280 backend + 61 frontend tests.

## [2.12.0] — 2026-08-17 — _the owner wins_

A full-repo archaeology pass produced ~45 findings; this is all of them, plus
the two things 2.11.0 got wrong in front of the owner.

### Fixed — the crash

Three independent analyses converged on why the container died mid-upload, and
every structural precondition was confirmed in code:

- **The single-hat photo upload had no size cap at all** — bulk import caps
  per file, the route you actually use capped nothing, and Pillow decodes at
  native resolution before the resize. Now capped and streaming, along with the
  case-photo and logo routes. One definition in `utils/upload.py`, used by all
  four.
- **No compose file set a memory limit**, so a spike competed for the whole Pi
  and the kernel picked a victim with `SIGKILL`, which logs nothing.
  `mem_limit`/`memswap_limit` default to 1g (`HEADROOM_MEM_LIMIT`), so a
  recurrence is a scoped, diagnosable `OOMKilled=true` against this container.
- **rembg ran unbounded across both workers.** The lock was removed for
  throughput; with only two single-consumer producers that bought a factor of
  two and cost double the peak memory, for the largest allocation the process
  makes. Now a semaphore, default one (`HEADROOM_REMBG_CONCURRENCY`).
- **On-demand backup download buffered the entire tarball in RAM** — the whole
  database plus every photo — and called itself streaming. Now spooled to disk
  and streamed in 1 MB chunks.

### Fixed — the backup scheduler

**It could die once and stay dead for the life of the process.** The startup
age-check ran above its own `try`, and only `CancelledError` was caught inside
it — so one unwritable `/data` at boot, or a single transient
`database is locked`, ended automated backups with no warning while the UI kept
listing the last successful one. The loop now survives everything short of
cancellation, and `GET /api/admin/backups/health` reports last attempt, last
success, consecutive failures and whether the task is still alive.

A backup that fell back to the raw-file copy (possibly torn) was
byte-indistinguishable from a clean snapshot; it now carries a
`DEGRADED-BACKUP-README.txt` inside the archive, because a file travels with the
backup and a log line does not.

### Changed — analysis no longer overrides you

**Claude only fills a construction that is empty.** 2.11.0 let a named fabric
overwrite what was on record. In practice it reads HYDRO vs HYDROLite off one
photo unreliably, so "correcting" meant replacing a right answer from the person
holding the hat with a wrong one from a picture. Clearing the field makes it
eligible again.

`scripts/restore-construction.py` restores values from a backup for hats already
overwritten. Hat edits now record their **previous values** in the activity log,
so this class of change is reversible from history rather than only from a
backup.

### Fixed — 2.11.0 regressions

- **Construction is a real autocomplete**, not a bare `<datalist>` — iOS renders
  those as a thin strip above the keyboard that is easy to miss, so ten known
  values read as a blank text box.
- **The analysis badge shows the step name again**, alongside the counter:
  `2/4 · Identifying`, one word so it still fits a phone.
- **Edit is in the top action row** on a hat, not only at the foot of the page.
- A legacy client sending `hydro: false` no longer wipes a construction the
  booleans cannot express.

### Fixed — correctness

- A photo replaced mid-analysis raised an uncaught `FileNotFoundError` past the
  pipeline's error handling; the queue then stamped the hat `error` and the
  correctly-queued run for the NEW photo found a non-pending status and silently
  did nothing. Same shape in `google_vision.py`.
- A per-case capacity of exactly `0` fell through to the type default via
  truthiness, letting four hats into a case set to hold none.
- `undispose_hat` restored a hat into a case that may have been deleted.
- `reattach_orphaned_cases` now calls `ensure_default_room` itself rather than
  depending on boot ordering — with no default room its subquery returns NULL and
  it would make permanent the exact state it repairs.
- The activity-log prune slept 24h **before** its first run, so a host that
  reboots daily never pruned at all. It now prunes first, and also sweeps
  expired auth sessions — which were only ever collected lazily.
- `hat_service`'s six mutating functions committed twice with no shared
  transaction, so a lock timeout on the audit write turned an already-durable
  change into a 500 and invited a duplicate retry.
- Bulk import queued with no worker running now says so instead of sitting at
  0%.

### Added — security & audit

- CSP, `X-Frame-Options`, `X-Content-Type-Options` and `Referrer-Policy` on
  every response. No HSTS from the app deliberately: the primary deployment is
  `http://` on a LAN, and one HSTS response would pin that hostname to HTTPS in
  the browser and lock the owner out.
- Unauthenticated API probes are logged. Never with the credential.
- Case and room mutations are audited — previously only hats, auth, settings,
  backups and share links were.

### Fixed — documentation and naming

- `HatAnalysis.construction` still described the pre-2.11 three-value enum, 100
  lines below the schema that contradicts it.
- `package.json` declared `engines.node >=22.12`, the exact floor `setup.sh`'s
  own comments call insufficient; react-router 8 needs `>=22.22`.
- The documented search field list and `USAGE.md`'s status-pill table were both
  behind the code.
- `melin_recap`'s style map and listing query are public — a second module
  already depended on them, so the underscore was a lie.
- The two `apiFetch` calls bypassing `api/hats.ts` now go through it.
- `uploads/branding/logo.png` was git-tracked inside an otherwise-ignored tree,
  byte-identical to `seed/branding/logo.png`.

272 backend + 61 frontend tests.

## [2.11.0] — 2026-08-17 — _what the tag says_

### Added
- **Construction is now free-form, with structured suggestions.** It was two
  booleans, HYDRO and HYDROLite, so a hat in any other fabric could not be
  recorded at all — melin ships specialty materials in seasonal and collab
  drops, and every one of them was unrecordable until somebody shipped a
  migration. The field is now text with a datalist, and
  `GET /api/meta/constructions` merges the curated list with every value already
  in use.

  `hydro` and `hydrolite` survive as columns, because search filters query them
  and a `@property` cannot appear in a `WHERE` clause — but they are now
  *derived*, with `Hat.set_construction()` the only writer of all three.
  Existing rows are backfilled from their flags on boot.

- **Collection / collab can be set when adding a hat**, not only when editing
  one. It is printed on the box and the hang tag and is frequently invisible in
  a photo, so the owner knows something the analyzer cannot see.

- Searching a fabric name finds it: `canvas` now returns a Waxed Canvas hat.

### Changed
- **The analysis badge is a step counter (`2/4`), not a spinner.** It used to
  spell the step out, which wrapped onto a second line on a phone and pushed the
  badge row down into the photo, and because the wording changed every few
  seconds the layout moved while you were reading it. The counter is fixed-width
  and monotonic; the step name moved to the tooltip and the accessible label.

- **Claude may now correct a construction it can identify.** It was
  additive-only, which was right when the field was two booleans and there was no
  way to distinguish "this is not HYDROLite" from "I can't see whether it is".
  Naming a fabric is a positive identification, so it wins; a null still changes
  nothing.

### Fixed
- A stale comment on `Hat.analysis_stage` claimed the column is "cleared when the
  run finishes". It never was — `HatRead` masks it instead, deliberately, so
  that eight terminal-status call sites can't each forget to.

259 backend + 54 frontend tests.

## [2.10.0] — 2026-08-16 — _watch the run_

### Added
- **Bulk re-analysis is now a tracked job.** Firing "Re-analyze every hat" used
  to leave you watching a backlog number tick down, with no record that a run
  had happened at all. The Analysis Queue card now shows a progress bar with **X
  of Y**, how long ago it started, a running failure count, and a short history
  of recent runs.

  **Progress is derived, never accumulated.** The analysis worker drains hat ids
  and knows nothing about jobs; making it bump a counter per hat would mean two
  writes per item, and a crash between them would leave a progress bar
  permanently disagreeing with the hats it describes. So a job stores only what
  cannot be recomputed — its size and start time — and everything else is a
  COUNT over `hats.analysis_job_id`. That is right by construction, including
  after a restart mid-run.

  A job closes itself once nothing tagged with it is still pending, which is
  computed when the card asks.

246 backend + 47 frontend tests.

## [2.9.0] — 2026-08-16 — _redo the cutout, shrink the gallery_

### Added
- **Redo cutout.** The pre-cutout JPEG is now kept instead of being deleted the
  moment rembg succeeded, and the hat page grows a **✂ Redo cutout** button.
  This was the gap behind "my existing hats still look wrong": the stored PNG can
  never be re-segmented — running rembg on an already-transparent image eats the
  alpha and trims the bill a little more each pass.

  Hats analyzed before this release have no original; the button is hidden for
  them and the endpoint says so rather than failing obscurely.
- **Gallery thumbnails.** A 320px WebP derivative is generated alongside every
  cutout, and the small-tile views use it. Measured on a representative 1200px
  RGBA cutout: **1728 KB → 4.5 KB**, so a fifty-hat gallery drops from ~84 MB to
  ~0.2 MB over the wire. WebP specifically because these are transparent — a
  flattened JPEG thumbnail would put a box behind every floating hat.

  Existing hats are backfilled by a background task on startup, off the boot path
  and idempotent, so a restart mid-run resumes. Tiles fall back to the full photo
  until the backfill reaches them.

### Fixed
- **Replacing a hat's photo left its derivatives behind.** Only the cutout was
  deleted, so the old original and thumbnail stayed on disk — and a stale
  `thumb_path` would have shown the *previous* hat in the gallery.

244 backend + 44 frontend tests.

## [2.8.1] — 2026-08-16 — _say what it's doing_

### Fixed
- **The 2.8.0 price anchors were incomplete, and one number was invented.** They
  covered whatever products turned up in a search rather than the model lines
  the app actually enumerates — Trenches, which is in the prompt's own list, had
  no anchor at all — and the stated "$59–$99 band" had no data point at $59
  behind it.

  Re-researched properly. The finding that matters: **construction drives the
  price, not the model line.** A-Game Hydro, Coronado Anchored Hydro and
  Trenches Icon Hydro are all $69 — but **HYDROLite is the premium tier at
  $89–$99** and had no mention at all. The prompt now carries HYDRO, HYDROLite
  (explicitly priced *above* HYDRO), Thermal and beanies, tells Claude to read
  the construction rather than the model line, and puts the floor where the
  evidence actually is. A test pins the anchors.

### Added
- **The analyzing spinner now says which step is running** — "Removing
  background…", "Identifying the hat…", "Checking prices…", "Checking resale…" —
  instead of a bare "Analyzing…" for the whole multi-minute run. The queue card
  shows it too.

  The stage is written from a **separate** short-lived session rather than by
  committing the pipeline's own. That matters: the pipeline commits only at the
  end precisely so the queue can throw the whole run away if the photo was
  replaced mid-flight, and a mid-pipeline commit would persist a stale path and
  defeat the guard.

  A stage is never shown on a finished analysis. That is derived in `HatRead`
  rather than cleared at each terminal transition: eight separate places set a
  terminal status, and any one of them forgetting would leave a confident label
  on work that had stopped.

237 backend + 44 frontend tests.

## [2.8.0] — 2026-08-16 — _see the queue, fix the prices_

### Fixed
- **Estimated retail was coming in about half of actual.** The prompt asked
  Claude to price hats "using your knowledge of the brand's typical pricing
  tiers" and gave it nothing to anchor on, which for melin meant guesses around
  $35 against real retail of $59–$99. The system prompt now carries verified
  current prices plus rough tiers for the other brands it knows, and an explicit
  note that sub-$50 for a melin is almost certainly wrong.
- **Rooms page cards jumped around.** "Make default" was *hidden* on the default
  room while Delete was only *disabled*, so cards carried different numbers of
  buttons; with `flex-wrap` some wrapped to a second line and others didn't.
  Same three buttons on every card now, in a fixed two-row layout.

### Added
- **Analysis Queue card in Settings.** The queue was invisible — a hat showed
  "Analyzing…" with no way to tell whether twenty were ahead of it or whether
  anything was draining the queue at all. Shows the backlog, whether the worker
  is running, and the hats currently waiting. Polls only while there's something
  to watch. A backlog with a stopped worker is called out explicitly.
- **Re-analyze every hat**, from the same card. This is the retroactive half of
  any change to identification or pricing. Background removal is skipped for
  stored cutouts, so it's a Claude call per hat rather than the full pipeline.
  Disposed hats are excluded, and "leave hand-entered prices alone" (on by
  default) limits it to hats Claude priced.
- `GET /api/admin/analysis/queue` and `POST /api/admin/analysis/reanalyze-all`.

235 backend + 44 frontend tests.

## [2.7.1] — 2026-08-16 — _give the bill back_

### Fixed
- **2.6.2's ghosting fix was deleting hat bills.** That release hardened the
  cutout with rembg's `post_process_mask`, which blurs the mask and then
  thresholds it at 127. It did remove the washed-out look — by throwing away
  every pixel the model was less than ~50% confident about, which on a hat is
  precisely the thin bill. Measured against a synthetic brim: at confidence 128
  about 76% survives, at 120 that collapses to 6%, and by 40 the brim is gone
  entirely.

  Replaced with an alpha *ramp* instead of a threshold: clearly-background
  pixels still go to zero, but anything above that is scaled up to opaque rather
  than judged against a cutoff. A brim the model saw at 39% opacity now comes out
  at 73%. Both the fading and the missing bills are addressed by the same
  change.

  Verified against the mechanism (mask confidence in, alpha out) rather than a
  photo, and mutation-checked against both failure modes.

  **This applies to photos processed from here on.** Existing cutouts are
  unchanged — the pre-cutout original is not retained, so there is nothing to
  re-cut from. Re-upload a hat's photo to regenerate it.

230 backend + 44 frontend tests.

## [2.7.0] — 2026-08-16 — _the code review release_

A full two-axis review of the codebase (standards + spec) plus wiring, bug and
optimization passes. Everything below was found by that review; nothing here was
reported from use.

### Fixed — data loss and silent truncation

- **Backups omitted the write-ahead log.** The DB runs in WAL mode, so commits
  live in `headroom.db-wal` until a checkpoint folds them into the main file —
  and the tarball contained only the main file. Every commit since the last
  checkpoint was silently absent from the backup, and a checkpoint landing during
  the tar read could produce a torn copy that restores as "database disk image is
  malformed". Both are invisible until a restore. Backups now ask SQLite for a
  proper snapshot (`VACUUM INTO`); if that fails they fall back to the raw file
  set *including* the `-wal`/`-shm` sidecars.
- **The hat list stopped at 50.** `GET /api/hats` defaults to `limit=50` and the
  Hats grid, Home carousel and Valuation page all fetched with no limit. Past 50
  hats the grid silently hid them and **every valuation total was wrong**. Those
  three views now request the whole collection explicitly, and the API ceiling
  was raised to match.
- **Re-analysis could overwrite a photo you'd just replaced.** The worker held a
  hat for minutes, then wrote back a `photo_path` from before the replacement,
  orphaning the new photo. The result is now discarded if the committed photo
  changed while the pipeline ran.
- **A hat could sit "Analyzing…" forever.** With the worker disabled there is no
  boot sweep either, so an inline pipeline failure stranded `analysis_status` on
  `pending`. Both paths now stamp a terminal status.

### Fixed — behavior

- **New cases ignored the default room, and could be orphaned outright.** The
  frontend hardcoded a room id regardless of what the picker showed, bypassing
  the `is_default` flag entirely. Delete the room that happened to be id 1 —
  which that flag exists to permit — and every case created afterwards pointed at
  a room that wasn't there. The symptoms never named the cause: the case reported
  its room as **"Unknown"**, and the room it should have been in reported **zero
  cases**. Three fixes: the picker defaults to whichever room actually carries
  the flag; case create and update both reject an unknown `room_id`; and existing
  orphans are reattached to the default room on boot.
- **"Cancel" in the photo cropper uploaded the photo.** Cancel, ×, and a stray
  tap on the backdrop were all wired to "use the original". Cancel now cancels;
  skipping the crop got its own **Use Original** button.
- **Editing a hat discarded what you were typing.** The form re-seeded from the
  server on every refetch, and since 2.6.0 the row changes *while you edit it*.
  It now seeds once per hat.
- **The hex field couldn't be typed into.** It only accepted input that already
  matched a complete 6-digit value, so every partial keystroke was rejected.
- **The Home carousel could crash the page.** The active index was never clamped,
  so a list that shrank under it threw and dropped the whole page to the error
  boundary. It also reshuffled on every poll.
- **Case occupancy went stale.** Disposing, deleting, adding or re-assigning a
  hat invalidated `['hats']` but not the case-shaped views. All hat mutations now
  go through one `invalidateHatViews` helper.
- **Bulk Import dead-ended on a bad `?job=`.** The upload form is hidden whenever
  a job id is set, so a stale link showed a header and nothing else — while
  polling the 404 every two seconds forever.
- **`hydro` / `hydrolite` searches found nothing.** USAGE promised "`hydro` finds
  every Hydro", but 2.6.0 moved them from `style` values to boolean columns that
  no text match could reach. Both terms match their flag again, and search now
  also covers `artist_series`.
- **Case detail ignored a per-case capacity override**, showing "3/4" for a case
  limited to 3 and inviting an add the API then rejected.
- The login page redirected during render; three-column price tiles never became
  thirds because `.col-4` was used but never defined (along with four other
  utility classes); the settings error-list refresh left the nav badge stale;
  camera images were pinned in memory for the life of the SPA.

### Performance

- **`GET /api/rooms` loaded the entire collection to produce a case count.** The
  eager load cascaded through mapper-level loads into every hat, color and
  wear-log row — measured 30ms vs 0.3ms for the COUNT that replaces it.
- Color search converted the target color to LAB once per stored swatch instead
  of once per search.

### Changed

- `logo_detected` aside, analysis no longer erases `brand` / `model_name` /
  `artist_series` (shipped in 2.6.1, noted here for completeness).
- Shutdown no longer aborts if a background task had already died holding an
  exception — the import and analysis workers were left running and mDNS never
  sent its goodbye packets.
- `analysis_queue._queue_depth` / `_mark_failed` are now public; `/health/ready`
  no longer reaches into a private name.
- Removed dead code: the `custom_style_detail` column (unread since the initial
  commit), and three uncalled functions. Existing databases keep the column; it
  is simply no longer mapped.
- Docs no longer quote test counts. That claim has now gone stale twice, so the
  suite is the source of truth and the per-release number lives here.
- `nanoid` bumped to 3.3.18 (build-time only via vite → postcss).

229 backend + 44 frontend tests.

## [2.6.2] — 2026-08-16 — _hats that keep their brims_

### Fixed
- **The Docker image was still being built with `u2netp`.** 2.6.0 changed the
  code default to `isnet-general-use` because `u2netp` trims hat bills, but
  `docker-compose.yml` passed the old model as a build arg — which bakes it into
  the image *and* sets the env var, beating the code default. So the documented
  install path never got the fix, and the README table still advertised the old
  default. Compose now defaults to `isnet-general-use`;
  `REMBG_MODEL=u2netp docker compose up -d --build` remains the escape hatch.
- **Cutouts rendered faded / "ghosted".** Background removal took the model's raw
  mask, so mid-confidence regions came through as semi-transparent alpha.
  `remove()` now runs with `post_process_mask=True`, which opens the mask, blurs
  it and thresholds it — every pixel ends up fully opaque or fully clear.
- **Re-analysis destroyed the cutout a little more each time.** A queued
  reanalyze always ran background removal — and for a stored PNG the output path
  resolves to the *input file*. rembg re-segmented an already-transparent image
  and wrote it back over the only copy, so every tap ate further into the alpha.
  Background removal is now skipped when the input is already a cutout; uploads
  are normalized to JPEG first, so a `.png` here can only mean "already cut out".
- **Navigation kept the previous page's scroll position.** A `<ScrollToTop />`
  in the app shell resets it on each navigation. Back/Forward are deliberately
  exempt.

### Note
Existing hats keep the cutouts they were already given; the improvements apply
to photos processed from here on. The pre-cutout JPEG is not retained, so there
is nothing to re-cut from.

## [2.6.1] — 2026-08-16 — _name the collab yourself_

### Added
- **Artist / Collab is editable.** `artist_series` was readable on the hat page
  but there was no way to set or correct it — 2.6.0 shipped it as a Claude-only
  field. It now has an input in the Edit Hat form's AI / Pricing Overrides card.
  Special editions are the hats Claude is least likely to name and the ones most
  worth recording.

### Fixed
- **A re-analysis no longer erases a brand, model or collab you typed.**
  `_apply_analysis` assigned Claude's answer straight through, nulls included, so
  tapping Reanalyze wiped any of those three fields Claude couldn't identify —
  and the tool schema explicitly tells it to answer null rather than guess.
  Without this the new field would have been erased by the very workflow it
  exists for. A real answer still wins, so Claude can still correct an earlier
  identification; only erasure is blocked. `logo_detected` is deliberately
  exempt — it records what is visible in *this* photo, so null there is an
  answer, not a gap.

## [2.6.0] — 2026-08-16 — _analysis gets out of your way_

### Added
- **Photo analysis is queued instead of blocking the upload.**
  `POST /api/hats/{id}/photo` now saves the photo, marks the hat
  `analysis_status='pending'` and returns immediately; a background worker runs
  rembg → Claude → eBay → Melin. You can keep adding hats while earlier ones
  analyze. The hat page shows a spinning **Analyzing…** badge and polls until the
  status is terminal. Previously the request stayed open for the whole pipeline,
  which read as a hang. Durability mirrors the bulk-import worker: the loop
  survives any per-hat exception, a crash mid-analysis is re-queued on boot, and
  if no worker is draining the queue the route runs the pipeline inline rather
  than dropping it.
- **`logo_detected` field.** Claude Vision now records the mark it actually SAW
  and the brand that owns it, kept apart from `brand`, which can be inferred from
  shape, colorway or a hang tag with no logo in frame. The Google Vision fallback
  fills it too — logo detection only fires on a visible mark, so that path is
  evidence by construction.
- **HYDRO + HYDROLite checkboxes, and Claude sets them.** melin lists HYDRO and
  HYDROLite as separate technologies offered across the model lines, so they are
  two per-hat flags. Claude answers a single `construction` field, which is
  mapped to the flags — one exclusive value rather than two booleans, so it
  cannot return a hat that is somehow both. Applying it is **additive**: analysis
  turns a flag ON and never off, because these are also checkboxes a human ticks.
- **`artist_series` field.** Claude names the collaborator on signature
  collaborations / artist series, which the `collab` STYLE could not — it only
  says *some* collab, not which one, and which one is what drives collectability.
  Instructed to leave it null rather than guess.
- **HYDROLite checkbox on the hat form.** HYDROLite is melin CONSTRUCTION
  offered across the model lines, so any hat can be one. It is a per-hat flag,
  deliberately NOT a `HatStyle` value: as a style it would need a second entry
  per model and would split one model's hats across two style buckets.
- **Clear All** on the hat's Color Palette card wipes the whole palette in one
  call, instead of removing swatches one modal at a time after a bad analysis.

### Changed
- **Default background-removal model is now `isnet-general-use`** (was
  `u2netp`). u2netp is 4.7 MB and was picked for Pi speed, but its low capacity
  loses thin protruding shapes — on a hat that is precisely the **bill**. The
  heavier model costs ~170 MB and slower inference, which stopped mattering once
  analysis left the request path. `HEADROOM_REMBG_MODEL=u2netp` restores the old
  behavior.

### Fixed
- **The photo button never offered your library.** The file input carried
  `capture="environment"`, which does not *prefer* the camera — it forces it, so
  iOS and Android skipped the picker and opened the rear camera. Removed.
- **Modals were painted over by the page behind them.** `.modal` is
  `z-index: 1050`, but z-index only ranks siblings *within a stacking context*,
  and `.card-body` is `position: relative; z-index: 1` — so a modal rendered
  inside a card was confined to that card's slot in the page order. All four
  modals now render through a `<body>` portal, which also immunizes them against
  the `overflow: hidden` and `transform` containing-block traps.
- **Editing a mis-detected color silently reverted.** Typing "green" over a color
  Claude had read as gray saved "gray": the colors endpoint re-derived
  `general_color` from the stored hex whenever one was present. An
  explicitly-typed name now wins and is snapped to the palette's spelling; the
  hex is consulted only when the field is blank.
- **Color ranks are renumbered server-side.** The endpoint stored the client's
  `dominance_rank` verbatim. The UI edits and removes a color BY rank, so a
  duplicate made one tap hit two rows. Ranks now follow submitted position, so
  they are always dense and unique.
- **The SQLite write lock was held across the whole analysis.** Setting
  `photo_path` before the pipeline's first DB read let autoflush open a write
  transaction, which SQLite holds until commit — so the lock stayed held through
  Claude, eBay and Melin, and any concurrent write waited out `busy_timeout`. The
  network-bound section now runs under `no_autoflush`.
- `vite.config.ts` used `__dirname`, which only exists because Vite's current
  config loader wraps the file in CJS shims. The config is ESM, and Vite's native
  config loader — slated to become the default — evaluates it without those
  shims, where `__dirname` is a `ReferenceError`. Now `import.meta.dirname`.

### Changed
- The merge/tag procedure from a git worktree is documented.
  `gh pr merge --delete-branch` merges on the server and *then* fails its local
  cleanup, which reads as "the merge failed" when it actually succeeded.

## [2.5.0] — 2026-08-16 — _current Claude models_

### Changed
- **The Claude model list is current again.** The picker offered the 4.5–4.7
  generation and defaulted to a model Anthropic now classifies as legacy. The
  default is now **`claude-sonnet-5`** — newer *and* cheaper than the 4.6 it
  replaces ($2/$10 per MTok vs $3/$15). The Settings picker lists the current
  lineup (Sonnet 5, Haiku 4.5, Opus 5, Fable 5) under a **Current** group, with
  the superseded ids kept under **Legacy** so an install that saved one stays on
  a named option. Any model id remains enterable by hand.
- **This only changes the default.** If you set a model in Settings, that choice
  is stored in the database and still wins — nothing is migrated or overwritten.
  Installs on the default will start using Sonnet 5 after upgrading; use **Test
  connection** on the Settings page to confirm the key reaches it.

### Added
- Consistency tests (`tests/test_docs_consistency.py`) asserting that the README
  env table, the OPERATIONS env table, and the Settings picker's "(default)"
  label all still match `config.anthropic_model`. Nothing linked those four
  places, which is how the app spent a model generation advertising a superseded
  id with every test green.

### Fixed
- The Claude model `<select>` and its custom-id input had no accessible name —
  the visible `<label>` carries no `htmlFor`. Both now set `aria-label`.

## [2.4.0] — 2026-08-16 — _any room can be the default_

### Added
- **The default room is now a flag, not a hardcoded id.** Previously room `id=1`
  was permanently undeletable, no matter how you'd since reorganized. Any room
  can now take the role via **Make default** on the Rooms page
  (`POST /api/rooms/{id}/default`), which frees the previous one for deletion.
  The Rooms page shows a **Default** badge and only disables delete on the room
  that actually holds the flag.

### Changed
- `RoomRead` gains `is_default`. `CaseCreate.room_id` is now optional — omitting
  it resolves to whichever room currently holds the flag instead of literally
  room 1. Both changes are backward compatible.
- **New-hat defaults live in one place.** `condition=new / size=classic /
  style=a_game` were independently hardcoded in the bulk-import endpoint, the
  import worker's fallback, and the Android share target — so photos shared from
  a phone could land differently than the same photos bulk-imported. All three
  now read `HAT_DEFAULTS`, with a test that fails if any drifts. The two frontend
  forms likewise share one `DEFAULT_HAT_BASICS` constant.

### Fixed
- Deleting a room reassigns its cases to the room that currently holds the
  default flag. It previously wrote `room_id=1` unconditionally.

### Migration
- Adds `rooms.is_default` and backfills the **lowest room id** (not literally 1,
  so a database whose original room was re-keyed still ends up with a usable
  fallback). `ensure_default_room()` now repairs the "exactly one default"
  invariant on every boot. No action needed on upgrade.

## [2.3.1] — 2026-08-09 — _quiet the build_

The Docker build printed 9 lines of warning/notice noise on every run. None of
it was a failure — every build was green — but noise like this is how a real
failure scrolls past unnoticed.

### Changed
- **npm pinned to 12.0.2 in the frontend build stage.** `node:26` bundles npm
  11.x, which printed an upgrade notice on every image build. Now pinned
  explicitly (`ARG NPM_VERSION`), matching how the uv toolchain is already
  pinned. Verified npm 12 installs, typechecks, tests and builds this project
  before pinning it.
- `NPM_CONFIG_LOGLEVEL=warn` in that stage — npm 12 logs a notice per script it
  runs. Warnings and errors still print.

### Fixed
- **onnxruntime device-probe warnings during the image build.** It probes the
  host for GPUs while `import onnxruntime` runs and logs a line per device it
  can't read — guaranteed noise in a container. The messages come from C++
  straight to fd 2 *during the import*, so the Python logging API runs too late;
  the rembg pre-download now redirects at the fd level across the import and
  restores it immediately. Scoped to that build step: the **runtime keeps
  onnxruntime's default logging**.
- **`StarletteDeprecationWarning` on every backend test run.** starlette's
  `TestClient` deprecated `httpx` in favor of `httpx2`; added `httpx2` to the dev
  group. Test-only — the app's own outbound calls still use `httpx`.

- **`setup.sh` and CI now use the image's npm.** Pinning npm only in the
  Dockerfile created fresh drift — CI and bare metal stayed on npm 11 while the
  image built on 12, so the frontend CI job was green-lighting a toolchain that
  never ships.

Net, measured in CI's own log: image build **9 noise lines → 0**, and
`uv run pytest` from "190 passed, 1 warning" to "190 passed".

## [2.3.0] — 2026-08-09 — _frontend tests, react-router 8, code-review cleanup_

### ⚠️ Requirements
- **`./scripts/setup.sh` now wants Node 22.22+** (was 22.12+). react-router 8
  declares `engines: node >=22.22.0`, which supersedes vite's `>=22.12.0` as the
  highest floor any dependency sets. Node 22.12–22.21 previously *passed* the
  setup check and then failed at `npm ci`; setup.sh now upgrades Node instead of
  waving it through. Docker (`node:26`) and CI (`node 26`) were already above the
  floor.
- `package.json` now declares `react`/`react-dom` `^19.2.7` (was `^19.1.0`) to
  match react-router 8's peer range. The installed version already satisfied it.

### Security
- **react-router 7.18.2 → 8.3.0**, clearing an advisory affecting a server-side
  rendering mode this app does not use. Headroom is a declarative-mode SPA with
  no RSC, loaders, actions or server rendering, so the advisory did not apply
  here — but the version was flagged and the upgrade is clean. No Dependabot
  alerts remain open.

### Added
- **Frontend test suite** — Vitest 4 + Testing Library 16 (jsdom), **35 tests**,
  run in the existing CI frontend job (no new job, no new trigger). The repo had
  no frontend test harness at all. Covers the shared hat filter/form components,
  the Settings composition, and the routing primitives the route table depends
  on. `npm test` / `npm run test:watch`.
- `tests/test_hats.py::test_hat_read_exposes_every_derived_field` pins the Hat
  read-model fields that come from relationships rather than columns, plus the
  unassigned-hat null case. `room_id` had no coverage and is what the Hats page
  filters on — a silent null there would have quietly matched nothing.

### Changed
- **Code-review cleanup — no behavior change.** Verified by generating the full
  OpenAPI document before and after and diffing it: **90 routes, identical**,
  every response schema byte-identical.
  - The Anthropic and Google-Vision API-key routes were line-for-line twins.
    Both now derive from one `KeyProvider` descriptor — a third provider is one
    dataclass entry plus one line.
  - `_hat_to_read` hand-copied ~45 attributes and walked `hat.case.room` from the
    route layer. The derived values are now properties on the `Hat` model and
    `HatRead` builds itself with `model_validate`.
  - `routes/admin.py` (334 lines, seven reasons to change) is now a package of
    six single-concern modules; the `/api/admin` prefix, tag and `require_admin`
    are applied once, so a submodule cannot ship an unguarded route.
  - `SettingsPage.tsx` 1084 → 44 lines over 15 card modules; the shared hat
    filter and form components take the four hat pages from 1093 → 819 lines.
  - Import-job counters no longer dispatch on a string; eBay's Browse request
    block was duplicated three times and is now one helper.
- `react-router-dom` is **removed in v8**; every import moves to `react-router`.
  Dropping the re-export shim trimmed ~2 kB off the bundle.
- `rembg[cpu]` floor `>=2.0.50` → `>=2.0.77`.

### Fixed
- **Form controls were not associated with their labels.** The `<label>` elements
  carry no `htmlFor` and do not wrap their inputs, so assistive tech announced
  every filter and hat-form select as unlabeled. All eleven controls now carry an
  `aria-label`. Found by the new tests.
- **`HEADROOM_REMBG_MODEL` was documented as configurable but impossible to
  change.** `ARG` is stage-scoped, so the runtime stage discarded the build arg
  and compose pinned the env var on top; following the docs baked a ~170 MB model
  into the image that was never loaded.

## [2.2.2] — 2026-08-05 — _faster rebuilds, infra cleanup_

### Changed
- **Docker rebuilds are ~40s faster after a code change.** The rembg model
  pre-download sat *after* `COPY src ./src`, so every source edit re-downloaded
  the ONNX weights — measured at 51% of total image build time. It only needs
  `rembg`, so it now runs before the source copy. The two Python stages also
  share one `base` stage instead of repeating the image tag and native-lib list.

### Fixed
- **`./scripts/setup.sh --help` was truncating mid-list.** It printed a
  hardcoded line range that the header outgrew; it now prints the comment block
  itself.

### Docs
- Corrected the `pymatting` constraint rationale in `pyproject.toml`: 1.1.14
  declares `numba!=0.49.0` (*unbounded*, which is why an ancient numba can be
  selected), not "pins numba 0.53.1" as previously written — a maintainer
  checking the old claim would have found it false and dropped the constraint.

## [2.2.1] — 2026-08-05 — _cryptography Bleichenbacher fix_

The automation added in 2.2.0 immediately earned its keep: enabling Dependabot
alerts surfaced a **high**-severity advisory nothing had caught before.

### Security
- **`cryptography` 49.0.0 → 50.0.0**, clearing an advisory in PKCS#7
  `EnvelopedData` decryption (vulnerable `>=44.0.0,<50.0.0`). It reaches us
  through `webauthn`, i.e. the passkey path. **`pyopenssl` 26.3.0 → 26.4.0**
  rides along because 26.3 caps `cryptography<50` — upgrading cryptography alone
  was impossible, the resolver just silently backtracked.

### Changed
- **`[tool.uv] exclude-newer-package = { cryptography = false, pyopenssl = false }`.**
  The 7-day cooldown exists to dodge freshly published *malicious* packages, but
  for the crypto stack a fresh release is usually the *security fix itself* —
  50.0.0 landed 4 days after the advisory and a plain `uv lock` kept silently
  reverting. These two are now exempt; everything else still waits out the
  cooldown.

## [2.2.0] — 2026-08-04 — _stop the drift: automated dependency updates + CI_

Answering "why is so much always out of date?": **nothing was automated.** No
CI, no Dependabot, no Renovate — no `.github/` directory at all. Every bump was
manual and reactive, and `package-lock.json` pinned versions that nothing ever
refreshed.

### Added
- **`.github/dependabot.yml`** — weekly PRs for **npm**, **uv**, **Docker base
  images** (including the `COPY --from=` toolchain pin that sat at uv 0.5.4 from
  v0.2.0 to v2.0.6) and **GitHub Actions**. Minor/patch are grouped into one PR;
  majors arrive individually. Each ecosystem carries a 7-day `cooldown`,
  mirroring `[tool.uv] exclude-newer`. Validated against the official schema.
- **`.github/workflows/ci.yml`** — pytest + typecheck + production build on every
  PR, plus a **real Docker build and container health check**. That last job is
  deliberate: the 2.0.6 breakage was config the *image's* toolchain couldn't
  parse, which the test suite could never have caught.
- **Dependabot alerts and automated security fixes are now enabled** on the
  repository.

### Changed
- **Frontend dependencies brought current.** In-range refresh plus four majors:
  **vite 6 → 8**, **TypeScript 5.8 → 7**, **@vitejs/plugin-react 4 → 6**,
  **react-easy-crop 5 → 6**. Typecheck and production build verified clean; the
  bundle got *smaller* (446 → 439 kB) and the build faster.
- **Node floor raised to 22.12** in `scripts/setup.sh`, with a real minor-version
  check. vite 8 and the React plugin require `^20.19 || >=22.12`, so a bare major
  comparison would have waved through Node 22.0 and then failed at build time —
  and the Node 20 line reached end-of-life 2026-04-30.

## [2.1.1] — 2026-08-04 — _bare metal catches up to the image_

2.1.0 moved the **Docker** toolchain forward but left the bare-metal path
behind, so `./scripts/setup.sh` still provisioned the old versions.

### Changed
- **`scripts/setup.sh` now installs what the image runs**: NodeSource
  `setup_22.x` → `setup_26.x`, and Python comes from a new committed
  `.python-version` pin (**3.14**) instead of whatever uv defaulted to. An
  existing **Node 20+** is still accepted; only *fresh* installs get 26.
- **`.python-version` is now tracked in git.** It was in `.gitignore` under
  "local-only files", which would have made the pin invisible to everyone else —
  the interpreter version is a project decision, not a per-developer one.
- Doc claims corrected where they'd gone stale: README bare-metal prereqs and
  architecture line, and the project setup/backend notes.

### Note
`pyproject.toml` keeps `requires-python = ">=3.12"` — verified the suite passes
on **both** 3.12.12 and 3.14. There is no `requirements.txt` in this project;
`uv.lock` is the dependency manifest and is updated with every dependency
change.

## [2.1.0] — 2026-08-03 — _latest toolchain across the whole build_

Every pinned tool in the image was audited, not just the one that broke in
2.0.7. The `uv` pin had sat at 0.5.4 since v0.2.0 — through a "production
hardening" pass that edited the same file — which is what let the 2.0.6
regression happen in the first place.

### Changed
- **Node 22 → 26** (SPA build stage), **Python 3.12 → 3.14**, **Debian bookworm
  → trixie**, **uv 0.11.28 → 0.12.1**. Caddy sidecars were already floating on
  latest `2-alpine`.
- Verified by **building and running the image**, not by checking versions
  locally — the exact gap that caused 2.0.7. Confirmed inside the container:
  Python 3.14.6 on Debian 13, `rembg`/`onnxruntime` load and produce a real
  session, and a full end-to-end run (owner setup → create hat → photo upload →
  auth-gated photo fetch) returns a **transparent PNG**, which only happens when
  background removal genuinely ran. Zero tracebacks in the log.
- Note `fastapi` resolves to 0.139.2 rather than 0.140.x — the 7-day
  `exclude-newer` cooldown from 2.0.6 holding back a just-published release,
  working as designed.

## [2.0.7] — 2026-08-03 — _fix the Docker build's uv pin_

### Fixed
- **`failed to parse year in date "7 days"` during `docker compose build`**, a
  regression from 2.0.6. The image pinned **uv 0.5.4** (Nov 2024), but the
  `exclude-newer = "7 days"` cooldown added in 2.0.6 needs **uv ≥ 0.9.17** —
  relative durations didn't exist before that. The old uv warned and then
  **silently ignored the setting**, so the build still produced an image, but
  **without the supply-chain cooldown 2.0.6 advertised**. The pin is now
  `uv 0.11.28`, which is also the version that writes `uv.lock` (revision 3).
  Verified by building the image and running it.

## [2.0.6] — 2026-07-27 — _dependency security updates_

### Security
- **Cleared 74 Python advisories across 11 packages**, including three in the
  photo-upload path: **pillow-heif** 1.2.1 → 1.4.0, **Pillow** 12.1.1 → 12.3.0
  (36 advisories), and **python-multipart** 0.0.22 → 0.0.32. Also **urllib3** →
  2.7.0, **starlette** 0.52.1 → 1.3.1, **idna** → 3.18, **click** → 8.4.2,
  **pydantic-settings** → 2.14.2, **python-dotenv** → 1.2.2, **pygments** →
  2.20.0, **pytest** → 9.1.1.
- **Frontend: 11 advisories → 1.** `react-router-dom` 7.13.0 → 7.18.1 and `vite`
  6.4.1 → 6.4.3 clear the reported issues; `npm audit fix` cleared the
  postcss/picomatch/babel build-toolchain advisories.
- **Known-accepted, not applicable:** one React Router advisory remains, fixed
  only in react-router 8.3.0. This app is a pure client-side SPA — no RSC mode,
  no loaders/actions, no server packages — so the affected code path cannot be
  reached. Deferred rather than take a major-version migration for an
  unreachable path.

### Changed
- `[tool.uv]` gains a **7-day dependency cooldown** (`exclude-newer`) so a
  compromised or broken package published minutes ago can't be pulled straight
  into a build, plus a `pymatting>=1.1.15` constraint — the resolver otherwise
  picked 1.1.14, which drags in a numba/llvmlite pair that only builds on Python
  <3.10, breaking `uv sync` and the Docker image on our 3.12 baseline.

## [2.0.5] — 2026-07-25 — _case-rack top-cap fix (v3.1)_

### Fixed
- **Case-rack top cap didn't seat on the pegs** (`hardware/melin-rack-v3.zip`).
  The v3 staggered legs are C2-*rotation* symmetric but **not mirror**
  symmetric, and the cap installs **flipped** — which mirrors its plan pattern —
  so the cap's bosses/pockets landed at the wrong positions. The cap is now
  modeled at the x-mirrored leg positions so it seats exactly after the flip.
  **Only the top cap changed**: the rack and fit-test STLs are byte-identical to
  v3, so already-printed bays and coupons stay good — reprint just the cap.

### Removed
- `melin-rack-top_cap.3mf` from the model archive. It was sliced from the
  pre-fix geometry, and shipping a ready-to-print project of a part that doesn't
  fit is worse than shipping none — slice the corrected STL instead. The bay and
  fit-test `.3mf` projects are unaffected and still included.

## [2.0.4] — 2026-07-19 — _off-site backups_

### Added
- **Off-site scheduled backups.** New `HEADROOM_BACKUP_UPLOAD_CMD` runs after
  each scheduled backup and ships the new tarball off-box (`{path}`/`{dir}`/
  `{name}` substituted, argv/no-shell, bounded by
  `HEADROOM_BACKUP_UPLOAD_TIMEOUT`, best-effort — a failed or missing uploader
  never breaks the local backup). New `docker-compose.backup-rclone.yml` overlay
  wires it to rclone (Box, S3, Backblaze B2, Google Drive, …); OPERATIONS.md §4
  also documents a host-cron alternative.

### Docs
- **"Start fresh / reset the database" instructions** — how to wipe the
  `headroom-data` volume for a clean install (with the backup-first warning and
  the `https-lan` Caddy-CA caveat), plus keep-the-cert and keep-the-photos
  variants. Added to the README `Updating` section and OPERATIONS.md §4.

## [2.0.3] — 2026-07-17 — _mDNS behind the sidecar_

### Fixed
- **`headroom.local` not resolving in the Docker host-net / sidecar deploys**
  (the raw IP worked, the name didn't). The mDNS responder ran in zeroconf's
  default "all interfaces" mode, so in a host-net container it also bound sockets
  on `docker0`/`veth`: a flaky bridge socket could make registration throw and be
  swallowed, and even on success the responder leaked onto the bridge and
  multicast could egress the wrong NIC. It now binds the **detected LAN interface
  only**. Escape hatch: `HEADROOM_MDNS_INTERFACE` — an IP to pin, or the literal
  `all` to restore the previous mode. `GET /api/settings/mdns` reports the
  advertised IP and any error.

## [2.0.2] — 2026-07-17 — _case-rack v3_

### Changed
- **Case-rack model → v3** (`hardware/melin-rack-v3.zip`, replaces
  `melin-rack-v2.zip`). Legs are now **staggered** so adjacent stands interleave
  side by side at 235 mm center-to-center (C2 symmetric — orientation-free); the
  side channel is 5 mm tighter for a snugger hold, trimming the footprint to
  ~241 × 258 mm. Every printable part now ships a ready-to-slice Bambu Studio
  `.3mf` (bay + top cap + fit test).

## [2.0.1] — 2026-07-16 — _test hardening_

### Added
- **Plain-HTTP-on-80 deploy overlay** (`docker-compose.http80.yml`) — a Caddy
  sidecar serves `http://headroom.local` (and `http://<host-ip>`) on port 80 with
  no HTTPS and no certificate to trust. The app stays non-root on :8000; Caddy
  owns the low port. Password login only (http isn't a secure context — use
  `docker-compose.https-lan.yml` for passkeys/Face ID).
- README "Run it" now opens with an overview table of every deploy mode with its
  command, URL, and passkey support.
- **Browser-tab favicon is now the Headroom logo** (`favicon.ico` at 16/32/48 +
  a 32px PNG, generated from the app icon).

### Changed
- **Case-rack model → v2** (`hardware/melin-rack-v2.zip`, replaces
  `melin-stand-slim.zip`). Bay is sized for the case measured **zipped shut**
  (`case_w` 200 → 220 mm, footprint ~246 × 258 mm), print profile bumped to
  4 walls / 20% infill, and a ready-to-slice Bambu Studio `.3mf` is included.

### Tests
- **Assertion-strength pass over the whole suite.** Refined tests whose name
  promised a behavior their assertions never verified — they stayed green even
  when that behavior broke. Replacing a photo now checks the old file actually
  left disk; image conversion decodes the output bytes rather than trusting the
  `.jpg` suffix; the backup download is opened as a gzip tar and walked instead
  of measured by length; the `hat.created` audit row is tied to the specific hat;
  and wear's `date_last_worn` is asserted against today's date.
- **New coverage for previously-untested paths.** The token-gated share-photo
  streamer's path containment guard, and the eBay comparable-listings service
  (query hierarchy, degrade-to-link-only, and price aggregation with the network
  seam stubbed — no live API, per house rule). A duplicate `/health` test was
  removed.
- Three of these guards are **mutation-verified**: breaking the code makes the
  corresponding test fail, proving it catches the real regression.

## [2.0.0] — 2026-07-16 — _production hardening_

A forensic multi-agent review gated the v1.x line for production; this release
fixes every finding and folds in the preceding cleanup pass. Databases upgrade
in place — no schema-breaking changes — but two operational interfaces changed,
hence the major bump.

### Breaking
- **`BUILD_SHA` build arg renamed to `HEADROOM_BUILD_SHA`.** Stamp the footer
  with `HEADROOM_BUILD_SHA=$(git rev-parse --short HEAD) docker compose up
  --build`. The old `BUILD_SHA` name is no longer read.
- **The Docker image install is now `uv sync --frozen` only** (no unpinned
  fallback). A `uv.lock` / `pyproject.toml` mismatch fails the build instead of
  silently resolving fresh versions — run `uv lock` and commit if it errors.
- **Changing your password now rotates the API bearer token** as well as
  revoking other sessions. Cookie-less clients (the iOS Shortcut) must copy the
  new token from Settings → Account after a password change.

### Changed (cleanup pass)
- mDNS advertising registers off the boot path (≈1.2 s faster startup) and
  withdraws with a single goodbye broadcast; the Settings LAN card derives its
  state instead of caching it. A shared `env_flag()` replaces three copies of the
  truthy-env idiom.
- README gains a full step-by-step **HTTPS-on-the-LAN / Face ID** walkthrough.

### Fixed — reliability
- **Bulk-import worker can no longer silently die.** The worker loop now
  survives any per-item exception (including a transient `database is locked`),
  and a bug in its own error handler is fixed.
- **Crash recovery for imports.** On boot, items stranded in `processing` are
  re-queued and jobs whose items are all terminal are closed — no more jobs that
  poll "running" forever.
- **Backups no longer self-destruct under restart loops.** Retention is now
  age-based, the newest snapshot is never pruned, and the startup backup is
  skipped when a recent one already exists.
- **SQLite tuned** with WAL + `busy_timeout` + `synchronous=NORMAL`, shrinking
  the transient-lock error class.

### Fixed — correctness
- **Undispose no longer collides slots.** Restoring a disposed hat reassigns its
  `position_in_case`, so it can't share a slot / display ID / QR label with a hat
  added while it was disposed.
- **Manual color edits stay searchable.** `PUT /hats/{id}/colors` now normalizes
  `general_color` onto the curated palette, as the analysis pipeline does.
- **One wear per hat per day** is enforced by a unique constraint, closing the
  double-tap race.
- Case-photo upload no longer blocks the event loop (async image processing).

### Fixed — security / operability
- **Auth telemetry.** Failed logins, lockouts, and successes are logged and
  audited; backup downloads, key/cred changes, and share-link create/revoke now
  write `activity_log` rows.
- **`/health/ready` redacts** filesystem paths, key source, and raw errors for
  anonymous callers; authenticated callers also get an import-worker liveness
  signal.
- **Password change is a complete compromise response** — it now rotates the API
  token alongside revoking other sessions.
- **First-run setup is serialized** against a concurrent second POST (no
  duplicate owners).
- argon2 verify runs off the event loop under a concurrency bound; login
  rate-limiter entries are cleaned up; bulk-upload memory is bounded; the
  Dockerfile install is `--frozen`-only.
- Single-process assumption is now warned about at startup when
  `WEB_CONCURRENCY` > 1. Retired `HEADROOM_ADMIN_TOKEN` references removed from
  docs.

### Added
- **Public branding logo** (`GET /api/public/branding/logo`) — the login page now
  shows the configured logo, not just the wordmark.
- Model↔migration consistency test so a new `Hat` column can never be forgotten
  in the DDL. 14 new hardening regression tests (170 total).

## [1.3.0] — 2026-07-15 — _headroom.local + LAN passkeys + printable case rack_

### Added
- **mDNS LAN discovery.** The app advertises itself as **`headroom.local`**
  (python-zeroconf, best-effort, `HEADROOM_MDNS_ENABLED` / `_HOSTNAME` /
  `_PORT`). Multicast can't cross Docker's bridge network, so the new
  `docker-compose.mdns.yml` overlay switches to host networking (Linux/Pi). A
  read-only **LAN Discovery** card on Settings shows the advertised URL, LAN IP,
  or registration error.
- **LAN HTTPS overlay** (`docker-compose.https-lan.yml`) — Caddy with its
  internal CA on 443 makes `https://headroom.local` a secure context, so **Face
  ID / passkeys work on the LAN name** (Let's Encrypt can't issue for `.local`).
  Trust the exported root cert once per device; passkey identity and mDNS port
  are set automatically. Proxy-header trust scoped to loopback since :8000 stays
  LAN-reachable.
- **3D-printable case rack** (`hardware/melin-stand-slim.zip`) — modular,
  stackable, supports-free slide-in rack for Melin 3-hat travel cases
  (parametric OpenSCAD + STLs, filament-optimized skeleton floor). Print notes
  recommend an H2D-class bed (~222 × 258 mm footprint).
- **Build stamp.** The footer shows the git short SHA next to the version: baked
  at build time from `HEADROOM_BUILD_SHA` / local git, injectable in Docker via
  the `BUILD_SHA` build arg.
- README: **Updating** section (upgrade commands + automatic SQLite migrations +
  backup-first advice) and a LAN discovery guide.
- 7 new tests (154 total).

## [1.2.0] — 2026-07-12 — _wear tracking + QR case labels_

### Added
- **Wear tracking.** "🧢 Wearing this today" button on the hat page appends to a
  new `wear_log` table (idempotent per day, undo supported) and bumps
  `date_last_worn`. Hat pages show wear count and **cost-per-wear**. The
  Valuation page gets a "Wear Rotation" card surfacing the five longest-unworn
  active hats. `POST /api/hats/{id}/wear`, `DELETE /api/hats/{id}/wear/latest`.
- **QR case labels.** `GET /api/admin/case-labels` renders a printable sheet —
  one label per case with an inline-SVG QR (deep link to the case page), display
  id, room, and fill/capacity. "🏷 Labels" button on the Cases page. New dep:
  `qrcode` (pure Python, SVG output — no raster stack).
- 3 new tests (147 total).

## [1.1.0] — 2026-07-12 — _colorway catalog + purchase history_

### Added
- **Colorway catalog.** `POST /api/admin/colorways/refresh` sweeps every style
  category on the melinrecap marketplace API and parses listing titles ("Model -
  Colorway") into a catalog table — live-verified: 987 listings → 501 unique
  entries, including years of sold-out drops absent from melin.com.
  `GET /api/meta/colorways` powers autocomplete for model + colorway on the Edit
  Hat form; Settings gets a refresh card. New `colorway` column on hats.
- **Purchase history + cost basis.** `purchases` table with
  `POST /api/admin/purchases/import` (structured line items from order emails;
  deduped) and `POST /api/admin/purchases/match`, which links purchases to hats
  by model (+colorway when both sides have one) and sets `purchase_price` /
  `purchased_at` / `colorway` on the hat. Edit Hat form exposes colorway +
  purchase price; Settings shows the purchase list.
- 5 new tests (144 total).

## [1.0.0] — 2026-07-12 — _auth: accounts, passkeys, share links, HTTPS_

Headroom is now safe to expose to the internet. **Breaking**: accounts are
mandatory — on first boot the app walks you through creating the owner account;
the iOS Shortcut import now needs an `Authorization: Bearer <api-token>` header
(token in Settings → Account). `HEADROOM_ADMIN_TOKEN` is retired and ignored.

### Added
- **Accounts + sessions.** First-run owner setup, argon2id password hashing,
  server-side revocable sessions (256-bit, 30-day, httpOnly + SameSite=Lax
  cookies, `secure` auto-set over HTTPS), login rate limiting, logout,
  change-password.
- **Everything data-bearing is gated** — all of `/api/*` AND the `/uploads/*`
  photo mount (previously world-readable). Open by design: SPA shell/assets,
  manifest/icons, `/health*`, `/api/auth/*`, `/api/public/*`. The Android
  share-target POST needs a session; the public share page does not.
- **Passkeys (WebAuthn).** Add from Settings → Account; sign in with Face ID /
  Touch ID from the login page. py_webauthn on the backend, hand-rolled base64url
  plumbing on the frontend (no new JS deps). `HEADROOM_RP_ID` / `HEADROOM_ORIGIN`
  config; set automatically by the HTTPS overlay.
- **API token per user** (shown/rotated in Settings → Account) for cookie-less
  clients — the iOS Shortcut recipe card now includes the header step.
- **Read-only share links.** Settings → Share Links mints `/share/<token>` URLs
  (256-bit, revocable, optional expiry): a public gallery view with token-gated
  photo streaming — photos never leak through the protected uploads mount.
- **HTTPS overlay** (`docker-compose.https.yml`): Caddy sidecar with automatic
  Let's Encrypt certs; port 8000 no longer exposed directly; uvicorn honors
  X-Forwarded-Proto.
- Login page (first-run setup + password + passkey), Account card, Share Links
  card; 401s anywhere in the SPA bounce to /login.
- 9 new auth tests (138 total); full lifecycle also smoke-tested live.
- Deps: `argon2-cffi`, `webauthn`.

### Fixed
- Password reset procedure documented for the no-email reality (OPERATIONS §6).

## [0.9.0] — 2026-07-11 — _find-the-hat: color-similarity search + capacity_

### Added
- **Search by color.** Tap a palette chip (or pick any color) and every active
  hat is ranked by perceptual closeness — ΔE*76 in LAB space over the *stored hex
  swatches*, so "light blue" finds sky/powder/baby blue hats regardless of what
  the analyzer named them, and a hat whose *secondary* color matches still
  surfaces. `GET /api/search/color?hex=`, palette chips from
  `GET /api/meta/colors`.
- **Normalized color vocabulary.** `general_color` now snaps to the curated
  palette from the hex at analysis time, with a one-time startup backfill for
  existing rows. Default color search uses the normalized names; `exact_colors`
  still matches the analyzer's original phrasing.
- **Find-it result cards.** Search results now include brand + model name and a
  location breadcrumb (Case display-id · Room); text search also matches
  brand/model. Disposed hats are excluded from search — they're not findable on a
  shelf.
- **Per-case capacity.** New nullable `capacity` column (inline DDL migration)
  overrides the type defaults per case, editable on the New/Edit Case forms.
- 13 new tests (129 total).

## [0.8.0] — 2026-07-07 — _live Melin Recap resale prices_

### Added
- **Live median resale price from melinrecap.com.** The site is a Treet
  marketplace on Sharetribe Flex; its frontend queries the public Flex
  Marketplace API with an anonymous public-read token. `melin_recap.py` now does
  the same — one `listings/query` per analysis, narrowed to the specific model
  when enough title matches exist. Median asking price lands in `resale_price`
  with a transparent source label. No scraping, no headless browser —
  Pi-friendly, and verified live.
- Runs in every analysis path: Claude success, reanalyze, and the v0.7.0 fallback
  when logo detection identifies a Melin.
- `HEADROOM_MELIN_CLIENT_ID` env override in case Treet rotates the id;
  anonymous token cached ~20 min with a retry-once-on-401.
- Conftest guard: the Sharetribe seam is stubbed suite-wide so tests can never
  hit the live marketplace; 7 new tests (116 total) cover median math,
  model-vs-category sampling, persistence, and API-failure degrade.
- **Standalone guides**: `docs/OPERATIONS.md` (deployment, configuration, health
  checks, backup/restore with the archive's actual `data/` layout, upgrades,
  security posture, Pi notes, troubleshooting) and `docs/USAGE.md` (first-run
  setup, rooms/cases/hats model, all three import paths, analysis status pills,
  pricing signals, search, disposition, reports, PWA install).

## [0.7.0] — 2026-07-07 — _analysis fallback: mask colors + Google logo brand_

### Added
- **No-Claude fallback analysis** (`analysis_status="fallback"`). When no
  Anthropic key is configured — or a Claude call fails — hats no longer come out
  blank:
  - **Colors, zero keys required.** Dominant colors are extracted locally from
    the rembg cutout's alpha mask (pixels with alpha ≥ 200 only), so
    **background colors are rejected by construction** — the mask *is* the
    segmentation. Median-cut quantization + a curated ~25-name palette fills the
    color fields. If bg-removal failed for a photo, no colors are guessed from
    the contaminated frame.
  - **Brand via Google Cloud Vision logo detection** (optional). New Settings
    card + `GET/PUT/DELETE /api/settings/google-vision-key` (masked reads,
    admin-guarded writes, DB > env — same pattern as the Anthropic key). REST +
    API key, no Google SDK dependency. Logos below 0.6 confidence are ignored.
  - Model name, price, and design notes stay empty — **Reanalyze** with a Claude
    key upgrades a fallback hat to full identification. Reanalyze now also *runs*
    the fallback when no Claude key is set, and Claude-error reanalyzes degrade
    to fallback data instead of error-only.
  - UI: orange "Basic ID (fallback)" pill + info banner on the hat detail page;
    eBay comps remain Claude-gated.
- 15 new tests (109 total): background rejection proven against synthetic RGBA
  fixtures with poisoned transparent pixels, Vision JSON parsing, all pipeline
  degradation paths, reanalyze fallback, key-route masking.

### Fixed
- **Test suite no longer writes into the developer's real `uploads/`
  directory.** `settings.upload_dir` is a relative path and conftest never
  redirected it, so every photo-upload test had been depositing tiny synthetic
  images into `uploads/hats/`. New autouse `isolated_upload_dir` fixture points
  each test at a temp dir with the lifespan's directory tree pre-created.

## [0.6.4] — 2026-07-06 — _self-installing setup + fresh-install logo fix_

### Fixed
- **Seeded logo now loads on the very first boot.** `create_app()` only mounted
  `/uploads` if the uploads directory already existed at import time — but the
  lifespan creates and seeds it *after* the factory runs. On a fresh install the
  logo 404'd — or worse, the SPA catch-all served `index.html` with a 200 for it
  — until the server was restarted. The mount is now unconditional; the lifespan
  still owns directory creation and runs before the first request. Regression
  test: `test_uploads_mount_survives_missing_dir_at_import`.

### Changed
- **`scripts/setup.sh` now installs its own prerequisites** instead of erroring
  when they're missing. Installs (only what's absent, safe to re-run): uv, Node
  20+, Python 3.12 (via uv itself), and — unless `--no-docker` — a Docker engine
  **without Docker Desktop**: colima + docker CLI + compose/buildx plugins via
  brew on macOS, native Docker Engine via get.docker.com on Linux. Also builds
  the production SPA by default (`--skip-build` to opt out). Remote installers
  are downloaded to a temp file and executed — never piped from curl into a
  shell. `--docker-only` installs/starts just the Docker engine and exits.
- **README restructured around "Run it".** Run instructions moved to the top
  (they were buried under five versions of release notes — now a short "What's
  new" that links to this file). First Docker run is shown attached so
  build/boot progress is visible; `-d` is introduced second, with a
  troubleshooting note for the `unknown shorthand flag: 'd'` error. Placeholder
  `<repo-url>` replaced with the real clone URL, and the Development section now
  uses the npm scripts that actually exist.

## [0.6.3] — 2026-05-04 — _eBay env detection + raw error surfacing_

### Added
- **eBay env detection.** `/api/admin/ebay/creds` now returns
  `detected_env: "production" | "sandbox" | "unknown"` by inspecting the saved
  App ID for eBay's keyset format markers. Settings page renders a colored chip
  next to the masked App ID, with an explicit warning banner when sandbox keys
  are saved.
- **Defensive paste handling.** The creds endpoint now strips surrounding quotes
  in addition to whitespace, in case the value is pasted from a code block.

### Changed
- **eBay OAuth errors now surface eBay's actual response.** Previously any
  non-200 from the token endpoint just displayed a generic guess. Now the
  structured `{error, error_description}` is parsed and led with. The "probably
  sandbox" hint is appended only for 401s.
- Server-side: failed OAuth responses are now logged at WARNING with the full
  status code, error code, description, and truncated raw body.

## [0.6.2] — 2026-05-04 — _eBay diagnostics_

### Added
- **"Test connection" button** on the eBay Settings card. Probes OAuth + a
  sample Browse search end-to-end and surfaces a structured `{ok, stage, detail}`
  so the user knows whether OAuth succeeded, the Browse query worked, or the
  creds aren't configured at all. Backend: new `POST /api/admin/ebay/test` and
  `ebay_service.verify_creds()`.

### Changed
- **Specific error message for sandbox-vs-production keyset mismatch.** When
  eBay returns 401 on the OAuth call — the most common failure mode — the error
  now explains that the keyset is probably a sandbox one and names where to
  generate a production keyset. Previously this surfaced as an opaque
  `502 Bad Gateway`.
- Settings card help text now explicitly calls out **Production** (vs Sandbox)
  as the required keyset type.

## [0.6.1] — 2026-05-03 — _user style is ground truth + tap-to-edit colors_

### Changed
- **Owner-selected style is now ground truth for Claude.** When a hat is
  uploaded with `style=trenches`, the analysis prompt explicitly tells Claude
  that line is authoritative — Claude identifies the specific variant within the
  line and is told NOT to pick a model from a different line. If the photo seems
  inconsistent, Claude lowers `model_confidence` rather than overriding.
  `analyze_hat_image()` gains a `selected_style` parameter; the upload pipeline
  and reanalyze route both pass it.

### Added
- **Tap-to-edit color rows** on the Hat detail page. Every color in the palette
  is now a button that opens a modal with: a big color preview that triggers the
  system color wheel, a hex text field, specific name + general (filter) name
  fields, and a tier dropdown. Save / remove / cancel. New "+ Add Color" button
  at the top of the palette card.

## [0.6.0] — 2026-05-03 — _Share-to-Headroom + version display_

### Added
- **Web Share Target API** in `manifest.json` — Android Chrome users who install
  Headroom as a PWA get a "Share to Headroom" entry in the system share sheet
  automatically. Selected photos route through the existing bulk-import job
  worker. New backend endpoint `POST /share` accepts the multipart payload,
  queues an import job, and 303-redirects into `/hats/import?job=N`.
- **iOS Shortcut recipe** in Settings — step-by-step instructions for building a
  one-time Shortcut that POSTs photos from the iOS Photos share sheet to
  `/api/hats/import`. Auto-fills the URL with the running origin.
- **App version in the footer.** `vite.config.ts` reads `package.json` and bakes
  the version into the bundle as `__APP_VERSION__`.
- `BulkImportPage` now reads `?job=N` from the URL so the share-target redirect
  lands on the active job.

### Bumped
- Project version → `0.6.0` (synced across `pyproject.toml` and
  `frontend/package.json`).

## [0.5.0] — 2026-05-03 — _Polish_

PWA install + photo crop on upload. Pure UX wins, no data model touches.

### Added
- **Installable PWA.** Proper `manifest.json` (192px + 512px + maskable icons,
  standalone display, theme color, background color) and `apple-touch-icon` link
  in `index.html`. Generated PNG icons from the seed logo via Pillow on every
  build. iOS "Add to Home Screen" now produces a fullscreen Headroom app.
- **Photo edit on upload** via `react-easy-crop` (~30KB gzipped, no peer deps).
  PhotoCapture flow now: pick → crop modal (free aspect, 90° rotate, zoom
  slider) → upload. Cropping happens client-side via canvas; backend pipeline is
  unchanged.

## [0.4.0] — 2026-05-03 — _Real Numbers_

Live eBay comparable-listings prices replace the heuristic resale guess.
Insurance-grade inventory report.

### Added
- **eBay Browse-API integration.** `services/ebay_service.py` does OAuth
  client-credentials → token cache → search by `brand + model + style`, returns
  mean / median / count of currently-listed comparable prices. Refreshes
  automatically when Claude finishes analysis (best-effort, never fails the
  upload). Per-hat refresh button on the detail page. New Hat columns:
  `ebay_avg_price`, `ebay_median_price`, `ebay_listing_count`,
  `ebay_search_url`, `ebay_checked_at`.
- **Settings UI for eBay creds** — admin-gated `app_id` + `cert_id` +
  `marketplace` (default `EBAY_US`), masked on read, env-var fallback.
- **Inventory Report** — `GET /api/admin/inventory-report` returns a
  self-contained HTML page with a print stylesheet (A4, page-break-inside
  avoid). Two-column totals tile + per-hat row with thumbnail, brand/model,
  condition, location, original retail, and best-available current value.
  Settings page button opens the report in a new tab; user uses browser Print →
  Save as PDF. Zero new heavy deps.
- **Hat detail Valuation card** now shows three tiles side-by-side: New Retail /
  eBay Median / Resale (manual), plus a refresh button and deep-link buttons.

### Notes
- The free Browse-API tier is 5,000 calls/day; with caching you'll be nowhere
  near it.
- Browse API surfaces *currently listed* items, not sold prices — asking prices
  skew higher than realized values. Marketplace Insights requires partner
  approval; deferred.

## [0.3.0] — 2026-05-03 — _Inventory Loop_

Hats in fast, hats tracked, hats out, all audited.

### Added
- **Activity log** — append-only `activity_log` table with `kind /
  entity_type / entity_id / summary / details(JSON)`. Hooks at every hat-service
  write path emit rows automatically. `/api/admin/activity-log` endpoint with
  filtering by `kind` and `entity_type`. Daily prune task (configurable
  retention via `HEADROOM_ACTIVITY_LOG_RETENTION_DAYS=90`). New "Recent Activity"
  card on the Settings page.
- **Sale / disposition tracking.** Five new Hat columns: `disposed_at`,
  `disposed_via` (sold/gifted/lost/trashed/trade), `disposed_price`,
  `disposed_to`, `disposed_notes`. Soft-delete only — undoable via
  `DELETE /api/hats/{id}/dispose`. Disposed hats free their case slot but remain
  in the DB. `GET /api/hats?status=` defaults to `active`; `disposed` and `all`
  available. Hat detail page gets a Disposition card with a modal form plus an
  "Undo — restore" action. Valuation page surfaces realized values.
- **Bulk photo import.** Multipart upload of up to 100 photos creates an
  `import_jobs` row + `import_job_items` per file, queues a single background
  asyncio worker that runs the existing pipeline one-at-a-time. Per-file status,
  hat-id link on completion, cancellation. Survives container restart (queued
  items re-enqueue at boot). New `/hats/import` page with drag-drop + per-file
  progress + defaults applied to every hat.

### Changed
- `_validate_capacity` skips disposed hats — sold/lost hats no longer count
  against case capacity.
- `_get_next_position` excludes disposed hats — the slot reopens.

### Tests: 81 → 93 (+12)
- `tests/test_disposition.py` — dispose + undispose + status filter +
  capacity-respecting-disposed.
- `tests/test_activity_log.py` — log emission, count endpoint, filters.
- `tests/test_import.py` — job creation, item structure, content-type rejection,
  cancellation. Worker disabled in conftest so jobs stay queued for assertion.

---

## [0.2.2] — 2026-05-02 — _author-question follow-ups_

Closes the action items from the ten reviewer questions in the archaeology
bundle. Six questions, six fixes.

### Added
- **Configurable Claude model in Settings UI.** New `app_settings.anthropic_model`
  row, `GET/PUT/DELETE /api/settings/model`, datalist of known model ids on the
  Settings page. Resolution: DB > env > built-in default.
- **In-app "Recent Analysis Errors" view** (`/api/admin/recent-errors`) listing
  the last 20 hats whose analysis failed, newest first, with thumbnail + error
  message + timestamp. Companion `/api/admin/recent-errors/count` powers a
  pulsing red badge on the Settings nav item — surfaces silent pipeline failures
  without anyone tailing `docker logs`.
- **One-click backup download** (`GET /api/admin/backup`) — streams a gzipped tar
  of `/data/{headroom.db, uploads/}` with an `attachment`
  content-disposition.
- **Scheduled rolling backups.** Background asyncio task writes a timestamped
  tar.gz to `/data/backups/` every 24 h (configurable:
  `HEADROOM_BACKUP_INTERVAL_HOURS`, `HEADROOM_BACKUP_RETENTION_DAYS=7`,
  `HEADROOM_BACKUP_ENABLED`). Canceled cleanly on lifespan exit. Initial snapshot
  at startup so a fresh deploy isn't one bad sector away from total loss.
- **"Unassigned / In a Case / All" quick-chips** on the Hats page, so
  case-orphaned hats are never invisible.
- **`/api/admin/*` route group** behind `require_admin`.

### Changed
- `verify_api_key` now takes a model parameter and reports it in the success
  message, so the test button validates the active model+key combo rather than
  just the key.
- Bumped version to 0.2.2.

### Removed
- Stray dev SQLite files — both were gitignored, just disk hygiene.

### Tests: 72 → 81 (+9)
- `tests/test_admin.py` — model setting CRUD + validation, recent-errors
  endpoints, backup gzip download, admin auth gate.

### Verified
- Live container: `/api/settings/model` GET → default → PUT → database → DELETE →
  default.
- Backup: GET returns valid gzip (~27 KB on a fresh DB), with the right
  Content-Disposition header, `file(1)` confirms gzip integrity.
- Container logs show logging configured, scheduler started, initial snapshot
  written.

---

## [0.2.1] — 2026-05-02 — _post-archaeology hardening_

A focused security + reliability pass driven by a full-repo archaeology run.
Closes the critical issues the audit surfaced and lifts the diagnosis from
"ready with conditions" toward "ready."

### Security
- **Path traversal in the SPA fallback handler closed.** `app.py:_safe_spa_path`
  now resolves the requested path and verifies it is inside `FRONTEND_DIST`
  before serving. Verified against the live container: traversal attempts now
  return the `index.html` fallback. (`tests/test_security.py`)
- **Optional admin-token guard** on `/api/settings/api-key` PUT/DELETE/test via
  `HEADROOM_ADMIN_TOKEN`. Unset → endpoints stay open (single-user-LAN default)
  with a startup warning. Set → `Authorization: Bearer <token>` required,
  constant-time compare.

### Reliability / performance
- **Dropped the upload concurrency footgun.** `background_removal.py` no longer
  wraps `asyncio.to_thread` in a process-global `asyncio.Lock`; inference now
  runs on whatever worker threads asyncio's executor provides. A small init lock
  still guards the one-shot ONNX session creation.
- **Pillow no longer blocks the event loop.** `utils/photo.process_image_async`
  wraps the existing sync function via `asyncio.to_thread`; the hat upload route
  uses it.
- **Real `/health/ready` endpoint** that probes the DB (`SELECT 1`), upload-dir
  writability, and reports API-key configuration. `docker-compose.yml` now points
  the container `HEALTHCHECK` at it.
- **Default logging is now visible.** `app.py` calls `logging.basicConfig` on
  startup if no root handlers are configured, so warnings actually reach
  `docker logs`. Level via `HEADROOM_LOG_LEVEL`.
- **Docker log rotation.** `docker-compose.yml` pins `max-size: 10m` and
  `max-file: 5` on the JSON log driver — no more silent SD-card fill from
  unbounded uvicorn access logs.
- **Function-local imports in `reanalyze_hat` removed.** Routes now have clean
  top-level imports.

### Tests
- **+8 tests** covering the gaps the archaeology surfaced (72 total, all green):
  - `tests/test_pipeline_e2e.py` — happy-path Claude analysis with
    structured-response stub, reanalyze, and error-path coverage.
  - `tests/test_security.py` — path-traversal regression + admin-token
    enforcement.
  - `tests/test_health.py` — readiness probe.

### Cleanup
- Removed unused `beautifulsoup4` dependency.
- Removed a dead duplicate branch in `utils/photo.py`.
- Removed a vestigial value from the `analysis_status` comment in
  `models/hat.py` (no code path ever wrote it).
- Clarified the `anthropic_model` default with an inline comment + pointer to the
  key-verification endpoint.

## [0.2.0] — 2026-05-02 — _"Outrun"_

The big one. Full UI rebuild + AI-powered hat identification.

### Added
- **Claude Vision analysis** for every uploaded hat photo. Single tool-use call
  returns brand, specific model name, model confidence, style descriptor, design
  notes, primary / secondary / tertiary / accent colors with name + hex + tier,
  and an estimated new retail price in USD. Prompt caching enabled on the system
  prompt.
- **Background removal** via [`rembg`](https://github.com/danielgatis/rembg) with
  ONNX runtime. Hat photos save as transparent PNGs and float on the synthwave
  canvas. Default model is `u2netp` (4.7 MB) for Pi-friendliness; swap via
  `HEADROOM_REMBG_MODEL`.
- **Hat record** now stores: `brand`, `model_name`, `model_confidence`,
  `style_descriptor`, `design_notes`, `estimated_new_price`,
  `estimated_new_price_source`, `resale_price`, `resale_price_source`,
  `resale_price_url`, `resale_checked_at`, `analysis_status`, `analysis_error`,
  `analyzed_at`. `HatColor` gets a `tier` column.
- **Melin Recap deep-linking**: hats Claude identifies as Melin get a link to the
  matching filter page for live resale comparables.
- **Settings page — Claude API key management.** Get / Set / Delete / Test
  connection endpoints; stored in DB (masked on read) with env-var fallback.
- **`POST /api/hats/{id}/reanalyze`** — re-run Claude on an existing photo
  without re-uploading.
- **AppSetting** key/value model + table for app-level configuration.
- **Dockerfile** (multi-stage, multi-arch amd64+arm64, runs as non-root
  `headroom` user, pre-caches rembg model) and **docker-compose.yml** for
  one-command Pi deployment.
- **CHANGELOG.md** (this file) and a real **`.gitignore`**.

### Changed
- **Total frontend rebuild** — dropped Bootstrap 5 entirely. Synthwave /
  retro-80s design system: near-black canvas, neon hot-pink + cyan accents,
  sunset gradients, perspective grid background (desktop), Audiowide / Orbitron /
  Inter / JetBrains Mono typography, glow effects on primary actions, animated
  carousel with swipe gestures, glassmorphic modals + lightbox. CSS bundle shrunk
  from ~250 KB (Bootstrap) to **29 KB**.
- **Mobile / iPad first.** All layouts start single-column and progressively
  enhance. Tap targets ≥ 44 px. Bottom nav is the primary nav on portrait
  devices; top nav only renders at `lg+`. `viewport-fit=cover` and safe-area
  padding for notched devices.
- **Photo upload pipeline** is now: upload → resize/HEIC convert → background
  removal → Claude Vision → persist. Each step degrades gracefully. The canonical
  photo is the transparent PNG when bg-removal succeeds, the JPEG otherwise.
- **Search** now indexes brand alongside style/condition/size/colors/room.
- **Hats listing + gallery cards** show brand + model when known.
- **Hat detail page** redesigned with discrete sections: Identification, Photo +
  Reanalyze, Valuation, Specs, Case, Color palette with tiered breakdown.
- **Edit Hat page** lets you override every Claude-derived field manually.
- **Database migrations** extended to add the new hat columns + `tier` on
  `hat_colors` + the new `app_settings` table. Existing DBs upgrade in place.

### Removed
- `colorthief` + `webcolors` dependencies (replaced by Claude Vision).
- `src/headroom/services/color_service.py`.
- Bootstrap CSS + JS imports from the frontend.

### Security
- Dockerfile runs as non-root user `headroom` (uid 1000).
- Inline-migration DDL is now fully static — no f-string interpolation into
  `text()` even for trusted column names.
- API keys are masked on read; only the prefix and last four characters are ever
  sent over the wire.

### Notes / known limitations
- The pipeline runs synchronously inside the upload request, so a hat upload
  with Claude + bg removal can take 5–15 s on a Pi. A future release may move
  this to a background queue.
- Melin Recap doesn't expose a stable JSON API and the listing page is
  client-rendered, so the resale_price field stays null and we surface a browse
  link instead of fabricating a number.

---

## [0.1.0] — 2026-02-22

Initial release. FastAPI + React SPA. Rooms / Cases / Hats domain. Local
ColorThief-based color detection. Bootstrap 5 navy/gold theme.
