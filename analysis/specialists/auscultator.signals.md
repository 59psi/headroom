---
agent: auscultator
version: 1.0
target: /Users/brandon/Things/Headroom @ a2efd86
confidence: high
findings:
  - "No structured logging configuration anywhere — `logging.basicConfig()` is never called, no formatter, no handlers, no level set. Three modules (`hat_analysis_pipeline`, `background_removal`, `claude_analysis`) declare `logger = logging.getLogger(__name__)` but only two of them ever call it."
  - "Total log call sites in src/headroom/: 2. (background_removal.py:58 WARNING, hat_analysis_pipeline.py:75 WARNING). claude_analysis.py declares a logger and never uses it."
  - "Zero metrics. No counters, gauges, histograms. No prometheus, statsd, otel, or in-process counters. No `/metrics` endpoint."
  - "Zero tracing/spans. No OpenTelemetry, no Sentry, no APM. pyproject.toml has no observability dependency."
  - "/health (routes/health.py:6-8) returns hard-coded `{\"status\": \"ok\"}` — does not check DB, disk, rembg session, or API key. It is a liveness probe at best, not a readiness probe."
  - "No HEALTHCHECK directive in Dockerfile and no `healthcheck:` block in docker-compose.yml — even the trivial /health endpoint is not consumed by the container runtime."
  - "uvicorn is launched bare (`uvicorn headroom.app:app --host 0.0.0.0 --port 8000`, Dockerfile:89) so default uvicorn access logs go to stdout and end up in `docker logs headroom`. That is the only operational signal the operator gets out of the box."
  - "Anthropic failures: caught in claude_analysis.analyze_hat_image (claude_analysis.py:209-214), re-raised as ClaudeAnalysisError, caught one frame up in hat_analysis_pipeline.py:74-79 which logs at WARNING and persists `hat.analysis_status='error'` + `hat.analysis_error=str(exc)`. Operator sees the error in two places: (a) `docker logs` if they look (no level filter, no rotation config), (b) the hat detail page (HatDetailPage.tsx:283-287 renders a red alert with the raw exception string). No alerting, no aggregation."
  - "rembg failures: background_removal.py:54-59 catches bare `Exception`, logs WARNING, returns None. The pipeline (hat_analysis_pipeline.py:54-60) silently falls back to the JPEG. The user sees a hat photo with a background — they have no UI signal that bg removal failed. Only signal is the WARNING line in `docker logs`."
  - "Partial-failure asymmetry: bg-removal-fails-but-Claude-succeeds → user sees photo-with-background + correct analysis (silently degraded). Bg-removal-succeeds-but-Claude-fails → user sees clean PNG + 'Analysis error' red banner with the exception text. Only the second case is visible to the operator."
  - "rembg model load failure (e.g. ONNX model file missing/corrupt on the Pi) is also caught by the same bare-except — operator gets a single WARNING line per upload, no startup probe. Dockerfile pre-caches the model at build time (Dockerfile:50, copies to /home/headroom/.u2net at line 73), so this is unlikely but undetectable if it does happen."
  - "Disk-full on /data/uploads: completely invisible. No metric, no log, no health check. First symptom is a Pillow/IOError on the next photo write surfacing as a 500 to the user."
  - "Revoked Anthropic key: visible only when a user uploads/reanalyzes a hat — the per-hat `analysis_error` will read 'Invalid Anthropic API key.' (claude_analysis.py:210). The Settings page has a 'Test API key' button (routes/settings.py:120-126 → verify_api_key) but no scheduled probe. Operator only finds out by trying."
  - "verify_api_key (claude_analysis.py:245-262) burns a real `messages.create` call against the configured model with max_tokens=4 — cheap but non-zero cost, and it's only triggered manually."
  - "Config surface (config.py:6-20): `database_url`, `upload_dir`, `cors_origins`, `anthropic_api_key`, `anthropic_model`, `http_timeout`. All env-prefixed `HEADROOM_`. Plus `HEADROOM_REMBG_MODEL` read directly via `os.environ` (background_removal.py:19), which bypasses pydantic-settings — it isn't in the Settings model and won't show up in any settings dump."
  - "docker-compose.yml sets `HEADROOM_REMBG_MODEL=u2netp` and `HEADROOM_CORS_ORIGINS='[\"http://localhost:8000\"]'` and leaves `HEADROOM_ANTHROPIC_API_KEY` commented out (UI-stored key in DB takes precedence — settings_service.get_anthropic_key)."
  - "No log rotation / retention configured for the Docker logs driver in docker-compose.yml. On a Pi this is a slow disk-fill vector if the app ever gets chatty (it currently doesn't, but the 500-from-uvicorn case is unbounded)."
  - "Tests directory has zero tests for the failure-visibility paths above (no test asserts that a Claude error sets analysis_status='error' from the route, no test asserts background_removal returns None gracefully)."

open_questions:
  - "Does the operator actually `docker logs -f headroom` on the Pi, or do they only look when something is reported broken? If the latter, the WARNING-only-to-stdout pattern is effectively /dev/null."
  - "Is there an external uptime check pointed at the Pi (UptimeRobot, etc.)? If yes, /health is sufficient as liveness. If no, even container restart-loops go undetected."
  - "Does the Pi's Docker daemon have a json-file log rotation cap configured at the daemon level (/etc/docker/daemon.json)? Compose doesn't set one."
  - "Single-user app — is alerting even desired? Or is 'I'll notice when I try to upload a hat' acceptable?"

