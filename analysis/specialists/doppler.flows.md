---
agent: doppler
version: 1.0
target: /Users/brandon/Things/Headroom @ a2efd86
confidence: high
findings:
  - "Hat photo upload is a 5-stage pipeline (validate -> tempfile -> Pillow JPEG -> rembg PNG -> Claude Vision -> Melin pointer) where each stage degrades independently; no stage failing rolls back the upload itself."
  - "Pipeline degradation order: missing API key -> analysis_status='skipped'; rembg failure -> falls back to JPEG silently; Claude failure -> analysis_status='error' but photo still saved."
  - "Only one piece of true concurrency: rembg runs in asyncio.to_thread() (background_removal.py:56) guarded by an asyncio.Lock — so even on a multi-core box, only ONE background-removal can run at a time across the whole process."
  - "process_image (Pillow resize) and base64 encoding for Claude both run inline on the event loop without to_thread — these block the loop on every photo upload."
  - "Reanalyze (POST /api/hats/{id}/reanalyze) skips background removal entirely — uses the existing canonical photo path on disk."
  - "API key resolution is DB-first then env (settings_service.py:38-48); UI-stored key beats HEADROOM_ANTHROPIC_API_KEY."
  - "case_service.delete_case unassigns hats by setting case_id=None / position_in_case=None then deletes — no FK ON DELETE cascade is relied upon."
  - "Lifespan does work in this order: mkdir uploads/{cases,hats,branding} -> _seed_branding (idempotent) -> init_db (raw-SQL migrations -> create_all -> ensure_default_room raw insert)."
  - "analysis_status state machine is simple but underspecified: model docstring says 'pending/ok/error/skipped' (hat.py:43) yet 'pending' is never assigned anywhere in code."
  - "Search is multi-term AND with each term checked across {style, condition, size, color (general OR exact based on flag), room name} — implemented as N chained WHERE clauses, one per term (search_service.py:41-53)."
open_questions:
  - "Is rembg session truly safe to use concurrently? The asyncio.Lock suggests not; this is a hard serialization bottleneck for image throughput."
  - "Why does process_image (Pillow) NOT use to_thread when remove_background does? Both are CPU-bound and block the loop."
  - "When rembg returns a PNG path, the JPEG is unlinked. If Claude analysis then crashes mid-call, the hat row still has photo_path set to the PNG — but if remove_background returned None, photo_path points to the JPEG. The fallback is silent, so observability of degradation is limited to log warnings."
  - "Anthropic 'claude-sonnet-4-6' (config.py:15) — is this a typo for sonnet-4.5 or a forward-dated model id? Worth flagging to Sentinel."
  - "delete_case unassigns hats but does NOT clean up orphan hats from the gallery — they become case_id=NULL hats. Is this intentional (drawer of unassigned hats) or a leak?"
red_flags:
  - "background_removal._session is global mutable state behind a module-level lock. First-request-on-cold-start does the rembg model load (4.7MB ONNX) under the lock — that request will be slow and ALL other uploads queue behind it."
  - "process_image runs Pillow synchronously on the event loop. A large HEIC at 1200px will block all other requests during decode+resize."
  - "Claude analysis reads the entire image into memory then b64-encodes it inline (claude_analysis.py:152, 161) on the event loop. For a 1200x1200 PNG with alpha this is non-trivial and blocking."
  - "_seed_branding runs synchronously in the lifespan (app.py:50) — fine on first boot, but it iterates SEED_BRANDING and copies files using shutil.copy2 inside the async lifespan with no to_thread. Negligible in practice but pattern-inconsistent with rembg."
  - "settings.py upload_logo also does Pillow work inline on the event loop (settings.py:60-75)."
  - "search_service builds a SELECT with N subqueries via Hat.id.in_(select(...)) — for many terms this becomes correlated and slow on SQLite without indexes on color_name/general_color."
  - "No request-level transaction isolation: the upload route does Pillow work, file IO, network IO, and DB writes all under a single AsyncSession that stays open the whole pipeline (~5-30s)."
artifacts:
  - /Users/brandon/Things/Headroom/analysis/specialists/doppler.flows.md
---

# Doppler — Runtime Flow Analysis

