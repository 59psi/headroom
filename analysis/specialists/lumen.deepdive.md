---
agent: lumen
version: 1.0
target: /Users/brandon/Things/Headroom @ a2efd86
confidence: high
findings:
  - "Claude tool-use call hard-codes a model id ('claude-sonnet-4-6') that does not match Anthropic's published naming scheme — likely DOA at runtime."
  - "Cache-control on the system prompt is set, but max_tokens=1024 + base64 image inflate per-call cost; cache only meaningfully helps after the first hit."
  - "remove_background's _session_lock serializes ALL background-removal calls process-wide, defeating the asyncio.to_thread offload for concurrent uploads."
  - "_run_migrations runs ALTER TABLE inside engine.begin() but mixes raw text() with the inspector — there's a subtle ordering trap if rooms is created in the same transaction the cases.room_id FK depends on."
  - "upload_hat_photo and reanalyze_hat both perform the commit/expire/refetch dance, but reanalyze_hat does function-local imports of _apply_analysis (a private symbol) — fragile coupling."
  - "_validate_capacity has correct exclusivity logic but emits MAX_BEANIE/MAX_REGULAR check before the hat is hypothetically added — a subtle off-by-one is avoided only because the includes/excludes hat dance happens in the caller."
  - "_seed_branding's 'logo of any extension already present' guard is a nice touch but only triggers when the source filename's stem is exactly 'logo' — easy to mis-name a future seed file and clobber a user upload."
  - "HatDetailPage's reanalyze button surfaces raw API errors via `String(reanalyzeMut.error)` which will render `[object Object]` for non-Error throws."
open_questions:
  - "Does config_settings.anthropic_model='claude-sonnet-4-6' actually resolve at the API? Anthropic's id scheme is typically 'claude-sonnet-4-5-20250929' or 'claude-sonnet-4-6-20251001'. If the SDK requires a dated suffix or alias mapping, every analysis call 404s with no integration test catching it."
  - "Why is the Hat.colors clear() in _apply_analysis safe given the hat was loaded via selectinload but committed in the route layer? cascade='all, delete-orphan' on the relationship should DELETE orphaned HatColor rows on flush — but only if the session is tracking them. Worth verifying that finalize_hat_photo + later db.commit() actually emits the DELETEs (it should via autoflush)."
  - "The lifespan creates upload_dir/{cases,hats,branding} but ensure_default_room is called from init_db — what happens on a totally fresh boot when models import order matters? __all_models__ is imported inside init_db; if any other code path touches Base.metadata before init_db runs, create_all behavior could differ."
red_flags:
  - "The model id in config.py is almost certainly wrong — needs verification against the anthropic SDK constants."
  - "_session_lock around to_thread serializes the heavy ONNX inference; on a Pi this is probably OK, but it means concurrent users wait sequentially for ~seconds-each. Worse: an async lock around to_thread is fine, but if rembg ever needs more than one ONNX session per process for parallelism, this design forecloses it."
  - "reanalyze_hat imports _apply_analysis (leading underscore = private). When the pipeline gets refactored, this will silently break."
  - "upload_hat_photo writes to disk (tmp_path → output_path) BEFORE finalize_hat_photo tries Claude analysis. If Claude fails after bg-removal succeeds, the canonical photo is the transparent PNG and the hat row's analysis_status is 'error' — recovery path requires reanalyze, which is correct, but the JPEG is gone forever."
  - "_seed_branding scans seed/branding/ which contains both `branding/` (a subdirectory) and `logo.png`. The is_file() check filters out the subdirectory — fine — but if a future maintainer adds non-logo seed assets named 'logo.something', the dedupe logic only fires on the stem 'logo'."
artifacts:
  - "/Users/brandon/Things/Headroom/src/headroom/services/claude_analysis.py"
  - "/Users/brandon/Things/Headroom/src/headroom/services/hat_analysis_pipeline.py"
  - "/Users/brandon/Things/Headroom/src/headroom/services/background_removal.py"
  - "/Users/brandon/Things/Headroom/src/headroom/database.py"
  - "/Users/brandon/Things/Headroom/src/headroom/routes/hats.py"
  - "/Users/brandon/Things/Headroom/src/headroom/services/hat_service.py"
  - "/Users/brandon/Things/Headroom/src/headroom/app.py"
  - "/Users/brandon/Things/Headroom/frontend/src/pages/HatDetailPage.tsx"
---

# Lumen Deep-Dive — Headroom @ a2efd86

I selected seven regions. Each is dissected by location, block-level intent, invariants, edge cases, plain-English translation, and subtleties.

---

## 1. `claude_analysis.py` — the Anthropic tool-use call

