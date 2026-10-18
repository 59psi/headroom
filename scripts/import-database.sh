#!/usr/bin/env bash
# Import a Headroom backup (.tar.gz) or database (.db) into the Docker install.
#
#   ./scripts/import-database.sh headroom-backup-<time>.tar.gz
#   ./scripts/import-database.sh old-headroom.db --yes
#   ./scripts/import-database.sh --list
#   ./scripts/import-database.sh --restore-point pre-upgrade-<…>.db
#
# The same import as Settings → Upkeep → Import a database, from the host —
# for a new machine set up from an old one's backup, an archive too big to
# send from a phone, or a server whose app will not start. It:
#
#   1. shows what the file holds and what it would replace (the app keeps
#      running meanwhile);
#   2. asks before going on (`--yes` skips the question);
#   3. stops the app, runs the import in a one-off container on the app's own
#      volume, and starts the app again — its boot re-queues anything the
#      imported database left pending — then waits until it is healthy.
#
# A FILE on this machine is streamed in on stdin, so nothing has to be copied
# into the volume first. `--restore-point NAME` imports a file already in the
# volume's backups folder (`--list` shows them: the nightly archives and the
# copies taken before each upgrade and import). The collection it replaces is
# saved as `/data/backups/pre-import-<time>.db`, which is importable the same
# way: that is the undo. This install's account, passkeys, share links, API
# keys, model and off-site backup stay as they are.
#
# Compose overlays come from COMPOSE_FILE in .env (`scripts/upgrade.sh`
# records them), so the app stops and starts with the same front door.
set -euo pipefail

FILE=""
POINT=""
YES=0
LIST=0
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes) YES=1 ;;
    --list) LIST=1 ;;
    --restore-point)
      [ $# -ge 2 ] || { echo "--restore-point needs a name (see --list)" >&2; exit 1; }
      POINT="$2"; shift ;;
    -h|--help) awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; exit 0 ;;
    -*) echo "Unknown option: $1 (try --help)" >&2; exit 1 ;;
    *)
      [ -z "$FILE" ] || { echo "One file at a time (try --help)" >&2; exit 1; }
      FILE="$1" ;;
  esac
  shift
done
if [ "$LIST" -eq 0 ]; then
  if [ -z "$FILE" ] && [ -z "$POINT" ]; then
    echo "Usage: $0 FILE | --restore-point NAME | --list  [--yes]   (try --help)" >&2; exit 1
  fi
  [ -z "$FILE" ] || [ -z "$POINT" ] || { echo "A FILE or --restore-point, not both" >&2; exit 1; }
fi
if [ -n "$FILE" ]; then
  [ -f "$FILE" ] && [ -r "$FILE" ] || { echo "Cannot read $FILE" >&2; exit 1; }
  # Absolute before the cd below, so a relative path still names the same file.
  FILE="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"
fi

# upgrade.sh's helpers: the compose-file bookkeeping and the health wait.
# Sourcing it defines functions and runs nothing.
# shellcheck source=scripts/upgrade.sh
source "$(dirname "${BASH_SOURCE[0]}")/upgrade.sh"
log() { printf '\033[1;35m[import]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[import]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[import]\033[0m %s\n' "$*" >&2; exit 1; }
cd "$REPO_DIR"

# The import, in a throwaway container with the app's image, volume and
# environment. `run` gives it a generated name (the service's container_name
# is the app's), `--no-deps` leaves Caddy alone, `-T` passes stdin through.
# It inherits the service's healthcheck too, which it never answers — so it
# is labeled out of autoheal's watch, or the autoheal overlay would restart
# it as "unhealthy" a couple of minutes into a long import.
importer() {
  docker compose run --rm --no-deps -T --label headroom.autoheal=false \
    headroom python -m headroom.import_database "$@"
}

# The source, as the importer takes it: the file on stdin, or a name it
# looks up in the volume's backups folder itself.
from_source() {
  if [ -n "$POINT" ]; then
    importer "$@" --restore-point "$POINT" < /dev/null
  else
    importer "$@" - < "$FILE"
  fi
}

ensure_compose_files

if [ "$LIST" -eq 1 ]; then
  importer --list < /dev/null
  exit 0
fi

log "Reading ${POINT:-$(basename "$FILE")}..."
from_source --preview || die "Nothing was imported."

if [ "$YES" -ne 1 ]; then
  # `|| answer=""`: `read` fails at end of input, and under `set -e` a closed
  # stdin would end the script silently instead of reading as "no".
  read -r -p "Replace this collection? [y/N] " answer || answer=""
  case "$answer" in
    y|Y|yes|YES) ;;
    *) log "Nothing changed."; exit 0 ;;
  esac
fi

log "Stopping the app for the import..."
docker compose stop headroom
# Started again whatever happens below: a refused import must not leave the
# collection offline.
restarted=0
start_again() {
  [ "$restarted" -eq 1 ] && return 0
  restarted=1
  log "Starting the app again..."
  docker compose start headroom
}
trap start_again EXIT

status=0
from_source --yes || status=$?
start_again
trap - EXIT
wait_until_healthy

[ "$status" -eq 0 ] || die "The import did not complete (exit $status); the collection was not replaced."
log "Done. The previous collection is in /data/backups/pre-import-*.db — import it the same way to undo."
