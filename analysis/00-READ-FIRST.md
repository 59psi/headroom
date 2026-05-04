---
agent: confidant
version: 1.0
target: /Users/brandon/Things/Headroom @ a2efd86
confidence: high
findings:
  - "Headroom is a single-user, self-hosted hat-collection tracker (FastAPI + React SPA in one Docker container) whose v0.2.0 release just bolted on a Claude Vision + rembg photo-analysis pipeline."
  - "The pre-v0.2.0 CRUD core (rooms/cases/hats/search) is genuinely well-built: clean 4-layer onion, no circular imports, 64 passing tests, documented async-SQLAlchemy workarounds."
  - "The new v0.2.0 layer is plausible but empirically unverified — its happy path is exercised by zero tests and one critical default value (the Anthropic model id) is almost certainly wrong."
  - "There is a CRITICAL path-traversal vulnerability in the SPA fallback handler that exposes the Anthropic API key in plaintext to anyone who can reach the HTTP port."
  - "The author is openly AI-collaborating on the v0.2 work (Claude Opus 4.7 co-author trailer); the codebase has two distinct moods you can read side-by-side."
open_questions:
  - "Is HEADROOM_ANTHROPIC_MODEL overridden in the actual Pi deployment, or is every Claude analysis silently failing right now?"
  - "Has the operator ever observed a successful end-to-end Claude analysis since v0.2.0 was deployed?"
  - "Is the rembg session actually thread-unsafe, or is the asyncio.Lock defensive over-engineering that defeats concurrency for nothing?"
  - "Is the Pi exposed beyond the trusted home LAN (Tailscale, Cloudflare Tunnel, public IP)? If so, the threat model collapses."
  - "Is the operator actually tailing docker logs, or is the WARNING-only-to-stdout pattern effectively /dev/null?"
red_flags:
  - "Path traversal in app.py:83-89 SPA fallback — verified exploitable, leaks /data/headroom.db with the API key."
  - "anthropic_model='claude-sonnet-4-6' (config.py:15) — likely not a real Anthropic model id; no test catches it."
  - "asyncio.Lock around asyncio.to_thread in background_removal.py — pays the threading cost, gains zero concurrency."
  - "No auth on /api/settings/api-key endpoints — anyone on the network can read masked key, overwrite, delete, or burn quota."
  - "CSRF-equivalent on multipart upload endpoints — malicious tab can POST attacker bytes."
  - "Disk-full on /data is invisible — no metric, no log, no health check."
artifacts:
  - /Users/brandon/Things/Headroom/analysis/00-READ-FIRST.md
  - /Users/brandon/Things/Headroom/analysis/01-diagnosis.md
  - /Users/brandon/Things/Headroom/analysis/02-security.md
  - /Users/brandon/Things/Headroom/analysis/03-design-doc.md
  - /Users/brandon/Things/Headroom/analysis/specialists/roentgen.structure.md
  - /Users/brandon/Things/Headroom/analysis/specialists/stratum.layers.md
  - /Users/brandon/Things/Headroom/analysis/specialists/doppler.flows.md
  - /Users/brandon/Things/Headroom/analysis/specialists/lumen.deepdive.md
  - /Users/brandon/Things/Headroom/analysis/specialists/auscultator.signals.md
  - /Users/brandon/Things/Headroom/analysis/specialists/rorschach.intent.md
---

# Headroom — Read This First

## TL;DR

Headroom is a single-user, self-hosted hat-collection tracker (FastAPI + React, one Docker container on a Raspberry Pi) whose v0.2.0 release just added a Claude Vision photo-analysis pipeline that is plausibly correct but empirically unverified. The headline finding is a **critical path-traversal bug in the SPA fallback handler** (app.py:83-89) that lets anyone who can reach the HTTP port exfiltrate the SQLite database — and with it the plaintext Anthropic API key. Fix that one line, then verify the Anthropic model id (`claude-sonnet-4-6` is almost certainly wrong) and rip out the asyncio lock that's silently serializing all photo uploads — the rest is polish.