Target: `/Users/brandon/Things/Headroom` @ commit `a2efd86`. Stack: FastAPI + SQLAlchemy async + aiosqlite + Anthropic SDK + rembg + Pillow.

## 1. Hat Photo Upload — `POST /api/hats/{id}/photo`

**Anchor**: `src/headroom/routes/hats.py:142-174` -> `src/headroom/services/hat_analysis_pipeline.py:38-82` -> `src/headroom/services/background_removal.py:49-59` -> `src/headroom/services/claude_analysis.py:164-242` -> `src/headroom/services/melin_recap.py:47-60`.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Route as routes/hats.py:upload_hat_photo
    participant Photo as utils/photo.py:process_image
    participant Pipe as hat_analysis_pipeline.finalize_hat_photo
    participant Bg as background_removal.remove_background
    participant Set as settings_service.get_anthropic_key
    participant Claude as claude_analysis.analyze_hat_image
    participant Melin as melin_recap.build_resale_pointer
    participant DB as AsyncSession

    Client->>Route: POST multipart photo
    Route->>Route: validate_image_content_type (photo.py:40)
    alt invalid
        Route-->>Client: 400 Invalid image type
    end
    Route->>DB: hat_service.get_hat(id)
    alt not found
        Route-->>Client: 404 Hat not found
    end
    Route->>Route: tempfile.NamedTemporaryFile + shutil.copyfileobj
    Route->>Photo: process_image(tmp, output)
    Note over Photo: Pillow open -> RGB convert -><br/>thumbnail(1200,1200) -> JPEG q=85<br/>BLOCKS event loop
    Photo-->>Route: final_path (.jpg)
    Route->>Route: tmp_path.unlink()
    opt hat had old photo
        Route->>Route: unlink(old_path)
    end
    Route->>Pipe: finalize_hat_photo(db, hat, final_path)

    Pipe->>Bg: remove_background(jpeg, target)
    Note over Bg: asyncio.to_thread(_remove_sync)<br/>guarded by module asyncio.Lock<br/>lazy rembg session init (cold-start tax)
    alt rembg raises
        Bg-->>Pipe: None (logger.warning)
        Note over Pipe: canonical_path = jpeg (fallback)
    else success
        Bg-->>Pipe: transparent PNG path
        Pipe->>Pipe: unlink original JPEG
        Note over Pipe: canonical_path = png
    end
    Pipe->>Pipe: hat.photo_path = "hats/{name}"

    Pipe->>Set: get_anthropic_key(db)
    Set->>DB: SELECT app_settings WHERE key='anthropic_api_key'
    alt no key (DB or env)
        Set-->>Pipe: (None, None)
        Note over Pipe: status='skipped', error='No Anthropic API key configured.'
        Pipe-->>Route: hat (mutated)
    else key found
        Set-->>Pipe: (key, source)
    end

    Pipe->>Claude: analyze_hat_image(canonical_path, key)
    Note over Claude: read_bytes -> b64encode (BLOCKS loop)<br/>AsyncAnthropic.messages.create<br/>tools=[record_hat_analysis], tool_choice forced<br/>system prompt cache_control=ephemeral
    alt AuthenticationError
        Claude-->>Pipe: raise ClaudeAnalysisError("Invalid Anthropic API key")
    else APIError / unexpected
        Claude-->>Pipe: raise ClaudeAnalysisError(...)
    else no tool_use block in response
        Claude-->>Pipe: raise ClaudeAnalysisError("Claude did not return a tool_use block")
    else parse error
        Claude-->>Pipe: raise ClaudeAnalysisError("Could not parse Claude response")
    else success
        Claude-->>Pipe: HatAnalysis(brand,model,colors,price,...)
    end

    alt ClaudeAnalysisError caught
        Pipe->>Pipe: status='error', analysis_error=str(exc), analyzed_at=now
        Pipe-->>Route: hat
    else ok
        Pipe->>Pipe: _apply_analysis(hat, analysis)
        Note over Pipe: brand/model/notes/price assigned<br/>colors.clear() + new HatColor rows<br/>status='ok', analyzed_at=now
        Pipe->>Melin: build_resale_pointer(brand, style)
        alt brand contains 'melin'
            Melin-->>Pipe: {resale_price=None, source='Melin Recap', url=deeplink}
            Pipe->>Pipe: assign resale_* fields
        else
            Melin-->>Pipe: None
        end
        Pipe-->>Route: hat
    end

    Route->>DB: db.commit()
    Route->>DB: db.expire_all()
    Route->>DB: hat_service.get_hat(id) (reload with selectinload)
    Route-->>Client: 200 HatRead JSON