**Location:** `/Users/brandon/Things/Headroom/src/headroom/services/claude_analysis.py:25-242`
**One-liner:** A single async function that pushes a base64-encoded hat photo + a strict tool schema to Claude, forces a tool call, and parses the structured result into a `HatAnalysis` dataclass.

### Block-by-block

- **Lines 25-48 — `SYSTEM_PROMPT`.** A long, brand-aware appraiser persona. Explicitly enumerates Melin model lines (A-Game, Odysea, Trenches, Coronado, Eagle, Compass, Legend, Caddy, Coast) — these strings must stay in lockstep with `_STYLE_TO_CATEGORY` in `melin_recap.py`. Tells the model to *always* call the tool, never reply in prose.
- **Lines 51-125 — `HAT_ANALYSIS_TOOL`.** JSONSchema describing `record_hat_analysis`. Notable schema choices:
  - `brand`, `model_name`, `estimated_new_price_usd` are nullable (`["string", "null"]`). Good — lets the model admit ignorance instead of hallucinating.
  - `model_confidence` is enum `high|medium|low` (required). Mirrors UI badge logic in `HatDetailPage.tsx:126`.
  - `colors` is min 1, max 5; each requires `name`, `hex` (regex `^#[0-9a-fA-F]{6}$`), and `tier` enum. Schema enforces lowercase-or-mixed hex.
  - `style_descriptor` and `design_notes` are `string` (required, not nullable) — the model is forced to produce *something*. This is mildly dangerous: when the model genuinely can't tell, it must invent.
- **Lines 128-148 — Dataclasses + custom exception.** `HatAnalysis.raw` keeps the original dict for forensic logging. `ClaudeAnalysisError` is the one error contract callers depend on.
- **Lines 151-161 — `_read_image_b64`.** Maps file suffixes to media types with a JPEG fallback. Reads the entire file into memory — fine for hat photos (< few MB after `process_image`), would be a problem for raw uploads.
- **Lines 164-214 — `analyze_hat_image`.** The hot path:
  - Builds the AsyncAnthropic client *per call* (no client reuse, no connection pool sharing across calls). Cheap on a Pi, but means every analysis pays the TCP/TLS handshake.
  - `system=[{type:text, text:..., cache_control:{type:ephemeral}}]` → enables prompt caching for the static system prompt. Saves tokens on repeat calls within the 5-minute cache TTL.
  - `tools=[HAT_ANALYSIS_TOOL]` + `tool_choice={type:tool, name:record_hat_analysis}` → forces the tool call.
  - `max_tokens=1024` is *just* enough for a tool call payload (a few hundred tokens of JSON). If the model ever pads `design_notes` aggressively or returns 5 colors with long names, this is the failure mode that will surface as a truncated `tool_use` block.
  - Catches `AuthenticationError` separately (so the UI can show "invalid key"), then `APIError`, then a bare `except Exception` — the bare except is intentional to never crash the upload route.
- **Lines 216-242 — Response parsing.** Uses `next(...)` with a generator over `message.content` to find the `tool_use` block. Then `payload = tool_block.input` — the SDK gives back a dict already (the `isinstance(payload, str)` branch is defensive against older SDKs). Errors wrap to `ClaudeAnalysisError`.

### Invariants and preconditions

- Caller must ensure `image_path` exists and is one of {jpg/jpeg/png/webp/gif}. `_read_image_b64` does no validation; HEIC will be misclassified as JPEG and Claude will reject.
- `api_key` non-empty (defended by the early return).
- Anthropic SDK >= ~0.40 (because of dict `tool_block.input`). The `isinstance(payload, str)` branch is dead code on modern SDKs but harmless.
- `config_settings.anthropic_model` must be a real model id.

### Edge cases