---

## In plain English

Headroom is what happens when somebody owns a lot of hats and decides their phone's photo library is not enough — they want a proper digital index of their collection that lives on a Raspberry Pi in their house, not in someone else's cloud. You take a photo of a hat with your phone, and the app does three magic things: it strips the background out of the photo so the hat floats on a synthwave gallery, it asks Claude what brand and model and colors the hat is, and (for one specific brand the owner cares about) it builds a deep link into a resale-tracking site so you can check what it's worth. The hat lives in a "case" (a physical storage container that holds either four regular hats or six beanies, never mixed) and the case lives in a "room" (a physical room in the house). It is a thoughtful, well-shaped little app for a niche personal need.

The structure is genuinely clean. The backend is a textbook FastAPI/SQLAlchemy onion: HTTP routes parse requests, services hold business rules, models are persistence, and there's a separate "pipeline" service that orchestrates the AI work without knowing anything about transactions or HTTP. The frontend is a React SPA that uses TanStack Query consistently — no custom state management, no prop drilling, query keys follow a documented convention. The deployment story is a single multi-arch Docker container that runs as a non-root user with `tini` as PID 1, with the rembg AI model pre-baked into the image so the Pi doesn't have to download it on first boot. The CSS is the most carefully-crafted artifact in the entire repo — 1,278 lines of hand-tuned synthwave styling with token discipline, neon-flicker animations, and iOS-specific touches that show somebody actually tested this on real hardware.

The trouble is concentrated in the layer that was added two weeks ago. The v0.2.0 release brought in Claude Vision analysis, background removal via rembg/ONNX, and a Docker rebuild — and it brought in three real problems. First, the default Anthropic model id (`claude-sonnet-4-6`) is not a real published Anthropic model, and no test in the suite ever calls the actual Anthropic API, so there's a non-trivial chance every photo analysis has been silently failing in production since the day it shipped. Second, the background-removal code wraps a thread offload in an async lock, which means concurrent uploads pay the cost of threading without getting any of the benefit — uploads serialize one at a time, and the second user clicking "upload" sees a spinner that's mysteriously slow. Third, and worst, the catch-all SPA route handler that serves the React frontend doesn't validate that the requested path stays inside the frontend directory; a request for `/%2e%2e/data/headroom.db` returns the SQLite database file, and inside that database, in plaintext, sits the Anthropic API key.

The codebase has two distinct moods you can read side-by-side. The pre-v0.2 services from February are casual hobby code — sentence-case commit messages, no module docstrings, raises HTTPException directly from services. The v0.2 work from May is openly AI-collaborated (the commits carry a `Co-Authored-By: Claude Opus 4.7` trailer), and it shows: every new file has a real docstring explaining the *why*, errors are translated at boundaries, conventional commits with multi-paragraph bodies, semgrep findings called out by name. The author isn't pretending to be alone in the room — they used Claude Code to do a major release, kept the attribution, and shipped it. The same honesty principle shows up in three independent product decisions: the app refuses to fabricate resale prices (it links out instead), API keys are masked when read back, and "no key configured" is a first-class state called `skipped` that's distinct from `error`.