```

**Degradation summary** (every box is a "still 200 OK" path):
| Stage | Failure mode | Outcome |
|---|---|---|
| Content-type | Invalid mime | 400, no DB write |
| Pillow process_image | Exception | Bubbles to 500 (no try/except) |
| rembg remove_background | Any exception | Returns None; canonical = original JPEG; logged |
| Settings key lookup | None returned | `analysis_status='skipped'`; photo still saved |
| Claude API | AuthError / APIError / parse | `analysis_status='error'`; photo still saved |
| Melin pointer | Brand not Melin | Silently skipped; null resale fields |

## 2. Reanalyze — `POST /api/hats/{id}/reanalyze`

**Anchor**: `src/headroom/routes/hats.py:177-213`.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Route as routes/hats.py:reanalyze_hat
    participant Set as settings_service.get_anthropic_key
    participant Claude as claude_analysis.analyze_hat_image
    participant Apply as hat_analysis_pipeline._apply_analysis
    participant DB

    Client->>Route: POST /api/hats/{id}/reanalyze
    Route->>DB: hat_service.get_hat(id)
    alt no hat.photo_path
        Route-->>Client: 400 Hat has no photo to analyze
    end
    Route->>Route: photo_path = upload_dir / hat.photo_path
    alt file missing on disk
        Route-->>Client: 404 Photo file missing on disk
    end
    Route->>Set: get_anthropic_key(db)
    alt no key
        Route-->>Client: 400 No Anthropic API key configured
    end
    Route->>Claude: analyze_hat_image(photo_path, key)
    alt ClaudeAnalysisError
        Route->>Route: status='error', analysis_error=str(exc), analyzed_at=now
        Route->>DB: commit + expire_all
        Route-->>Client: 200 HatRead (with error fields populated)
    else ok
        Route->>Apply: _apply_analysis(hat, analysis)
        Note over Apply: same brand/model/colors/price/Melin assignment<br/>as upload pipeline
        Route->>DB: commit + expire_all
        Route-->>Client: 200 HatRead
    end
```

**Difference vs upload**: no `process_image`, no `remove_background`, no temp-file. Reuses canonical photo as-is. Missing-key returns 400 (upload returns 200 with status=skipped) — inconsistent error model.

## 3. Hat Search — `GET /api/search`

**Anchor**: `src/headroom/routes/search.py:12-43` -> `src/headroom/services/search_service.py:11-57`.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Route as routes/search.py:search
    participant Svc as search_service.search_hats
    participant DB

    Client->>Route: GET /api/search?q=navy+small+caddy&exact_colors=false&room_id=2
    Route->>Svc: search_hats(db, q, exact_colors, room_id)
    Svc->>Svc: terms = q.strip().split()
    alt empty terms
        Svc-->>Route: []
    end
    Svc->>Svc: Build SELECT Hat with selectinload(case.room, colors)
    opt room_id provided
        Svc->>Svc: WHERE Hat.case.has(room_id == X)
    end
    Svc->>Svc: color_field = color_name if exact else general_color
    loop for each term
        Svc->>Svc: AND ( Hat.style ILIKE %term% OR Hat.condition ILIKE %term% OR Hat.size ILIKE %term% OR Hat.id IN (SELECT hat_id FROM hat_colors WHERE color_field ILIKE %term%) OR Hat.case.has(Case.room.has(Room.name ILIKE %term%)) )
    end
    Svc->>Svc: ORDER BY Hat.id LIMIT 50
    Svc->>DB: execute (one query, N subqueries via has() + in_)
    DB-->>Svc: list[Hat]
    Svc-->>Route: list[Hat]
    Route->>Route: map -> SearchResult[]
    Route-->>Client: 200 JSON
