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
- **LAN-only by name (`headroom.local`)**: the app advertises itself over
  mDNS, but multicast can't cross Docker's bridge network — stack
  `docker-compose.mdns.yml` (host networking, Linux/Pi only). Host networking
  claims only the ports the app binds; other services on the host are
  unaffected. For passkeys on the LAN name, use `docker-compose.https-lan.yml`
  *instead* (includes mDNS + host networking): it fronts the app with Caddy's
  internal CA on 443. Each device must trust the exported root cert once —
  full walkthrough in the README ("HTTPS on the LAN"). The Settings page
  shows live mDNS status read-only.
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
(pydantic-settings). API keys, the model and the eBay credentials set via the
Settings UI are stored in the database and **win over the environment** — env
vars are the fleet-default, the UI is the per-install override. (One
exception, the other way round: an off-box upload configured with
`HEADROOM_BACKUP_UPLOAD_CMD` overrides the provider chosen in the Backups
card, so a scripted command a fleet relies on cannot be switched off from a
phone.)

**Under Docker, a variable reaches the app only if `docker-compose.yml`
forwards it.** A `.env` beside the compose file is read by Compose for
interpolation, not handed to the container — so every `HEADROOM_*` knob below
is listed in the compose file's `environment:` block as `${VAR:-}`, and an
empty value is treated as unset by the app. Until 2.78 most of this table was
not forwarded at all: `HEADROOM_SETUP_TOKEN` in `.env` protected nothing, and
`HEADROOM_MDNS_HOSTNAME=hats` renamed Caddy's site while the app went on
advertising `headroom.local`. A test now parses the compose file against the
names the code reads, so a new knob cannot silently join that list.

