---
agent: prognosis
version: 1.0
target: /Users/brandon/Things/Headroom @ a2efd86
confidence: high
findings:
  - "The Anthropic model id `claude-sonnet-4-6` (config.py:15) is not a published Anthropic model; every Claude call will likely fail with a generic APIError unless `HEADROOM_ANTHROPIC_MODEL` is overridden in deployment. Tests cannot catch this because no test exercises the real Claude path."
  - "Concurrency capacity is effectively one upload at a time end-to-end. `background_removal._session_lock` (background_removal.py:21,55) wraps the asyncio.to_thread call, so two simultaneous uploads serialize on rembg even when both could run in parallel; this defeats the offload."
  - "Pillow `process_image` (utils/photo.py:14-37) and Anthropic base64 encoding (claude_analysis.py:151-161) both run inline on the event loop, blocking the loop for the duration of decode/resize/encode of every photo upload."
  - "The reanalyze route (routes/hats.py:188-194) imports a private `_apply_analysis` helper plus four other modules inside the function body — formal encapsulation violation and a silent-break trap when the pipeline is refactored."
  - "Inconsistent error contract: `POST /api/hats/{id}/photo` with no API key returns 200 + `analysis_status='skipped'`; `POST /api/hats/{id}/reanalyze` with no API key returns 400. Frontend handlers fork."
  - "Tests pass (64) but the Anthropic flow is never exercised end-to-end and rembg is monkey-patched to always return `None`, so the entire 'happy path' of the v0.2 pipeline (bg-removal succeeds + Claude succeeds + colors persisted + Melin pointer built) is never executed by CI. No frontend tests exist. No `_run_migrations` idempotency test exists."
  - "No auth, no rate limiting, no log rotation, no real `/health` check, no observability beyond two `logger.warning` lines. `analyzed_at` is set even on `skipped` (no analysis happened), which is misleading."
  - "Several smaller debt items confirmed by grep: `beautifulsoup4` declared in pyproject.toml line 18 but imported nowhere; `pending` analysis_status is documented in models/hat.py:43 but never written; utils/photo.py:25-28 has a dead branch (both arms `convert('RGB')`)."
open_questions:
  - "Is `HEADROOM_ANTHROPIC_MODEL` set in the actual Pi deployment? If yes, the bad default is dormant. If no, every analysis is currently failing in production and the operator hasn't noticed because the photo-save still 'succeeds'."
  - "Has the operator ever observed a successful end-to-end Claude analysis since v0.2.0 was deployed? The absence of a real-path test means this is an empirical question, not a code-review one."
  - "Is the rembg session actually unsafe under concurrent inference, or is `_session_lock` defensive over-engineering? If safe, dropping the lock unlocks real concurrency at no risk."
  - "Are SQLite writes serialized enough by aiosqlite that the long-held AsyncSession during photo upload (~5–30s holding a connection while bg-removal + network IO run) is harmless? On Pi/SQLite yes; if the DB ever moves, no."
red_flags:
  - "claude-sonnet-4-6 model id is almost certainly wrong and is not caught by any test."
  - "_session_lock around asyncio.to_thread is the architectural pessimum: pays the threading cost without gaining concurrency."
  - "Function-local imports of a private symbol inside reanalyze_hat — code-review fail, hides at runtime."
  - "Anthropic SDK private import: `from anthropic._exceptions import AuthenticationError` (claude_analysis.py:18) — leading underscore, will silently break on SDK upgrade."
  - "Disk-full on /data is invisible to the app: no metric, no log, no /healthz check; first symptom is a 500 to the user."
  - "No log rotation in docker-compose; the json-file driver can fill the SD card if anything ever gets chatty."
  - "API key endpoints (`/api/settings/api-key` GET/PUT/DELETE) are unauthenticated — anyone reachable on the network can read the masked key, overwrite it, or delete it. Single-user Pi assumes trusted network and nothing enforces that."
artifacts:
  - /Users/brandon/Things/Headroom/analysis/01-diagnosis.md
  - /Users/brandon/Things/Headroom/src/headroom/config.py
  - /Users/brandon/Things/Headroom/src/headroom/routes/hats.py
  - /Users/brandon/Things/Headroom/src/headroom/services/hat_analysis_pipeline.py
  - /Users/brandon/Things/Headroom/src/headroom/services/background_removal.py
  - /Users/brandon/Things/Headroom/src/headroom/services/claude_analysis.py
  - /Users/brandon/Things/Headroom/src/headroom/utils/photo.py
  - /Users/brandon/Things/Headroom/tests/conftest.py
  - /Users/brandon/Things/Headroom/pyproject.toml
