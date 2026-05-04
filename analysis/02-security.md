---
agent: sentinel
version: 1.0
target: /Users/brandon/Things/Headroom @ a2efd86
confidence: high
findings:
  - "CRITICAL path traversal in SPA fallback at app.py:83-89: `FileResponse(FRONTEND_DIST / full_path)` followed by `is_file()` resolves `..` segments. Verified by raw ASGI test that `/%2e%2e/secret_test.txt` returns the file outside FRONTEND_DIST. Reaches /data/headroom.db which contains the Anthropic API key in plaintext."
  - "No authentication and no authorization on any /api/* route — any actor reaching the TCP port can read all data, mutate all rows, delete cases/rooms/hats, set/clear/test the Anthropic API key, and upload arbitrary files."
  - "Anthropic API key handling is otherwise correct: Pydantic ApiKeyStatus only ever returns `mask_key` form (first 5 + ellipsis + last 4); the raw key never appears in any response body, log line, or analysis_error string."
  - "CORS posture is sane (default ['http://localhost:5173'], compose ['http://localhost:8000'], no wildcard, allow_credentials=True with explicit origin list) — preflighted JSON requests from other origins are blocked. But multipart upload endpoints are CORS-simple (no preflight), so any malicious page the user visits can POST attacker-controlled bytes to /api/hats/{id}/photo, /api/cases/{display_id}/photo, /api/settings/logo. CSRF-equivalent on uploads."
  - "Static /uploads mount uses Starlette StaticFiles which IS hardened against path traversal (verified). The vulnerability above is unique to the custom SPA fallback handler."
  - "Pillow operates on user-supplied bytes with no MAX_IMAGE_PIXELS override, no body size limit on uvicorn, no try/except around process_image — a 500MB image upload fills the tempfile, then any decompression bomb error 500s without cleanup. Disk-fill DoS is unauthenticated."
  - "rembg ONNX model fetched at Docker build time from github.com/danielgatis/rembg/releases over TLS with MD5 checksum verification baked into the rembg library (md5:8e83ca70e441ab06c318d82300c84806). Adequate for the threat model."
  - "Container security: runs as non-root headroom (uid 1000), tini PID 1, single mounted /data volume. The /root/.u2net → /home/headroom/.u2net copy at Dockerfile:73 is correct because rembg resolves `~/.u2net` via os.path.expanduser, and HOME is set per useradd."
  - "Supply chain: beautifulsoup4 declared in pyproject.toml but never imported anywhere in src/ or tests/ — dead dependency, removable. httpx declared at top level but only imported in tests/conftest.py (transitively required by anthropic SDK at runtime, so the top-level declaration is harmless)."
  - "Claude tool-use response is parsed as a dict and color hex strings flow into React inline `style={{ backgroundColor: c.hex_value }}` (HatDetailPage.tsx:259, ColorSwatch.tsx:13) without validating against the input_schema regex `^#[0-9a-fA-F]{6}$` — that pattern is only a hint to Claude, not enforced by the SDK or any post-parse validator. Practical impact is limited: modern browsers parse CSS values per-property, so the worst plausible result is an embedded url() background fetch (tracking pixel from a malicious model). Not RCE/DOM XSS."
  - "All other AI-controlled fields (brand, model_name, style_descriptor, design_notes, analysis_error) render as React text children → auto-escaped. resale_price_url is built from hardcoded MELIN_BASE + urlencode → never AI-controlled. Safe from script injection."
  - "Outbound network from services/melin_recap.py is URL-string construction only (verified — no httpx/requests/urllib calls) — claim from Roentgen holds today."
  - "Filename handling in utils/photo.py:generate_filename uses uuid4 + sanitized suffix → no user-controlled filename ever lands on disk. routes/hats.py:upload_hat_photo and routes/cases.py:upload_case_photo also use generate_filename then write inside settings.upload_dir/{hats,cases}/. Path traversal via filename is not reachable."

open_questions:
  - "Is the /uploads/ static mount intended to be world-readable? Anyone with TCP port access can enumerate uploaded photos (filenames are uuid4 so not directory-listed, but if the photo URL ever leaks via analytics/referer/screenshot it is forever public). Acceptable for personal Pi but document it."
  - "If the Pi is exposed via Tailscale/Cloudflare Tunnel/reverse-proxy publicly, every API endpoint is anonymous — including DELETE /api/settings/api-key. Should the README explicitly require an upstream auth proxy (basic auth, oauth2-proxy, Tailscale-only) before public exposure?"
  - "Does the Settings UI expose the masked key on the dashboard / hat-detail pages? The mask reveals 5 prefix chars (which are deterministic 'sk-an' for Anthropic keys) plus 4 suffix chars. Combined with brute force or a key-leak elsewhere, the suffix is a plaintext oracle. Could mask to '•••' instead."
  - "frontend/headroom.db at the repo root (per Roentgen) — is that a leftover dev DB? If it contains a real key it would be a secret-in-git risk."