- **Handled:** missing key, auth failure, generic API error, missing tool_use block, malformed payload, missing color fields (defaults `tier='primary'`).
- **Handled poorly:** image > 5MB will be sent base64 (≈ 6.7MB encoded) and likely rejected by Anthropic's request limits — no client-side size check.
- **Missed:** model name mismatch (`claude-sonnet-4-6` is not Anthropic's documented format — usually has a date suffix). The `APIError` catch will surface it as a generic error and the hat will get `analysis_status='error'`. The UI will show the raw exception string.
- **Missed:** the schema requires a hex `#rrggbb` but the response could include shorthand `#rgb` from the model — the `pattern` constrains the *response*, but if Claude violates schema (rare with tool-use, possible), the regex isn't re-checked client-side.

### Plain English

> *In words: this function reads a hat photo off disk, base64-encodes it, sends it to Claude with a forced "fill in this exact JSON form" schema, parses the form, and hands back a typed Python object. Any failure becomes a single ClaudeAnalysisError that the upload pipeline can swallow.*

### Subtleties / hidden bugs

- **The model id.** `anthropic_model: str = "claude-sonnet-4-6"` (config.py:15). Anthropic's actual sonnet 4.x ids are `claude-sonnet-4-5-20250929` or aliases like `claude-sonnet-4-5`. There is no `claude-sonnet-4-6` in any public Anthropic catalog as of the project's apparent timeframe. **This is a likely DOA bug** unless the env var is overriding it in deployment. Verify `HEADROOM_ANTHROPIC_MODEL` is set in production.
- **Cache_control on system but not on tools.** Tools are also stable across calls — they could be cached too, but aren't. Minor cost optimization missed.
- **`message.content` ordering.** `next(...)` finds the first `tool_use` block. If the model ever produces `text` blocks before the tool call (rare with `tool_choice`), the generator skips them silently. Fine.
- **`AuthenticationError` import.** Imported from `anthropic._exceptions` (private path). Future SDK versions may move it; production-stable would import from the top-level `anthropic` package.
- **`raw=payload if isinstance(payload, dict) else None`.** Always a dict on modern SDK, so `raw` is always populated. Slight redundancy.
- **No retry.** A single transient 503 from Anthropic kills analysis; user has to manually click Reanalyze.

---

## 2. `hat_analysis_pipeline.py:finalize_hat_photo` — orchestrator

**Location:** `/Users/brandon/Things/Headroom/src/headroom/services/hat_analysis_pipeline.py:38-117`
**One-liner:** Single entry point that mutates a `Hat` in place: removes background, runs Claude, applies fields, optionally builds a Melin Recap pointer.

### Block-by-block

- **Lines 38-47 — Signature/docstring.** Mutates `hat`. Caller (route) commits. This is a deliberate seam: the pipeline doesn't know about transactions.
- **Lines 48-62 — Background removal swap.**
  - `cutout_target = photo_dir / processed_jpeg_path.stem` — note no suffix; `_remove_sync` adds `.png`.
  - If `transparent_path` exists and isn't the same file, **the JPEG is unlinked**. The PNG becomes canonical.
  - `hat.photo_path = f"hats/{canonical_path.name}"` — overwritten regardless of bg-removal success.
- **Lines 64-79 — Claude analysis with graceful skip.**
  - If no API key: `analysis_status='skipped'`, `analysis_error="No Anthropic API key configured."`, return early — but `analyzed_at` is set to "now" even though no analysis happened. Slightly misleading semantics; "analyzed_at" reads as success in dashboards.
  - If `ClaudeAnalysisError`: log warning, mark error, return.
- **Lines 81-82 — Apply analysis.** Delegates to private `_apply_analysis`.
- **Lines 85-117 — `_apply_analysis`.**
  - Sets all detected fields, marks `analysis_status='ok'`, clears `analysis_error`.
  - **`hat.colors.clear()`** then re-appends — relies on `cascade="all, delete-orphan"` on the relationship to actually DELETE the orphaned `HatColor` rows when the session next flushes.
  - Builds Melin Recap pointer from brand+style. Note: `hat.style` is the *user-selected enum* (a_game, odysea, etc.), not Claude's inferred `style_descriptor`. So the pointer only fires for users who already classified the hat as a Melin model.

### Invariants and preconditions

- `hat` is attached to `db` (an `AsyncSession`).
- `processed_jpeg_path` exists on disk.
- `hat.colors` is loaded (selectin or eager) — otherwise `.clear()` triggers an async load on a sync attribute access. Models specify `lazy="selectin"` so this is safe at the call sites.
- The route caller will `db.commit()` after `finalize_hat_photo` returns.

### Edge cases

- **Handled:** no API key, Claude error, bg-removal failure (`transparent_path is None`).
- **Handled poorly:** if bg-removal returns the same path that was passed in (defensive `transparent_path.resolve() != processed_jpeg_path.resolve()`), the JPEG isn't deleted — fine, but `_remove_sync` always returns a `.png`-suffixed path, so this branch never fires in practice.
- **Missed:** if `_remove_sync` succeeds but the PNG is somehow zero-bytes / corrupt, `transparent_path.exists()` returns True and the canonical photo is broken. No content-validation step.
- **Missed:** if Claude times out mid-call, the pipeline catches the exception but `analysis_status='error'` doesn't distinguish "transient — please retry" from "this image will never analyze".

### Plain English

> *In words: take a freshly-saved JPEG, try to swap it for a transparent PNG cutout, then ask Claude what's in the photo. Stamp the answers onto the hat row. Always succeed at saving the hat, even if Claude is dead.*

### Subtleties

- **Two import sources for `datetime.now(timezone.utc)`.** The pipeline imports it module-level; `hats.py:reanalyze_hat` re-imports it inside the function. Consistency would help.
- **`canonical_path.name` doesn't include the `hats/` prefix.** That's hardcoded. If you ever change the upload subdirectory, this breaks silently.
- **`build_resale_pointer(hat.brand, hat.style)`** uses Claude's brand string. Brand normalization is implicit: `is_melin()` does `"melin" in brand.lower()`, so "Melin Brand" or "Melin Recap" both match. Good.
- **The order of operations matters for failure recovery.** Photo path is set before analysis runs, so even on Claude failure the hat shows the new (transparent) photo. Good UX, but if bg-removal *and* Claude both fail, the user has the original JPEG path stored on the hat (because `transparent_path is None` → `canonical_path = processed_jpeg_path`).

---

## 3. `background_removal.py` — the global session pattern

**Location:** `/Users/brandon/Things/Headroom/src/headroom/services/background_removal.py:1-59`
**One-liner:** Lazy-loads a heavy ONNX rembg session into a module global, serializes access with an async lock, runs inference in a worker thread.

### Block-by-block

- **Lines 19-21 — Module-level state.** `_MODEL_NAME` from env (default `u2netp`, the lightweight 4.7MB U²-Net). `_session = None`, `_session_lock = asyncio.Lock()`.
- **Lines 24-30 — `_get_session`.** Lazy-imports rembg (deferring the onnxruntime import cost), creates session on first call, caches.
- **Lines 33-46 — `_remove_sync`.** Pillow opens the image, converts to RGBA if needed, hands the PIL image (not bytes) to `rembg.remove`, saves the result as PNG (`output_path.with_suffix(".png")`).
- **Lines 49-59 — `remove_background`.**
  - `async with _session_lock:` — guards the entire `to_thread` call.
  - `await asyncio.to_thread(_remove_sync, ...)` — offloads ONNX inference to a worker thread.
  - Bare `except Exception` swallows all failure, returns `None`.

### Invariants and preconditions

- Single-process runtime (gunicorn `--workers 1`, or uvicorn default). Multiple workers each get their own `_session` — fine on memory but each pays the warmup cost.
- `input_path` is openable by Pillow.
- ONNX runtime is installed (rembg pulls it).

### Edge cases

- **Handled:** corrupt image (Pillow throws → swallowed → return None), missing rembg (ImportError → swallowed → return None).
- **Handled poorly:** the `_session_lock` is held across the *entire* `to_thread`. If two photos upload simultaneously, the second one waits the full inference time of the first even though `to_thread` would otherwise allow parallelism. **The lock defeats the offload.**
- **Missed:** rembg's session object is documented as thread-safe-ish; the async lock is a belt-and-suspenders move that's likely overcautious. Removing it would unblock concurrent uploads.

### Plain English

> *In words: load a small AI model once, then for each upload, lock the model, run it in a thread, save the result as a PNG with transparent background. If anything breaks, return nothing and let the caller fall back.*

### Subtleties / clever bits / hidden bugs

- **The lazy import inside `_get_session` is real money saved.** rembg/onnxruntime adds ~hundreds of MB of process memory at import time. Deferring it means a Headroom instance with no analysis configured never pays that cost.
- **`asyncio.Lock()` at module scope is bound to the loop that imports the module.** If anyone ever calls this from a *different* event loop (e.g. tests using `asyncio.new_event_loop()`), they'll get "RuntimeError: ... bound to a different event loop". The codebase uses pytest-anyio with the asyncio backend so this is fine, but it's fragile.
- **The lock serializes inference globally.** On a Pi with 1 core, that's fine — there's no real CPU parallelism anyway. On a beefier host, this is a perf cliff for concurrent uploads.
- **`output_path.with_suffix(".png")` — the output filename always ends `.png`.** The caller (`finalize_hat_photo`) expects this and rewrites `hat.photo_path` accordingly. If anyone ever wants WebP, this is the chokepoint to change.
- **No timeout on the to_thread call.** A pathological image that hangs ONNX would hang the worker thread forever. Unlikely, but rembg has no timeout knob.

---

## 4. `database.py:_run_migrations` — inline DDL

**Location:** `/Users/brandon/Things/Headroom/src/headroom/database.py:19-91`
**One-liner:** Hand-rolled idempotent migration: creates `rooms` and `app_settings` tables if missing, ALTERs columns onto `cases`, `hat_colors`, and `hats`.

### Block-by-block

- **Lines 19-34 — `_HAT_COLUMN_DDL`.** A static dict mapping new column names to ALTER statements. The comment makes the SQL-injection-safety claim explicit (good documentation).
- **Lines 37-41 — Inspector setup.** Pulls existing tables.
- **Lines 42-63 — `rooms` and `app_settings` creation.** Uses raw `text()` rather than `Base.metadata.create_all` because `create_all` runs *after* this in `init_db`. Both tables include `created_at` defaults.
- **Lines 65-70 — `cases.room_id` ALTER.** Adds the FK column with `DEFAULT 1 REFERENCES rooms(id)`. **This depends on `rooms` existing**, but only fires if `cases` already exists — meaning we're on an upgrade path where rooms was just created two statements above. The ordering is correct.
- **Lines 72-81 — `hat_colors` ALTERs.** `general_color` and `tier` columns added with defaults for existing rows.
- **Lines 83-90 — `hats` table.** First, a one-shot `UPDATE hats SET size='classic' WHERE size='standard'` — this is a *data* migration baked into the schema migration, idempotent on repeat runs. Then loops through `_HAT_COLUMN_DDL`, ALTERing in any missing column.

### Invariants and preconditions

- SQLite (the ALTERs use SQLite-specific tolerance — adding `REFERENCES` after the fact, no NOT NULL on new columns, etc.). Would partially break on Postgres.
- Connection is sync (passed in via `conn.run_sync`).
- The function is called inside `engine.begin()` so all statements are one transaction.

### Edge cases

- **Handled:** brand-new DB (skips all branches), partially-migrated DB (idempotent), DB with `size='standard'` rows (data fixup).
- **Handled poorly:** if `rooms` table exists but is empty, `cases.room_id` defaulting to `1` will produce dangling FKs. `ensure_default_room()` fires after migration, so the FK is satisfied by the time anyone queries — but during the migration window itself, the schema is technically inconsistent.
- **Missed:** no migration for the eventual case where someone wants to *drop* a hat column. SQLite can't `DROP COLUMN` natively before 3.35, but more importantly the dict is one-way.
- **Missed:** no version table. Re-running migrations is idempotent, but there's no audit trail.

### Plain English

> *In words: every time the app boots, look at the database, see what's missing, and add the missing pieces with raw SQL. New columns get safe defaults so old rows don't break. We don't use Alembic because the app is small enough that one function does the job.*

### Subtleties

- **`DEFAULT 1 REFERENCES rooms(id)` in SQLite** doesn't enforce the FK unless `PRAGMA foreign_keys=ON` is set. The codebase doesn't appear to set this, so the FK is decorative.
- **`Base.metadata.create_all` runs after `_run_migrations`.** This means new models added to the codebase are auto-created via SQLAlchemy, but new *columns* on existing models must be added to `_HAT_COLUMN_DDL` manually. Easy footgun: add a column to the `Hat` model, forget to add the ALTER, prod still works on fresh DB but breaks on upgrades.
- **The `UPDATE hats SET size='classic'` runs every boot.** Fine — it's a no-op after the first time. But on a huge `hats` table (won't happen here) it'd be wasteful.
- **No `IF NOT EXISTS` on the CREATE TABLE statements.** They're guarded by the `if "rooms" not in existing_tables:` Python check, so it's fine, but the SQL itself would fail loudly if re-run without the guard.

