#!/usr/bin/env bash
# Record the current commit so the footer can show which build is running.
#
# `docker compose` reads `.env` from the project directory automatically, and
# docker-compose.yml passes HEADROOM_BUILD_SHA through as a build arg. So
# writing it here is what makes a plain `docker compose up -d --build` produce
# a stamped image — no extra flags to remember, which is the only version of
# this that actually gets used.
#
# Why it can't be worked out inside the build: `.dockerignore` excludes `.git`,
# and the frontend stage only receives `frontend/`, so nothing in the image has
# any way to learn the commit. The value has to come from the host.
#
# Run directly, or let the git hooks installed by setup.sh run it after every
# pull/checkout.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! sha=$(git rev-parse --short HEAD 2>/dev/null); then
  echo "stamp-build: not a git checkout — leaving .env alone" >&2
  exit 0
fi

# Mark a working tree with uncommitted changes, so a footer reading
# "build a1b2c3d" can be trusted to mean exactly that commit.
if ! git diff --quiet HEAD 2>/dev/null; then
  sha="${sha}-dirty"
fi

touch .env
# Rewrite in place, preserving every other variable — this file is also where
# a person keeps their API keys, and clobbering it to set one value would be a
# genuinely bad day.
tmp=$(mktemp)
grep -v '^HEADROOM_BUILD_SHA=' .env > "$tmp" || true
printf 'HEADROOM_BUILD_SHA=%s\n' "$sha" >> "$tmp"
mv "$tmp" .env

echo "stamp-build: HEADROOM_BUILD_SHA=$sha"