```

Each term adds an OR-disjunction wrapped in an AND — semantically multi-term AND with per-term cross-field OR. Uses ILIKE (case-insensitive on Postgres; on SQLite this is just LIKE with case-folding for ASCII).

## 4. Case Lifecycle — Create / Assign Hat / Delete

**Anchor**: `src/headroom/routes/cases.py:65-93`, `src/headroom/services/case_service.py:34-91`, `src/headroom/services/hat_service.py:163-179` (assign), `src/headroom/services/hat_service.py:36-71` (capacity).

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant CaseRoute as routes/cases.py
    participant CaseSvc as case_service
    participant HatRoute as routes/hats.py
    participant HatSvc as hat_service
    participant DB

    Note over Client,DB: --- CREATE CASE ---
    Client->>CaseRoute: POST /api/cases {case_type, room_id}
    CaseRoute->>CaseSvc: create_case(data)
    CaseSvc->>DB: SELECT max(sequence_number) WHERE case_type=X
    CaseSvc->>CaseSvc: display_id = "A-001" or "D-001"
    CaseSvc->>DB: INSERT Case
    CaseSvc->>DB: COMMIT
    CaseSvc->>DB: _reload_case (expire_all + selectinload hats,room)
    CaseSvc-->>CaseRoute: Case
    CaseRoute-->>Client: 201 CaseRead

    Note over Client,DB: --- ASSIGN HAT TO CASE ---
    Client->>HatRoute: PATCH /api/hats/{id}/assign {case_id}
    HatRoute->>HatSvc: assign_hat(hat_id, case_id)
    HatSvc->>DB: get_hat (selectinload case.room, colors)
    HatSvc->>DB: get(Case, case_id)
    alt case missing
        HatSvc-->>HatRoute: HTTPException 404
    end
    HatSvc->>HatSvc: _validate_capacity
    Note over HatSvc: load all hats in case<br/>reject mix beanie+regular -> 409<br/>reject if >=4 regular OR >=6 beanies -> 409
    HatSvc->>DB: SELECT max(position_in_case)
    HatSvc->>HatSvc: hat.case_id=X, hat.position_in_case=N+1
    HatSvc->>DB: COMMIT
    HatSvc->>DB: _reload_hat (expire_all + selectinload)
    HatSvc-->>HatRoute: Hat
    HatRoute-->>Client: 200 HatRead

    Note over Client,DB: --- DELETE CASE ---
    Client->>CaseRoute: DELETE /api/cases/{display_id}
    CaseRoute->>CaseSvc: delete_case(display_id)
    CaseSvc->>DB: get_case_by_display_id (selectinload hats,room)
    alt case not found
        CaseSvc-->>CaseRoute: HTTPException 404
    end
    loop for each hat in case.hats
        CaseSvc->>CaseSvc: hat.case_id = None
        CaseSvc->>CaseSvc: hat.position_in_case = None
    end
    CaseSvc->>DB: DELETE Case
    CaseSvc->>DB: COMMIT
    CaseSvc-->>CaseRoute: None
    CaseRoute-->>Client: 204
```

**Note**: Deleting a case orphans its hats (they remain in DB with `case_id=NULL`). Frontend gallery should surface these as "unassigned" or they become invisible.

## 5. Settings — API Key Set + Resolution

**Anchor**: `src/headroom/routes/settings.py:104-112`, `src/headroom/services/settings_service.py:38-52`.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Route as routes/settings.py
    participant Svc as settings_service
    participant DB
    participant Env as config.py:Settings

    Note over Client,Env: --- SET KEY ---
    Client->>Route: PUT /api/settings/api-key {api_key}
    Route->>Svc: set_anthropic_key(db, value)
    Svc->>DB: SELECT app_settings WHERE key='anthropic_api_key'
    alt row exists
        Svc->>DB: UPDATE row SET value=...
    else row missing AND value provided
        Svc->>DB: INSERT app_settings(key, value)
    end
    Svc->>DB: COMMIT
    Route->>Svc: get_anthropic_key(db) (re-read for response)
    Svc-->>Route: (key, "database")
    Route-->>Client: ApiKeyStatus(configured=true, source="database", masked="sk-an…abcd")

    Note over Client,Env: --- RESOLUTION (used by pipeline + reanalyze + test) ---
    Route->>Svc: get_anthropic_key(db)
    Svc->>DB: SELECT value WHERE key='anthropic_api_key'
    alt DB has value
        Svc-->>Route: (db_value, "database")
    else DB empty AND env set
        Svc->>Env: config_settings.anthropic_api_key
        Svc-->>Route: (env_value, "environment")
    else neither
        Svc-->>Route: (None, None)
    end
