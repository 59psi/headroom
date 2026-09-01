#!/usr/bin/env bash
# Poll Headroom's readiness endpoint and restart the stack if it stays down.
#
# This is the no-privilege alternative to `docker-compose.autoheal.yml`. It
# needs no Docker socket mount: it speaks HTTP to the app and shells out to
# `docker compose` as the user that already owns the deployment.
#
# WHY: the container healthcheck in docker-compose.yml fails on low disk and on
# a dead background worker, and Docker's `restart: unless-stopped` does NOT act
# on `unhealthy` — only on exit. Without a consumer the check is a string in
# `docker ps`. See docs/OPERATIONS.md §7 for the systemd units that run this.
#
# Usage:  headroom-watchdog.sh [compose-dir]
# Env:    HEADROOM_HEALTH_URL   (default http://localhost:8000/health/ready)
#         HEADROOM_FAIL_THRESHOLD (default 3 consecutive failures)
#         HEADROOM_STATE_DIR    (default /var/tmp)

set -euo pipefail

COMPOSE_DIR="${1:-$HOME/headroom}"
URL="${HEADROOM_HEALTH_URL:-http://localhost:8000/health/ready}"
THRESHOLD="${HEADROOM_FAIL_THRESHOLD:-3}"
STATE="${HEADROOM_STATE_DIR:-/var/tmp}/headroom-watchdog.count"

log() { logger -t headroom-watchdog "$*" 2>/dev/null || echo "headroom-watchdog: $*"; }

# A readiness failure is a NON-200, a connection refusal, or a timeout. All
# three mean the same thing to an operator and none of them should be treated
# as success just because curl exited non-zero for a different reason.
if curl -fsS --max-time 10 -o /dev/null "$URL"; then
  # Reset only on a clean pass. A single good poll after two bad ones means
  # the condition was transient, which is exactly what the threshold is for.
  [ -f "$STATE" ] && rm -f "$STATE"
  exit 0
fi

count=$(( $( [ -f "$STATE" ] && cat "$STATE" || echo 0 ) + 1 ))
echo "$count" > "$STATE"
log "readiness check failed ($count/$THRESHOLD): $URL"

if [ "$count" -lt "$THRESHOLD" ]; then
  exit 0
fi

# Restarting does not fix a full disk — it fixes a dead worker or a wedged
# process, which are what this is for. Say so in the log either way, so the
# restart is never the only record of what happened.
log "threshold reached — restarting the Headroom stack in $COMPOSE_DIR"
rm -f "$STATE"
cd "$COMPOSE_DIR"
docker compose restart headroom 2>&1 | logger -t headroom-watchdog || {
  log "restart FAILED — the stack needs a human"
  exit 1
}
log "restart issued"