| Variable | Default | Notes |
|---|---|---|
| `HEADROOM_DATABASE_URL` | `sqlite+aiosqlite:///./headroom.db` | Docker image sets `sqlite+aiosqlite:////data/headroom.db` |
| `HEADROOM_UPLOAD_DIR` | `uploads` | Docker image sets `/data/uploads` |
| `HEADROOM_CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list. Compose file sets `["http://localhost:8000"]` |
| `HEADROOM_ANTHROPIC_API_KEY` | _(unset)_ | Claude Vision analysis. DB value wins |
| `HEADROOM_ANTHROPIC_MODEL` | `claude-sonnet-5` | Changeable in the Settings UI too |
| `HEADROOM_GOOGLE_VISION_API_KEY` | _(unset)_ | Fallback brand (logo) detection. DB value wins |
| `HEADROOM_MELIN_CLIENT_ID` | _(baked in)_ | Public Sharetribe client id for live Melin resale stats; override only if Treet rotates it |
| `HEADROOM_EBAY_APP_ID` / `HEADROOM_EBAY_CERT_ID` | _(unset)_ | eBay Browse API comps. Must be a **Production** keyset (sandbox keys 401) |
| `HEADROOM_SETUP_TOKEN` | _(unset)_ | When set, first-run setup also requires this token (the setup form always shows a *Setup token* field, marked "only if configured"; leave it blank when unset). Closes the window where whoever reaches the host first can claim the owner account — worth setting on an internet-facing deployment, unnecessary on a LAN. See §6 |
| `HEADROOM_RP_ID` | `localhost` | Passkey (WebAuthn) relying-party id — must equal the serving domain. Set automatically by the HTTPS overlay |
| `HEADROOM_ORIGIN` | `http://localhost:8000` | Full origin for passkey verification. Set automatically by the HTTPS overlay |
| `HEADROOM_HTTP_TIMEOUT` | `30.0` | Outbound HTTP to Claude, Google Vision and Melin Recap. eBay uses its own fixed 10–12 s timeouts |
| `HEADROOM_REMBG_MODEL` | `isnet-general-use` | See §7 Raspberry Pi |
| `HEADROOM_ANALYSIS_WORKER_ENABLED` | `true` | Queue photo analysis off the request. Off = run it inline (slow uploads) |
| `HEADROOM_REMBG_CONCURRENCY` | `1` | Concurrent background-removal inferences. Both workers reach rembg, and one inference is a 179 MB model plus a full-resolution decode — the app's largest allocation, so `1` inside a 1 GB container |
| `HEADROOM_REPRICING_ENABLED` | `true` | Nightly re-pricing of every melin hat against live Melin Recap asks — independent of analysis, no Claude call. Off = prices move only when you press *Re-price now* / *Re-price all* in Settings → Data |
| `HEADROOM_REPRICING_INTERVAL_HOURS` | `24` | Sweep cadence (floor 0.25) |
| `HEADROOM_REPRICING_DELAY_SECONDS` | `1.0` | Pause between hats — pacing for somebody else's public API |
| `HEADROOM_REPRICING_BATCH_LIMIT` | `0` | Cap hats per sweep; `0` = the whole shelf. A capped sweep visits the stalest prices first and resumes there next time |
| `HEADROOM_LOG_LEVEL` | `INFO` | Applies when no other logging config is active |
| `HEADROOM_BACKUP_ENABLED` | `true` | Scheduled backups on/off (on-demand download always works) |
| `HEADROOM_BACKUP_INTERVAL_HOURS` | `24` | Scheduled backup cadence |
| `HEADROOM_BACKUP_KEEP` | `5` | Keep the newest N local scheduled backups (a **count**; `HEADROOM_BACKUP_RETENTION_DAYS` is still read, as a count, for existing `.env` files) |
| `HEADROOM_SQLITE_SYNCHRONOUS` | `FULL` | SQLite durability. **`FULL` fsyncs the WAL on every commit** — committed means committed, even through a power cut. Was `NORMAL`, which is SQLite's own WAL recommendation and safe from *corruption* but **not from loss**: under `NORMAL` the WAL syncs at a checkpoint rather than at commit, so a committed transaction "might roll back following a power loss", and the default 1000-page threshold means what is at risk is every write since the last checkpoint. `FULL` costs one fsync per commit — negligible for this workload, and the reason the default changed after an unclean shutdown destroyed files on the deployment's SD card. Accepts `FULL`/`EXTRA`/`NORMAL`/`OFF`; anything else logs a warning and falls back to `FULL` |
| `HEADROOM_MAX_BODY_BYTES` | `2097152` | Non-multipart request bodies over this are refused with 413 |
| `HEADROOM_DISK_MIN_FREE_MB` | `500` | `/health/ready` fails below this, so the container reports `unhealthy`. **Acting on that requires a watchdog — see §3** |
| `HEADROOM_DISK_WARN_PCT` | `15` | Warn in the log below this share of the volume |
| `HEADROOM_BACKUP_INCLUDE_CA` | `true` | Fold Caddy's local CA — **including its private keys** — into each backup, under `data/caddy-pki/`. On by default because the root is installed by hand on every device and nothing can vouch for a replacement, so losing it means visiting them all. Set `false` if you would rather not have a key that can sign for *any* host sitting in an archive you upload off-box. See §4 |
| `HEADROOM_BACKUP_UPLOAD_CMD` | _(unset)_ | Command run after each scheduled backup to ship it off-box; `{path}`/`{dir}`/`{name}` substituted (argv, no shell). Best-effort — see §4. **Read the encryption note in §4 before pointing this at cloud storage** |
| `HEADROOM_BACKUP_UPLOAD_TIMEOUT` | `600` | Seconds before the upload command is killed |
| `HEADROOM_BACKUP_RSYNC_PASSWORD` | _(unset)_ | Password for the **Synology / rsync-daemon** provider (`user@host::module/path`). Mapped to rsync's own `RSYNC_PASSWORD` at upload time; read from the host, never stored by Headroom and never returned by the API. **Daemon mode only** — rsync ignores it over SSH, which is why the SSH provider takes no secret rather than one that looks set and does nothing. `docker-compose.yml` forwards it into the container explicitly; Compose's `.env` alone would only feed interpolation |
| `HEADROOM_BACKUP_SSH_KEY` / `HEADROOM_BACKUP_KNOWN_HOSTS` | `~/.ssh/headroom-backup` / `~/.ssh/known_hosts` | **`docker-compose.backup-rsync.yml` only.** Host paths bind-mounted read-only into the container for the rsync-over-SSH provider |
| `HEADROOM_IMPORT_WORKER_ENABLED` | `true` | Bulk-import background worker |
| `HEADROOM_ACTIVITY_LOG_RETENTION_DAYS` | `90` | Audit rows pruned daily |
| `HEADROOM_MDNS_ENABLED` | `true` | Advertise the app on the LAN via mDNS. Docker needs the `docker-compose.mdns.yml` overlay (host networking) for it to reach the LAN |
| `HEADROOM_MDNS_HOSTNAME` | `headroom` | mDNS host label — the app resolves as `<label>.local` |
| `HEADROOM_MDNS_PORT` | `8000` | Port the mDNS advertisement points at |
| `HEADROOM_MDNS_INTERFACE` | _(detected LAN IP)_ | Which interface the responder binds. Defaults to the detected LAN address so a host-net container doesn't leak onto `docker0`/`veth`; an IP pins a specific NIC, `all` restores zeroconf's all-interfaces mode |
| `HEADROOM_SITE_ADDRESSES` | `<HEADROOM_MDNS_HOSTNAME>.local` | **LAN HTTPS overlay only.** Comma-separated list of every name and address Caddy answers on, and every name that goes in the certificate. Add the LAN IP or a VPN hostname to reach it where `.local` can't resolve — `"headroom.local, 10.0.111.4"`. Caddy rejects a TLS connection whose SNI matches nothing here, so an address not listed fails the handshake outright. Passkeys still only work on `HEADROOM_ORIGIN` |

---

## 3. Health & monitoring

- `GET /health` — liveness: `{"status": "ok"}` if the process is up.
- `GET /health/ready` — readiness with per-dependency detail:

  ```json
  {"ok": true, "checks": {
    "database": {"ok": true},
    "uploads_writable": {"ok": true, "path": "/data/uploads"},
    "anthropic_key": {"ok": true, "configured": false, "source": null},
    "disk": {"ok": true, "low": false, "free_bytes": 21474836480, "total_bytes": 62277025792,
             "free_pct": 34.5, "min_free_mb": 500},
    "import_worker": {"ok": true, "expected": true},
    "analysis_worker": {"ok": true, "expected": true, "queued": 0}}}
  ```

  Returns **503** when the database or uploads check fails, when free space
  on the data volume is below `HEADROOM_DISK_MIN_FREE_MB`, or when a worker
  that is *expected* (its `HEADROOM_*_WORKER_ENABLED` flag is on) is not
  alive. `anthropic_key` is informational — an unconfigured key does not
  fail readiness — and `disk.low` (below `HEADROOM_DISK_WARN_PCT`) is a
  warning, not a failure.