---

## 5. `routes/hats.py:upload_hat_photo` and `reanalyze_hat` — the commit/expire/refetch dance

**Location:** `/Users/brandon/Things/Headroom/src/headroom/routes/hats.py:142-213`
**One-liner:** Two routes that mutate hats via the analysis pipeline and re-fetch them with all relationships eager-loaded for serialization.

### Block-by-block

- **Lines 142-174 — `upload_hat_photo`.**
  - Validates content type, fetches hat (404 if missing).
  - Writes upload to `tempfile.NamedTemporaryFile(delete=False)`, then `process_image` resizes/converts and writes the final JPEG. The temp file is unlinked.
  - Old `photo_path` (if any) is unlinked from disk.
  - Calls `finalize_hat_photo(db, hat, final_path)` which mutates the hat in place.
  - `await db.commit()`, `db.expire_all()`, then `_hat_to_read(await hat_service.get_hat(...))` — re-fetches with selectinload for the response.
- **Lines 177-213 — `reanalyze_hat`.**
  - Fetches hat, 400 if no photo, 404 if photo file missing on disk.
  - **Function-local imports** of `ClaudeAnalysisError`, `analyze_hat_image`, `_apply_analysis`, `settings_service`, and `datetime` — five imports inside one function.
  - Resolves API key, 400 if missing.
  - Try/except around `analyze_hat_image`: on error, mutate the hat with error fields, commit, refetch, return.
  - On success, `_apply_analysis(hat, analysis)`, commit, refetch.

