---
agent: stratum
version: 1.0
target: /Users/brandon/Things/Headroom @ a2efd86
confidence: high
findings:
  - "Backend follows a clean 4-layer onion (routes -> services -> models -> DB) plus a parallel 'pipeline' layer (hat_analysis_pipeline) that orchestrates external-IO services (Anthropic SDK, rembg, Melin Recap link builder)."
  - "Composition root is `src/headroom/app.py:55-91` (create_app), with the DI seam being FastAPI `Depends(get_db)` from `database.py:118`."
  - "Routes layer is mostly disciplined but has three concrete cross-layer reaches: (1) `routes/hats.py:124-138` directly creates/deletes ORM `HatColor` rows and commits inside a route, (2) `routes/cases.py:125-127` mutates `case.photo_path` and commits in the route, (3) `routes/hats.py:188-213` inside `reanalyze_hat` reaches across the service boundary by importing the private `_apply_analysis` helper from the pipeline and calling `analyze_hat_image` directly while also writing `analysis_status`/`analysis_error` to the ORM model."
  - "Anthropic SDK is correctly walled off behind `services/claude_analysis.py`; routes never import `anthropic`. However, `routes/settings.py:13` imports `verify_api_key` from `claude_analysis`, which is a service-layer leak into a sibling concern (settings) but stays inside the services package."
  - "There is NO authentication, NO rate limiting, NO retry layer, NO caching beyond Anthropic prompt-cache, and NO structured observability (no middleware logger, no request_id, no metrics). Anthropic prompt caching is the only caching mechanism (`claude_analysis.py:184`)."
  - "Frontend layering is consistent: pages own queries+mutations (TanStack Query), components are presentational with one notable exception (`NewCaseModal.tsx:17-29`) that owns its own query+mutation lifecycle. API clients are thin fetch wrappers; types are co-located in `frontend/src/types/index.ts`."
  - "Query-key convention is consistent and matches CLAUDE.md: `['rooms']` returns full RoomRead[], `['meta','rooms']` returns dropdown options, `['settings','logo']`/`['settings','api-key']`, `['hats']`/`['hat', id]`, `['cases']`/`['case', displayId]`, `['meta', 'styles'|'sizes'|'conditions']`, `['search', term, exactColors, roomId]`. Mutations correctly invalidate both `['rooms']` AND `['meta','rooms']` together (e.g. `RoomsPage.tsx:43-44`)."
open_questions:
  - "Should `update_hat_colors` be moved into `hat_service` to remove the route-layer ORM access at `routes/hats.py:124-138`?"
  - "Should `reanalyze_hat` route delegate fully to a `hat_analysis_pipeline.reanalyze(hat)` function rather than re-implementing the orchestration inline (currently uses `_apply_analysis` private helper)?"
  - "Is the lack of any auth intentional for a single-user-on-Pi deployment? If exposed publicly, the `/api/settings/api-key` endpoint is unauthenticated and lets anyone read the masked key, set a new key, or delete it."
red_flags:
  - "`routes/hats.py:188-213` imports a private `_apply_analysis` function (leading underscore) from `hat_analysis_pipeline` — formal encapsulation violation."
  - "No middleware-level error handling, request logging, or observability — only ad-hoc `logger.warning` calls in two service files."
  - "No retry policy on Anthropic calls; a single transient `APIError` is wrapped as `ClaudeAnalysisError` and ends up persisted as `hat.analysis_status='error'` (`claude_analysis.py:209-214`, `hat_analysis_pipeline.py:74-79`). User must manually click 'reanalyze'."
  - "`config.py:7` has `database_url` defaulting to `sqlite+aiosqlite:///./headroom.db` (relative path) — only works when CWD is project root."
  - "`/api/settings/api-key` (`routes/settings.py:104,115`) accepts and deletes the Anthropic key with no auth — shipping anywhere outside localhost would be a credential-loss vector."
artifacts:
  - /Users/brandon/Things/Headroom/analysis/specialists/stratum.layers.md
---

# Stratum: Layer Cross-Sections

