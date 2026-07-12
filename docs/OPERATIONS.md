# Headroom Operations Guide

Everything about *running* Headroom: deployment, configuration, health,
backups, upgrades, and troubleshooting. For using the app itself, see
[USAGE.md](USAGE.md). For a quick start, see the [README](../README.md).

---

## 1. Deployment options

### Docker (recommended — Mac, Linux, Raspberry Pi)

```bash
git clone https://github.com/59psi/headroom.git && cd headroom
./scripts/setup.sh --docker-only   # installs a Docker engine if missing; no-op otherwise
docker compose up --build -d
```

- The container runs as a non-root user, serves on port **8000**, and stores
  all state (database, photos, backups) in the `headroom-data` named volume
  mounted at `/data`.
- The Docker engine installed by the setup script is **not Docker Desktop**:
  colima + docker CLI + compose/buildx via Homebrew on macOS, native Docker
  Engine via Docker's official script on apt/dnf Linux.
- **Internet-facing with HTTPS**: point DNS at the host, open 80/443, then

  ```bash
  HEADROOM_DOMAIN=hats.example.com \
    docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
  ```

  The overlay adds a Caddy sidecar with automatic Let's Encrypt
  certificates, stops exposing port 8000 directly, and sets the passkey
  identity (`HEADROOM_RP_ID`/`HEADROOM_ORIGIN`) from the domain.
- On Linux the script adds your user to the `docker` group — log out/in (or
  `newgrp docker`) before the first `docker compose` command.
- macOS + colima: the VM does not auto-start after a reboot. Either run
  `colima start`, or make it a login service: `brew services start colima`.

### Bare metal (no Docker)

```bash
git clone https://github.com/59psi/headroom.git && cd headroom
./scripts/setup.sh --no-docker     # installs uv/Node/deps, inits DB, builds the SPA
uv run uvicorn headroom.app:app --host 0.0.0.0 --port 8000
```

State lives in the project directory: `headroom.db`, `uploads/`, and
`backups/` (sibling of the uploads dir). Run it under systemd / launchd /
tmux as you prefer; the app has no supervisor of its own.

### Development

```bash
uv run uvicorn headroom.app:app --reload    # backend :8000
cd frontend && npm run dev                  # frontend :5173, proxies /api + /uploads
```

---

## 2. Configuration

All settings are environment variables with the `HEADROOM_` prefix
(pydantic-settings). API keys set via the Settings UI are stored in the
database and **always win over the environment** — env vars are the
fleet-default, the UI is the per-install override.

| Variable | Default | Notes |
|---|---|---|
| `HEADROOM_DATABASE_URL` | `sqlite+aiosqlite:///./headroom.db` | Docker image sets `sqlite+aiosqlite:////data/headroom.db` |
| `HEADROOM_UPLOAD_DIR` | `uploads` | Docker image sets `/data/uploads` |
| `HEADROOM_CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list. Compose file sets `["http://localhost:8000"]` |
| `HEADROOM_ANTHROPIC_API_KEY` | _(unset)_ | Claude Vision analysis. DB value wins |
| `HEADROOM_ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Changeable in the Settings UI too |
| `HEADROOM_GOOGLE_VISION_API_KEY` | _(unset)_ | Fallback brand (logo) detection. DB value wins |
| `HEADROOM_MELIN_CLIENT_ID` | _(baked in)_ | Public Sharetribe client id for live Melin resale stats; override only if Treet rotates it |
| `HEADROOM_EBAY_APP_ID` / `HEADROOM_EBAY_CERT_ID` | _(unset)_ | eBay Browse API comps. Must be a **Production** keyset (sandbox keys 401) |
| `HEADROOM_RP_ID` | `localhost` | Passkey (WebAuthn) relying-party id — must equal the serving domain. Set automatically by the HTTPS overlay |
| `HEADROOM_ORIGIN` | `http://localhost:8000` | Full origin for passkey verification. Set automatically by the HTTPS overlay |
| `HEADROOM_HTTP_TIMEOUT` | `30.0` | Outbound HTTP (Claude, Google, eBay, Melin) |
| `HEADROOM_REMBG_MODEL` | `u2netp` | See §7 Raspberry Pi |
| `HEADROOM_LOG_LEVEL` | `INFO` | Applies when no other logging config is active |
| `HEADROOM_BACKUP_ENABLED` | `true` | Scheduled backups on/off (on-demand download always works) |
| `HEADROOM_BACKUP_INTERVAL_HOURS` | `24` | Scheduled backup cadence |
| `HEADROOM_BACKUP_RETENTION_DAYS` | `7` | Older scheduled backups are pruned |
| `HEADROOM_IMPORT_WORKER_ENABLED` | `true` | Bulk-import background worker |
| `HEADROOM_ACTIVITY_LOG_RETENTION_DAYS` | `90` | Audit rows pruned daily |

