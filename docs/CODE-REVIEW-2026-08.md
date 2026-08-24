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

### Previously outstanding — all 8 now fixed ✅

Ordered as originally triaged. None was a correctness bug; all were in working,
tested code.

| # | Finding | Fix |
|---|---|---|
| 1 | **Duplicated API-key management** *(highest value)* — the Anthropic and Google-Vision route triples (GET status / PUT set / DELETE clear) were line-for-line twins, plus a get/set/clear trio per provider in the service. The source even said "Same shape as the Anthropic key routes". | One frozen `KeyProvider` dataclass per provider drives both layers: `get_key`/`set_key`/`clear_key` in the service, and `_mount_key_routes()` generating the three routes. A third provider is one dataclass entry + one line in the mount loop. The two named getters (`get_anthropic_key`, `get_google_vision_key`) stay as the seams the pipeline reads and the tests patch per-provider. |
| 2 | **`_hat_to_read` shotgun surgery** — hand-copied ~45 `hat.*` attributes and walked `hat.case.room` in the route layer. | The five derived values are now `@property` on the `Hat` model beside the existing `display_id`; `HatRead` is `from_attributes=True` and `_hat_to_read` is one `model_validate` call. `ColorTag` gained validators preserving the old `or ""` / `or "primary"` null tolerance. New test pins every derived field **and** the unassigned-hat null case — `room_id`/`room_name`/`case_type` had zero coverage before, and `room_id` is what the Hats page filters on. |
| 3 | **`import_service` string dispatch** — `_bump_job_counter` switched on counter names, and the counter is `"errors"` while the item status is `"error"`. | Takes the item status and maps through one `_JOB_COUNTER` dict that `_recover_on_boot` also recounts from. |
| 4 | **eBay Browse request duplicated** for the initial call and the 401 retry. | One `_browse()` helper — which found a *third* copy in `verify_creds` (differing only in timeout). |
| 5 | **`hat_analysis_pipeline`** duplicated resale-pointer apply block. | Extracted to `_apply_resale_pointer`. |
| 6 | **Frontend duplication** — the whole hat form across Add/Edit; the `availableColors`/`filteredData` memos + filter bar across Hats/Search. | `components/hats/HatFormFields.tsx` (`useHatFormOptions`, `useHatPhoto`, `PhotoCard`, `HatBasicsCard`) and `components/hats/HatFilters.tsx` (`useHatFilters`, `HatFilterBar`, `matchesHatFilters`, `collectGeneralColors`). Room stays out of the shared predicate on purpose: Hats matches `room_id` client-side, Search sends it to the API. The four pages went 1093 → 819 lines. |
| 7 | **Divergent change / large modules** — `routes/admin.py` (334 lines, 7 reasons to change); `SettingsPage.tsx` (1084 lines). | `routes/admin/` package of six single-concern modules, with prefix/tag/`require_admin` applied once in `__init__`. `SettingsPage.tsx` → 44-line composition root over 15 card modules in `components/settings/`. |
| 8 | **Inconsistent schema placement** — four Pydantic models declared inline in `routes/admin.py` while `BackupInfo`/`RecentError` came from `schemas/`. | All six now in `schemas/admin.py`, mirroring `routes/admin/`. |

**How the no-behavior-change claim was verified** (not just "tests pass"): the
full OpenAPI document was generated from `origin/main` and from HEAD and
diffed. **90 routes before, 90 after, identical**; every response schema
byte-identical. The only path-level differences are three `operationId`/`summary`
strings on the Anthropic key routes (now provider-qualified — `Delete Anthropic
Key` rather than `Delete Api Key`, which is more accurate given there are two
providers) and one added endpoint description. Backend tests 190/190;
frontend typecheck and production build clean.

One deliberate behavior change: `SettingsPage` used to hold a single spinner
over the whole page until the logo/key/model queries resolved. With per-card
state that would have flashed "No key configured" at someone who has one, so
those three cards now show their own inline "Loading…" instead.

---

## Follow-up: frontend test coverage

The gap called out above — "verified structurally, not behaviorally" — is now
closed. Vitest 4 + Testing Library 16 (jsdom), **27 tests** at the time of
writing (35 as of v2.3.0 — the react-router 8 upgrade added 8 routing tests),
wired into the existing CI frontend job (no new job, no new workflow trigger).

What they cover, chosen to be the things the refactor could plausibly have
broken and that nothing else catches:

- `matchesHatFilters` / `collectGeneralColors` — every predicate, the AND-ing,
  multi-swatch color matching, and an explicit assertion that **`room` is not
  applied** (if it ever were, Search would filter an already-server-filtered
  list against a field it doesn't carry).
- `HatFilterBar` — the six selects populate from the meta queries, state and
  active-count update, Clear resets shared filters *and* invokes
  `onClearExtras` (without which the Hats page's brand filter would silently
  stay applied).
- `HatBasicsCard` — each field reports under the right key, and the `__new__`
  sentinel opens the modal **without** being written as a case id (it would
  otherwise submit `case_id=NaN`).
- `SettingsPage` — the full 15-card list renders in the documented order.
  Dropping a card from a composition root is otherwise an invisible failure.
- `AnthropicKeyCard` — the loading guard never shows "No key configured" while
  loading, does once the query resolves empty, and drops a stale test result
  when the active model changes.

**Mutation-checked**, not just green: removing `<MdnsCard />` fails 2 tests;
disabling the loading guard fails the guard test.

Two real defects surfaced while writing them:

1. **No form control was associated with its label** — the `<label>` elements
   carry no `htmlFor` and don't wrap their inputs, so assistive tech announced
   the filter and hat-form selects as unlabelled. Fixed with `aria-label` on
   all eleven controls (six filters, four form selects, the date input).
2. **A test mock disagreed with the real payload** — `ApiKeyStatus` was mocked
   as `{configured: false}`, but pydantic emits fields with defaults, so the
   wire format is `{configured, source: null, masked: null}`. `tsc` caught it
   because test files sit inside `src/`.