## 1. Layer Catalog

The codebase is a classic onion with one named "pipeline" lobe grafted onto the services layer for the AI flow. From the outside in:

### Backend layers

| # | Layer | Responsibility | Files |
|---|-------|----------------|-------|
| L0 | **Composition root / app shell** | Build FastAPI app, wire CORS, mount static, run lifespan (uploads dir, DB init, branding seed). | `src/headroom/app.py:55-94`, `src/headroom/app.py:43-52` (lifespan), `src/headroom/app.py:20-40` (`_seed_branding`) |
| L1 | **Routes (HTTP edge)** | Parse request, call service, shape ORM -> Pydantic via local `_x_to_read` mappers. | `src/headroom/routes/__init__.py`, `routes/health.py`, `routes/hats.py`, `routes/cases.py`, `routes/rooms.py`, `routes/search.py`, `routes/meta.py`, `routes/settings.py` |
| L1.5 | **Schemas (DTO / I-O contract)** | Pydantic request/response models, enums (StrEnum). | `src/headroom/schemas/hat.py`, `schemas/case.py`, `schemas/room.py`, `schemas/search.py`, `schemas/settings.py` |
| L2 | **Services (business logic)** | Capacity rules, sequence numbers, display IDs, color CRUD, default-room protection, key resolution priority. | `services/hat_service.py`, `services/case_service.py`, `services/room_service.py`, `services/search_service.py`, `services/settings_service.py` |
| L2′ | **Pipeline (parallel orchestration)** | Multi-step async orchestration of external IO for the AI hat-analysis flow. Composes L2′-IO and Anthropic SDK; mutates ORM models in place; defers commit to caller. | `services/hat_analysis_pipeline.py:38-117` |
| L2′-IO | **External-service adapters** | Single-purpose async adapters that hide third-party SDKs/HTTP. | `services/claude_analysis.py` (Anthropic SDK), `services/background_removal.py` (rembg+ONNX), `services/melin_recap.py` (URL builder) |
| L3 | **Models (ORM)** | SQLAlchemy 2.x typed `Mapped[...]` declarations, relationships, computed properties (`Hat.display_id`). | `models/hat.py`, `models/case.py`, `models/room.py`, `models/hat_color.py`, `models/app_setting.py`, `models/__init__.py` |
| L4 | **Persistence / infrastructure** | Async engine, session factory, `Base`, inline migrations (`_run_migrations`), default-room seeding, `get_db` dependency. | `src/headroom/database.py`, `src/headroom/config.py` (pydantic-settings), `src/headroom/utils/photo.py` (Pillow util shared between L1 routes) |

### Frontend layers

| # | Layer | Responsibility | Files |
|---|-------|----------------|-------|
| F0 | **App shell / router** | `QueryClientProvider`, `BrowserRouter`, route table; `staleTime: 30_000`, `retry: 1`. | `frontend/src/App.tsx:17-49`, `frontend/src/main.tsx` |
| F1 | **Pages** | Own data lifecycle: `useQuery` keys, `useMutation`, invalidation. | `frontend/src/pages/*.tsx` |
| F2 | **Components** | Presentational + a few smart components (`NewCaseModal`, `TopNav`). | `frontend/src/components/{layout,common,photos}/*.tsx` |
| F3 | **API clients** | Thin `fetch` wrappers returning typed Promises. | `frontend/src/api/{client,hats,cases,rooms,search,settings}.ts` |
| F4 | **Types (DTO mirror)** | Hand-authored TS interfaces mirroring backend Pydantic. | `frontend/src/types/index.ts` |
| F5 | **React-Query cache** | In-memory store keyed by tuple keys; the implicit "DB" of the SPA. | runtime (`@tanstack/react-query`) |

---

## 2. Layer Interaction Contract

### Backend boundaries