red_flags:
  - "Path traversal in SPA fallback (Critical) — see finding #1."
  - "No auth + no rate limit on /api/settings/api-key (PUT/DELETE/GET-status/POST-test) — anyone reaching the port can rotate, delete, or burn-test the operator's Anthropic key, costing money and locking the user out."
  - "Multipart photo uploads bypass CORS preflight → CSRF-equivalent on /api/{hats,cases}/{id}/photo and /api/settings/logo from any browser tab the user visits."
  - "No upload size limit anywhere in the stack — uvicorn defaults to unlimited, FastAPI/Starlette doesn't add one, and process_image opens an arbitrary tempfile in Pillow. Disk-fill DoS or memory exhaustion on a Pi from a single multipart POST."
  - "Pillow + libheif1 from Debian Bookworm process untrusted image bytes inline. CVE history for libheif/libwebp is non-trivial (e.g. CVE-2023-4863 webp 0-day in 2023). No image-bomb cap (Image.MAX_IMAGE_PIXELS unset)."
  - "frontend/headroom.db tracked in repo root may be a dev DB containing data — should be .gitignored if not already."
  - "No CSP, no X-Frame-Options, no Referrer-Policy, no security headers anywhere."

artifacts:
  - /Users/brandon/Things/Headroom/analysis/02-security.md
  - /Users/brandon/Things/Headroom/src/headroom/app.py:83-89 (path traversal site)
  - /Users/brandon/Things/Headroom/src/headroom/routes/settings.py:104-117 (unauth API key endpoints)
  - /Users/brandon/Things/Headroom/src/headroom/utils/photo.py:14-37 (Pillow on user bytes)
  - /Users/brandon/Things/Headroom/src/headroom/services/claude_analysis.py:222-242 (tool-use parser)
  - /Users/brandon/Things/Headroom/Dockerfile:67-83 (non-root setup)
---

# Sentinel — Security Audit

**Threat model assumed:** single-user Pi on a trusted home LAN, no public exposure, no other users with shell access on the Pi. Findings labelled "(out of stated threat model)" only become relevant if the box is exposed publicly or the LAN is hostile.

## 1. Attack Surface Summary

Inputs that cross a trust boundary:

### HTTP ingress (33 endpoints, all unauthenticated)
| Surface | Path | Trust crossing |
|---|---|---|
| TCP :8000 | docker-compose port mapping | Whoever can reach the host:port |
| GET /health | routes/health.py | trivial |
| GET /api/* (reads) | rooms, hats, cases, search, meta, settings | reveal all data |
| POST/PUT/PATCH/DELETE /api/* (writes) | every router | mutate / delete everything |
| GET/PUT/DELETE /api/settings/api-key | routes/settings.py:92-117 | **read masked key, set raw key, delete key** |
| POST /api/settings/api-key/test | routes/settings.py:120-126 | burn 1 Anthropic call against config |
| POST /api/hats/{id}/photo | routes/hats.py:142-174 | **arbitrary multipart bytes → Pillow → rembg → Claude** |
| POST /api/cases/{id}/photo | routes/cases.py:96-128 | arbitrary multipart bytes → Pillow |
| POST /api/settings/logo | routes/settings.py:42-79 | arbitrary multipart bytes → Pillow |
| GET /uploads/* | StaticFiles mount, app.py:69-73 | reads upload dir directly (hardened, no traversal) |
| GET /assets/* | StaticFiles mount, app.py:77-81 | reads built JS/CSS |
| GET /{full_path:path} | SPA fallback, app.py:83-89 | **path traversal** — see finding 1 |

### Deserialization points
- **Image bytes via Pillow** — every photo upload runs `Image.open` on attacker bytes (utils/photo.py:22, routes/settings.py:60, services/background_removal.py:37). HEIC bytes additionally pass through libheif1 system lib. No `Image.MAX_IMAGE_PIXELS` cap, no try/except — a decompression bomb 500s; libheif/libwebp CVEs are a transitive supply-chain concern.
- **JSON bodies via Pydantic** — strongly typed by HatCreate, HatUpdate, RoomCreate, etc. Enums constrain style/size/condition. `HatUpdate.brand|model_name|design_notes|estimated_new_price` accept arbitrary strings/floats with no max length (SQLite VARCHAR(N) is advisory, not enforced).
- **Multipart bodies via python-multipart** — UploadFile.filename is only used for suffix detection (`Path(...).suffix.lower()`); the on-disk filename is `uuid4().hex + suffix` (utils/photo.py:11). Filename traversal not reachable.
- **Anthropic tool-use response parsed as JSON** — claude_analysis.py:222-242 calls `tool_block.input` and indexes into the dict directly. No re-validation against the input_schema (which is only an instruction to Claude, not an SDK invariant). A malicious or hallucinating model can return any value for any field; downstream renders trust the data.
- **No unsafe deserialization** of untrusted yaml.load / xml.etree / shelve / marshal anywhere in the codebase. Good.

### Outbound (egress)
- `https://api.anthropic.com` via AsyncAnthropic SDK in services/claude_analysis.py — necessary, configured with `timeout=settings.http_timeout`. Authenticated with the configured key.
- `https://www.melinrecap.com/?…` is a URL **constructed but not fetched** — claim re-verified: services/melin_recap.py contains zero `httpx`/`requests`/`urllib.request` calls. Only `urllib.parse.urlencode`. The URL ends up in `hat.resale_price_url` and is rendered as an `<a href>` in the SPA.
- `https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx` fetched **at Docker build time** by the rembg library (via `pooch.retrieve`) with MD5 checksum verification.

## 2. Threat Model — Top Threats

| # | Threat | Likelihood | Impact | Anchor |
|---|--------|:----------:|:------:|--------|
| T1 | **Arbitrary file read via SPA fallback path traversal** — attacker reaches /etc/passwd, /data/headroom.db (Anthropic key in DB), Python source. | H (if exposed beyond trusted LAN); L (LAN-only) | **H** | app.py:83-89 |
| T2 | **CSRF on multipart upload endpoints** — malicious tab user visits in same browser POSTs an attacker-chosen image to /api/hats/{id}/photo / /api/cases/{id}/photo / /api/settings/logo. Multipart is a CORS-simple request type → no preflight → CORS allow-list does not block the request, only the response. | M | M (overwrites collection photos; runs Claude analysis billed to user; replaces logo) | routes/hats.py:142, routes/cases.py:96, routes/settings.py:42 |
| T3 | **Anonymous API-key abuse** — attacker on the same network with port access calls `DELETE /api/settings/api-key` (locks user out), `POST /api/settings/api-key/test` (burns API calls / triggers rate limits), or `PUT` (sets attacker key — phishing variant). | M (LAN); H (public) | M-H (financial via key burn; lockout; key swap → all future analyses leak hat photos to attacker) | routes/settings.py:104-126 |
| T4 | **Disk-fill DoS via giant multipart upload** — no body size limit; Pillow opens the tempfile; if it OOMs / fills /data the container is wedged. | M | M (Pi outage) | utils/photo.py:14-37; uvicorn defaults |
| T5 | **Pillow / libheif image-decode CVE** triggered by crafted HEIC/WebP — Pillow + libheif1 + Debian Bookworm freshness. | L (no specific CVE known today) | M-H (RCE in worst case) | utils/photo.py:22; Dockerfile:31-33,63-65 |
| T6 | **Hat data tamper / mass delete** — every state-changing route is anonymous. | M (LAN, malicious tab); H (public) | M (data loss, no backup mechanism documented) | every routes/*.py |
| T7 | **Claude tool-use poisoning** — model returns CSS-injection in `colors[].hex` since the `^#[0-9a-fA-F]{6}$` regex is only a tool hint, not enforced post-parse. Worst plausible: `url(http://evil)` background fetch (tracking pixel) on every page render. | L | L | claude_analysis.py:222-242; HatDetailPage.tsx:259, ColorSwatch.tsx:13 |
| T8 | **DNS rebinding** — attacker page tricks browser into treating an attacker-controlled domain as same-origin with localhost:8000 and submits requests with no CORS preflight involvement. CORS only checks Origin, not Host; no Host-header allowlist. | L | M | app.py middleware stack |
| T9 | **Database file leak** — `frontend/headroom.db` exists at frontend/ root per Roentgen. If it's tracked in git or shipped to GitHub it leaks any UI-stored API key. | Low (verify .gitignore) | H (key disclosure) | repo root |
| T10 | **Log-rotation disk-fill** (auscultator already flagged) — uvicorn access logs + WARNING lines unbounded; docker-compose has no logging driver options. | L (current call sites are quiet) | L-M | docker-compose.yml |

## 3. AuthN / AuthZ Review

There is none. Every route is reachable by every TCP client.

### What a LAN-adjacent attacker can do
- Read all hats, cases, rooms, photos, branding.
- Create/modify/delete any row.
- Upload arbitrary multipart bytes to three photo endpoints (CSRF-friendly because multipart is CORS-simple).
- Read the Anthropic API key in **masked form** via `GET /api/settings/api-key`.
- **Replace** the Anthropic API key with their own via `PUT /api/settings/api-key` (phishing — every subsequent hat photo is sent to attacker's Anthropic account, leaking the photo + accruing their billing).
- **Delete** the Anthropic API key via `DELETE /api/settings/api-key`, locking the operator out.
- **Burn API quota** via `POST /api/settings/api-key/test` — each call is a billed `messages.create` against `claude-sonnet-4-6`. Cheap, but rate-limit-counted.
- Read **arbitrary files** on the host filesystem via path traversal (T1) — yields the raw key from `/data/headroom.db` (`SELECT value FROM app_settings WHERE key='anthropic_api_key'`).

### What a malicious tab can do
- CORS allow-list (`http://localhost:8000`) blocks the **response** of cross-origin XHR/fetch, so JSON-bodied state changes from JS on a non-listed origin reach preflight and are blocked.
- Multipart POST to upload endpoints is **CORS-simple** — no preflight, request reaches the server. Malicious origin can't read the response, but the side-effect (hat photo overwrite, logo overwrite, Claude analysis billed) is achieved.
- A `<form action="http://localhost:8000/api/settings/api-key" method="post">` with `enctype="application/x-www-form-urlencoded"` would be CORS-simple too, but the endpoint expects JSON (Pydantic ApiKeyUpdate) so the body parser would reject — luckily.
- DNS rebinding: no Host-header allowlist on the FastAPI app; in principle a malicious page could rebind a domain to 127.0.0.1 after first connection and then send Origin: http://attacker.example. The CORS check would block… unless the attacker page IS at the rebound origin, in which case Origin matches the rebound name. Mitigation: nothing today.

### CORS posture
`config.py:9` defaults to `["http://localhost:5173"]` (the Vite dev server). `docker-compose.yml:17` overrides to `["http://localhost:8000"]`. Both are explicit, neither is wildcard, `allow_credentials=True` is **safe** because origin is not `*`. Posture is correct **for the intended dev/prod setup**. The issue is not CORS — it's the absence of any auth behind it.

## 4. Sensitive Data Handling — Anthropic API Key

Verified by reading `services/settings_service.py` and `routes/settings.py`:

- The raw key is **never** returned in any response body. `ApiKeyStatus` (schemas/settings.py:4-9) has `configured: bool`, `source: str | None`, `masked: str | None`. The `GET /api/settings/api-key` and `PUT /api/settings/api-key` endpoints both populate `masked` via `settings_service.mask_key(key)`, never the raw value.
- `mask_key` (settings_service.py:10-15) returns `f"{key[:5]}…{key[-4:]}"` for keys longer than 10 chars; for short keys returns `•` repeated. For a typical Anthropic key (`sk-ant-api03-…`, ~108 chars), the user sees `sk-an…abcd` — 5 prefix + 4 suffix exposed. The 5-char prefix is deterministic across all Anthropic keys (`sk-an`), so effectively only 4 random chars (the suffix) leak. Acceptable, though one could argue for `•••…abcd`.
- The key is **never logged**: `claude_analysis.py:22` declares a logger but never calls it; the only log call sites in the codebase (`background_removal.py:58`, `hat_analysis_pipeline.py:75`) do not include the key. The `analysis_error` text persisted to the Hat row comes from `str(exc)` of `ClaudeAnalysisError` — that exception text is built from the SDK exception, which does not echo the API key in its messages (verified by inspection of the SDK exception classes used: AuthenticationError, APIError).
- The key is **stored in plaintext** in `app_settings.value` in SQLite. There is no app-level encryption. Rationale (single-user Pi): acceptable. **But** combined with the SPA path-traversal vulnerability (T1), the key is reachable to anyone who can hit the HTTP port. Path-traversal → read `/data/headroom.db` → `sqlite3` → `SELECT value FROM app_settings`.
- The key is **transmitted in cleartext** between client and server because the app does not configure TLS — that is expected for a Pi behind a reverse proxy / Tailscale, but the README should make this dependency explicit.

## 5. Supply Chain

### Heavy new deps (per Roentgen)
| Dep | Pin | Notes |
|---|---|---|
| `anthropic` | `>=0.40.0` (lock 0.97.0) | Active, well-maintained, official SDK. Pulls jiter, distro, docstring-parser, jsonschema. Low risk. |
| `rembg[cpu]` | `>=2.0.50` | Single maintainer (danielgatis). Pulls numpy, numba, llvmlite, scipy, scikit-image, tifffile, imageio, pymatting, pooch, networkx, lazy-loader. **Wide blast radius**; numpy/numba have CVE history. Also pulls `pooch` which downloads model files (uses MD5 — see model fetch above). |
| `onnxruntime` | unpinned | Microsoft, trusted upstream but binary wheels can be large; ARM64 wheels exist. |
| `Pillow` | unpinned | Mature; CVE history non-trivial; should be **pinned** in pyproject.toml to a known-good 10.x or 11.x baseline so a yanked transitive doesn't slip in. |
| `pillow-heif` | unpinned | Wraps libheif1 from system; CVE-2023-4863-style webp issues are in a related codec but libheif itself has had CVEs. |
| `httpx` | unpinned | **Declared at top level but only directly imported in tests/conftest.py.** Anthropic SDK pulls it transitively. Either move to `[dependency-groups] dev` or remove. Harmless either way. |
| `beautifulsoup4` | unpinned | **Declared but never imported anywhere in src/ or tests/.** Dead dependency. Remove. |

### Pinning hygiene
Only two deps pin a floor (`anthropic>=0.40.0`, `rembg[cpu]>=2.0.50`). Everything else is unpinned; `uv.lock` provides reproducibility for a fresh build but `uv sync --upgrade` would silently roll forward. For a Pi build that may go months between rebuilds, this is the right tradeoff. For a security-sensitive deployment, prefer `uv lock --upgrade-package <name>` per upgrade.

### Model supply chain
- `u2netp.onnx` is fetched at Docker build time by rembg from `https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx` over TLS, with MD5 checksum `8e83ca70e441ab06c318d82300c84806` baked into rembg's `U2netpSession.download_models`. MD5 is weak as a cryptographic primitive but adequate to detect accidental corruption/CDN issues; the integrity guarantee is "rembg's source code is what the operator built, and rembg trusts this hash." If an attacker compromised the GitHub release artifact AND rembg's source AND the MD5 wasn't updated, that's beyond this threat model. Document acknowledgement: trust transferred to rembg + GitHub.
- Model file is **pre-downloaded into the Docker image** (Dockerfile:50) so runtime never reaches out for it. Good — no runtime dependency on github.com being up, no surprise download on first photo.

## 6. Injection / SSRF / Path Traversal

### Filename handling
- `utils/photo.py:9-11` `generate_filename`: `f"{uuid.uuid4().hex}{ext}"` where `ext = Path(original_filename).suffix.lower()`. The user-supplied filename influences only the extension. `Path(...).suffix` extracts `.foo` from anywhere; a filename like `../../etc/passwd.jpg` returns `.jpg`, not `/passwd`. **Safe.**
- `routes/hats.py:156-162` writes to `upload_dir / filename` where `filename = generate_filename(photo.filename or "photo.jpg")`. The directory is fixed at `settings.upload_dir / "hats"`. Path traversal via filename is structurally impossible.
- `routes/settings.py:54-77` `upload_logo`: uses `Path(photo.filename or "logo.png").suffix.lower()` only for suffix sniff; final path is `branding_dir / f"logo{out_ext}"`. **Safe.**

### SQL
- All ORM queries use SQLAlchemy parameter binding via `select(Model).where(col == value)` and `col.ilike(pattern)`. No `text()` interpolation with user input anywhere in services/. The two `text()` call sites in `database.py` (migrations + ensure_default_room) use static SQL literals only — verified at lines 37-90 and 93-101.
- `case_service.py:61` uppercases display_id then compares — no `like`, no interpolation. Safe.

### Image processing
- Pillow against malicious bytes: `process_image` (utils/photo.py:14-37) calls `Image.open(input_path)`. **No try/except**, **no `Image.MAX_IMAGE_PIXELS` override**, **no input size cap**. Pillow will raise `DecompressionBombError` at 2× the default 89,478,485 px and `DecompressionBombWarning` at 1×. Errors propagate as 500. The file remains in the tempfile until `finally` cleanup — but there's no `finally` block in `routes/hats.py:153-163` either, so a Pillow exception leaves the tempfile in /tmp. For HEIC/HEIF the bytes pass through libheif1 (system) which has a separate CVE history. **Mitigations recommended**: (a) reject content-length above N MB at uvicorn level; (b) `Image.MAX_IMAGE_PIXELS = 50_000_000`; (c) `try/finally` to unlink the tempfile.

### `/uploads` static mount (app.py:69-73)
- Uses `StaticFiles(directory=str(settings.upload_dir))`. **Verified safe** by direct test: requests like `/uploads/%2e%2e/foo` and `/uploads/..%2ffoo` return 404. Starlette's StaticFiles normalizes and bounds the path inside `directory`.

### `/{full_path:path}` SPA fallback (app.py:83-89) — **CRITICAL**
- The handler computes `file_path = FRONTEND_DIST / full_path` then checks `file_path.is_file()`. `Path.__truediv__` does **not** normalize `..` segments; `is_file()` happens against the resolved filesystem path. URL-decoded `..` traverses out of FRONTEND_DIST.
- **Verified** by raw ASGI test (this audit, see notes): `GET /%2e%2e/secret_test.txt` and `GET /..%2fsecret_test.txt` returned the file content from `/tmp/secret_test.txt` outside `FRONTEND_DIST`. A raw ASGI scope with `path='/../../tmp/secret_test.txt'` also worked.
- **Reachable targets** (in Docker as headroom uid 1000): `/data/headroom.db` (Anthropic key in plaintext), `/app/src/headroom/**` (source + secrets in any future config), `/etc/passwd`, `/etc/hostname`, `/proc/self/environ`. Not reachable: `/etc/shadow` (root-owned), `/root/**` (perms).
- **Fix**: After computing `file_path`, validate `FRONTEND_DIST.resolve() in file_path.resolve().parents` (or use `Path.is_relative_to(FRONTEND_DIST.resolve())` in 3.9+). Alternatively, simplify by just always serving `index.html` for non-`/assets/` and non-`/api/` requests and let `/assets/` mount handle the rest.

### `display_id` URL parameter
- Bound to `case_service.get_case_by_display_id(db, display_id)` which calls `.where(Case.display_id == display_id.upper())`. Parameter binding, no interpolation. Safe.

### Outbound HTTP (SSRF)
- Anthropic SDK call uses `model=settings.anthropic_model` and the endpoint is fixed inside the SDK. Not user-controllable.
- `melin_recap.py` builds URLs from a hardcoded base + a fixed dict (`_STYLE_TO_CATEGORY`). The brand string from Claude is checked with `is_melin()` (case-insensitive substring `melin in brand.lower()`); the style string is mapped through the dict — unknown styles fall through to `MELIN_BASE` itself. There is no `httpx` import, no `requests`, no `urllib.request` — **verified no fetch happens today.**

## 7. Pipeline-specific risks

### Claude tool-use → DOM
- The `colors[].hex` field is parsed at `claude_analysis.py:228` as `c["hex"]` with no regex re-validation. The tool input_schema specifies `"pattern": "^#[0-9a-fA-F]{6}$"` but that pattern is **only** an instruction in the JSON-Schema sent to Claude, not enforced by the SDK or any server-side parser. The Anthropic SDK does not run JSON-Schema validation against tool_use.input by default.
- The hex value flows to `HatColor.hex_value` (DB) → HatRead JSON → `style={{ backgroundColor: c.hex_value }}` in HatDetailPage.tsx:259 and ColorSwatch.tsx:13.
- React passes inline-style values to the DOM as a per-property string. CSS `background-color` parsing rejects values that don't match a color grammar — **but** `backgroundColor: "red; background-image: url('http://evil/x.png')"` is parsed as `red; ...` and modern browsers may set both. **Tested behavior depends on the browser**: WebKit/Chromium typically reject the whole declaration if it contains `;`. Risk is therefore low but non-zero — a malicious model output could plausibly inject a tracking-pixel URL on a permissive engine.
- **Recommendation**: validate `^#[0-9a-fA-F]{6}$` at the parser boundary (`claude_analysis.py:222-242`) and either coerce to a default color or drop the color entry. Also: Pydantic-validate the Hat color writes from `routes/hats.py:118-139` (`update_hat_colors`) which currently accepts an arbitrary `ColorTag` from the client — `ColorTag.hex_value` has no pattern constraint either.
- Other AI fields (`brand`, `model_name`, `style_descriptor`, `design_notes`, `analysis_error`) are rendered as React text children → auto-escaped → no XSS even with `<script>` payloads.
- `resale_price_url` is built from hardcoded MELIN_BASE + urlencode of constrained values → **not** AI-controlled. Safe.

### rembg ONNX model integrity
- Pre-downloaded at `Dockerfile:50`. Source: `https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx`, MD5 `8e83ca70e441ab06c318d82300c84806`, verified by `pooch` inside `U2netpSession.download_models` (`.venv/.../rembg/sessions/u2netp.py:54-64`). MD5 is sufficient for integrity-against-corruption; for adversarial integrity, an attacker controlling either GitHub releases or rembg's source could swap in a hostile model. The blast radius of a hostile rembg model is limited to producing wrong masks — it cannot RCE the host because ONNX inference is data-only. **Acceptable.**

## 8. Container Security

- **Non-root**: Dockerfile:67-83 creates a system user `headroom` with uid/gid 1000, sets `HOME=/home/headroom`, `WORKDIR /app`, then `USER headroom`. Verified.
- **PID 1**: tini at `Dockerfile:88` (`ENTRYPOINT ["/usr/bin/tini", "--"]`). Reaps zombies, propagates signals.
- **/data volume permissions**: `Dockerfile:80-81` does `mkdir -p /data/uploads/...` AND `chown -R headroom:headroom /data /app` BEFORE switching to `USER headroom`. Correct.
- **rembg model under non-root**: `Dockerfile:73` is `COPY --from=python-base --chown=headroom:headroom /root/.u2net /home/headroom/.u2net`. The chown is correct. The location matches `os.path.expanduser("~/.u2net")` because `useradd --home-dir /home/headroom` sets `HOME=/home/headroom` for the headroom user. **Model loads correctly under the non-root user.** Verified by inspecting `rembg/sessions/base.py:74-80` (`u2net_home` resolution).
- **Capabilities**: docker-compose.yml does not drop capabilities, doesn't set `read_only: true`, doesn't set `cap_drop`. Process runs as uid 1000 but with default Linux capabilities. For a personal Pi this is acceptable; for hardening, consider `cap_drop: [ALL]`, `read_only: true`, `tmpfs: [/tmp]`, `security_opt: [no-new-privileges:true]`.
- **No HEALTHCHECK** (Dockerfile) and **no `healthcheck:` block** (docker-compose) — operational hygiene issue, not a security one. (Already flagged by Auscultator.)
- **No resource limits** (mem, cpu) — combined with the unbounded upload size (T4), the container can eat the Pi's RAM.