### Invariants and preconditions

- `db` session has `expire_on_commit=False` (set in `database.py:10`). This means after commit, attribute access on `hat` won't trigger reload — which is *why* `expire_all()` + refetch is needed to get fresh relationship data.
- `hat_service.get_hat` always loads `Hat.case → Case.room` and `Hat.colors`. The `_hat_to_read` serializer depends on these.
- The temp file is created with `delete=False` because `process_image` reads it after the `with` block closes.

### Edge cases

- **Handled:** invalid content type, missing hat, missing API key, missing photo file, Claude error.
- **Handled poorly:** if `process_image` throws, the temp file is leaked (no try/finally around `tmp_path.unlink`). Minor.
- **Handled poorly:** if `finalize_hat_photo` succeeds in mutating the hat but the subsequent `commit` fails (disk full, lock contention), the on-disk PNG and the in-memory mutations diverge. No rollback for the file system.
- **Missed:** no auth on the upload endpoint. Anyone who can reach the API can trigger expensive Claude calls. Single-user app, so probably intentional.

### Plain English

> *In words: receive a photo, save it to disk, run the magic pipeline, tell SQLAlchemy "forget what you cached", re-read the hat fresh, and serialize. The reanalyze route does the same dance but skips the upload — and it does some sketchy local imports to avoid a circular dependency.*