| Boundary | What crosses (down) | What crosses (up) | Sync/async | Where |
|----------|--------------------|-------------------|------------|-------|
| Client → L1 (Routes) | HTTP request, Pydantic-validated body, query params, `UploadFile` | `HatRead`, `CaseRead`, etc., or `HTTPException` | async | `routes/hats.py:73`, `routes/cases.py:67`, etc. |
| L1 → L2 (Services) | `AsyncSession` (via `Depends(get_db)`), Pydantic `*Create`/`*Update` DTOs, primitive IDs | SQLAlchemy ORM instances (`Hat`, `Case`, `Room`) with `selectinload`-eager relationships | async | `routes/hats.py:74`, `routes/cases.py:67`, etc. |
| L1 → L1.5 (Schemas) | ORM instance | `XRead` Pydantic via local `_x_to_read` mapper functions (e.g. `routes/hats.py:26`, `routes/cases.py:17`) | sync | `routes/hats.py:75`, `routes/cases.py:68` |
| L2 → L2′ (Pipeline) | `AsyncSession`, `Hat` ORM, processed JPEG `Path` | mutated `Hat` (in place), no commit | async | `routes/hats.py:171` calls `finalize_hat_photo` |
| L2′ → L2′-IO | API key (str), image `Path` | `HatAnalysis` dataclass or `ClaudeAnalysisError` | async | `hat_analysis_pipeline.py:73` → `claude_analysis.analyze_hat_image` |
| L2′ → L2 (siblings) | `AsyncSession` | resolved API key + source | async | `hat_analysis_pipeline.py:65` calls `settings_service.get_anthropic_key` |
| L2 → L3 (Models) | SQLAlchemy `select(...)` with `selectinload(...)` options | typed ORM rows | async | every service file |
| L3 → L4 (Persistence) | DDL via `Base.metadata.create_all`, raw `text(...)` migrations | row state | async via `engine.begin()` | `database.py:104-115` |
| L4 → L1 (DI) | `AsyncGenerator[AsyncSession, None]` | n/a | async | `database.py:118-120` `get_db` |

Notes:
- **Down direction = data + intent; up direction = ORM/DTO.** Services return ORM objects (not DTOs); the route is responsible for the ORM→DTO translation.
- **Commit ownership:** services own commits for the simple cases (e.g. `case_service.create_case` commits at `:44`). The pipeline explicitly defers commit (`hat_analysis_pipeline.py:8` docstring) and the route commits at `routes/hats.py:172`. This is asymmetric and a recurring source of expire/refresh dance — see `_reload_hat`/`_reload_case` helpers.
- **Background removal** runs `asyncio.to_thread` (`background_removal.py:56`) under an `asyncio.Lock` so the ONNX session isn't shared concurrently.

### Frontend boundaries

| Boundary | What crosses | Sync/async |
|----------|--------------|------------|
| F0 → F1 | route URL → page component | sync |
| F1 → F3 | `queryFn: () => listX()` callback | async via Promise |
| F1 → F5 | `queryKey: [...]` reads from cache, `qc.invalidateQueries(...)` writes | sync (with async backing fetch) |
| F3 → server | `fetch(BASE+path)` with optional `FormData` body | async |
| F2 → F1/F3 | callbacks via props, occasional direct `useQuery` (TopNav, NewCaseModal) | mixed |

The single `fetch` wrapper is `apiFetch` at `frontend/src/api/client.ts:3-17` — handles JSON vs. FormData, throws `Error` from `body.detail` on non-2xx, returns `undefined` for 204.

---

## 3. Layer Violations

Concrete leaks across layer boundaries, ranked by severity.

### Severity: medium

1. **Route directly mutates ORM relationships and commits.**
   File: `routes/hats.py:118-139` (`update_hat_colors`).
   - Imports `HatColor` ORM model directly (`routes/hats.py:10`).
   - Iterates `hat.colors` and calls `db.delete(color)` (`routes/hats.py:124-125`).
   - Constructs `HatColor(...)` rows and `db.add(...)` them (`routes/hats.py:127-135`).
   - Calls `await db.commit()` and `db.expire_all()` (`routes/hats.py:137-138`).
   - **Should be** in `hat_service` (e.g. `replace_colors(db, hat_id, colors)`).