- **That payload is the *authenticated* view.** The endpoint is unauthenticated
  so Docker's healthcheck can reach it, so for anonymous callers it returns
  booleans only: `database`, `uploads_writable`, `anthropic_key` (configured
  or not, no `source`), `disk` collapsed to `{ok, low}` and the two workers
  collapsed to one `workers: {ok}` — no path, no capacity figures, no queue
  depth, no error text. Those two are present anonymously because they gate
  the 503 and a 503 with no reason is a worse artifact than one that names
  the check. Authenticate (session cookie or bearer token) for the detail
  above.
- The compose file wires `/health/ready` as the container healthcheck
  (30s interval, 30s start period).
- **⚠️ By default nothing acts on that healthcheck, and you have to choose a
  consumer.** Docker restart policies — including this stack's
  `restart: unless-stopped` — fire when a container **exits**. They never fire
  on `unhealthy`. So out of the box a container sitting up with a dead import
  worker, or a data volume with 200 MB free, reports `unhealthy` in
  `docker ps` and nothing else happens. The check is real; it just needs
  something watching it. Two options, neither enabled by default:

  | Option | Command | Trade-off |
  |---|---|---|
  | **Host timer** (recommended) | systemd units below + `scripts/headroom-watchdog.sh` | No container holds the Docker socket. Polls over HTTP and restarts via the compose CLI as the deploying user, who is in the `docker` group (root-equivalent on the host — the same capability, just not lent to a third-party container). |
  | **Autoheal sidecar** | `docker compose -f docker-compose.yml -f docker-compose.autoheal.yml up -d` | One extra container, but needs `/var/run/docker.sock` (mounted read-only). **That socket is root-equivalent on the host** — a fair trade only if you already accept it. |

  Either way a restart fixes a *wedged process or dead worker*; it does not
  fix a full disk, so check the log before assuming the loop is healthy.

  <details><summary>systemd units for the host-timer option</summary>

  ```ini
  # /etc/systemd/system/headroom-watchdog.service
  [Unit]
  Description=Headroom readiness watchdog
  [Service]
  Type=oneshot
  User=pi
  ExecStart=/home/pi/headroom/scripts/headroom-watchdog.sh /home/pi/headroom
  ```

  ```ini
  # /etc/systemd/system/headroom-watchdog.timer
  [Unit]
  Description=Poll Headroom readiness every minute
  [Timer]
  OnBootSec=2min
  OnUnitActiveSec=1min
  [Install]
  WantedBy=timers.target
  ```

  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable --now headroom-watchdog.timer
  journalctl -t headroom-watchdog -f     # what it is seeing
  ```

  The script restarts only after `HEADROOM_FAIL_THRESHOLD` consecutive
  failures (default 3), so a single slow poll during a backup does not bounce
  the app. Its other knobs are `HEADROOM_HEALTH_URL` (default
  `http://localhost:8000/health/ready`) and `HEADROOM_STATE_DIR` (where the
  failure count lives between runs). **On the Let's Encrypt overlay `:8000`
  is not published**, so the default URL fails every poll and the timer would
  restart a healthy stack every third minute — add
  `Environment=HEADROOM_HEALTH_URL=https://hats.example.com/health/ready` to
  the `[Service]` section there (the LAN overlays publish `:8000` and need
  nothing).
  </details>
- **Logs**: `docker compose logs -f` (JSON-file driver, capped 10 MB × 5
  files). Failed analyses are logged at WARNING; a marketplace or eBay
  degradation logs at WARNING/ERROR (best-effort by design — the sweep
  records the outage and moves on), and the pipeline's own "skipped" lines
  at INFO.