---

# Prognosis — Diagnosis @ a2efd86

The Phase 1 specialists are unanimous on the shape of the patient: the codebase is clean, layered, idiomatic, and visually polished — but the v0.2.0 release added a Claude Vision + rembg pipeline that ships with one almost-certainly-broken default, a serialized concurrency model, no end-to-end tests of its own happy path, and zero observability for the failure modes most likely to surface in production. The pre-v0.2.0 CRUD core is healthy; the new pipeline is *plausible* but *unverified*.

---

## 1. Vital signs

| System | Status | One-line read |
|---|---|---|
| **Correctness** | Concerning | `anthropic_model='claude-sonnet-4-6'` is not a real Anthropic id and no test catches it; reanalyze imports a private symbol that will silently break on refactor; `pending` analysis status is documented but never written. |
| **Performance** | Concerning | `_session_lock` wrapping `asyncio.to_thread` defeats concurrency; Pillow + base64 encoding block the event loop inline; effective throughput is ~one upload at a time end-to-end. |
| **Scalability** | Concerning | Single-writer SQLite + serialized rembg + no background queue. Acceptable for a single-user Pi (the explicit target), would fail immediately under any concurrent load. |
| **Reliability** | Healthy-with-caveats | The graceful-degradation design is genuinely well-implemented (bg-removal failure → JPEG fallback, no key → `skipped`, Claude error → persisted error state, photo always saved). But: no retries on transient Anthropic 5xx, no rollback for filesystem writes if commit fails. |
| **Maintainability** | Healthy | Clean 4-layer onion, no circular imports, consistent SQLAlchemy idioms, documented query-key conventions. Real debt: 1278-line app.css, 213-line routes/hats.py with five intra-function imports, asymmetric commit ownership between routes/services/pipeline. |
| **Testability** | Concerning | 64 tests pass; ~960 LOC of test code. The v0.2.0 pipeline is the only meaningfully-untested code: zero E2E coverage of the Claude path, rembg always returns `None` in fixtures so the bg-removal happy path is never run, no migration-runner tests, zero frontend tests. |
| **Observability** | Critical | Two `logger.warning` calls in the entire backend. No metrics, no tracing, no log rotation, no real health check (`/health` is a tautology), no readiness probe, no usage of `logger.exception` (so traceback context is lost). On a Pi meant to run unattended, this is the highest-leverage gap after the model id. |
| **Security** | Concerning (defer to Sentinel) | No auth on any endpoint including `/api/settings/api-key`; AGPL exposed by default; uploaded photos run through Pillow with no magic-byte validation; outbound URL builder for Melin is parameterized by Claude-returned strings. Single-user-on-trusted-network is the assumption; nothing enforces it. |

Net: one **Critical** (observability), six **Concerning**, one **Healthy** (maintainability of the existing structure). The new pipeline is the source of every Concerning rating.

---

## 2. Capacity analysis

**Headline number**: ~1 upload concurrently, end-to-end. ~5–30 seconds per upload on a Pi (rembg ~seconds + Anthropic ~5–10s + Pillow + IO).

**Bottleneck order**, from first to break:

1. **Two concurrent uploads.** The second request waits for the first to release `_session_lock` (background_removal.py:55) before bg-removal even starts. While the first upload is in its bg-removal phase, the loop is *also* blocked on Pillow `process_image` for whatever request triggered it most recently. Net: a burst of N uploads finishes in ~N × (Pillow + rembg + Claude) wall time, not parallel.
2. **One large photo (>10MB).** Pillow opens it inline on the event loop. A 12MB HEIC at full resolution is several hundred ms of decode + resize on a Pi. During that window, every other request — gallery loads, settings reads, health probes — stalls. The base64 encoding for Anthropic happens *also* inline (claude_analysis.py:151-161) on the now-resized image (~1MB after `process_image`), adding more loop-blocking time. There is no client-side max-size check.
3. **A flood of `GET /api/hats`.** The route does `selectinload(Hat.case→Case.room, Hat.colors)` per row; for N hats this is O(N) row loads plus 2 IN-list selectins. SQLite handles this fine for hundreds of hats; for thousands, the query gets slow and uvicorn's single worker has no parallelism to spread the work. There is no pagination cap on `/api/hats` beyond `limit ≤ 100`, but the default `limit=50` is sane.
4. **Anthropic rate limits.** The free-tier rate limit on Sonnet 4.x is in the dozens of RPM. A user clicking Reanalyze repeatedly (no client-side debounce, no server-side rate limit) can easily exceed it; the visible failure is `analysis_status='error'` with the rate-limit message displayed verbatim in the UI.
5. **Disk fill on `/data`.** Photos accumulate forever. Deleted hats *do* get their photos unlinked (verified in upload route lines 166-168 — old photo deletion). But orphaned hats from `delete_case` (case_service unsets `case_id` but doesn't delete) keep their photos. Long-tail risk on a 32GB SD card with HEIC originals.

**Where it falls over first**: the user clicks "upload photo", then immediately clicks "upload photo" on a second hat. The second one is queued behind the first for the entire bg-removal step. Visible as "the spinner is taking forever for the second photo." This is the single most likely user-noticed failure mode and it's a 100% reproducible architectural property, not a transient.

---

## 3. Risk register (top 10)

Ranked by `probability × blast radius`.

| # | Risk | Probability | Blast radius | Current mitigation | Recommended mitigation |
|---|---|---|---|---|---|
| 1 | **`anthropic_model='claude-sonnet-4-6'` is not a real model id; every Claude call 404s.** | High (default value, no test) | Medium — every photo upload silently degrades to `analysis_status='error'` with a confusing error string in the UI; users still get the photo saved. | None in code. Operator must override `HEADROOM_ANTHROPIC_MODEL` in deployment env. | Change default to a verified id (`claude-sonnet-4-5`) **and** add a startup check that pings `verify_api_key` once, logs the result, and gates `/readyz`. |
| 2 | **`_session_lock` around `asyncio.to_thread` serializes ALL concurrent uploads.** | Certain (architectural property) | Medium — second upload waits ~5–10s; user perceives the app as broken. | None. | Drop the lock and trust rembg's session reentrancy (verify with one quick concurrent-call test), OR keep the lock and skip the to_thread offload (since you can't run things in parallel anyway). The current combo pays the cost of both. |
| 3 | **Pillow + base64 encoding block the event loop inline on every photo upload.** | Certain (architectural property) | Medium — every other request stalls during decode/resize/encode (sub-second on Pi for normal photos, multi-second for HEIC originals). | None. | Wrap `process_image` in `asyncio.to_thread`. Same for `_read_image_b64` for images >1MB. Cheap fix, immediate latency win. |
| 4 | **Reanalyze imports private `_apply_analysis` from pipeline, with five function-local imports.** | Medium (silent-break risk on refactor) | Low — one route stops working. | None — no test exercises the reanalyze success path. | Promote `_apply_analysis` to public `apply_analysis`. Add a `reanalyze_hat()` public function in the pipeline. Move imports to module top. Add a test that mocks `analyze_hat_image` and verifies the success branch. |
| 5 | **Inconsistent error contract: upload returns 200+skipped, reanalyze returns 400.** | Certain (current behavior) | Low — frontend has to fork its error handling. | None. | Pick one. Recommendation: reanalyze should return 200 with the same `analysis_status='skipped'` shape; frontend already handles that for upload. |
| 6 | **No retries on transient Anthropic 5xx.** | Medium (Anthropic has occasional blips) | Low — user clicks Reanalyze manually. | Manual reanalyze button. | Add `tenacity` retry on `APIError` (excluding `AuthenticationError`), 2 attempts with jittered backoff. |
| 7 | **Disk full on `/data` is invisible.** | Low–Medium (32GB SD card + HEIC photos accumulating) | High — app starts 500-ing on writes; SQLite write contention; no signal until users notice. | None. | `/readyz` checks `shutil.disk_usage(settings.upload_dir)`; configure docker-compose `logging.options.max-size: 10m, max-file: 3`; consider a periodic cleanup job for orphan files. |
| 8 | **No auth on `/api/settings/api-key`.** | Medium (depends on network exposure) | High if exposed — anyone on the network can read masked key, overwrite, or delete; can also rack up Anthropic charges by hitting `/test`. | "Don't expose to the internet" — assumption only. | At minimum, require a static `HEADROOM_ADMIN_TOKEN` for the settings router. Better: full auth (single-user is fine, just need a password). Defer details to Sentinel. |
| 9 | **No log rotation in docker-compose.** | Low (app is quiet today) | Medium — a 500 storm from a bug fills the SD card and wedges the Pi. | None. | Add `logging: { driver: json-file, options: { max-size: 10m, max-file: 3 } }` to the headroom service in docker-compose.yml. |
| 10 | **`AuthenticationError` imported from `anthropic._exceptions` (private path).** | Low (depends on SDK release cadence) | Low — auth errors stop being distinguishable from generic API errors; UI shows "Unexpected analysis failure". | Pin `anthropic>=0.40.0` (no upper bound). | Import from public `anthropic` namespace; pin upper bound on the SDK or run a CI smoke test. |