---

## 3. Health & monitoring

- `GET /health` — liveness: `{"status": "ok"}` if the process is up.
- `GET /health/ready` — readiness with per-dependency detail:

  ```json
  {"ok": true, "checks": {"database": {"ok": true},
                          "uploads_writable": {"ok": true, "path": "/data/uploads"},
                          "anthropic_key": {"ok": true, "configured": false, "source": null}}}
  ```

  Returns **503** when database or uploads checks fail. (`anthropic_key`
  is informational — an unconfigured key does not fail readiness.)
- The compose file wires `/health/ready` as the container healthcheck
  (30s interval, 30s start period).
- **Logs**: `docker compose logs -f` (JSON-file driver, capped 10 MB × 5
  files). Failed analyses are logged at WARNING; external-API degradations
  (eBay, Melin, Google) at INFO — they are best-effort by design.
- **In-app**: Settings shows *Recent analysis errors* (hats whose analysis
  failed, with the error text) and the *Activity log* (append-only audit
  of every significant change, pruned daily per retention).

---

## 4. Backups & restore

**Scheduled**: a rolling `tar.gz` (database + uploads) is written every
`HEADROOM_BACKUP_INTERVAL_HOURS` to `backups/` next to the upload dir —
`/data/backups/` in Docker. Files are named
`headroom-backup-<timestamp>.tar.gz`; ones older than the retention window
are pruned after each new write. The Settings page lists them.

**On-demand**: Settings → Backup, or
`GET /api/admin/backup` (add `?include_uploads=false` for a database-only
archive). This streams a fresh archive — use it before upgrades or before
experimenting.

**Restore** — archive contents are prefixed `data/` (`data/headroom.db`,
`data/uploads/…`). Docker:

```bash
docker compose down
docker run --rm -v headroom_headroom-data:/data -v "$PWD":/backup alpine \
  tar xzf /backup/headroom-backup-<timestamp>.tar.gz -C /
docker compose up -d
```

Bare metal: stop the server, then from the project root
`tar xzf headroom-backup-<timestamp>.tar.gz --strip-components=1`
(restores `./headroom.db` + `./uploads/`), start again.

Off-machine safety: periodically copy the newest file out of the backups
directory (or download via the Settings page) to somewhere that isn't the
same disk.

---

## 5. Upgrades

```bash
git pull
docker compose up --build -d     # Docker
# — or —
./scripts/setup.sh --no-docker   # bare metal: re-sync deps + rebuild SPA, then restart uvicorn
```

- Database migrations are **automatic**: `init_db()` runs inline DDL
  migrations at every boot. There is no separate migrate step and no
  downgrade path — take a backup before major upgrades.
- Version sanity check: the footer of the web app shows the running build's
  version; compare with `CHANGELOG.md`.

---

## 6. Security posture (v1.0+)

Accounts are mandatory. On first boot no users exist; the first visit to
the web app runs **first-run setup** (create the owner account), after
which every data-bearing route requires authentication.

**What's protected:** all of `/api/*` and the `/uploads/*` photo mount —
via session cookie or bearer API token. **What's open by design:** the SPA
shell + hashed JS/CSS assets + PWA manifest/icons (no data in them),
`/health*` (probes), `/api/auth/*` (each endpoint self-guards), and
`/api/public/share/*` (the share-link token *is* the credential).

