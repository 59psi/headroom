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

# --install-hooks: wire this into git so a pull refreshes the stamp on its own.
# Lives here rather than in setup.sh so a running deployment can get it without
# re-running a script that installs Docker, Node and the Python toolchain.
if [ "${1:-}" = "--install-hooks" ]; then
  # Outside a git checkout there is nothing to hook. Without this guard the
  # `|| echo .git/hooks` fallback created a `.git/hooks` in a plain directory,
  # wrote three hooks into it, and reported success — then said "not a git
  # checkout" two lines later.
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "stamp-build: not a git checkout — no hooks to install" >&2
    exit 0
  fi
  hooks="$(git rev-parse --git-path hooks)"
  mkdir -p "$hooks"
  for hook in post-merge post-checkout post-rewrite; do
    if [ -e "$hooks/$hook" ] && ! grep -q 'stamp-build.sh' "$hooks/$hook" 2>/dev/null; then
      echo "stamp-build: leaving your existing $hook hook alone" >&2
      continue
    fi
    printf '#!/bin/sh\n# Refresh HEADROOM_BUILD_SHA in .env so the footer shows this commit.\nexec "$(git rev-parse --show-toplevel)/scripts/stamp-build.sh" >/dev/null 2>&1 || true\n' > "$hooks/$hook"
    chmod +x "$hooks/$hook"
  done
  echo "stamp-build: hooks installed — a pull now keeps the stamp current"
fi

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
# genuinely bad day. Written to a temp file and copied back over the SAME
# inode (`cat >`, not `mv`), so a symlinked `.env` stays a symlink and its
# permissions are kept rather than replaced with a fresh 0600 regular file.
tmp=$(mktemp)
grep -v '^HEADROOM_BUILD_SHA=' .env > "$tmp" || true
printf 'HEADROOM_BUILD_SHA=%s\n' "$sha" >> "$tmp"
cat "$tmp" > .env
rm -f "$tmp"

echo "stamp-build: HEADROOM_BUILD_SHA=$sha"