## 9. Ranked Findings

### CRITICAL

**S1. Path traversal via SPA fallback** — `src/headroom/app.py:83-89`
```
@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    file_path = FRONTEND_DIST / full_path
    if file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(FRONTEND_DIST / "index.html")
```
Verified exploitable via URL-encoded `..` and via raw ASGI. Reads any file readable by the headroom user, including `/data/headroom.db` (extracts the Anthropic API key in plaintext).

**Remediation** (any one):
```
file_path = (FRONTEND_DIST / full_path).resolve()
if file_path.is_file() and file_path.is_relative_to(FRONTEND_DIST.resolve()):
    return FileResponse(file_path)
return FileResponse(FRONTEND_DIST / "index.html")
```
Or restrict the SPA fallback to a known list of SPA route paths and let StaticFiles handle the rest.

### HIGH

**S2. No authentication on /api/settings/api-key endpoints** — `src/headroom/routes/settings.py:92-126`. Anyone reaching the port can `GET` (masked), `PUT` (set / replace with attacker key), `DELETE` (lock out), `POST /test` (burn quota). Combined with no auth elsewhere, the entire app is an unprivileged playground. **Within the stated single-user-LAN-only Pi threat model, acceptable.** **Outside it (Tailscale-exposed, public, untrusted LAN), a hard fail.** Remediation: require an upstream auth proxy (Tailscale ACL, Cloudflare Access, oauth2-proxy, basic auth via Caddy) AND/OR add a server-side admin token check on `/api/settings/*`.

