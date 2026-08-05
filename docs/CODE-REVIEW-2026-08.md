# Code review — 2026-08-05

Two-axis review (`/code-review`) of the whole codebase: `a8c5c62` (initial
commit) → `v2.2.2`. **Standards** = conformance to `CLAUDE.md` + a Fowler smell
baseline. **Spec** = does the code do what the docs promise.

There is no issue tracker and no PRD in this repo (0 GitHub issues), so the Spec
axis was run against the project's own documented claims — README, CHANGELOG,
`docs/`, `CLAUDE.md`.

---

## Spec axis — all 4 fixed ✅

| # | Finding | Status |
|---|---|---|
| S1 | **`HEADROOM_REMBG_MODEL` documented as configurable but impossible to change.** `OPERATIONS.md` said "rebuild the image after changing it (the model bakes in via a build arg)", but the runtime stage hardcoded `u2netp` (`ARG` is stage-scoped, so the build arg was discarded), compose pinned `HEADROOM_REMBG_MODEL` in `environment:` (which beats image ENV), and compose passed no such build arg at all. Following the doc baked a ~170 MB model into the image that was never loaded. | **Fixed** — runtime re-declares `ARG REMBG_MODEL`; compose passes it as a build arg and no longer pins the env. `REMBG_MODEL=isnet-general-use docker compose up -d --build` now works as documented. |
| S2 | `/health/ready` payload in `OPERATIONS.md §3` is the *authenticated* view; anonymous callers get booleans only (no `path`, `source`, error text, or `import_worker`). Redaction was undocumented. | **Fixed** — redaction documented. |
| S3 | README env table omitted `HEADROOM_BACKUP_UPLOAD_TIMEOUT` and `HEADROOM_MDNS_INTERFACE`; OPERATIONS omitted the latter. | **Fixed** — both tables updated. |
| S4 | `CLAUDE.md` claimed "170 passing"; actual is 189. | **Fixed.** |

**Verified correct** (no action): off-site upload hook semantics, both documented
restore commands, all `/api/auth/*` guards, passkeys gated on `isSecureContext`
(so the plain-HTTP overlays genuinely hide the button), `MAX_FILES_PER_JOB = 100`,
and the fallback/pipeline status-pill table in USAGE §4.

---

## Standards axis

**Verdict: substantially conformant.** Zero breaches of the hard-edged
`CLAUDE.md` rules — no `utcnow()`, no f-strings in `text()`, `import_jobs`
registers before `hats`, Dockerfile non-root + `--frozen` only, `.d-lg-none`
correct, no hooks-after-early-return.

### Fixed ✅

| # | Finding | Fix |
|---|---|---|
| N1 | `routes/admin.py` scar tissue: dead `_ = Case` with a comment describing a mechanism it doesn't have; mid-file `# noqa: E402` imports; `select as _select` shadowing an existing import. | Removed; `catalog_service` hoisted into the top import block. |
| N2 | `routes/settings.py` dead branch — both arms of the logo `if` set the same `out_ext`/`save_fmt`. | Collapsed to one conversion guard. |
| N3 | **Speculative generality**: `settings_service._get_setting`/`_set_setting` aliases had zero callers. | Deleted; `CLAUDE.md` updated. |
| N4 | **Encapsulation leak**: `health.py` imported `auth._resolve_user`; `admin.py` called `ebay_service._get_creds` with a `# noqa: SLF001`. | Promoted both to public `resolve_user` / `get_creds` (matching the repo's own `_get_setting`→`get_setting` precedent). |
| N5 | **Data clump**: `routes/hats.py` unpacked `HatDispose` into five kwargs for `dispose_hat`. | `dispose_hat(db, hat_id, data)` takes the schema whole. |
| N6 | **Duplicated code**: the same `selectinload` option set appeared three times in `hat_service.py`. | One `_hat_loads()` helper. (`wear_logs` deliberately excluded — the model declares it `lazy="selectin"`.) |
| N7 | **Duplicated code**: `_case_to_read` / `_case_to_detail` restated 13 identical fields. | `_case_to_detail` derives from `_case_to_read`. |
| N8 | `CLAUDE.md` stale test count (same as S4). | Fixed. |

### Outstanding ⏳

Ordered by value. All are in working, tested code — none is a correctness bug.

1. **Duplicated API-key management** *(highest value)* — `routes/settings.py:96-146`
   vs `148-193`, plus `settings_service.py:47-84`. The Anthropic and
   Google-Vision key triples (GET status / PUT set / DELETE clear) are
   line-for-line twins; the source even says "Same shape as the Anthropic key
   routes". A third provider means a third copy. → factor into one
   parameterised router factory or a shared `_key_routes(name, getter, setter)`.
2. **`_hat_to_read` shotgun surgery** — `routes/hats.py:38-92` hand-copies ~45
   `hat.*` attributes. A new Hat column already requires edits to the model,
   `_HAT_COLUMN_DDL`, `HatRead`, this function, and `types/index.ts`
   (`tests/test_schema_consistency.py` exists because forgetting one is a known
   failure). → build `HatRead` from the ORM object with
   `model_config = ConfigDict(from_attributes=True)` + computed fields for the
   handful of derived ones (`wear_count`, `case_display_id`, `room_name`).
3. **`import_service` string dispatch** — `_bump_job_counter(job_id, field)`
   switches on `"done"/"errors"/"skipped"`, re-derived again in
   `_recover_on_boot`. Note the counter is `"errors"` while the item status is
   `"error"` — exactly the mismatch string dispatch invites. → an enum or a
   single shared mapping.
4. **`ebay_service.py:214-220` vs `229-236`** — the Browse API request block is
   duplicated for the initial call and the 401-retry. → one `_browse(...)` helper.
5. **`hat_analysis_pipeline.py:245-249` vs `290-294`** — duplicated apply block
   between the upload and reanalyze paths.
6. **Frontend duplication** (no test coverage — typecheck only):
   `AddHatPage.tsx:93-160` vs `EditHatPage.tsx:143-180+` (the whole hat form incl.
   `NewCaseModal`); `HatsPage.tsx:96-130` vs `SearchPage.tsx:54-80`
   (`availableColors`/`filteredData` memos + filter bar).
7. **Divergent change / large modules** — `routes/admin.py` (341 lines) changes
   for errors, backups, activity, reports, eBay creds, colorways, purchases and
   labels; `SettingsPage.tsx` (1084 lines) likewise, though it already extracts
   `AccountCard`/`ShareLinksCard`/`PurchasesCard` — the pattern just isn't
   finished. → split along those seams.
8. **Inconsistent schema placement** — `CLAUDE.md:46` puts Pydantic models in
   `schemas/`, but `routes/admin.py` defines `EbayCredsStatus`,
   `EbayCredsUpdate`, `ActivityRow`, `PurchaseImport` inline while
   `BackupInfo`/`RecentError` come from `schemas/`.

Items 6 and 7 are multi-hour refactors of working code with meaningful
regression risk; 1–5 are contained and test-covered.