2. **Route imports private pipeline helper (`_apply_analysis`).**
   File: `routes/hats.py:188-213` (`reanalyze_hat`).
   - `from headroom.services.hat_analysis_pipeline import _apply_analysis` (`routes/hats.py:192`) — private (leading underscore) symbol.
   - Route calls `analyze_hat_image` directly (`routes/hats.py:201`), catches `ClaudeAnalysisError`, sets `hat.analysis_status` / `hat.analysis_error` / `hat.analyzed_at` (`routes/hats.py:203-205`).
   - **Should be** a `hat_analysis_pipeline.reanalyze_hat(db, hat)` public function that mirrors `finalize_hat_photo`.

3. **Route mutates ORM and commits during photo upload.**
   File: `routes/cases.py:96-128` (`upload_case_photo`).
   - `case.photo_path = f"cases/{final_path.name}"` (`routes/cases.py:125`).
   - `await db.commit(); await db.refresh(case)` (`routes/cases.py:126-127`).
   - **Should be** in `case_service.set_photo_path(db, display_id, path)` for symmetry with `hat_service`.

### Severity: low

4. **Route owns I/O orchestration around the pipeline.**
   File: `routes/hats.py:142-174` (`upload_hat_photo`).
   - Tempfile + Pillow processing + old-photo deletion (`routes/hats.py:153-168`) is route-level orchestration that probably belongs in a `hat_photo_service`. The `case` photo upload is even worse because it doesn't go through the pipeline at all. Acceptable as-is for a small app, but it duplicates the prelude between hats and cases.

5. **Settings route imports a sibling service's `verify_api_key`.**
   File: `routes/settings.py:13` `from headroom.services.claude_analysis import verify_api_key`.
   - This is a service-layer call (legal) but `verify_api_key` is conceptually a settings-domain concern living in the Anthropic adapter. Tolerable; flagged for visibility.

### What is *not* violated (good)

- No service imports anything from `routes/`. Verified by reading all service files.
- No route imports `anthropic` directly; the SDK is fully encapsulated in `services/claude_analysis.py:17`.
- Models import only from `database.Base` and SQLAlchemy. They have no awareness of Pydantic, FastAPI, or Anthropic.
- Schemas are pure Pydantic with no SQLAlchemy/FastAPI imports.

---

## 4. Concerns Matrix

Rows = cross-cutting concerns. Cols = layers (Composition / Routes / Services / Pipeline / Models / DB).

| Concern | L0 Composition | L1 Routes | L2 Services | L2′ Pipeline | L3 Models | L4 DB / Infra |
|---|---|---|---|---|---|---|
| **Auth** | absent | absent | absent | absent | absent | absent |
| **Logging** | absent (no `logging.basicConfig`) | absent | `services/background_removal.py:17,58` (warning), `services/claude_analysis.py:22` (logger declared, never used) | `hat_analysis_pipeline.py:35,75` (warning) | absent | absent |
| **Error handling** | CORS only; no exception handler middleware | `HTTPException` raised on bad uploads (`routes/hats.py:149`, `routes/cases.py:103`, `routes/settings.py:45`); guards on `reanalyze` (`routes/hats.py:182,185,198`) | `HTTPException(404/409/400)` from services (e.g. `hat_service.py:50,64,81,135,169`, `room_service.py:35,59`) — services raising HTTPException is itself a mild leak of HTTP semantics into business logic | `ClaudeAnalysisError` caught and persisted as `hat.analysis_status='error'` (`hat_analysis_pipeline.py:74-79`) | absent | absent |
| **Caching** | absent (no Cache-Control headers) | absent | absent | Anthropic **prompt** cache via `cache_control: ephemeral` on system prompt (`claude_analysis.py:184`) | absent | absent — `staleTime: 30_000` lives in *frontend* (`App.tsx:20`) |
| **Transactions** | n/a | A few routes commit (`routes/hats.py:137,172,206,211`, `routes/cases.py:126`) | Most commits live here (`hat_service.py:95,153,160,178`, `case_service.py:44,80,91`, `room_service.py:43,53,72`, `settings_service.py:35`) | Pipeline explicitly does *not* commit; defers to route (`hat_analysis_pipeline.py:47`) | n/a | `expire_on_commit=False` (`database.py:10`) — relies on explicit `db.expire_all()` calls |
| **Retries** | absent | absent | absent | **absent** — single Anthropic call, no backoff/retry on `APIError` (`claude_analysis.py:211`); first failure becomes a persisted error state | absent | absent (frontend has `retry: 1` at `App.tsx:21`) |
| **Rate limiting** | absent | absent | absent | absent | absent | absent |
| **Validation** | n/a | Pydantic via `response_model` + body parsing; manual `validate_image_content_type` (`routes/hats.py:148`, `routes/cases.py:102`, `routes/settings.py:44`) | Domain rules: capacity (`hat_service.py:36-71`), default-room protection (`room_service.py:58-61`), default-style sequence (`case_service.py:25-31`) | JSON-Schema in tool definition (`claude_analysis.py:56-125`); SDK-side parse defence (`claude_analysis.py:222-242`) | Type-level constraints via `Mapped[...]` and `String(N)`/`ForeignKey` | inline migrations via `_run_migrations` (`database.py:37-90`) — no Alembic |
| **Observability** | absent (no metrics, no request id, no tracing) | absent | absent | logger.warning on hat-analysis failure | absent | absent |