**S3. CSRF on multipart upload endpoints** — `routes/hats.py:142`, `routes/cases.py:96`, `routes/settings.py:42`. Multipart form posts are CORS-simple (no preflight). A malicious page in a tab the user has open can POST attacker bytes to overwrite hat/case photos and the logo. Remediation: require a same-origin `Origin` header check in middleware, or add a custom header (`X-Requested-By: headroom`) which forces preflight.

**S4. No upload size limit anywhere** — uvicorn launched with no `--limit-max-requests` / `--limit-concurrency` flags (Dockerfile:89), Starlette has no default body cap, FastAPI doesn't enforce one. A single multipart POST can fill the Pi's disk or RAM. Remediation: add `Middleware(LimitUploadSize, max_size=20 * 1024 * 1024)` or check `request.headers.get("content-length")` in the upload routes.

### MEDIUM

**S5. No image-bomb cap and no try/finally around tempfile** — `utils/photo.py:14-37`, `routes/hats.py:153-163`, `routes/cases.py:111-118`. A malicious PNG with extreme dimensions triggers Pillow's `DecompressionBombError`; the tempfile is leaked because there's no `finally`. Add `Image.MAX_IMAGE_PIXELS = 50_000_000` and wrap in try/finally.

**S6. Claude tool-use response not re-validated** — `services/claude_analysis.py:222-242`. The JSON-Schema in `HAT_ANALYSIS_TOOL.input_schema` is a hint to Claude, not an SDK invariant. A malicious or hallucinating model can return any string for `colors[].hex`, which lands in a CSS inline style. Remediation: validate hex with a regex post-parse; coerce to `#000000` or drop on mismatch. Also tighten the post-parse for `model_confidence ∈ {high,medium,low}` and `colors[].tier ∈ {primary,secondary,tertiary,accent}`.