What you should do, in order: fix the path-traversal bug today (it's a one-line change adding `is_relative_to` validation), then verify whether `HEADROOM_ANTHROPIC_MODEL` is actually overridden in the deployed environment — if it isn't, every photo analysis since v0.2.0 has been silently degrading to `analysis_status='error'` and the user just hasn't noticed because the photo still saves. Then add one end-to-end test that mocks Claude returning a valid analysis and asserts the success path — this single test would have caught both bugs. Drop the unnecessary async lock, wrap Pillow in `asyncio.to_thread`, configure docker-compose log rotation, and you've moved from "ready with conditions" to "ready" in about half a day's work.

---

## The good

- **The architecture is honest-to-god clean.** Backend is a 4-layer onion with no circular imports, services own commits, routes are thin, models are pure SQLAlchemy. The pipeline orchestrator that composes external IO (rembg + Anthropic + Melin) is a *parallel* lobe grafted onto the services layer rather than threaded through everything — a real design choice that pays off.
- **Graceful degradation in the photo pipeline is genuinely well-implemented.** Every failure mode (rembg crash, no API key, Claude error, malformed brand) leaves the user with a saved photo and a row in the database; the system treats "we couldn't analyze it" as a first-class state (`skipped`) distinct from "we tried and failed" (`error`). Rare polish for a hobby project.
- **Three product decisions reinforce a "don't lie to the user" stance.** No fabricated resale prices (link out instead), masked API keys on read, `analysis_status='skipped'` is its own thing. These are values calls, not LLM defaults.
- **The async-SQLAlchemy scar tissue is documented.** The `_reload_X` + `db.expire_all()` pattern is consistent across services, and the gotchas live in CLAUDE.md and MEMORY.md. The author got bitten by the `expire_on_commit=False` interaction with selectinload, learned, and wrote it down.
- **The visual design is the most carefully-shaped artifact in the repo.** 1,278 lines of hand-tuned synthwave CSS with token discipline, perspective grid disabled on mobile for performance, iOS zoom prevention, JetBrains Mono for hex values. Somebody wanted this to *look* a specific way and made it happen.

---

## The concerns

Ranked by `probability × blast radius`:

1. **CRITICAL: Path traversal in SPA fallback (Sentinel S1).** The handler at `app.py:83-89` does `FileResponse(FRONTEND_DIST / full_path)` then checks `is_file()` — but `Path.__truediv__` does not normalize `..` segments, and `is_file()` resolves against the actual filesystem. Verified exploitable: a request like `/%2e%2e/data/headroom.db` returns the SQLite database file. Inside that database, the Anthropic API key sits in plaintext in the `app_settings` table. **If this Pi is ever exposed beyond the home LAN, the operator's API key leaks the moment somebody tries `curl`. Even on a trusted LAN, anyone on the same Wi-Fi can read it.** Fix: add `file_path.is_relative_to(FRONTEND_DIST.resolve())` validation.

2. **HIGH: The Anthropic model id is almost certainly wrong (Lumen, Doppler).** `config.py:15` defaults `anthropic_model` to `"claude-sonnet-4-6"`, which does not match Anthropic's published id scheme (typically dated like `claude-sonnet-4-5-20250929` or aliased like `claude-sonnet-4-5`). Zero tests exercise the real Anthropic path — `rembg` is monkey-patched to always return None and Claude is never actually called. **If the production deployment doesn't override `HEADROOM_ANTHROPIC_MODEL`, every photo analysis since v0.2.0 shipped has been silently failing to a 404, and users see a red "Analysis error" banner with a confusing message — but the photo still saves so the user might not realize it's broken end-to-end.**

3. **HIGH: The upload pipeline serializes globally on a useless lock (Doppler R1, Lumen §3).** `background_removal.py` wraps `asyncio.to_thread` inside an `asyncio.Lock`, which means it pays the threading cost (overhead, context switch) but gains zero concurrency — two simultaneous uploads serialize one at a time across the entire process, then *also* compete for the event loop because Pillow runs inline (not in a thread). **If a user clicks upload on two hats in quick succession, the second one waits 5-10 seconds with a spinner before bg-removal even starts. This is a 100%-reproducible architectural property, not a transient.** Fix: drop the lock and trust rembg's reentrancy, or drop the to_thread and accept serial mode — pick one.

4. **MEDIUM: Zero authentication on `/api/settings/api-key` (Stratum, Sentinel S2).** Any device on the network can `GET` the masked key, `PUT` to overwrite it (a phishing variant — every subsequent hat photo gets sent to the *attacker's* Anthropic account, leaking the photo and accruing their billing), `DELETE` to lock the operator out, or `POST /test` to burn API quota. The threat model is "single user on trusted home LAN" but nothing in code enforces that. **The day this Pi is exposed to anything wider — Tailscale, a guest network, a roommate — these endpoints become a credential-loss vector.**

5. **MEDIUM: Zero observability for the failure modes most likely to surface (Auscultator).** Two `logger.warning` calls in the entire backend. No `logging.basicConfig`, no metrics, no tracing, no log rotation in docker-compose, no real `/health` check (the existing one returns hard-coded `{"status":"ok"}` regardless of whether the DB is reachable, the disk is full, or rembg can load). **The most likely Pi failure mode is the SD card filling up with accumulated hat photos, and the app has exactly zero visibility into it — first symptom is a 500 to the user.**

---

## If you only read one diagram

The photo-upload sequence diagram from Doppler. It's the marquee flow of the entire v0.2.0 release, it's where every concern in this document lives, and it's the thing that actually breaks if the Anthropic model id is wrong or the lock is held.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant Route as routes/hats.py:upload_hat_photo
    participant Photo as utils/photo.process_image
    participant Pipe as hat_analysis_pipeline.finalize_hat_photo
    participant Bg as background_removal.remove_background
    participant Set as settings_service.get_anthropic_key
    participant Claude as claude_analysis.analyze_hat_image
    participant Melin as melin_recap.build_resale_pointer
    participant DB

    Client->>Route: POST multipart photo
    Route->>Route: validate_image_content_type
    Route->>DB: hat_service.get_hat(id)
    Route->>Route: tempfile + shutil.copyfileobj
    Route->>Photo: Pillow open -> RGB -> thumbnail(1200) -> JPEG q=85
    Note over Photo: BLOCKS event loop (sync Pillow)
    Route->>Pipe: finalize_hat_photo(db, hat, jpeg_path)

    Pipe->>Bg: remove_background(jpeg, target)
    Note over Bg: asyncio.to_thread under module-global asyncio.Lock<br/>(serializes ALL concurrent uploads)
    alt rembg succeeds
        Bg-->>Pipe: PNG path; unlink JPEG; canonical=PNG
    else rembg fails
        Bg-->>Pipe: None (logger.warning); canonical=JPEG (silent fallback)
    end

    Pipe->>Set: get_anthropic_key(db)
    alt no key
        Pipe->>Pipe: status='skipped'; return
    else key found
        Pipe->>Claude: analyze_hat_image(canonical_path, key)
        Note over Claude: read_bytes + b64encode (BLOCKS loop)<br/>messages.create(model='claude-sonnet-4-6'?!)
        alt ClaudeAnalysisError (incl. bad model id -> 404)
            Pipe->>Pipe: status='error', analysis_error=str(exc)
        else success
            Pipe->>Pipe: _apply_analysis (brand, model, colors, prices)
            Pipe->>Melin: build_resale_pointer(brand, style)
            Pipe->>Pipe: status='ok'
        end
    end

    Route->>DB: commit + expire_all + reload
    Route-->>Client: 200 HatRead JSON
```

**Caption.** This single diagram tells you everything load-bearing about Headroom's most important flow. Read it left to right and the design is genuinely thoughtful — every failure stage degrades to a "still 200 OK" outcome, the photo always saves, and the analysis status is honest about what happened. Then read it again with the concerns in mind: the `BLOCKS event loop` annotations are the inline-Pillow performance problem; the `module-global asyncio.Lock` is the concurrency-defeating bottleneck; the `model='claude-sonnet-4-6'` is the suspect default that no test exercises; the photo on disk happens before Claude runs, so a Claude failure leaves the user with the new photo but stale-or-empty analysis fields. Every concern in section 4 of this document corresponds to a specific arrow or note in this diagram. Internalize this picture and you understand the patient.

---

## Questions to ask the author

1. **Have you ever seen a successful end-to-end Claude analysis on the deployed Pi since v0.2.0 shipped?** (Empirical question — the test suite cannot answer it because the Anthropic happy path is unmocked.)
2. **Is `HEADROOM_ANTHROPIC_MODEL` set to a real model id in the deployed environment, or are you relying on the `claude-sonnet-4-6` default in `config.py:15`?**
3. **Is the Pi reachable only from the home LAN, or have you exposed it via Tailscale/Cloudflare Tunnel/router port-forward?** (Determines whether the auth-free settings endpoints and the path-traversal vulnerability are theoretical or load-bearing.)
4. **Was the asyncio.Lock around the rembg `to_thread` call defensive over-engineering, or did you observe a real concurrency bug with the rembg session?** (Removing it unlocks real upload concurrency at zero risk if no real bug exists.)
5. **Why does `reanalyze_hat` import the private `_apply_analysis` symbol with five function-local imports inside the route handler?** (Smells like LLM defensive coding around a circular import that didn't exist.)
6. **Is `frontend/headroom.db` a leftover dev database, or is something actually using it?** If it's tracked in git, does it contain a real API key?
7. **Do you actually `docker logs -f headroom` on the Pi, or do you only look when something is reported broken?** (Determines how much observability matters in practice.)
8. **Was the synthwave CSS hand-tuned by you or generated by Claude?** (No technical impact — this is the "what was load-bearing about the human in the loop" question, since the CSS is the most carefully-shaped artifact in the repo.)
9. **Is hats-orphaned-to-`case_id=NULL`-on-case-delete intentional (a "drawer of unassigned hats") or a leak you didn't know about?** (Currently they remain in the DB but the gallery may not surface them.)
10. **What's the backup story for `/data`?** The README says "back it up periodically" but there's no in-app endpoint, no scheduled snapshot, no documented recovery procedure.

---

## Reading guide

For the reader who wants to go deeper, in order of recommended reading:

- **Start with `03-design-doc.md` (Scribe).** This is the system overview — what Headroom is, what it does, how it's deployed, what the 33 HTTP endpoints are. Read sections 4 (High-Level Design), 7 (Key Flows), and 8 (Data Model) and you understand the whole app. Skim the rest.

- **Then `01-diagnosis.md` (Prognosis).** The vital signs table at section 1, the risk register at section 3, and the prescription at section 6 are the action items. Read these three sections and you have the to-do list.

- **For the security questions, `02-security.md` (Sentinel).** Section 9 ("Ranked Findings") is the punchline — read S1 in detail (the path-traversal verified exploit), then skim S2 through S8 for the threat-model-dependent stuff.

- **If you want to argue with the analysis or verify a specific claim, the specialists are below.** They're each scoped:
  - `roentgen.structure.md` — file inventory, LOC counts, dependency graph. Read first if you want to know "where does X live."
  - `stratum.layers.md` — the 4-layer onion catalog and where each cross-cutting concern (auth, logging, etc.) does or doesn't live.
  - `doppler.flows.md` — runtime sequence diagrams for every important flow. The hat-upload diagram in section 1 is the must-read.
  - `lumen.deepdive.md` — eight regions dissected at line-anchor depth. Read section 1 (the Anthropic call) and section 3 (the rembg session pattern) for the technical meat.
  - `auscultator.signals.md` — observability gap analysis. The `minimum_viable_instrumentation` block in the frontmatter is a copy-paste-ready starter pack.
  - `rorschach.intent.md` — authorial fingerprint analysis. Read section 7 ("Two-author hypothesis") for the AI-collaboration story; the rest is texture.

- **Skip if pressed for time:** the appendix and file-index sections of the design doc, the LOC tables in Roentgen, the cross-region observations at the end of Lumen. These are reference material, not narrative.

The whole bundle is about 4 hours of reading. The TL;DR at the top of this file plus the Doppler hat-upload diagram is about 5 minutes. Most readers want the second one.
