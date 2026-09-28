#!/usr/bin/env bash
# Upgrade a Docker install of Headroom in place — one command instead of a
# checklist in the release notes.
#
#   ./scripts/upgrade.sh [--tz Area/City] [--no-pull] [--prune-build-cache]
#
# Every upgrade used to be a list of things to remember: back up first, pull,
# rebuild with the SAME `-f` overlay flags (a bare `docker compose up` on an
# HTTPS host quietly reverts to the base config), restart Caddy when its
# config changed (a `git pull` replaces the file's inode and the bind-mounted
# container keeps reading the old one), set `TZ`, move the rclone config.
# Each was documented, and each was the kind of step that gets missed on the
# one day it matters. This script is those steps, in order:
#
#   1. refuses to run on a checkout with uncommitted changes to tracked files
#   2. remembers the compose files in `.env` (`COMPOSE_FILE`), taken from the
#      running project, so every later `docker compose` — this script's and a
#      person's — keeps the overlays without any `-f`
#   3. sets `TZ` in `.env` (from `--tz`, else from the host when the host is
#      not on UTC) so a tag scan logs your local day
#   4. with the rclone overlay: copies an existing rclone config into the
#      writable directory the overlay mounts
#   5. `git pull --ff-only`, stamps the build SHA
#   6. `docker compose build`, then `up -d`
#   7. waits for the container's healthcheck (/health/ready) to pass
#   8. restarts any Caddy container whose served Caddyfile differs from the
#      file on disk
#   9. with --prune-build-cache: drops Docker build cache older than a week
#
# "Back up first" is not here because the app does it itself: the first boot
# of a new version snapshots the database to
# `/data/backups/pre-upgrade-<from>-to-<to>-<time>.db` before migrating
# (`services/upgrade_guard.py`).
#
# Sourcing the file defines the functions without running anything, which is
# how `tests/test_upgrade_script.py` exercises them.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env}"
HEALTH_TIMEOUT="${HEADROOM_UPGRADE_HEALTH_TIMEOUT:-900}"
APP_CONTAINER="${HEADROOM_CONTAINER:-headroom}"

log() { printf '\033[1;35m[upgrade]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[upgrade]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[upgrade]\033[0m %s\n' "$*" >&2; exit 1; }

# --- .env ------------------------------------------------------------------

# The value of KEY in .env (the last assignment wins, as compose reads it).
env_get() {
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true
}

# Set KEY=VALUE in .env, replacing any earlier assignment. Written back
# through the same inode (`cat >`, like stamp-build.sh), so a symlinked .env
# stays a symlink.
env_set() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp="$(mktemp)"
  grep -vE "^$key=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}

# --- compose files ---------------------------------------------------------

# The running project's compose files as a COMPOSE_FILE value (colon-joined,
# relative to the repo), read from `docker compose ls`. Empty when none runs.
running_compose_files() {
  local project="${COMPOSE_PROJECT_NAME:-$(basename "$REPO_DIR")}"
  # `|| true` inside the braces: under `pipefail` a failing `compose ls` (an
  # old compose without `--format`, a daemon still starting) would fail the
  # whole pipeline and, through `set -e`, end the upgrade — where the right
  # outcome is "no running project found".
  { docker compose ls --all --format json 2>/dev/null || true; } | python3 -c '
import json, os, sys
project, repo = sys.argv[1], sys.argv[2]
try:
    rows = json.load(sys.stdin) or []
except ValueError:
    rows = []
for row in rows:
    if row.get("Name") != project:
        continue
    files = [f.strip() for f in row.get("ConfigFiles", "").split(",") if f.strip()]
    print(":".join(os.path.relpath(f, repo) for f in files))
    break
' "$project" "$REPO_DIR"
}

# Make COMPOSE_FILE in .env name the overlays this install actually runs.
# An existing value is kept: it is either this script's or a deliberate one.
ensure_compose_files() {
  local current detected
  current="$(env_get COMPOSE_FILE)"
  if [ -n "$current" ]; then
    log "compose files (from .env): $current"
    return 0
  fi
  detected="$(running_compose_files)"
  if [ -n "$detected" ]; then
    env_set COMPOSE_FILE "$detected"
    log "compose files recorded in .env: $detected"
  else
    log "no running project found — using docker-compose.yml alone"
  fi
}

# --- time zone -------------------------------------------------------------

host_timezone() {
  local tz=""
  if command -v timedatectl >/dev/null 2>&1; then
    tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  fi
  if [ -z "$tz" ] && [ -L /etc/localtime ]; then
    tz="$(readlink /etc/localtime | sed 's#.*/zoneinfo/##')"
  fi
  if [ -z "$tz" ] && [ -f /etc/timezone ]; then
    tz="$(cat /etc/timezone)"
  fi
  printf '%s' "$tz"
}

is_utc() {
  case "$1" in
    ""|UTC|Etc/UTC|Etc/Universal|Universal|Zulu|Etc/Zulu|GMT|Etc/GMT) return 0 ;;
    *) return 1 ;;
  esac
}

