#!/usr/bin/env bash
#
# Headroom setup — installs every dependency, then prepares the app.
#
#   ./scripts/setup.sh                 # full setup (deps + Docker engine + build)
#   ./scripts/setup.sh --docker-only   # ONLY install the Docker engine, then exit
#                                      # (for the `docker compose up` path)
#   ./scripts/setup.sh --no-docker     # skip the Docker engine install
#   ./scripts/setup.sh --skip-build    # skip the production SPA build
#
# Installs (only what's missing — safe to re-run):
#   * uv        — brew on macOS, otherwise the official Astral installer
#   * Node      — brew on macOS, NodeSource on apt/dnf Linux. Accepts an
#                 existing Node that every locked package's `engines`
#                 accepts: 22.22.2+ on the 22 line, 24.15+ on the 24 line, or
#                 26+ (jsdom 30's range; 23, 25 and early 24 are refused);
#                 a FRESH install gets 26, matching the Docker image.
#   * Docker    — WITHOUT Docker Desktop:
#                   macOS: docker CLI + compose + buildx + colima (brew)
#                   Linux: Docker Engine via get.docker.com (apt & dnf distros)
#   * Python    — handled by uv itself. `.python-version` pins 3.14 (same as the
#                 Docker image); pyproject still supports >=3.12 if you bring
#                 your own.
#
set -euo pipefail

INSTALL_DOCKER=1
BUILD_SPA=1
DOCKER_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --docker-only) DOCKER_ONLY=1 ;;
    --no-docker)  INSTALL_DOCKER=0 ;;
    --skip-build) BUILD_SPA=0 ;;
    # Print the leading comment block itself. A hardcoded line range silently
    # truncates the moment the header grows — which is exactly what happened.
    -h|--help)    awk 'NR>1 && !/^#/{exit} NR>1{sub(/^# ?/,""); print}' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done
[ "$DOCKER_ONLY" -eq 1 ] && [ "$INSTALL_DOCKER" -eq 0 ] \
  && { echo "--docker-only and --no-docker are mutually exclusive"; exit 1; }

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

# Download an installer to a temp file, then run it — never `curl | bash`.
# A failed/truncated download aborts (curl -f + set -e) instead of executing
# half a script, and the file can be inspected before execution if desired.
run_remote_installer() {
  local url="$1"; shift
  local tmp
  tmp="$(mktemp)"
  curl -fsSL "$url" -o "$tmp"
  "$@" "$tmp"
  rm -f "$tmp"
}

OS="$(uname -s)"
SUDO=""
[ "${EUID:-$(id -u)}" -ne 0 ] && SUDO="sudo"

# ------------------------------------------------------------------ #
# Homebrew (macOS only)
# ------------------------------------------------------------------ #
ensure_brew() {
  command -v brew &>/dev/null && return 0
  log "Homebrew not found — installing (you may be asked for your password)..."
  run_remote_installer \
    "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh" \
    env NONINTERACTIVE=1 /bin/bash
  # Put brew on PATH for the rest of this run (Apple Silicon vs Intel)
  if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"
  fi
  command -v brew &>/dev/null || die "Homebrew install failed — see https://brew.sh"
}

# ------------------------------------------------------------------ #
# uv
# ------------------------------------------------------------------ #
UV_FRESHLY_INSTALLED=0

ensure_uv() {
  command -v uv &>/dev/null && return 0
  log "Installing uv..."
  if [ "$OS" = "Darwin" ]; then
    ensure_brew
    brew install uv
  else
    run_remote_installer "https://astral.sh/uv/install.sh" sh
    export PATH="$HOME/.local/bin:$PATH"
    UV_FRESHLY_INSTALLED=1
  fi
  command -v uv &>/dev/null || die "uv install failed — see https://docs.astral.sh/uv/"
}