Honorable mentions that didn't make the top 10: the `pending` analysis_status documentation drift; the dead `if/elif` branch in `utils/photo.py:25-28`; the unused `beautifulsoup4` dep; the `String(error)` rendering pattern in HatDetailPage that will render `[object Object]` for non-Error throws.

---

## 4. Test coverage assessment

Roentgen counted ~960 LOC across 11 test files; pytest reports 64 passing.

**Tested well**:
- CRUD for cases, hats, rooms (test_cases.py 108 LOC, test_hats.py 141 LOC, test_rooms.py 78 LOC).
- Capacity rules (test_capacity.py 99 LOC) — the 4-regular vs. 6-beanie exclusivity is genuinely well-tested.
- Search semantics including multi-term AND, exact vs. general colors, room filter (test_search.py 227 LOC — largest test file, doing real work).
- Photo upload happy path *up to and excluding* the AI pipeline (test_photos.py 113 LOC) — relies on the autouse rembg stub and verifies `analysis_status='skipped'` since no key is configured.
- Settings API key surface (test_settings_api.py 63 LOC) including masking, env vs. DB precedence, the no-key-on-reanalyze 400 path.
- Melin Recap URL builder (test_melin_recap.py 40 LOC) — pure function tests.

**Not tested (the v0.2.0 hot stuff)**:
- **End-to-end Anthropic flow**: zero. No test mocks `analyze_hat_image` to return a `HatAnalysis` and verifies that `_apply_analysis` populates brand/model/colors/price + creates `HatColor` rows + invokes `build_resale_pointer`. The success path of the entire feature you released this morning is unexercised.
- **rembg happy path**: zero. The autouse fixture (conftest.py:21-36) monkeypatches `remove_background` to return `None` always — meaning the test suite exclusively exercises the *fallback* branch. The branch where rembg returns a transparent PNG, the JPEG gets unlinked, and `hat.photo_path` switches to `.png` is never executed.
- **Migration runner idempotency**: zero. `_run_migrations` (database.py:19-91) is critical infrastructure with hand-written DDL; there is no test that creates a v0.1-shaped DB on disk, runs `_run_migrations`, and verifies the resulting schema matches a v0.2-shaped DB created from `create_all`. A regression here corrupts every existing user's database.
- **Reanalyze success path**: zero. The unauthenticated 400 path is tested (test_settings_api.py:53-62); the success path is not. This is what would catch the `_apply_analysis` private-import breakage.
- **Frontend**: zero tests. No vitest, no jest, no playwright. The 1278-line app.css has no visual-regression tests; the 304-line HatDetailPage has no component test for the Reanalyze button's disabled-state logic.

**Untestable as written**:
- The `_session_lock` serialization behavior — would require a real concurrent-upload test against a real rembg session, which the CI deliberately avoids because of the model download cost.
- The bare `except Exception` in `background_removal.py:57` swallows every distinguishable failure mode into a single "return None"; you can't write a test that distinguishes "ONNX session failed to load" from "the input image was corrupt" because the production code threw away the information.

**Verdict on tests**: the suite is competent for what it covers (CRUD + search + URL building + capacity), but it provides essentially no signal about whether v0.2.0 actually works. "Tests pass" is consistent with "Claude returns 404 for every request and every hat is in `analysis_status='error'` state." That gap matters.

---

## 5. Technical debt ledger

Things that work but will hurt later. Cost-to-fix is ranked relative to a single afternoon's work.