- **In-app**: Settings → Analysis shows *Recent analysis errors* (a list of
  the latest failures) and, on the *Analysis Queue* card, failures grouped by
  cause with a per-group *Retry*; Settings →
  Upkeep the *Activity log* (append-only audit of every significant change,
  pruned daily per retention, with the pruner's own health beside it).
- **Operator endpoints** (all under the auth gate; a bearer token works):
  `GET /api/admin/config` — the effective configuration as this process
  resolved it (env, database overrides, defaults), for when you cannot see
  the container's environment; `GET /api/admin/activity-log/retention` — is
  the daily prune running; `GET /api/settings/tls` — is the served
  certificate valid and is the CA still the one devices trust (§4);
  `GET /api/admin/repricing` — last sweep, failures, live progress;
  `GET /api/admin/backups/health` and `GET /api/admin/backups/upload` — local
  and off-box backup health, separately, because they fail separately.

---

## 3b. Build time on the Pi

`docker compose up -d --build` rebuilds from source on the Pi. BuildKit cache
mounts keep that bearable, each targeting something that was being re-fetched
over your home connection for no reason:

| Mount | Why it exists |
|---|---|
| `/root/.npm` | Cutting a release edits `frontend/package.json`, which busts the `npm ci` layer. Without the mount that re-downloaded the entire dependency tree on **every upgrade**. |
| `/root/.cache/uv` | The Python dependency cache, mounted in both the dependency-install and `uv sync` layers, so a lock change re-resolves without re-downloading wheels. |
| `/opt/model-cache` | The rembg weights are **~179 MB**. That layer busts on any dependency change, so it was re-downloading a byte-identical file. |
| `/var/cache/apt`, `/var/lib/apt` | Same idea for the native libs. |

They are local disk and cost nothing to consult. Note the deliberate asymmetry
with CI, which has **no** registry-backed layer cache: exporting layers to
GitHub's cache backend was measured at ~2.7x slower than simply building
(98s → 204–284s), because this image carries a ~179 MB model plus a full venv
and shipping that over the network costs more than the build it replaces.

**The build's only non-registry network dependency is the model fetch**, and it
is deliberately non-fatal. rembg downloads the weights on first use anyway, so
a failure there costs a slow first analysis rather than a deploy you cannot
perform because somebody else's file host is down. Watch for
`WARNING: could not pre-cache the rembg model` in the build output.

**If you would rather not build on the Pi at all**, the alternative is to
publish the image from CI and `docker compose pull`. That turns a first build
into a download. It is not wired up, because it costs Actions minutes: an
arm64 image has to be built under QEMU emulation on an amd64 runner, which is
roughly 15–25 minutes per release. Restricting it to tags (not pull requests)
keeps that to about one run per release. The trade is Actions minutes against
Pi minutes; both are currently free for this repository, so it is a question of
which one you would rather wait for.

## 4. Backups & restore

**Scheduled**: every `HEADROOM_BACKUP_INTERVAL_HOURS` the scheduler checks
whether anything has changed, and writes a `tar.gz` (database + uploads) to
`backups/` next to the upload dir — `/data/backups/` in Docker — **only if it
has**. Files are named `headroom-backup-<timestamp>.tar.gz`; ones beyond the
newest `HEADROOM_BACKUP_KEEP` are pruned after each new write. The Settings
page lists them, along with whether the scheduler is healthy.

*Only when changed* matters because the alternative wastes the thing it is
protecting: on an untouched collection, a daily tarball re-reads every photo,
wears the card, and evicts a real historical snapshot from a fixed-size window
to store a restatement of the newest one. Change is judged from the size and
mtime of the database, its WAL sidecar, every file under uploads and (when
`HEADROOM_BACKUP_INCLUDE_CA` is on) Caddy's CA files, so a regenerated
authority triggers a backup too; the marker recording the last backed-up state
is a file in `backups/`, never a row in the database — the database is part of
what it measures.

This is also why retention is a **count** rather than an age. Age-based
pruning and change-gating combine badly: leave the collection alone for longer
than the window and the last backup ages out with nothing being written to
replace it, so the steady state on an idle system is zero backups.

An old newest-backup is therefore not by itself a problem. Check
`GET /api/admin/backups/health` (or the Settings card, which renders it): it
distinguishes *running and idle because nothing changed* from *failing* from
*not running at all*.

**On-demand**: Settings → Upkeep → Backups (*↓ Full Backup* / *↓ DB Only*), or
`GET /api/admin/backup` (add `?include_uploads=false` for a database-only
archive). This streams a fresh archive — use it before upgrades or before
experimenting.

**Restore** — archive contents are prefixed `data/` (`data/headroom.db`,
`data/uploads/…`). Docker:

```bash
docker compose down                       # same -f flags you deploy with
# Remove any stale WAL sidecar FIRST: SQLite replays whatever -wal sits beside
# a database on open, with no check that it belongs to it, so a leftover from
# before the restore would fold post-backup writes into the "restored" file.
docker run --rm -v headroom_headroom-data:/data alpine \
  sh -c 'rm -f /data/headroom.db-wal /data/headroom.db-shm'
docker run --rm -v headroom_headroom-data:/data -v "$PWD":/backup alpine \
  tar xzf /backup/headroom-backup-<timestamp>.tar.gz -C / \
  --exclude='data/caddy-pki'              # drop this exclude ONLY when restoring the CA too (§4 below)
docker compose up -d
```
A clean `docker compose down` truncates the WAL to nothing; an unclean stop
(power cut, OOM kill, `docker kill`) does not, which is why this is explicit.

(`headroom_headroom-data` is Compose's `<project>_<volume>` name — check
`docker volume ls` if you deployed under another project name.)

Bare metal: stop the server, then from the project root
`rm -f headroom.db-wal headroom.db-shm` (drop any stale WAL for the reason
above) and `tar xzf headroom-backup-<timestamp>.tar.gz --strip-components=1`
(restores `./headroom.db` + `./uploads/`), start again.

Off-machine safety: periodically copy the newest file out of the backups
directory (or download via the Settings page) to somewhere that isn't the
same disk.

### If certificates are far shorter than 820 days

Check the Caddy log for this line:

```
cert lifetime would exceed issuer NotAfter, clamping lifetime
```

It means the **intermediate** is nearly out and the leaf was cut down to match
it — a certificate cannot outlive the thing that signs it. The observed case
asked for 820 days and got six.

This bites installs that ran the LAN-HTTPS overlay *before* the `Caddyfile`
landed. Caddy loads the intermediate it already has and only regenerates one
when it is expiring, so shipping `intermediate_lifetime 3000d` does not
retroactively lengthen an existing seven-day intermediate. Nothing looks
broken: HTTPS works, the certificate is valid, it is just tiny — and it will
keep being tiny after every renewal.

**Restarting Caddy does not fix this.** Every reissue lands on the same issuer
ceiling. Delete the intermediate *and both issued leaves* — the leaves are
signed by the intermediate, so replacing the issuer alone leaves a chain that
does not build, which is worse than the short lifetime:

```bash
docker exec headroom-caddy rm -f \
  /data/caddy/pki/authorities/local/intermediate.crt \
  /data/caddy/pki/authorities/local/intermediate.key
docker exec headroom-caddy rm -rf /data/caddy/certificates/local
docker restart headroom-caddy
```

**The root is deliberately not touched, so no device has to be re-trusted.**
Verify afterwards that the root fingerprint is unchanged and the leaf is now
long-lived:

```bash
echo | openssl s_client -connect 127.0.0.1:443 -servername headroom.local \
  2>/dev/null | openssl x509 -noout -dates
```

Settings → Trust this device reports this case directly ("cut short to match
the intermediate that signs it") rather than telling you to restart Caddy.

### The certificate authority is in the backup too

If you run the LAN-HTTPS overlay, the archive also contains
`data/caddy-pki/` — Caddy's local certificate authority, **private keys
included**.

It is there because it is the one thing here that cannot be regenerated. A
leaf certificate expiring is a non-event: Caddy issues another. The **root**
of that authority was installed by hand on every device that browses the site,
through iOS Settings or macOS Keychain, and a root is self-signed — there is no
authority above it to vouch for a replacement. Lose it and the repair is
walking to every phone, tablet and laptop. Until now it existed only inside
Caddy's own volume, on the same card whose unclean shutdown caused the 37-day
HTTPS outage, and no backup contained it.

**Treat these archives accordingly.** Anyone holding `root.key` can mint a
certificate for *any* hostname those devices will trust — not just this app.
That is a broader capability than the database's contents, and the post-backup
upload hook may be sending the archive to a NAS or cloud. Set
`HEADROOM_BACKUP_INCLUDE_CA=false` in `.env` to leave it out; you keep the
database and photos and accept re-trusting every device if the card dies.

**Restoring the CA** — stop the stack, put the four files back, start again:

```bash
docker compose down
tar xzf headroom-backup-<timestamp>.tar.gz data/caddy-pki
docker run --rm -v headroom_caddy-data:/data -v "$PWD/data/caddy-pki":/restore \
  alpine sh -c 'mkdir -p /data/caddy/pki/authorities/local &&
                cp /restore/root.* /restore/intermediate.* /data/caddy/pki/authorities/local/ &&
                chown -R root:root /data/caddy/pki &&
                chmod 0700 /data/caddy/pki/authorities/local'
docker compose -f docker-compose.yml -f docker-compose.https-lan.yml up -d
```

Then check Settings → Trust this device. It records the CA fingerprint the
first time it sees one and compares every reading against it, so **"The
certificate authority has changed"** appearing there is the alarm for exactly
this failure — Caddy generated a fresh authority and every device is about to
refuse the connection. Caddy names every root
`Caddy Local Authority - <year> ECC Root`, so the fingerprint is the only
thing that distinguishes the one your devices trust from a replacement.

### Off-site / remote backups

> **⚠️ The archive is a credential bundle, and off-site copies are not
> encrypted by Headroom.**
>
> A backup tarball contains the whole database, and that database holds your
> **Anthropic and Google API keys in plaintext**, your **live API bearer
> token**, **live session ids**, **share-link tokens** and your password hash —
> plus, on the LAN-HTTPS overlay, **Caddy's CA private key** (see *The
> certificate authority is in the backup too*, above). The download endpoint
> writes an audit row on every manual download precisely because this is the
> highest-value single artifact in the deployment.
>
> The scheduled uploader ships that same artifact, as-is, to wherever you point
> it. Compromise of that Box/S3/Dropbox account — or of the rclone token sitting
> on the Pi — is therefore full application compromise, and a CA that can sign
> for **any** hostname every device in your house trusts.
>
> **Encrypt it.** With rclone this is configuration only, no code:
>
> ```bash
> rclone config create hr-crypt crypt \
>   remote=box:Headroom-Backups \
>   password="$(rclone obscure 'a long passphrase you store elsewhere')"
> ```
>
> then use `hr-crypt:` as the destination instead of `box:Headroom-Backups`.
> Keep the passphrase somewhere that is **not** this backup — a passphrase
> stored only inside the thing it encrypts protects nothing.
>
> If you would rather not ship the CA at all, set
> `HEADROOM_BACKUP_INCLUDE_CA=false`. You keep the database and photos and lose
> only the ability to restore the certificate authority without re-trusting each
> device by hand.

Local backups still share one disk (the SD card) with the database. Two ways to
push each backup off the box:

**A0. From the UI — Settings → Upkeep → Off-site backup.** Pick a provider,
give it a destination, press **Test now**. The card carries the host-side setup
steps for whichever provider you choose, reports whether that provider's binary
is actually present in the container, and tracks upload successes and failures
separately from local-backup health — a local backup can succeed nightly while
the off-box copy has been failing for a month, and only the second means the
archive exists nowhere but the card it is protecting against.

| Provider | Destination | Needs |
|---|---|---|
| Cloud storage (rclone) | `box:Headroom-Backups` | `rclone config` on the host + `docker-compose.backup-rclone.yml` |
| rsync over SSH | `pi@nas.local:/volume1/backups/headroom` | an SSH key + `docker-compose.backup-rsync.yml` (mounts `HEADROOM_BACKUP_SSH_KEY` and `HEADROOM_BACKUP_KNOWN_HOSTS` read-only) |
| Synology NAS (rsync service) | `backup@nas.local::backups/headroom` | DSM's rsync service + `HEADROOM_BACKUP_RSYNC_PASSWORD` |

`rsync` and `ssh` ship **in the image**; rclone is ~50 MB and stays a bind
mount. The browser never sends a command — it sends a provider name and a
destination, and the argv is assembled from a template the server owns, so no
input can add a flag, change the binary, or reach a shell.

The two rsync destinations differ by **one colon and that is the whole
transport**: `host:/path` is rsync over SSH, `host::module/path` connects
straight to an rsync daemon on port 873 and reads the first segment as a module
name. The validator keeps them apart per provider, because a destination that
silently switched transport would fail with credentials nobody configured and
look like a broken NAS.

**Synology, without enabling SSH:** Control Panel → File Services → rsync →
**Enable rsync service**. DSM then exposes your **shared folders** as modules,
so the module name is install-specific — `home`, `photo`, `docker`, whatever
you have. Discover the real list rather than guessing it: the app does this for
you (`list_rsync_modules`, which the card runs anonymously, since module
listing happens before authentication), or run `rsync rsync://HOST/` yourself
from a box with GNU rsync. Guessing gives `@ERROR: Unknown module '…'`, which
reads like a broken NAS rather than a wrong name.

**You do not need the `NetBackup` module.** The neighboring *Enable network
backup service* checkbox simply adds one more module by that name alongside
your shared folders; it is an option, not a requirement, and pointing at a
shared folder you already have works exactly as well. Then add an rsync account
under the same page — it is separate from your DSM login. Allow
port 873 if the NAS firewall is on. Put that account's password in `.env` as
`HEADROOM_BACKUP_RSYNC_PASSWORD`; it is read from the host at upload time,
mapped to rsync's own `RSYNC_PASSWORD`, and never stored by Headroom or
returned by the API. It applies to **daemon mode only** — rsync ignores it over
SSH, which is why the SSH provider carries no secret rather than one that would
look set and do nothing.

**A. Native upload hook (no separate cron).** Set `HEADROOM_BACKUP_UPLOAD_CMD`
and Headroom runs it after every scheduled backup, passing the new tarball.
Placeholders: `{path}` (full path), `{dir}`, `{name}`. It's parsed as an argv
(no shell), runs off the event loop, is bounded by `HEADROOM_BACKUP_UPLOAD_TIMEOUT`
(default 600 s), and is **best-effort** — a failed or missing uploader logs a
warning and never breaks the local backup. Grep `docker compose logs headroom`
for `Backup uploaded off-box:` to confirm.

The included **`docker-compose.backup-rclone.yml`** overlay wires this to
[rclone](https://rclone.org) (works with Box, S3, Backblaze B2, Google Drive,
Dropbox, …). Box has **no native Linux desktop client**, so rclone's `box`
backend is the supported route on a Pi. One-time: `rclone config` a remote
(headless → `rclone authorize "box"` on a laptop, paste the token back),
`chmod 644` the config so the container user can read it, then:

```bash
export RCLONE_BIN="$(command -v rclone)"
export RCLONE_CONF="$HOME/.config/rclone/rclone.conf"
export HEADROOM_BACKUP_REMOTE="box:Headroom-Backups"
docker compose -f docker-compose.yml -f docker-compose.backup-rclone.yml \
  -f docker-compose.http80.yml up -d --build   # + your front-door overlay
```

**B. Host cron (zero app config).** rclone + its OAuth token already live on the
host, so a cron job avoids the in-container mount/permission fiddliness. Pull a
fresh, consistent archive from the API and ship it:

```bash
# /etc/cron.d/headroom-offsite — 02:30 nightly
30 2 * * * pi  curl -fsS -H "Authorization: Bearer hr_YOUR_API_TOKEN" \
  http://localhost:8000/api/admin/backup -o /tmp/headroom-$(date +\%F).tar.gz \
  && rclone move /tmp/headroom-*.tar.gz box:Headroom-Backups
```

(The API token is the owner's: Settings → Device → Account → *Show*, which asks for your password — `POST /api/auth/token/reveal`; `GET /api/auth/me` deliberately does not return it.
`rclone move` deletes the local temp copy after a successful upload.) Same
recipe targets S3/B2/Drive by changing the remote.

Either way, keep an eye on retention **on the remote** — Headroom only prunes
its local copies.

### Start over (wipe & set up as new)

Reset to a clean install: fresh database, no hats/cases/photos, and the
first-run "create owner" screen returns. The database, photos, *and* rolling
backups all live in the
`headroom-data` volume, so this means removing that volume. **This is
irreversible — take a backup first** (Settings → Upkeep → Backups → *↓ Full Backup*) if you want
to keep anything.

Full reset (Docker) — use the same `-f` flags you deploy with:

```bash
docker compose -f docker-compose.yml -f docker-compose.http80.yml down -v
docker compose -f docker-compose.yml -f docker-compose.http80.yml up -d --build
```

`down -v` removes the `headroom-data` volume; the next boot re-creates a fresh
database and re-seeds the default room. **Note:** on the `https-lan` overlay
`-v` *also* removes Caddy's `caddy-data`/`caddy-config`/`caddy-ca` (its local CA
and the exported copy of the root), so each device has to re-trust the cert once.