# ------------------------------------------------------------------ #
# Node.js — accept what the lockfile accepts, install 26 (the image's)
#
# What `npm ci` will run on is the INTERSECTION of every locked package's
# `engines.node`, and `frontend/.npmrc` sets `engine-strict`, so anything
# outside it is a hard EBADENGINE error. That set is not "at least N" any
# more: jsdom 30 declares `^22.22.2 || ^24.15.0 || >=26.0.0`, which refuses
# Node 23, Node 25 and 24.0–24.14 — the last of those an LTS line people
# actually run. A single floor (this was `>= 22.22`) passed all of them here
# and then died in `npm ci`.
#
# So the accepted set is spelled as data: one minimum per supported release
# line, plus the major from which everything is accepted. `frontend/
# package.json`'s `engines` states the same range, and
# `tests/test_toolchain_pins.py` derives the intersection from
# `package-lock.json` and checks this function against it version by
# version — so a dependency that narrows the range fails a test, not a setup.
# ------------------------------------------------------------------ #
NODE_LINE_MINIMUMS="22.22.2 24.15.0"
NODE_OPEN_FROM_MAJOR=26
# What a fresh install gets. The Docker image's `FROM node:` major and CI's
# `node-version` must match it; the toolchain test holds all three together.
NODE_INSTALL_MAJOR=26

# 0 = usable, 1 = outside the accepted set or absent. One `node -v`.
node_ok() {
  [[ $(node -v 2>/dev/null) =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+) ]] || return 1
  local major=${BASH_REMATCH[1]} minor=${BASH_REMATCH[2]} patch=${BASH_REMATCH[3]}
  local line lmajor lminor lpatch
  if (( major >= NODE_OPEN_FROM_MAJOR )); then return 0; fi
  for line in $NODE_LINE_MINIMUMS; do
    IFS=. read -r lmajor lminor lpatch <<< "$line"
    if (( major == lmajor )); then
      if (( minor > lminor || (minor == lminor && patch >= lpatch) )); then return 0; fi
      return 1
    fi
  done
  return 1
}

# The accepted set, for messages.
node_range() {
  local line out=""
  for line in $NODE_LINE_MINIMUMS; do out+="${line%%.*}.x from ${line}, "; done
  printf '%s%s+' "$out" "$NODE_OPEN_FROM_MAJOR"
}

# npm — the Docker image pins npm 12 in its frontend stage (Dockerfile
# `ARG NPM_VERSION`). Node ships an older npm with every release, so without
# this a bare-metal setup would build the SPA on a different npm than the image
# does — the exact drift this script exists to prevent. Keep NPM_MIN_MAJOR and
# NPM_INSTALL in step with the Dockerfile when either moves.
NPM_MIN_MAJOR=12
NPM_INSTALL="12.1.0"

npm_ok() {
  [[ $(npm --version 2>/dev/null) =~ ^([0-9]+) ]] || return 1
  (( BASH_REMATCH[1] >= NPM_MIN_MAJOR ))
}