| Debt | Cost to fix | Cost of leaving | Verdict |
|---|---|---|---|
| **`beautifulsoup4` declared in pyproject.toml line 18, imported nowhere** | 30 seconds (delete the line) | Pulls a transitive dep tree, slows install, false signal to readers about web-scraping. | Fix now. |
| **Dead branch in `utils/photo.py:25-28`** (`if mode in ('RGBA','P'): convert('RGB') elif mode != 'RGB': convert('RGB')`) | 1 minute (collapse to `if mode != 'RGB': convert('RGB')`) | Confuses readers; cargo-cult preservation makes future edits riskier. | Fix now. |
| **`pending` analysis_status documented in models/hat.py:43, never written anywhere** | 5 minutes (remove the comment, OR implement an async pipeline that uses it) | Suggests an unfinished migration to a background worker; readers will look for code that doesn't exist. | Fix the comment now. Defer the actual async pipeline. |
| **`_apply_analysis` private import dance in routes/hats.py:188-194** | 30 minutes (promote to public, add `pipeline.reanalyze_hat()`, lift imports to top) | Silent breakage on pipeline refactor; one of the most-likely-to-rot lines in the repo. | Fix soon — also unblocks adding a reanalyze success-path test. |
| **`String(reanalyzeMut.error)` in HatDetailPage.tsx:160** (and likely sibling pages) | 1 hour (typed error formatter helper) | Renders `[object Object]` for non-Error throws; debugging a real problem becomes harder. | Fix soon. |
| **No log rotation in docker-compose.yml** | 5 minutes (add `logging.options.max-size: 10m, max-file: 3`) | SD-card fill on a noisy day; Pi wedges. | Fix now. |
| **1278-line `app.css` includes a 100-line Bootstrap utility shim (lines 1176-1278)** | 1–2 days (split into modules; consider re-adopting a real utility framework or per-component CSS modules) | Every CSS change touches a god-file; no tooling can tree-shake. | Leave alone for now; the shim is intentional per Rorschach. |
| **Asymmetric commit ownership** (some commits in routes, most in services, pipeline explicitly defers) | 2–3 hours (move all commits into services; pipeline already correctly defers) | Confusing for new contributors; expire/refresh dance is required because of it. | Should-fix. |
| **No Alembic / version table for migrations** | 1 day (introduce Alembic, baseline current schema, retire `_run_migrations`) | The static `_HAT_COLUMN_DDL` dict is a footgun every time someone adds a column to a model. Already shipped. | Leave alone unless schema churn picks up. The current pattern is documented and works. |
| **Long-held AsyncSession during photo upload (~5–30s)** | 1 day (split upload into three transactions: save photo, queue analysis, persist analysis) | Wasted DB connection on SQLite; would be a real problem on Postgres. | Leave alone for SQLite; revisit if DB ever changes. |
| **Function-local `from datetime import datetime, timezone` in reanalyze_hat** | 30 seconds (lift to module top) | Cosmetic; rolled into the larger reanalyze refactor. | Fix as part of #4 above. |
| **CSS `hr-` prefix discipline is religious but not enforced** | n/a | None — discipline holds today. | Leave alone. |

Total: there's about 1 day of high-value cleanup (items marked Fix now / Fix soon) plus 2–3 days of structural improvements that are nice-to-have. None of it is shipping-blocking; all of it is cheaper to do now than in 6 months when context is gone.

---

## 6. Prescription

### Must-fix before next deploy

1. **Verify and correct `anthropic_model`.** Either the deployment env overrides `HEADROOM_ANTHROPIC_MODEL` to a real id, or the default in `config.py:15` is wrong and every Claude call is failing. Check the running Pi; if the latter, change the default to `claude-sonnet-4-5` (or whatever the operator actually uses) and add a startup readiness check that calls `verify_api_key` once and logs the outcome.
2. **Add a real E2E test of the Anthropic happy path.** Mock `analyze_hat_image` at the conftest level (alongside the existing rembg stub) so it returns a `HatAnalysis` dataclass; assert that an upload populates brand/model/colors/price/Melin pointer and writes `analysis_status='ok'`. This single test would have caught both the model-id bug (if structured to verify the call args) and any future `_apply_analysis` private-import breakage.
3. **Configure docker-compose log rotation.** Five-minute change; eliminates the SD-card-fill failure mode.
4. **Remove the dead `beautifulsoup4` declaration and the dead `if/elif` branch in photo.py.** Cosmetic but free.