```

**Precedence**: DB > env. UI-stored key always wins. `mask_key` shows first 5 / last 4 with ellipsis.

## 6. App Boot — `lifespan`

**Anchor**: `src/headroom/app.py:43-52` -> `src/headroom/database.py:104-115`.

```mermaid
sequenceDiagram
    autonumber
    participant Uvicorn
    participant Lifespan as app.py:lifespan
    participant Seed as app.py:_seed_branding
    participant Init as database.init_db
    participant Mig as database._run_migrations
    participant Meta as Base.metadata.create_all
    participant Room as database.ensure_default_room

    Uvicorn->>Lifespan: ASGI startup
    Lifespan->>Lifespan: mkdir(uploads, exist_ok)
    Lifespan->>Lifespan: mkdir(uploads/cases, hats, branding)
    Lifespan->>Seed: _seed_branding(branding_dir)
    loop for each file in seed/branding/
        alt dest exists
            Seed-->>Lifespan: skip
        else stem=='logo' AND any logo.* exists in target
            Seed-->>Lifespan: skip
        else
            Seed->>Seed: shutil.copy2(src, dest)
        end
    end
    Lifespan->>Init: await init_db()
    Init->>Init: import models (registers tables)
    Init->>Mig: engine.begin -> run_sync(_run_migrations)
    Note over Mig: inspector.get_table_names()<br/>CREATE TABLE rooms IF missing<br/>CREATE TABLE app_settings IF missing<br/>ALTER cases ADD room_id IF missing<br/>ALTER hat_colors ADD general_color, tier IF missing<br/>UPDATE hats SET size='classic' WHERE size='standard'<br/>ALTER hats ADD {brand,model_name,model_confidence,style_descriptor,design_notes,estimated_new_price,estimated_new_price_source,resale_price,resale_price_source,resale_price_url,resale_checked_at,analysis_status,analysis_error,analyzed_at} for any missing
    Init->>Meta: engine.begin -> run_sync(create_all)
    Note over Meta: idempotent CREATE TABLE IF NOT EXISTS for any unmigrated tables
    Init->>Room: ensure_default_room()
    Room->>Room: SELECT id FROM rooms WHERE id=1
    alt missing
        Room->>Room: INSERT INTO rooms (1, 'Default Room')
        Room->>Room: COMMIT
    end
    Init-->>Lifespan: ok
    Lifespan-->>Uvicorn: yield (serve)
```

**Note**: migrations run BEFORE `create_all`. This matters: if a developer adds a new table, `_run_migrations` will not see it (the inspector reports it as missing → ALTER paths skip; the new table is created cleanly by `create_all` after). If a developer ALTERs an existing table, the explicit migration must be added to `_HAT_COLUMN_DDL` or analogous block — `create_all` will NOT add columns to existing tables. This is documented in `CLAUDE.md`.

---

## Data Flow Map — Photo Bytes → Disk + DB

```mermaid
flowchart LR
    A[Client multipart upload] --> B{validate mime}
    B -->|reject| Z[400]
    B -->|ok| C[shutil.copyfileobj -> NamedTemporaryFile]
    C --> D[Pillow Image.open]
    D --> E{HEIC?}
    E -->|yes| E2[pillow_heif.register_heif_opener]
    E -->|no| F[convert RGB]
    E2 --> F
    F --> G[thumbnail max 1200px LANCZOS]
    G --> H[save JPEG q=85 -> uploads/hats/UUID.jpg]
    H --> I[unlink temp]
    I --> J[rembg new_session u2netp lazy-init]
    J --> K{remove succeeded?}
    K -->|no| L[fallback: keep JPEG as canonical]
    K -->|yes| M[save PNG with alpha -> uploads/hats/UUID.png]
    M --> N[unlink JPEG]
    L --> O[hat.photo_path = hats/UUID.jpg]
    N --> P[hat.photo_path = hats/UUID.png]
    O --> Q[Claude analysis branch]
    P --> Q
    Q --> R{API key?}
    R -->|no| S[status='skipped']
    R -->|yes| T[read_bytes + b64encode in-loop]
    T --> U[AsyncAnthropic.messages.create with image+tool]
    U --> V{tool_use block returned?}
    V -->|no| W[status='error']
    V -->|yes| X[parse HatAnalysis]
    X --> Y[_apply_analysis: brand,model,confidence,style_descriptor,design_notes,estimated_new_price]
    Y --> AA[hat.colors.clear + insert N HatColor rows]
    AA --> AB[build_resale_pointer]
    AB --> AC{is melin?}
    AC -->|no| AD[skip]
    AC -->|yes| AE[resale_price_url = melinrecap deeplink, resale_price=None, source='Melin Recap']
    AD --> AF[db.commit + expire_all]
    AE --> AF
    S --> AF
    W --> AF
    AF --> AG[reload hat with selectinload -> HatRead JSON]