- **Sessions**: opaque 256-bit tokens, stored server-side (revocable),
  30-day expiry, httpOnly + SameSite=Lax cookies; the `secure` flag is set
  automatically when serving over HTTPS (uvicorn runs with
  `--proxy-headers`, so the Caddy overlay's X-Forwarded-Proto is honored).
- **Passwords**: argon2id hashes. Login is rate-limited per IP+username
  (5 failures → 15-minute lockout).
- **Passkeys (WebAuthn)**: add one from Settings → Account for Face ID /
  Touch ID sign-in. Requires a secure context (HTTPS or localhost) and
  `HEADROOM_RP_ID`/`HEADROOM_ORIGIN` matching the serving domain — the
  HTTPS overlay sets both from `HEADROOM_DOMAIN`.
- **API token**: each user has a static bearer token (Settings → Account,
  rotatable) for cookie-less clients — the iOS Shortcut import needs it in
  an `Authorization: Bearer …` header.
- **Share links**: 256-bit random tokens granting read-only access to the
  collection view and token-gated photo streaming; revocable, optional
  expiry. Revoking is immediate.
- Raw API keys (Anthropic/Google/eBay) are **never returned** by the API —
  status endpoints reply with a masked prefix/suffix only.
- `HEADROOM_ADMIN_TOKEN` is retired and ignored.

**Forgot the password?** There's no email reset (nothing to send from).
With shell access:
`sqlite3 /data/headroom.db "DELETE FROM users; DELETE FROM auth_sessions;"`
then reload the app — first-run setup reappears. Guard your backups
accordingly: they contain the database.

Tailscale/VPN remains a fine *additional* layer, but is no longer the only
thing standing between the internet and your hats.

---

## 7. Raspberry Pi notes

- The image is multi-arch (amd64 + arm64); build on the Pi (slow first
  build) or build/push from a faster machine with
  `docker buildx build --platform linux/arm64,linux/amd64 -t <registry>/headroom:latest --push .`
- The rembg model is pre-downloaded **into the image** at build time so the
  Pi never fetches it at runtime. Default `u2netp` (4.7 MB) takes 5–15 s per
  photo on a Pi 4. `HEADROOM_REMBG_MODEL=isnet-general-use` gives sharper
  cutouts at the cost of a ~170 MB model and slower inference — rebuild the
  image after changing it (the model bakes in via a build arg).
- SQLite on an SD card is fine at hat-collection scale, but SD cards die:
  that's what §4's off-machine backup copy is for.

---

## 8. External services & failure modes

Every external call is best-effort — **no outage ever blocks an upload**:

| Service | Used for | Needs | On failure |
|---|---|---|---|
| Anthropic (Claude Vision) | brand/model/colors/price/notes | API key | hat marked `error`/`skipped`, fallback analysis runs |
| Local mask extraction | fallback colors | nothing | no colors if bg-removal failed |
| Google Cloud Vision | fallback brand via logo | API key (free tier 1,000/mo) | fallback proceeds colors-only |
| eBay Browse API | sold-comparable stats | Production App ID + Cert ID (5,000 calls/day free) | comps skipped, logged INFO |
| Melin Recap (Sharetribe) | live resale median | nothing (public API) | deep link only, price stays null |

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `unknown shorthand flag: 'd' in -d` or `'compose' is not a docker command` | Compose v2 plugin missing — `./scripts/setup.sh --docker-only` |
| `Cannot connect to the Docker daemon` | Engine not running: `colima start` (macOS) / `sudo systemctl start docker` (Linux) |
| Logo/images 404 on first boot | Fixed in v0.6.4 — upgrade; the `/uploads` mount no longer depends on boot order |
| Frontend shows "Frontend not built" | `cd frontend && npx vite build` (or rerun setup.sh), then restart uvicorn |
| eBay test fails with 401 | Sandbox keyset — the Settings page flags `SBX` keys; create a **Production** keyset |
| Analysis stuck on `skipped` | No Anthropic key; add one in Settings and hit Reanalyze (fallback colors/brand still apply meanwhile) |
| Forgot the password | `sqlite3 /data/headroom.db "DELETE FROM users; DELETE FROM auth_sessions;"` → first-run setup reappears (§6) |
| iOS Shortcut import started failing after v1.0 | Add an `Authorization: Bearer <api-token>` header to the Shortcut — token in Settings → Account |
| Passkey button missing / erroring | Passkeys need HTTPS (or localhost) AND `HEADROOM_RP_ID` = the serving domain — use the HTTPS overlay |
| Melin price stopped appearing | Treet may have rotated the public client id — grab the new one from their site bundle and set `HEADROOM_MELIN_CLIENT_ID` |
| Bulk import queued but idle | Check `HEADROOM_IMPORT_WORKER_ENABLED`; queued items re-enqueue automatically on restart |
| Tests polluted `uploads/` with tiny images | Fixed in v0.7.0 (isolated test uploads); stray sub-10 KB files are safe to delete |