red_flags:
  - "claude_analysis.py:22 declares a logger but never logs anything — including not logging the Anthropic exception before re-raising. The pipeline-layer log (line 75) only sees `str(exc)`, losing the chained traceback unless something upstream calls `logger.exception`."
  - "Bare `except Exception` in background_removal.py:57 swallows all rembg/onnxruntime failures into a single WARNING with no traceback. A genuinely broken install (missing libgl1, model file corrupt, OOM-killed thread) looks identical to a one-off bad image."
  - "/health (routes/health.py) returns 200 even if the DB is unreachable, the upload volume is read-only, the Anthropic key is missing, and rembg can't load. It is a tautology, not a health check."
  - "No log-level configuration means `logger.warning(...)` calls go to the root logger with no handler attached → on Python 3.12 they hit the `lastResort` handler at WARNING+ and print to stderr. This works by accident; if anyone ever sets up `logging.basicConfig(level=ERROR)` to quiet things, the only two log lines in the codebase disappear."
  - "Disk space on /data is the single most likely Pi failure mode (photos accumulate, no cleanup, no quota) and there is exactly zero visibility into it from the app."
  - "analysis_error is shown in the UI verbatim (HatDetailPage.tsx:285) — fine for a single-user app, but it will surface raw API messages including model names and possibly request IDs to whoever is looking at the screen."

artifacts:
  - "src/headroom/routes/health.py:6-8 — trivial /health endpoint"
  - "src/headroom/config.py:6-20 — Settings model (HEADROOM_-prefixed env vars)"
  - "src/headroom/services/background_removal.py:17,19,54-59 — only WARNING log + bare-except + os.environ read"
  - "src/headroom/services/claude_analysis.py:22,209-214,245-262 — declared-but-unused logger, exception mapping, manual API key probe"
  - "src/headroom/services/hat_analysis_pipeline.py:35,72-79 — second WARNING log + DB-side error persistence"
  - "src/headroom/routes/hats.py:142-174 — upload pipeline; no try/except around finalize_hat_photo"
  - "src/headroom/routes/hats.py:177-213 — reanalyze endpoint; same error-to-DB pattern"
  - "src/headroom/routes/settings.py:120-126 — manual API key reachability test"
  - "src/headroom/app.py:43-52 — lifespan, no logging setup, no readiness gate"
  - "Dockerfile:50,73,88-89 — rembg model pre-cached at build, copied to /home/headroom/.u2net, uvicorn launched with no log config"
  - "docker-compose.yml — no healthcheck, no logging driver options, no resource limits"
  - "frontend/src/pages/HatDetailPage.tsx:277-287 — only user-facing surface for analysis errors (skipped + error states only; rembg failure is invisible)"

minimum_viable_instrumentation:
  what_to_log:
    - "Call `logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')` once in app.py lifespan or a dedicated `logging_config.py`. Right now log lines are only escaping by accident via lastResort."
    - "Log photo upload at INFO with hat_id, file size, content type, elapsed ms (routes/hats.py:142)."
    - "Log Claude analysis attempts at INFO with hat_id, model, elapsed ms, token usage from `message.usage` (claude_analysis.py:208)."
    - "In claude_analysis.py:209-214 use `logger.exception(...)` instead of dropping the traceback into a bare ClaudeAnalysisError string."
    - "Log rembg session creation once at INFO with model name and load time (background_removal.py:_get_session)."
    - "Log unhandled exceptions via FastAPI exception handler — currently a 500 just disappears unless uvicorn's access log catches the status code."
    - "Configure docker-compose logging driver: `logging: { driver: json-file, options: { max-size: 10m, max-file: 3 } }` on the headroom service, otherwise the journal can fill the SD card."
  what_to_expose_as_metric:
    - "Counter: hat_uploads_total{outcome=ok|bg_failed|claude_skipped|claude_failed}"
    - "Histogram: claude_analysis_duration_seconds, rembg_duration_seconds, photo_process_duration_seconds"
    - "Counter: claude_api_errors_total{kind=auth|api|parse|other} — derived from the four except branches in claude_analysis.py"
    - "Gauge: upload_dir_bytes_used and upload_dir_bytes_free (sample on a timer or on each upload)"
    - "Gauge: rembg_session_loaded (0/1) — flips to 0 if _get_session raises"
    - "For a single-user Pi app, prometheus is overkill — a `/api/diagnostics` JSON endpoint exposing the same numbers is sufficient and reuses the existing FastAPI surface."
  what_a_real_healthz_should_check:
    - "DB reachable: `await db.execute(text('SELECT 1'))` against a get_db() session."
    - "Upload volume writable: try a 1-byte write+unlink in /data/uploads/.healthz."
    - "Free disk on /data above a threshold (e.g. >100MB): `shutil.disk_usage(settings.upload_dir)`."
    - "rembg session loadable: call `_get_session()` once; cache the result on the lifespan so /healthz is cheap."
    - "Anthropic key configured (not necessarily valid — verifying costs an API call). Distinguish liveness (process up) from readiness (configured + dependencies reachable). Two endpoints: `/healthz` (liveness, cheap) and `/readyz` (readiness, may touch DB + disk)."
    - "Then add `healthcheck:` to docker-compose pointing at /readyz so `docker ps` shows health, and `restart: unless-stopped` actually means something."
---

# Auscultator: Observability Audit

## TL;DR

Headroom has essentially no observability. Two `logger.warning()` calls in the entire backend, no metrics, no tracing, no real health check, no alerting, no log rotation. This is fine for a single-user hat-collection app on a Pi — until the Anthropic key gets revoked, the SD card fills up, or rembg silently degrades, at which point the operator finds out by trying to use the app and noticing it feels weird.

The good news: the failure modes that *are* surfaced (Claude API errors → DB → red banner in UI) are surfaced well. The bad news: that's the only path that surfaces anywhere visible.

See frontmatter `findings`, `red_flags`, `open_questions`, `artifacts`, and `minimum_viable_instrumentation` above for the structured breakdown.