Keep Caddy's cert (reset only the app data) — remove just the one volume:

```bash
docker compose -f ... down
docker volume rm "$(docker volume ls -q | grep headroom-data)"
docker compose -f ... up -d --build
```

Zero the database but keep photo files on disk — delete the DB files in place
via a throwaway container while the stack is down (the kept photos become
orphaned, since the hat rows that referenced them are gone):

```bash
docker compose down
docker run --rm -v headroom_headroom-data:/data alpine \
  sh -c 'rm -f /data/headroom.db /data/headroom.db-wal /data/headroom.db-shm'
docker compose up -d
```

Bare metal: stop the server and delete `./headroom.db` (plus the `-wal`/`-shm`
sidecar files); add `rm -rf ./uploads/*` to drop photos too. Start again and
you'll land on the first-run setup screen.

---

## 5. Upgrades

```bash
git pull
docker compose up -d --build     # Docker — SEE THE WARNING BELOW about overlays
# — or —
./scripts/setup.sh --no-docker   # bare metal: re-sync deps + rebuild SPA, then restart uvicorn
```

> **Re-run with the same `-f` flags you deploy with.** Compose applies only the
> files named in the command, so a bare `docker compose up -d --build` on a
> host running an overlay is not an upgrade — it is a switch to the base
> config. On the `http80` overlay that means the Caddy sidecar isn't started
> and the app goes back to `:8000`, so `http://headroom.local` stops
> answering. Upgrade with the whole command:
>
> ```bash
> git pull
> docker compose -f docker-compose.yml -f docker-compose.http80.yml up -d --build
> ```