`absent` ≠ ❌ broken — it's just an empty cell. For a single-user, locally hosted Pi app this is intentional minimalism, but worth documenting before any public deployment.

---

## 5. Frontend Layering

### Layer flow

```
F0 App / QueryClient
  └── F1 Pages (own queryKey + invalidation)
        ├── F2 Components (mostly presentational; a few smart)
        ├── F3 api/*.ts  ← apiFetch (api/client.ts:3-17)
        └── F5 React-Query cache (keyed by tuples)
```

### Query-key catalog (verified consistent)

| Key | Returns | queryFn | Used in |
|-----|---------|---------|---------|
| `['rooms']` | `RoomRead[]` (full objects with case_count) | `listRooms` from `api/rooms.ts:4` | `RoomsPage.tsx:38`, `NewCasePage.tsx:13`, `EditCasePage.tsx:20`, `HomePage.tsx:22`, `NewCaseModal.tsx:17` |
| `['meta','rooms']` | `{value,label}[]` (dropdown options) | `getRoomOptions` from `api/rooms.ts:31` | `HatsPage.tsx:75`, `CasesPage.tsx:46`, `SearchPage.tsx:27` |
| `['meta','styles' | 'sizes' | 'conditions']` | `MetaOption[]` | `getStyles`/`getSizes`/`getConditions` from `api/hats.ts:58-68` | `HatsPage.tsx:72-74`, `AddHatPage.tsx:25-27`, `EditHatPage.tsx:21-23`, `SearchPage.tsx:24-26` |
| `['hats']` | `HatRead[]` | `() => listHats()` | `HatsPage.tsx:71`, `HomePage.tsx:21` |
| `['hat', id]` | `HatRead` | `() => getHat(id)` | `HatDetailPage.tsx:48`, `EditHatPage.tsx:20` |
| `['cases']` | `CaseRead[]` | `listCases` | `CasesPage.tsx:45`, `HomePage.tsx:20`, `AddHatPage.tsx:28`, `EditHatPage.tsx:24` |
| `['case', displayId]` | `CaseDetail` | `() => getCase(displayId)` | `CaseDetailPage.tsx:16`, `EditCasePage.tsx:15` |
| `['search', term, exactColors, roomId]` | `SearchResult[]` | `searchHats(...)` | `SearchPage.tsx:32` |
| `['settings','logo']` | `{logo_path}` | `getLogo` | `SettingsPage.tsx:16`, `HomePage.tsx:23`, `TopNav.tsx:6` |
| `['settings','api-key']` | `ApiKeyStatus` | `getApiKeyStatus` | `SettingsPage.tsx:17`, `AddHatPage.tsx:29` |

