#!/usr/bin/env bash
#
# Headroom setup — installs every dependency, then prepares the app.
#
#   ./scripts/setup.sh                 # full setup (deps + Docker engine + build)
#   ./scripts/setup.sh --no-docker     # skip the Docker engine install
#   ./scripts/setup.sh --skip-build    # skip the production SPA build
#
# Installs (only what's missing — safe to re-run):
#   * uv        — brew on macOS, otherwise the official Astral installer
#   * Node 20+  — brew on macOS, NodeSource on apt/dnf Linux
#   * Docker    — WITHOUT Docker Desktop:
#                   macOS: docker CLI + compose + buildx + colima (brew)
#                   Linux: Docker Engine via get.docker.com (apt & dnf distros)
#   * Python    — handled by uv itself (downloads 3.12 if the system lacks it)
#
set -euo pipefail

cd "$(dirname "$0")/.."

INSTALL_DOCKER=1
BUILD_SPA=1
for arg in "$@"; do
  case "$arg" in
    --no-docker)  INSTALL_DOCKER=0 ;;
    --skip-build) BUILD_SPA=0 ;;
    -h|--help)    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done

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
ensure_uv() {
  command -v uv &>/dev/null && return 0
  log "Installing uv..."
  if [ "$OS" = "Darwin" ]; then
    ensure_brew
    brew install uv
  else
    run_remote_installer "https://astral.sh/uv/install.sh" sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
  command -v uv &>/dev/null || die "uv install failed — see https://docs.astral.sh/uv/"
}

# ------------------------------------------------------------------ #
# Node.js 20+
# ------------------------------------------------------------------ #
node_major() { node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1; }

ensure_node() {
  if command -v node &>/dev/null && [ "$(node_major)" -ge 20 ]; then return 0; fi
  if command -v node &>/dev/null; then
    log "Node $(node -v) is too old (need 20+) — upgrading..."
  else
    log "Installing Node.js..."
  fi
  if [ "$OS" = "Darwin" ]; then
    ensure_brew
    brew install node
  elif command -v apt-get &>/dev/null; then
    run_remote_installer "https://deb.nodesource.com/setup_22.x" $SUDO bash
    $SUDO apt-get install -y nodejs
  elif command -v dnf &>/dev/null; then
    run_remote_installer "https://rpm.nodesource.com/setup_22.x" $SUDO bash
    $SUDO dnf install -y nodejs
  else
    die "No supported package manager found — install Node.js 20+ from https://nodejs.org/ and re-run."
  fi
  [ "$(node_major)" -ge 20 ] || die "Node install failed or is still < 20."
}

# ------------------------------------------------------------------ #
# Docker engine — deliberately NOT Docker Desktop.
#   macOS: docker CLI + compose/buildx plugins + colima (lightweight VM)
#   Linux: native Docker Engine via Docker's official install script
# ------------------------------------------------------------------ #
ensure_docker() {
  if docker info &>/dev/null; then
    log "Docker is already installed and running — leaving it alone."
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
    if [ -n "$SUDO" ] && ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
      $SUDO usermod -aG docker "$USER"
      warn "Added $USER to the docker group — log out/in (or run 'newgrp docker') before using docker without sudo."
    fi
  else
    warn "Unsupported OS '$OS' for automatic Docker install — see https://docs.docker.com/engine/install/"
    return 0
  fi

  docker info &>/dev/null || docker --version &>/dev/null \
    || warn "Docker installed but the daemon isn't reachable yet — see notes above."
}

# ------------------------------------------------------------------ #
# Run it
# ------------------------------------------------------------------ #
ensure_uv
ensure_node
[ "$INSTALL_DOCKER" -eq 1 ] && ensure_docker

log "Installing Python dependencies (uv will fetch Python 3.12 if needed)..."
uv sync

log "Installing frontend dependencies..."
(cd frontend && npm install)

log "Creating upload directories..."
mkdir -p uploads/cases uploads/hats uploads/branding

log "Initializing database..."
uv run python -c "import asyncio; from headroom.database import init_db; asyncio.run(init_db())"

if [ "$BUILD_SPA" -eq 1 ]; then
  log "Building the production SPA (skip with --skip-build)..."
  (cd frontend && npx vite build)
fi

echo ""
log "Setup complete! Run Headroom one of three ways:"
echo "  Single server (serves the built SPA):  uv run uvicorn headroom.app:app --host 0.0.0.0"
echo "  Dev servers:   uv run uvicorn headroom.app:app --reload"
echo "                 cd frontend && npm run dev   # http://localhost:5173"
echo "  Docker:        docker compose up -d --build # http://localhost:8000"