- Database migrations are **automatic**: `init_db()` runs inline DDL
  migrations at every boot. There is no separate migrate step and no
  downgrade path — take a backup before major upgrades.
- Version sanity check: the footer of the web app shows the running build's
  version; compare with `CHANGELOG.md`.

### The build stamp in the footer

The footer shows `v2.18.0 · build a1b2c3d`. The version comes from
`package.json`; the commit has to be supplied from the host, because
`.dockerignore` excludes `.git` and the frontend build stage only receives
`frontend/` — nothing inside the image can work out which commit it is.

Do it once and forget it:

```bash
./scripts/stamp-build.sh --install-hooks
```

That writes `HEADROOM_BUILD_SHA` into `.env` (which compose reads
automatically, whatever `-f` flags you use) and installs git hooks so every
`git pull` refreshes it. `./scripts/setup.sh` does the same thing.

Or set it inline per build:

```bash
HEADROOM_BUILD_SHA=$(git rev-parse --short HEAD) docker compose up -d --build
```

Notes:

- The arg was called `BUILD_SHA` before v2.0.0. That name is still accepted, so
  older commands keep working — but a build arg that doesn't match simply
  arrives empty, with no warning, and the footer just never shows a build.
  That is exactly how it can go unnoticed for months.
- A working tree with uncommitted changes is stamped `a1b2c3d-dirty`, so a
  stamp can be trusted to mean precisely that commit.