ensure_npm() {
  if npm_ok; then return 0; fi
  log "npm $(npm --version 2>/dev/null || echo 'missing') is older than ${NPM_MIN_MAJOR} (the image builds on ${NPM_INSTALL}) — upgrading..."
  npm install -g "npm@${NPM_INSTALL}" \
    || warn "Could not upgrade npm automatically."

  # Re-check rather than trusting the exit code. `npm install -g` can succeed
  # while changing nothing you will actually run: a global prefix that isn't
  # on PATH (nvm, a Homebrew node, a --prefix in ~/.npmrc) installs the new
  # npm somewhere the next command won't find. The failure then shows up much
  # later as the SPA being built by a different npm than the image uses, which
  # is precisely the drift this function exists to prevent — so say it now.
  hash -r 2>/dev/null || true
  if npm_ok; then
    log "npm is now $(npm --version)."
    return 0
  fi
  local current npm_path
  current="$(npm --version 2>/dev/null || echo 'missing')"
  npm_path="$(command -v npm 2>/dev/null || echo '')"

  # Homebrew's node formula OWNS /opt/homebrew/bin/npm as a symlink into its
  # Cellar, so `npm install -g npm@X` writes into Homebrew's tree and the next
  # `brew upgrade node` puts it back. npm therefore cannot be held above
  # whatever the node formula ships. Saying "run it again" here would send
  # someone round a loop that cannot terminate.
  if [[ "$npm_path" == /opt/homebrew/* || "$npm_path" == /usr/local/Cellar/* ]] \
     && [[ "$(readlink "$npm_path" 2>/dev/null)" == *Cellar* ]]; then
    warn "npm is $current and Homebrew's node formula owns it — a global upgrade won't stick."
    warn "  This is cosmetic for Docker deploys: the image installs npm ${NPM_INSTALL} in its own"
    warn "  build stage, so the shipped SPA is built on the pinned version regardless."
    warn "  It only matters if you build the SPA on THIS machine for a bare-metal deploy."
    return 0
  fi

  warn "npm is STILL $current after the upgrade — the image builds on ${NPM_INSTALL}."
  warn "  Your global npm prefix is likely not on PATH: $(npm prefix -g 2>/dev/null || echo '(unknown)')"
  warn "  Fix it with:  npm install -g npm@${NPM_INSTALL}    (sudo, or correct the prefix)"
  warn "  The SPA will still build; it just won't be on the npm the image uses."
}

ensure_node() {
  if node_ok; then return 0; fi
  if command -v node &>/dev/null; then
    log "Node $(node -v) is outside what the frontend's dependencies accept ($(node_range)) — installing ${NODE_INSTALL_MAJOR}..."
  else
    log "Installing Node.js ${NODE_INSTALL_MAJOR}..."
  fi
  if [ "$OS" = "Darwin" ]; then
    ensure_brew
    brew install node
  elif command -v apt-get &>/dev/null; then
    run_remote_installer "https://deb.nodesource.com/setup_${NODE_INSTALL_MAJOR}.x" $SUDO bash
    $SUDO apt-get install -y nodejs
  elif command -v dnf &>/dev/null; then
    run_remote_installer "https://rpm.nodesource.com/setup_${NODE_INSTALL_MAJOR}.x" $SUDO bash
    $SUDO dnf install -y nodejs
  else
    die "No supported package manager found — install Node.js ${NODE_INSTALL_MAJOR} from https://nodejs.org/ and re-run."
  fi
  hash -r 2>/dev/null || true
  node_ok || die "Node install failed, or $(node -v 2>/dev/null || echo 'none') is still outside $(node_range)."
}

# ------------------------------------------------------------------ #
# Docker engine — deliberately NOT Docker Desktop.
#   macOS: docker CLI + compose/buildx plugins + colima (lightweight VM)
#   Linux: native Docker Engine via Docker's official install script
# ------------------------------------------------------------------ #
#: 1 once `docker info` has answered — the DAEMON, not merely the CLI. Read by
#: the --docker-only path, which must not print "ready" over a dead engine.
DOCKER_READY=0

ensure_docker() {
  if docker info &>/dev/null; then
    log "Docker is already installed and running — leaving it alone."
    DOCKER_READY=1
    return 0
  fi

  if [ "$OS" = "Darwin" ]; then
    ensure_brew
    if ! command -v docker &>/dev/null || ! command -v colima &>/dev/null; then
      log "Installing docker CLI + compose + buildx + colima (no Docker Desktop)..."
      brew install docker docker-compose docker-buildx colima
    fi
    # Homebrew installs compose/buildx as standalone binaries; the docker CLI
    # discovers them via ~/.docker/cli-plugins so `docker compose` works.
    mkdir -p "$HOME/.docker/cli-plugins"
    ln -sfn "$(brew --prefix)/opt/docker-compose/bin/docker-compose" \
      "$HOME/.docker/cli-plugins/docker-compose"
    ln -sfn "$(brew --prefix)/opt/docker-buildx/bin/docker-buildx" \
      "$HOME/.docker/cli-plugins/docker-buildx"
    if ! colima status &>/dev/null; then
      log "Starting colima (first run downloads a VM image — a few minutes)..."
      colima start --memory 4
    fi
  elif [ "$OS" = "Linux" ]; then
    if ! command -v docker &>/dev/null; then
      log "Installing Docker Engine via get.docker.com (apt/dnf aware)..."
      run_remote_installer "https://get.docker.com" $SUDO sh
    fi
    command -v systemctl &>/dev/null && $SUDO systemctl enable --now docker || true
    _user="${USER:-$(id -un)}"
    if [ -n "$SUDO" ] && ! id -nG "$_user" | tr ' ' '\n' | grep -qx docker; then
      $SUDO usermod -aG docker "$_user"
      warn "Added $_user to the docker group — log out/in (or run 'newgrp docker') before using docker without sudo."
    fi
  else
    warn "Unsupported OS '$OS' for automatic Docker install — see https://docs.docker.com/engine/install/"
    return 0
  fi

  # The DAEMON, and only the daemon. This was `docker info || docker --version
  # || warn`, and `--version` answers from the CLI alone — so with the engine
  # installed but not running (or this user not yet in the docker group) the
  # warning never fired, and `--docker-only` went on to print "ready".
  if docker info &>/dev/null; then
    DOCKER_READY=1
  elif command -v docker &>/dev/null; then
    warn "Docker is installed but the daemon isn't reachable yet — see notes above"
    warn "  (a fresh docker-group membership needs a new login; 'docker info' shows why)."
  else
    warn "Docker did not install — see https://docs.docker.com/engine/install/"
  fi
}

# Everything above defines; everything below runs. Sourcing the file stops
# here, which is how tests/test_setup_script.py runs the REAL `node_ok` and
# `ensure_docker` against stubbed tools instead of grepping this file's text.
[[ "${BASH_SOURCE[0]}" == "$0" ]] || return 0

cd "$(dirname "$0")/.."

# ------------------------------------------------------------------ #
# Run it
# ------------------------------------------------------------------ #
if [ "$DOCKER_ONLY" -eq 1 ]; then
  ensure_docker
  echo ""
  if [ "$DOCKER_READY" -eq 1 ]; then
    log "Docker engine ready. Next: docker compose up --build"
    exit 0
  fi
  die "Docker isn't reachable yet — see the warning above. Once 'docker info' works: docker compose up --build"
fi

ensure_uv
ensure_node
ensure_npm   # after ensure_node — a fresh Node install brings its own npm
[ "$INSTALL_DOCKER" -eq 1 ] && ensure_docker

log "Installing Python dependencies (uv fetches the .python-version Python if needed)..."
uv sync

log "Installing frontend dependencies..."
# `npm ci`, not `npm install`: install can rewrite package-lock.json (the
# Homebrew-npm case this script documents above), and the Dockerfile and CI
# both build from that lockfile.
(cd frontend && npm ci)

log "Creating upload directories..."
mkdir -p uploads/hats uploads/branding

log "Initializing database..."
uv run python -c "import asyncio; from headroom.database import init_db; asyncio.run(init_db())"

if [ "$BUILD_SPA" -eq 1 ]; then
  log "Building the production SPA (skip with --skip-build)..."
  (cd frontend && npx vite build)
fi

echo ""
if [ "$UV_FRESHLY_INSTALLED" -eq 1 ]; then
  warn "uv was installed to ~/.local/bin — your CURRENT shell can't see it yet."
  warn "Open a new terminal (or run: source \$HOME/.local/bin/env) before the commands below."
fi
# ------------------------------------------------------------------ #
# Build stamp — so the footer can say which commit is running
# ------------------------------------------------------------------ #
# `.dockerignore` excludes `.git` and the frontend build stage only receives
# `frontend/`, so nothing inside the image can work out the commit. The value
# has to be written on the host, into the `.env` that compose reads
# automatically. Hooks keep it current after a pull, so the habit stays
# `docker compose up -d --build` with nothing to remember.
# `git rev-parse`, not `[ -d .git ]`: in a git WORKTREE `.git` is a file, not a
# directory, so the old test silently skipped the stamp and the hooks on every
# worktree checkout. `stamp-build.sh` already resolves the git dir properly.
if git rev-parse --git-dir >/dev/null 2>&1; then
  ./scripts/stamp-build.sh --install-hooks || warn "Could not write the build stamp (non-fatal)."
fi

log "Setup complete! Run Headroom one of three ways:"
echo "  Single server (serves the built SPA):  uv run uvicorn headroom.app:app --host 0.0.0.0"
echo "  Dev servers:   uv run uvicorn headroom.app:app --reload"
echo "                 cd frontend && npm run dev   # http://localhost:5173"
echo "  Docker:        docker compose up -d --build # http://localhost:8000"
echo ""
echo "  On your LAN it also answers at http://headroom.local:8000 (mDNS;"
echo "  Docker needs the docker-compose.mdns.yml overlay — see README)."