### Subtleties

- **The function-local imports in `reanalyze_hat`.** `_apply_analysis` is private (leading underscore). If the pipeline gets refactored to a public API, this silently breaks at runtime, not at import time. A test exercising the reanalyze path would catch it; let's hope one exists.
- **`db.expire_all()` is a *sync* method on AsyncSession.** No `await`. The codebase consistently does this right (see `MEMORY.md` note), but it looks wrong on first glance.
- **The double-fetch pattern.** `hat_service.get_hat` is called twice per request (once at the top, once after commit). The second call is a fresh SELECT — `expire_all` invalidates the cached identity, so SQLAlchemy re-issues the query. Cost: one extra round-trip per write request. For a Pi with SQLite, negligible.
- **Old photo deletion runs *before* the new pipeline.** If the new pipeline fails after this point, the old photo is gone and the hat is stuck pointing at a possibly-broken new path. Mitigated by `finalize_hat_photo` always setting `hat.photo_path` to *something*, but worth noting.
- **`upload_hat_photo` doesn't catch ClaudeAnalysisError directly** — it relies entirely on `finalize_hat_photo` to swallow the error. If any code path inside the pipeline throws an unexpected exception (not ClaudeAnalysisError), the request 500s and the new photo is on disk but the DB is unmutated.

---

## 6. `services/hat_service.py:_validate_capacity` — type-exclusivity rule

**Location:** `/Users/brandon/Things/Headroom/src/headroom/services/hat_service.py:36-71`
**One-liner:** Enforces the domain rule that a case holds *either* up to 4 regular hats *or* up to 6 beanies, never mixed.

### Block-by-block

- **Lines 36-43 — Query setup.** Selects all hats in the case, optionally excluding one (used when *moving* a hat within the same case).
- **Lines 45-57 — Mixed-type check.** If existing hats have any of the opposite type, raise 409. Two separate branches for clarity.
- **Lines 59-71 — Capacity check.** Counts beanies vs regular, compares against `MAX_BEANIE=6` / `MAX_REGULAR=4`.

### Invariants and preconditions