### Should-fix soon

5. **Promote `_apply_analysis` to public; add `pipeline.reanalyze_hat()` so the route is a one-liner.** Lift the function-local imports to module top. Adds clarity, removes a refactor-trap.
6. **Drop `_session_lock` from `background_removal.remove_background`** *if* a quick concurrent-call experiment confirms rembg sessions are reentrant. Otherwise, drop the to_thread offload (no benefit in serial mode). Pick one — the current combo is the worst of both.
7. **Wrap `process_image` in `asyncio.to_thread`.** One-liner change in `routes/hats.py`, `routes/cases.py`, `routes/settings.py:upload_logo` — frees the event loop during photo decode.
8. **Make the upload vs. reanalyze error contract consistent.** Recommendation: reanalyze returns 200 with `analysis_status='skipped'` on no-key, matching upload. Frontend simplifies.
9. **Add minimum-viable observability.** Per Auscultator's `minimum_viable_instrumentation` block: `logging.basicConfig(...)`, INFO logs on upload + analysis with `hat_id` + duration + token usage, `logger.exception` instead of bare except. This is one short PR and unlocks every operational improvement that follows.
10. **Replace the trivial `/health` with a real `/readyz`** that checks DB reachability + `/data` write + free disk + rembg session loadable. Wire docker-compose `healthcheck:` to it.
11. **Add a test for `_run_migrations` idempotency.** Create a v0.1-shaped DB on disk, run init, assert schema matches v0.2-from-scratch.
12. **Add at minimum a static-token check on `/api/settings/api-key`.** Defer real auth design to Sentinel, but the current state where any LAN device can rotate the operator's API key is not OK even for a "trusted home network."

### Nice-to-have

13. Add `tenacity`-based retry on `APIError` in `analyze_hat_image` (excluding `AuthenticationError`).
14. Stop importing `AuthenticationError` from the SDK's private namespace.
15. Add a typed error-formatter helper in the frontend; replace `String(error)` calls.
16. Consider splitting `app.css` into per-page modules; remove the Bootstrap utility shim if you're willing to touch JSX class names.
17. Add a periodic orphaned-photo cleanup job (hats deleted directly should already be cleaned; orphans from `delete_case` are not).
18. Frontend tests — at minimum a vitest setup with one test per page that asserts it renders without crashing and one test for the HatDetailPage Reanalyze disabled-state logic.

### Leave alone

- The 4-layer onion + selectinload + `_reload_X` patterns. They work, they're documented, the team has scar tissue around the SQLAlchemy async gotchas and the workarounds are correct.
- `_run_migrations` as a homegrown alternative to Alembic. Adequate for current schema churn; documented in CLAUDE.md.
- Single-process uvicorn, single-writer SQLite. Correct for the deployment target.
- The synthwave CSS aesthetic. Don't touch the visual identity; it's the most carefully-shaped artifact in the repo per Rorschach.
- The pre-v0.2.0 services that raise HTTPException directly. Inconsistent with v0.2.0 patterns but not worth refactoring.

---

## 7. Overall diagnosis

**Ready-with-conditions.** The pre-v0.2.0 core (rooms/cases/hats/search/CRUD) is healthy production-quality code with good test coverage and clean layering. The v0.2.0 layer added on top is *plausibly* correct but *empirically* unverified: the most likely-bad line in the codebase (`anthropic_model='claude-sonnet-4-6'`) is exactly the one that no test exercises. Until that is verified against a live Anthropic call — and ideally backstopped by an E2E test — the headline feature of v0.2.0 should be considered "shipping but unconfirmed working." The rest of v0.2.0's surface (rembg pipeline, settings UI, Docker packaging, branding seed, CSS rebuild) is in good shape; the observability gap is real but acceptable for an unattended single-user Pi *if and only if* the operator is willing to babysit. The five Must-fix items above are a half-day of work and would move the rating from "ready-with-conditions" to "ready." Without them, the next time something breaks — a revoked Anthropic key, a corrupt rembg model, a full SD card, an Anthropic model deprecation — the operator finds out by trying to use the app and noticing it feels weird. That's a survivable failure mode for a hobby tracker, but it's not the bar a thoughtful release deserves.