**S7. No security headers** — no CSP, X-Frame-Options, Referrer-Policy, X-Content-Type-Options. The SPA could be iframed by any site (clickjacking). Remediation: add a minimal middleware setting `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, and a CSP starting with `default-src 'self'; img-src 'self' data:`.

**S8. ApiKeyUpdate.api_key length (8-200) and lack of format check** — `schemas/settings.py:13`. Anthropic keys are ~108 chars. An 8-char garbage value is accepted, gets saved, and then the next photo upload returns "Invalid Anthropic API key" via the test/upload path. Functional, not security — but a basic `startswith("sk-")` check would help. Note: this also means an attacker can plant a short garbage key that costs nothing to try but locks out the operator.

### LOW

**S9. Mask reveals 4 trailing chars of the API key** — `services/settings_service.py:10-15`. The first 5 chars (`sk-an`) are deterministic; the last 4 are a real entropy leak. For a single-user Pi this is fine; for paranoid operation, mask to `•••…•` or only show "configured" without any character disclosure.

**S10. Dead dependency: beautifulsoup4** — `pyproject.toml:18`. Not imported anywhere. Remove to shrink attack surface.

**S11. httpx declared at top level but only used in tests** — `pyproject.toml:17`. Move to dev group, or accept that it's transitively required by anthropic. Cosmetic.

**S12. No .gitignore verified for frontend/headroom.db** — Roentgen flagged a stray `frontend/headroom.db`. If tracked in git it leaks any UI-stored API key. Verify it's `.gitignore`'d (and never committed historically).

**S13. No logging configuration** — `logging.basicConfig` never called; only two log call sites in the entire backend. Already covered by Auscultator. Security implication: an attacker probing the box leaves no audit trail beyond uvicorn access logs (no log rotation either).

### INFORMATIONAL

**S14. Anthropic model id `claude-sonnet-4-6`** — `config.py:15`. Doppler flagged this as possibly a typo. Not a security issue per se, but if the model id is wrong every Claude call 404s and writes a 404 message into `analysis_error` which renders to the DOM. Confirm the id is correct before shipping. (Today's date 2026-05-02 — a `claude-sonnet-4-6` may exist by now.)

**S15. CORS posture is correct** — Origin allowlist is explicit, not wildcard, with `allow_credentials=True`. This is the safe combination. No change needed.

**S16. /uploads static mount is hardened** — verified. No traversal possible.

**S17. SQL queries use parameter binding throughout** — verified. SQL injection structurally impossible at current call sites.

**S18. Filename handling uses uuid4** — verified. Path traversal via uploaded filename impossible.

**S19. Container runs as non-root with rembg model owned correctly** — verified.

**S20. rembg model fetched at build time from GitHub with MD5 verification** — adequate for the threat model.

**S21. melin_recap module performs zero outbound HTTP today** — verified by direct grep; no `httpx`, `requests`, `urllib.request` imports. Roentgen's claim holds.

---

## Summary table

| ID | Severity | Title | Anchor |
|---|:---:|---|---|
| S1 | **Critical** | Path traversal in SPA fallback | app.py:83-89 |
| S2 | High | No auth on /api/settings/api-key (out-of-scope for stated threat model) | routes/settings.py:92-126 |
| S3 | High | CSRF on multipart upload endpoints | routes/{hats,cases,settings}.py |
| S4 | High | No upload size limit (disk/memory DoS) | uvicorn/Starlette defaults |
| S5 | Medium | No image-bomb cap; no try/finally around tempfile | utils/photo.py:14-37 |
| S6 | Medium | Claude tool-use response not re-validated post-parse | claude_analysis.py:222-242 |
| S7 | Medium | No security headers (CSP, XFO, etc.) | app.py middleware stack |
| S8 | Medium | ApiKeyUpdate accepts 8-char garbage | schemas/settings.py:13 |
| S9 | Low | mask_key reveals 4-char suffix | settings_service.py:10-15 |
| S10 | Low | Dead dep: beautifulsoup4 | pyproject.toml:18 |
| S11 | Low | httpx declared at top level, only used in tests | pyproject.toml:17 |
| S12 | Low | Verify frontend/headroom.db is .gitignore'd | repo root |
| S13 | Low | No logging configuration → no audit trail | (Auscultator) |
| S14 | Info | Verify anthropic_model id is correct | config.py:15 |
| S15-S21 | Info | Things that are correct (CORS, /uploads mount, SQL, filename handling, container, model fetch, melin no-fetch) | various |

For the stated single-user-on-Pi-LAN threat model, **S1 is still a critical regardless of deployment** because the API key in `/data/headroom.db` is reachable to anyone who hits the port. Everything else (S2-S13) is appropriately handled by the assumption "trusted LAN, single user" — but should be revisited the moment the Pi is exposed to anything wider (including other family members on the same Wi-Fi who are using shared browsers).