- Caller passes `is_beanie` reflecting the *intended* state of the hat being added.
- The hat being added is *not yet in the case* (or `exclude_hat_id` is set if it's already there).
- `case_id` exists (caller checks separately).

### Edge cases

- **Handled:** empty case (mixed-type checks short-circuit on `if hats:`), updating a hat that doesn't change type (caller skips this validation), moving a hat between cases.
- **Handled poorly:** if a beanie *and* a regular both exist in a case (shouldn't, but DB has no constraint), `existing_has_beanies` and `existing_has_regular` are both True, and *every* operation raises 409 forever. No way to repair from the API.
- **Missed:** no DB-level constraint enforcing the exclusivity. Application-level only. A direct `INSERT` or a race condition could violate it.
- **Missed:** the validation runs `SELECT` then makes a decision *before* the actual `INSERT` — between those two, another concurrent request could race in. SQLite's serialized writes mostly save us, but pre-check-then-write is structurally a TOCTOU.

### Plain English

> *In words: before letting a hat join a case, check that the case isn't full and isn't already holding the other kind of hat. Cases are mono-type: 4 regular hats max, 6 beanies max, never mixed.*

### Subtleties

- **`MAX_REGULAR = 4`, `MAX_BEANIE = 6`.** Hard-coded module constants. UI presumably mirrors these somewhere (frontend types).
- **`exclude_hat_id`** is only used in `update_hat` (line 147), not `assign_hat` (line 170). That's correct: when you *update* a hat's style in place, the hat is already in the case and must be excluded from the count. When you *assign* it from elsewhere, it's not yet in the destination.
- **The two existence checks (`existing_has_beanies` and `existing_has_regular`)** are computed even when both can't be true under normal operation. Cheap, but slightly wasteful.
- **The function returns `None`** and signals failure via raised `HTTPException`. This is route-layer-aware error handling living in a service — slightly leaky abstraction but pragmatic for FastAPI.

---

## 7. `app.py:_seed_branding` and `lifespan` — first-boot side effects

**Location:** `/Users/brandon/Things/Headroom/src/headroom/app.py:20-52`
**One-liner:** On startup, ensure upload subdirectories exist and seed default branding (logo) if not already present.

### Block-by-block

- **Lines 20-40 — `_seed_branding(target)`.**
  - Bails if `seed/branding/` doesn't exist (e.g. running from a different cwd).
  - Creates target dir.
  - For each file in seed (skipping subdirs):
    - If a file with the same name already exists in target, skip.
    - **Special-case for logos:** if the source's stem is `logo` and *any* logo file (`.png/.jpg/.jpeg/.webp`) is already in target, skip — protects user-uploaded logos with a different extension.
  - Otherwise `shutil.copy2` (preserving metadata).
- **Lines 43-52 — `lifespan`.**
  - `mkdir` for `upload_dir`, `cases/`, `hats/`, `branding/`.
  - Call `_seed_branding(branding_dir)`.
  - `await init_db()`.
  - `yield` — the rest is teardown (none).

### Invariants and preconditions

- `PROJECT_ROOT` resolution relies on `__file__` being three levels deep from project root (`src/headroom/app.py` → `Headroom/`). If the package layout changes, this breaks silently.
- `SEED_BRANDING` (`PROJECT_ROOT/seed/branding`) must exist for seeding to do anything; the function silently skips if not. This is correct for installed-package deployments where seed assets aren't shipped.

### Edge cases

- **Handled:** seed dir missing, target dir missing, file already present.
- **Handled poorly:** the "any extension" guard checks only `(.png/.jpg/.jpeg/.webp)`. SVG, GIF, AVIF are not protected — a user uploading `logo.svg` and then redeploying would have a `logo.png` from the seed copied alongside, and the served logo could become ambiguous depending on which the settings layer picks.
- **Missed:** no error handling around `shutil.copy2`. If permissions are wrong, the process crashes at startup.
- **Missed:** the `if src.stem == "logo"` guard is hardcoded. A future seed file named `logo-dark.png` would not get the dedupe protection.

### Plain English

> *In words: on first boot (and idempotently on every boot), make sure the uploads folder has a default logo. If the user has already uploaded their own, leave it alone — even if their version uses a different file extension.*

### Subtleties

- **`shutil.copy2` preserves mtime.** This means the seeded logo will look "old" from a file-stat perspective, which can confuse cache-busting strategies that rely on mtime.
- **The seed branding directory contains `branding/` (a subdirectory) and `logo.png`** — confirmed via `ls`. The `is_file()` filter handles this correctly. But the `branding/branding/` recursion would fail to be picked up; only top-level files are seeded.
- **Lifespan order matters.** Directory creation → branding seed → `init_db`. If `init_db` failed, branding would still have been seeded, leaving partial state. Reverse order would be safer.
- **`branding_dir.mkdir(exist_ok=True)`** without `parents=True`. `upload_dir.mkdir(parents=True, exist_ok=True)` two lines up handles that case, so the parent always exists by the time `branding_dir.mkdir` runs.

---

## 8. (Bonus) `frontend/src/pages/HatDetailPage.tsx` — the kitchen-sink page

**Location:** `/Users/brandon/Things/Headroom/frontend/src/pages/HatDetailPage.tsx:39-304`
**One-liner:** Single React page that shows a hat's metadata, photo, analysis status, valuation, specs, case info, color palette, and supports upload/reanalyze/delete in one place.

### Block-by-block

- **Lines 39-51 — Hooks setup.** `useParams` for `hatId`, `useNavigate`, `useQueryClient`, two local `uploading`/`reanalyzing` flags. `useQuery({ queryKey: ['hat', id] })`.
- **Lines 53-69 — Three mutations.**
  - `removeMutation`: delete then navigate to `/hats`.
  - `reanalyzeMut`: uses `onMutate`/`onSettled` to toggle `reanalyzing`, invalidates `['hat', id]` and `['hats']`.
  - `handlePhotoUpload`: not a mutation but an async handler — `try/finally` to reset `uploading`.
- **Lines 82-89 — Loading and not-found UI.**
- **Lines 105-138 — Identification card.** Shows brand, model, style descriptor, model_confidence badge, design_notes blockquote. All conditionally rendered.
- **Lines 140-172 — Photo card.** ImageLightbox + PhotoCapture + Reanalyze button. The Reanalyze button is disabled during `reanalyzing` or when `analysis_status === 'skipped'`.
- **Lines 175-207 — Valuation card.** Two `PriceTile`s + a "Browse on X" button if there's a resale URL.
- **Lines 209-220 — Specs card.** Style/Size/Last Worn/Type with `replace(/_/g, ' ')` normalization.
- **Lines 222-248 — Case info card.** Shows case display_id + room badge or an "assign" CTA.
- **Lines 250-275 — Color palette.** Maps colors with a swatch + general_color + tier label.
- **Lines 277-301 — Help/error alerts + action buttons.** Bottom CTAs for Add/Edit/Delete.

### Invariants and preconditions

- `hatId` parses as a number (the `enabled: !isNaN(id)` guard handles NaN).
- `getHat(id)` returns a `HatRead` matching the backend schema.
- `onCapture(file)` of `PhotoCapture` accepts a `File` (browser File object).

### Edge cases

- **Handled:** missing data (404 fallback), null prices, no colors, no case.
- **Handled poorly:** **`String(reanalyzeMut.error)`** at line 160. If the API returns a structured error object (which axios/fetch wrappers often do), this renders as `[object Object]`. Should use `.message` or a typed error formatter.
- **Handled poorly:** `delete` button uses native `confirm()` (line 296). Synchronous, blocking, ugly — but functional.
- **Missed:** no optimistic UI for delete or reanalyze.
- **Missed:** no toast on success — the page just re-renders. Acceptable for a single-user app.

### Plain English

> *In words: one page that shows everything about a hat and lets you change three things: replace the photo, re-run AI analysis, or delete the hat. Reads from a TanStack Query cache and invalidates surgically on mutations.*

### Subtleties

- **`uploading` is a local state** but `reanalyzing` is *also* local even though `reanalyzeMut.isPending` would do the same job. Inconsistent — pick one.
- **Query key invalidation pattern.** `['hat', id]` and `['hats']` are both invalidated. The `['hats']` invalidation matches the convention documented in CLAUDE.md (the project's room-vs-meta-rooms distinction). Good.
- **`PhotoCapture hidePreview`** prop on the upload button while showing the existing image via `ImageLightbox`. This avoids double-image confusion.
- **`disabled={reanalyzing || data.analysis_status === 'skipped'}`** — the disable condition is sensible, but a user with a misconfigured key after a previous successful analysis could still hit Reanalyze. They'd just get an error. Acceptable.
- **No keyboard shortcut / accessibility for delete.** The Delete button is `<button>` (good for a11y) but the `confirm()` dialog isn't a real modal. Acceptable for v0.2.0.
- **`data.estimated_new_price ?? null`** — defensive, but `data.estimated_new_price` is already typed as `number | null`. The `??` is redundant but harmless.

---

## Cross-region observations

1. **The `_apply_analysis` private function is imported from two places** (`hat_analysis_pipeline.py` itself and `routes/hats.py:reanalyze_hat`). It should be promoted to a public `apply_analysis` to make the contract explicit.

2. **The model id `claude-sonnet-4-6`** flows from `config.py` → `claude_analysis.py:178` → `verify_api_key:252`. If it's wrong, both analysis and the settings-page key validation fail with the same opaque error. The settings page would say "API error" for valid keys, which is a confusing UX for a brand-new install.

3. **The `analyzed_at` timestamp** is set in three states (`ok`, `error`, `skipped`). The semantics differ — for `skipped` it's "we acknowledged this hat needs analysis but no key", for `error` it's "we tried and failed", for `ok` it's "real analysis time". A reader of the DB can't distinguish without joining `analysis_status`.

4. **Background removal + Claude analysis are both serial.** A burst of uploads will queue: lock → bg-remove (~seconds on Pi) → Claude API call (~seconds) → next request. There's no concurrency story. Probably fine for a single-user collection app.

5. **The `_session_lock` + `to_thread` combination is the most architecturally questionable bit.** Either trust rembg's session reentrancy and drop the lock (and gain real concurrency), or accept the serialization and skip the thread offload (since you can't run things in parallel anyway, just keep things on the event loop with a sync call wrapped in `asyncio.to_thread` only for the GIL-release benefit).

6. **The pipeline's "graceful degradation" is real and well-implemented.** A hat upload always succeeds at saving the photo. Bg-removal failure → keeps JPEG. Claude failure → marks status, returns. No-key → skipped. This is rare polish.