- No stamp at all is not an error — the footer shows the version alone.

---

## 6. Security posture (v1.0+)

Accounts are mandatory. On first boot no users exist; the first visit to
the web app runs **first-run setup** (create the owner account), after
which every data-bearing route requires authentication.

**What's protected:** all of `/api/*`, the `/uploads/*` photo mount, and
the API's own description (`/openapi.json`, `/docs`, `/redoc` — a complete
map of the attack surface, which used to be public) — via session cookie or
bearer API token. **What's open by design:** the SPA shell + hashed JS/CSS
assets + PWA manifest/icons (no data in them), `/health*` (probes, redacted
for anonymous callers — §3), `/api/auth/*` (each endpoint self-guards), and
the `/api/public/*` prefix: the share-link view (`share/<token>` — the token
*is* the credential), the login page's branding logo, the Caddy root
certificate (`ca-certificate`, LAN-HTTPS overlay only — a public cert), and
**guest browsing** (`guest/*`), which is **off by default**: switch it on in
Settings → Sharing → *Guest browsing* and the login page grows a *Browse the
collection as a guest* link to `/guest` — read-only, no prices, purchases, condition or
notes, the same projection a share link gets, and `404` (not `403`) while
it is off, so a stranger cannot learn the feature exists. One test enumerates
every operation in the OpenAPI schema and probes it anonymously, so a new
route is protected unless someone writes it onto that test's allowlist.

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
- **API token**: each user has a static bearer token (Settings → Device →
  Account, rotatable) for cookie-less clients — the iOS Shortcut import needs
  it in an `Authorization: Bearer …` header. **Reading or rotating it
  requires your password**, not just a signed-in session: the token survives
  logout and session revocation, so a stolen session must not be able to
  trade itself up for a credential those cannot reach. A **password change
  rotates it** (a compromise response is a complete one) — anything holding
  the old token stops working, so update the Shortcut afterwards.
- **Share links**: 256-bit random tokens granting read-only access to the
  collection view and token-gated photo streaming; revocable, immediately.
  **They expire in 30 days by default** — a link is unscoped and
  whole-collection, including the room and case each hat is in, so a
  forwarded one is a lasting room-by-room inventory of valuables. Pick
  *Never* in Settings → Sharing if you actually want that; links created
  before this default was added never expire, and the card now says so
  per link.
- **First-run setup** is claimable by whoever reaches the host first, and
  `GET /api/auth/status` advertises that the box is unclaimed. On a LAN
  that is nearly theoretical. Facing the internet it is not — a
  Let's Encrypt hostname is in a public certificate-transparency log within
  seconds — so set **`HEADROOM_SETUP_TOKEN`** there and enter it in the
  extra field on the setup form. Unset (the default), nothing changes.