```

**What lands where**:
- Disk: `uploads/hats/{uuid}.png` (or `.jpg` on rembg failure)
- `hats` row: `photo_path`, `brand`, `model_name`, `model_confidence`, `style_descriptor`, `design_notes`, `estimated_new_price`, `estimated_new_price_source='Claude Vision'`, `resale_*` fields (only for Melin), `analysis_status`, `analysis_error`, `analyzed_at`
- `hat_colors` rows: 1–5 per hat, with `dominance_rank`, `tier`, `color_name`, `general_color`, `hex_value`

---

## Async Map — Concurrency Reality

```mermaid
flowchart TB
    subgraph Loop[Event Loop - blocked while these run]
      A1[Pillow process_image - resize HEIC/JPEG]
      A2[Pillow upload_logo resize]
      A3[base64 encode of PNG bytes for Claude]
      A4[shutil.copyfileobj from UploadFile to tempfile]
      A5[shutil.copy2 in _seed_branding]
      A6[SQLite queries via aiosqlite - actually runs in aiosqlite's thread]
    end

    subgraph Thread[asyncio.to_thread / threadpool]
      B1[rembg _remove_sync - guarded by module asyncio.Lock]
    end

    subgraph Network[True awaits - loop is free]
      C1[AsyncAnthropic.messages.create - HTTP to Claude]
      C2[verify_api_key - HTTP ping]
    end

    A1 --> A3
    B1 -.serialised by lock.-> B1
```

**Reality check**:
- Only ONE thing in the entire codebase uses `asyncio.to_thread`: `background_removal.remove_background` (`background_removal.py:56`).
- That `to_thread` call is wrapped in `_session_lock` (`background_removal.py:21, 55`) — so even though it runs off-loop, only one rembg call is in flight at a time across the whole process.
- `process_image` (Pillow) is CPU-bound and runs INLINE on the event loop — it blocks all other requests during resize/decode.
- `_read_image_b64` (`claude_analysis.py:151-161`) reads the file and base64-encodes it inline — for a 1MB image, this is short but synchronous on the loop.
- aiosqlite (`sqlite+aiosqlite://`) does run queries in a background thread per-connection, so DB IO doesn't block the loop, but everything else above does.
- Multiple uploads in parallel → serialised on rembg, contention on Pillow. Throughput is ~one upload at a time end-to-end.

---

## State Transitions — `hat.analysis_status`

```mermaid
stateDiagram-v2
    [*] --> NULL: Hat created without photo
    NULL --> skipped: upload + no API key configured
    NULL --> error: upload + Claude raised
    NULL --> ok: upload + Claude success
    skipped --> ok: reanalyze succeeded
    skipped --> error: reanalyze failed
    error --> ok: reanalyze succeeded
    error --> error: reanalyze failed again (analysis_error overwritten, analyzed_at refreshed)
    ok --> ok: reanalyze succeeded again (overwrites brand/model/colors/price)
    ok --> error: reanalyze failed (KEEPS old brand/model/colors but flips status)
```

**Anchors**:
- skipped: `hat_analysis_pipeline.py:67-70`
- error (upload): `hat_analysis_pipeline.py:74-79`
- ok: `hat_analysis_pipeline.py:93` via `_apply_analysis`
- error (reanalyze): `routes/hats.py:202-208`

**Note on the model docstring**: `hat.py:43` mentions a `pending` value in its inline comment, but no code path ever writes `pending`. Either dead documentation or a planned async-job state that hasn't been implemented (since the pipeline runs inline with the request, "pending" never makes sense in the current synchronous flow).

**Note on `error -> error`**: when reanalyze fails, it overwrites `analysis_error` and `analyzed_at` but does NOT clear `brand`/`model`/`colors`/`price` from a prior successful run — so the UI may show stale-but-good data plus an error badge. This is probably intentional (don't lose good data on a transient failure) but worth flagging.

---

## Hot vs. Cold Paths

```mermaid
flowchart LR
    subgraph Hot[HOT - user-facing, every screen load]
      H1[GET /api/hats - gallery]
      H2[GET /api/cases - case grid]
      H3[GET /api/cases/display_id - detail]
      H4[GET /api/rooms - dropdowns]
      H5[GET /api/meta/* - filter options]
      H6[GET /api/search - free-text]
      H7[GET /uploads/hats/*.png - static photos]
      H8[GET /api/settings/logo - branding]
      H9[GET /assets/* - SPA bundles]
    end

    subgraph Warm[WARM - intentional user actions]
      W1[POST /api/hats - add hat]
      W2[PATCH /api/hats/id/assign]
      W3[PUT /api/hats/id - edit]
      W4[POST /api/cases]
      W5[DELETE /api/cases/display_id]
    end

    subgraph Cold[COLD but EXPENSIVE - rare, slow]
      C1[POST /api/hats/id/photo - 5-30s pipeline]
      C2[POST /api/hats/id/reanalyze - 3-15s Claude]
      C3[POST /api/cases/display_id/photo - Pillow only]
      C4[POST /api/settings/logo - Pillow only]
      C5[POST /api/settings/api-key/test - Claude ping]
    end

    subgraph Boot[BOOT-ONLY]
      B1[lifespan - migrations + seed default room + branding seed]
    end
```

**Observations**:
- The HOT paths are pure read-side SQLAlchemy + selectinload + Pydantic serialization. Cheap. The bottleneck under load will be SQLite write contention (single-writer) — not relevant for this small tool.
- Static asset serving (`/uploads/`, `/assets/`) goes through Starlette `StaticFiles` — fine for personal use, would want a CDN/nginx in front for many users.
- The COLD paths are where the runtime risk lives. A single hat photo upload can monopolize the rembg thread for ~10s on a Raspberry Pi (the explicit deployment target per `background_removal.py:5`). During that time other uploads queue, and Pillow on the loop blocks all other requests.
- `/api/settings/api-key/test` does a real Claude API ping with `max_tokens=4` — cheap but rate-limit-counted. Don't spam it.

---

## Cross-Cutting Notes

1. **Single AsyncSession per request, held for whole pipeline**: `routes/hats.py:142-174` opens a session via `Depends(get_db)` and keeps it for ~5–30 seconds while Pillow + rembg + Claude all run. SQLite handles this fine (the session isn't actively executing queries during the network calls), but if this ever moves to Postgres, that's a long-held connection.

2. **No background job queue**: everything runs synchronously inside the request. The `analysis_status='pending'` mentioned in the model is suggestive of a planned migration to a background worker (Celery / arq / dramatiq) where the upload returns immediately and analysis fills in later. Right now the client waits the full pipeline duration.

3. **Idempotency**: rebuilding `frontend/dist` and restarting the container will re-seed branding only for files not already present (`app.py:30-40`). Custom logos survive restarts. The default room is similarly idempotent (`database.py:93-101`).

4. **Error surface inconsistency between upload and reanalyze**: upload returns 200 with `analysis_status='skipped'` when no API key; reanalyze returns 400. This makes client error-handling forky.

5. **Anthropic model id**: `config.py:15` declares `claude-sonnet-4-6` — verify this is a real published model id. If it's a typo for `claude-sonnet-4-5` (or `claude-sonnet-4-5-20250929`-style), every upload's Claude call will 404 and degrade to `analysis_status='error'`.

End of report.