**Convention is consistent.** The `[domain]` vs. `[domain, id]` split is uniform; the `['meta', x]` namespace is used for meta endpoints; the `['settings', x]` namespace for settings. The CLAUDE.md rule "room mutations must invalidate BOTH `['rooms']` AND `['meta','rooms']`" is honored everywhere room mutations live (`RoomsPage.tsx:43-44`, `:52-53`, `:62-63`).

### Layer-violation observations (frontend)

- `NewCaseModal.tsx:17-29` is a "smart" component — it owns its own `useQuery`, `useMutation`, and `qc.invalidateQueries`. This blurs F1↔F2 but is a common React pattern and arguably justified for a self-contained modal.
- `TopNav.tsx:6` likewise issues `useQuery({ queryKey: ['settings','logo'], queryFn: getLogo })` — pragmatic since the logo is a header concern.
- All other components are pure presentational (`PhotoCapture.tsx`, `ColorSwatch.tsx`, `ConditionBadge.tsx`, `EmptyState.tsx`, `ImageLightbox.tsx`, `LoadingSpinner.tsx`).
- API clients never reach into React or React-Query — verified by grepping `frontend/src/api/` for `useQuery`/`useMutation` (no hits).
- `BASE = ''` in `api/client.ts:1` relies on Vite's dev-server proxy / same-origin in prod. There's no environment-based URL switch; this is fine because the SPA is served from the same FastAPI process in production.

---

## Cross-section diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ Browser                                                             │
│  ┌──────────────┐  fetch  ┌───────────────────────────────────────┐ │
│  │ F1 Pages     │────────▶│ F3 api/*.ts (apiFetch wrapper)        │ │
│  │ + F5 Cache   │◀────────│                                       │ │
│  └──────────────┘  JSON   └─────────────────────┬─────────────────┘ │
└──────────────────────────────────────────────────│──────────────────┘
                                                   │ HTTP
┌──────────────────────────────────────────────────▼──────────────────┐
│ FastAPI process (uvicorn)                                           │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ L0 app.py: create_app, lifespan, CORS, static mounts            │ │
│ ├─────────────────────────────────────────────────────────────────┤ │
│ │ L1 routes/*.py  ── _x_to_read mapper ──▶ L1.5 schemas/*.py      │ │
│ │   │  Depends(get_db) ── AsyncSession                            │ │
│ │   ▼                                                             │ │
│ │ L2 services/*_service.py  (commits live here, mostly)           │ │
│ │   │                                                             │ │
│ │   ├──▶ L2′ services/hat_analysis_pipeline.py (orchestrator)     │ │
│ │   │      ├──▶ services/background_removal.py (rembg+ONNX)       │ │
│ │   │      ├──▶ services/claude_analysis.py ──▶ Anthropic API     │ │
│ │   │      └──▶ services/melin_recap.py (URL builder)             │ │
│ │   ▼                                                             │ │
│ │ L3 models/*.py (SQLAlchemy, lazy='selectin')                    │ │
│ │   ▼                                                             │ │
│ │ L4 database.py (engine, session, _run_migrations)               │ │
│ │   ▼                                                             │ │
│ │ aiosqlite ──▶ headroom.db                                       │ │
│ └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Quick-fix recommendations (not implemented)

1. Move color CRUD out of `routes/hats.py:118-139` into `hat_service.replace_colors`.
2. Add `hat_analysis_pipeline.reanalyze_hat(db, hat) -> Hat` and have `routes/hats.py:177` call it; drop the `_apply_analysis` import.
3. Move `case.photo_path = ...; commit; refresh` out of `routes/cases.py:125-127` into a `case_service.set_photo_path` helper.
4. Stop raising `HTTPException` from services — return domain exceptions and translate at the route boundary.
5. Add a single `loguru` / `structlog` logger config at L0 plus a request-id middleware; this is the cheapest observability win.
6. Wrap `analyze_hat_image` in a small retry (`tenacity`, two attempts on `APIError` excluding `AuthenticationError`).