# TZ for the container: an explicit --tz wins; an existing TZ is kept; else the
# host's zone, unless the host is on UTC — many Pis are, and "UTC" there means
# nobody set it, not that the owner lives in Greenwich, so it is not guessed.
ensure_timezone() {
  local wanted="${1:-}" current host
  if [ -n "$wanted" ]; then
    if [ -d /usr/share/zoneinfo ] && [ ! -e "/usr/share/zoneinfo/$wanted" ]; then
      die "unknown time zone: $wanted (expected Area/City, e.g. America/Los_Angeles)"
    fi
    env_set TZ "$wanted"
    log "TZ=$wanted"
    return 0
  fi
  current="$(env_get TZ)"
  if [ -n "$current" ]; then
    log "TZ=$current (from .env)"
    return 0
  fi
  host="$(host_timezone)"
  if is_utc "$host"; then
    warn "TZ is not set and this host is on UTC — tag scans will log UTC days."
    warn "Re-run with --tz Area/City (e.g. --tz America/Los_Angeles) to fix it."
    return 0
  fi
  env_set TZ "$host"
  log "TZ=$host (from the host)"
}

# --- rclone ----------------------------------------------------------------

# The rclone overlay mounts a writable DIRECTORY (token refreshes are written
# back), where it used to mount one file read-only via RCLONE_CONF. Copy the
# old config into the new place the first time; never overwrite one there.
ensure_rclone_config() {
  case ":$(env_get COMPOSE_FILE):" in
    *docker-compose.backup-rclone.yml*) ;;
    *) return 0 ;;
  esac
  local dir old
  dir="$(env_get HEADROOM_RCLONE_CONFIG_DIR)"
  dir="${dir:-$HOME/.config/headroom-rclone}"
  if [ -f "$dir/rclone.conf" ]; then
    return 0
  fi
  old="$(env_get RCLONE_CONF)"
  old="${old:-$HOME/.config/rclone/rclone.conf}"
  if [ ! -f "$old" ]; then
    warn "rclone overlay in use but no rclone.conf found at $old — see OPERATIONS (off-site backup)."
    return 0
  fi
  mkdir -p "$dir"
  cp "$old" "$dir/rclone.conf"
  chmod 600 "$dir/rclone.conf"
  log "copied $old to $dir/rclone.conf"
  if [ "$(id -u)" != "1000" ]; then
    warn "the container runs as uid 1000; run: sudo chown -R 1000:1000 '$dir'"
  fi
}

# --- the upgrade -----------------------------------------------------------

require_clean_checkout() {
  if ! git -C "$REPO_DIR" diff --quiet || ! git -C "$REPO_DIR" diff --cached --quiet; then
    die "tracked files have uncommitted changes — commit or stash them first (git status)."
  fi
}

wait_until_healthy() {
  local waited=0 status
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$APP_CONTAINER" 2>/dev/null || echo missing)"
    case "$status" in
      healthy) log "$APP_CONTAINER is healthy"; return 0 ;;
      none) log "$APP_CONTAINER has no healthcheck — not waiting"; return 0 ;;
    esac
    sleep 5
    waited=$((waited + 5))
  done
  docker logs --tail 40 "$APP_CONTAINER" >&2 || true
  die "$APP_CONTAINER did not become healthy within ${HEALTH_TIMEOUT}s (status: $status)"
}

# A Caddyfile is bind-mounted as a single file, which pins the inode the
# container started with; `git pull` writes a new file, and Caddy goes on
# serving the old config until it is restarted. Compare, and restart only on
# a difference.
refresh_caddy() {
  local c src served ondisk
  for c in $(docker ps --format '{{.Names}}' | grep -E 'caddy' || true); do
    src="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' "$c" 2>/dev/null || true)"
    [ -n "$src" ] && [ -f "$src" ] || continue
    ondisk="$(md5sum < "$src" | cut -d' ' -f1)"
    served="$(docker exec "$c" md5sum /etc/caddy/Caddyfile 2>/dev/null | cut -d' ' -f1 || true)"
    if [ "$ondisk" != "$served" ]; then
      log "$c is serving an old Caddyfile — restarting it"
      docker restart "$c" >/dev/null
    fi
  done
}

main() {
  local tz="" pull=1 prune=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --tz) tz="${2:-}"; [ -n "$tz" ] || die "--tz needs a value"; shift 2 ;;
      --tz=*) tz="${1#--tz=}"; shift ;;
      --no-pull) pull=0; shift ;;
      --prune-build-cache) prune=1; shift ;;
      -h|--help) sed -n '2,33p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
  done

  cd "$REPO_DIR"
  command -v docker >/dev/null 2>&1 || die "docker is not installed"
  require_clean_checkout
  ensure_compose_files
  ensure_timezone "$tz"
  ensure_rclone_config

  if [ "$pull" = 1 ]; then
    log "pulling"
    git pull --ff-only
  fi
  if [ -x scripts/stamp-build.sh ]; then
    scripts/stamp-build.sh >/dev/null 2>&1 || warn "could not stamp the build SHA"
  fi

  log "building (this is the slow part on a Pi)"
  docker compose build
  log "starting"
  docker compose up -d
  wait_until_healthy
  refresh_caddy

  if [ "$prune" = 1 ]; then
    log "pruning build cache older than a week"
    docker builder prune -f --filter until=168h >/dev/null
  fi

  log "running $(docker exec "$APP_CONTAINER" python -c 'import importlib.metadata as m; print(m.version("headroom"))' 2>/dev/null || echo '?')"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