- **Client IP on the plain bridge compose may be the Docker gateway.**
  If it is, per-IP login rate limiting collapses into one shared bucket
  (a stranger's failed logins can lock you out) and the IP recorded on
  `auth.login_failed` rows is not the caller's. It depends on the host's
  `userland-proxy` setting — on, and the source is rewritten; off, and
  iptables DNAT preserves it. **All three LAN overlays use host networking
  and are unaffected**, as is the Let's Encrypt overlay, where Caddy sets
  `X-Forwarded-For` and uvicorn honors it only from the compose network's own
  subnet (`FORWARDED_ALLOW_IPS=172.31.71.0/24`, pinned in
  `docker-compose.https.yml` — the Caddy container beside it and nothing
  else; the LAN overlays keep the `127.0.0.1` default). The header is
  deliberately not trusted from arbitrary peers: on a direct request it is
  attacker-supplied, so honoring it would let a caller choose its own
  rate-limit bucket, which is worse than sharing one.
- Raw API keys (Anthropic/Google/eBay) are **never returned** by the API —
  status endpoints reply with a masked prefix/suffix only.
- `HEADROOM_ADMIN_TOKEN` is retired and ignored.

**Forgot the password?** There's no email reset (nothing to send from).
With shell access on the host, delete the owner (the image ships no `sqlite3`
binary, so borrow one; use the same `-f` flags you deploy with for the
`down`/`up`):

```bash
docker compose down
docker run --rm -v headroom_headroom-data:/data alpine sh -c \
  'apk add -q sqlite && sqlite3 /data/headroom.db "DELETE FROM users; DELETE FROM auth_sessions; DELETE FROM passkey_credentials;"'
docker compose up -d
```

Bare metal: stop the server and run the same three `DELETE`s against
`headroom.db`. First-run setup then reappears — the app notices its
`owner_setup_done` marker with no owner behind it and clears it (until 2.78
that marker outlived the row it guarded, and this recipe answered *"Setup
already completed"* forever). Guard your backups accordingly: they contain
the database.

Tailscale/VPN remains a fine *additional* layer, but is no longer the only
thing standing between the internet and your hats.

---

## 7. Raspberry Pi notes

- The image is multi-arch (amd64 + arm64); build on the Pi (slow first
  build) or build/push from a faster machine with
  `docker buildx build --platform linux/arm64,linux/amd64 -t <registry>/headroom:latest --push .`
- The rembg model is pre-downloaded **into the image** at build time so the
  Pi never fetches it at runtime. Default `isnet-general-use` (~179 MB).
  `u2netp` (4.7 MB) is far faster — 5–15 s per photo on a Pi 4 — but its low
  capacity loses thin protruding shapes, which on a hat means the BILL: it
  keeps the crown and cuts the brim off. Since analysis moved onto the
  background worker nothing waits on the slower model, so accuracy wins by
  default. Rebuild the image after changing it (the model bakes in via a
  build arg): `REMBG_MODEL=u2netp docker compose up -d --build`.
- SQLite on an SD card is fine at hat-collection scale, but SD cards die:
  that's what §4's off-machine backup copy is for.

### Enable the memory cgroup (do this once)

`docker compose up` prints this on Raspberry Pi OS:

```
! headroom  Your kernel does not support memory limit capabilities or the
            cgroup is not mounted. Limitation discarded.
```

That means the `mem_limit` in `docker-compose.yml` is being **silently
ignored**. Raspberry Pi OS ships with the memory cgroup off (it costs a little
RAM and kernel overhead), so Docker cannot enforce a ceiling until you turn it
on. Everything still runs — you just lose the protection.

It matters because of what the ceiling is for. Without it, a memory spike
competes for the whole machine and the kernel's OOM killer picks a victim
system-wide — which can be sshd, or the container killed with `SIGKILL` so
nothing is logged and there is no evidence afterwards. With it, Docker records
`OOMKilled=true` against this container and the failure is diagnosable.

Add these two options to the **end of the existing single line** in
`/boot/firmware/cmdline.txt` (older images: `/boot/cmdline.txt`) — it must stay
one line, space-separated:

```
cgroup_enable=memory cgroup_memory=1
```

Then reboot and confirm:

```
sudo reboot
# after it comes back:
docker info | grep -i "memory limit"      # expect no "WARNING: No memory limit support"
docker inspect headroom --format '{{.HostConfig.Memory}}'   # expect 1073741824, not 0
```

Tune the ceiling with `HEADROOM_MEM_LIMIT` (default `1g`). Don't go below
~640M — the analysis worker holds a ~179 MB model plus a decoded image, and a
tighter limit kills it mid-inference on every upload.

**If the app is ever killed anyway**, this is how you find out why:

```
docker inspect headroom --format '{{.State.ExitCode}} {{.State.OOMKilled}}'
```

`OOMKilled=true` means it hit the ceiling. A Pi that browns out under load
(undervoltage, or thermal throttling during rembg's CPU burst) produces an
identical-looking sudden death with no logs — check `vcgencmd get_throttled`,
where anything other than `0x0` points at power or heat rather than memory.

---

## 8. External services & failure modes

Every external call is best-effort — **no outage ever blocks an upload**:

| Service | Used for | Needs | On failure |
|---|---|---|---|
| Anthropic (Claude Vision) | brand/model/colors/price/notes | API key | hat marked `error`/`skipped`, fallback analysis runs |
| Local mask extraction | fallback colors | nothing | no colors if bg-removal failed |
| Google Cloud Vision | fallback brand via logo | API key (free tier 1,000/mo) | fallback proceeds colors-only |
| eBay Browse API | live asking-price stats for comparable listings (eBay publishes no sold history to this API) | Production App ID + Cert ID (5,000 calls/day free) | comps skipped, logged INFO |
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
| Forgot the password | Delete the owner rows with a borrowed `sqlite3` (recipe in §6) → first-run setup reappears |
| iOS Shortcut import started failing after v1.0 | Add an `Authorization: Bearer <api-token>` header to the Shortcut — token in Settings → Account |
| Passkey button missing / erroring | Passkeys need HTTPS (or localhost) AND `HEADROOM_RP_ID` = the serving domain — use the HTTPS overlay |
| Melin price stopped appearing | Treet may have rotated the public client id — grab the new one from their site bundle and set `HEADROOM_MELIN_CLIENT_ID` |
| Bulk import queued but idle | Check `HEADROOM_IMPORT_WORKER_ENABLED`; queued items re-enqueue automatically on restart |
| Tests polluted `uploads/` with tiny images | Fixed in v0.7.0 (isolated test uploads); stray sub-10 KB files are safe to delete |
