# syntax=docker/dockerfile:1.6
#
# Multi-stage build:
#   1. node       — install JS deps + build the SPA
#   2. python-base — install uv + Python deps + cache the rembg model
#   3. runtime    — slim image with the built SPA + Python app, runs as non-root
#
# Builds on linux/arm64 (Raspberry Pi 4/5) and linux/amd64.

# ============================================================ #
# Stage 1 — Frontend bundle
# ============================================================ #
# Declared first so Dependabot sees it (see the note where it is COPYed in).
FROM ghcr.io/astral-sh/uv:0.12.1 AS uv

FROM node:26-trixie-slim AS frontend
# node:26 bundles npm 11.x, which prints a "New major version available" notice
# on every build. Pin the npm we actually want rather than living with the
# nag — same convention as the uv pin below. Bump this alongside the base image.
ARG NPM_VERSION=12.0.2
RUN npm install -g "npm@${NPM_VERSION}"
# npm 12 logs a "notice" line for every script it runs. Warnings and errors
# still print — this only drops the informational chatter, so a real problem
# in the SPA build stays visible instead of scrolling past in a wall of notices.
ENV NPM_CONFIG_LOGLEVEL=warn
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
# Cache mount, matching the uv one in the Python stage below.
#
# This layer is busted by every release, because cutting one edits
# `frontend/package.json` — so without a cache the Pi re-downloaded the entire
# dependency tree over its own network on every single upgrade, which is the
# slowest part of `docker compose up -d --build` there. The mount survives the
# layer invalidation: npm still re-resolves, it just stops re-fetching.
#
# `--prefer-offline` makes it use those cached tarballs instead of revalidating
# each one against the registry, which is most of the remaining wall time on a
# link like that.
# `--no-audit --no-fund` drop two registry round trips whose output nobody
# reads during a deploy. `--ignore-scripts` is deliberately NOT here: rolldown
# and esbuild fetch their platform binary in a postinstall, so skipping scripts
# produces a build that fails later and further away.
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline --no-audit --no-fund
COPY frontend/ ./
# .git never enters the build context, so the footer's build SHA must be
# injected via this arg (empty → footer hides it).
ARG HEADROOM_BUILD_SHA=""
ENV HEADROOM_BUILD_SHA=$HEADROOM_BUILD_SHA
RUN npx tsc -b --noEmit && npx vite build

# ============================================================ #
# Stage 2 — Python deps via uv (also pre-caches the rembg model)
# ============================================================ #
# One base for both Python stages: the image tag and the native-lib list each
# lived in two places, so adding a lib for a new dep to only the builder used to
# build clean and then fail on import at container start.
FROM python:3.14-slim-trixie AS base
# rembg + Pillow + onnxruntime need these; tini is the runtime init.
# Cache mounts, so a cold rebuild does not re-download the same debs.
# `docker-clean` is Debian's hook that deletes them straight after install,
# which would empty the cache we are trying to fill. Neither mount lands in
# the layer, so the image is no bigger and the explicit `rm -rf` this replaces
# is no longer needed to keep it small.
# `rsync` + `openssh-client` are here for the off-site backup upload, and they
# are in the IMAGE rather than bind-mounted from the host on purpose. rclone is
# ~50 MB and mounted by its overlay; these two are ~3 MB together, and mounting
# them meant the two most ordinary destinations — another Linux box, a Synology
# — could not work without an overlay whose only job was to supply a binary the
# image could have carried all along.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libheif1 tini rsync openssh-client

FROM base AS python-base
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The uv binary comes from the `uv` stage declared at the top of this file —
# a `FROM ... AS uv` line rather than a `COPY --from=ghcr.io/...:tag`, because
# Dependabot's docker ecosystem parses FROM lines and nothing else: the pin sat
# in a COPY for months, eleven updater runs reported "no dependencies to
# update", and it was never bumped once. The rule the pin must satisfy: the
# pinned uv must read the lock's `revision` (3) and be >= 0.9.17, where
# `exclude-newer` learned relative durations ("7 days") — an older uv warns
# "failed to parse year in date" and then silently IGNORES the cooldown, so the
# image would build without the supply-chain protection we advertise.
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
# Dependencies install from a VERSION-FREE export of the lock, and that is the
# single biggest thing in this file.
#
# Measured on the Pi this deploys to: a release rebuild took 873s, and 490s of
# it was reinstalling dependencies that had not changed. Cutting a release
# edits the `version` field in pyproject.toml — which is the file that used to
# gate this step — so `COPY pyproject.toml` busted every time, `uv sync` re-ran
# (237s), and the rembg model layer below it fell with it (149s). The cache
# mount meant nothing was re-DOWNLOADED, but uv still unpacked and
# bytecode-compiled thousands of files onto an SD card.
#
# `requirements.txt` is `uv export --no-emit-project` — the same locked,
# hash-pinned set, with the project itself (and therefore its version) left
# out. It is byte-identical across a version bump, so this layer now survives
# one. `tests/test_requirements_export.py` fails if it drifts from uv.lock.
#
# --require-hashes keeps the supply-chain guarantee `--frozen` gave here: every
# artifact must match the digest recorded in the lock, so a compromised mirror
# cannot substitute one.
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv \
 && uv pip install --python /opt/venv --require-hashes -r requirements.txt

# Before COPY src on purpose: this only needs rembg (installed above), so
# keeping it here means a source edit doesn't re-download ~40s of ONNX weights.
ARG REMBG_MODEL=isnet-general-use
ENV HEADROOM_REMBG_MODEL=${REMBG_MODEL}
# The weights are ~179 MB, and this layer busts whenever anything above it
# changes — a dependency bump, the uv pin, the model arg. On a Pi that meant a
# 179 MB download over a home connection to reproduce a file that had not
# changed. `U2NET_HOME` points rembg at a BuildKit cache mount; the copy
# afterwards materializes the weights INTO the layer, which is required because
# a cache mount is not part of the image and the runtime stage `COPY --from`s
# this exact path. The runtime stage sets `U2NET_HOME` to where the copy
# lands, or rembg looks in `~/.rembg` and downloads the weights again.
#
# The `python -c` body looks odd for a reason. onnxruntime probes the host for
# GPUs while `import onnxruntime` runs and logs a WARNING per device it can't
# read — guaranteed noise in a container, which has none, and it buries real
# build errors. Those messages come from C++ straight to fd 2 *during the
# import*, so `set_default_logger_severity()` runs too late to stop them; only
# an fd-level redirect works, and it is restored immediately so anything rembg
# reports afterwards still surfaces. Build-step only — the runtime keeps
# onnxruntime's default logging.
# NON-FATAL, deliberately. Every other network call in this build is a package
# manager against a registry; this one is arbitrary Python reaching out to a
# file host, and it is the only build step that can fail for a reason that has
# nothing to do with this project. rembg fetches the weights on first use
# anyway, so a failure here costs a slow first analysis — not a deploy you
# cannot perform because someone else's host is down.
#
# The directory is created FIRST so the runtime stage's `COPY --from` has
# something to copy even when the fetch failed.
RUN --mount=type=cache,target=/opt/model-cache,sharing=locked \
    mkdir -p /root/.u2net \
 && { U2NET_HOME=/opt/model-cache /opt/venv/bin/python -c "\
import os; _n=os.open(os.devnull, os.O_WRONLY); _e=os.dup(2); os.dup2(_n, 2); \
import onnxruntime; os.dup2(_e, 2); os.close(_n); os.close(_e); \
onnxruntime.set_default_logger_severity(3); \
from rembg import new_session; new_session('${REMBG_MODEL}')" \
      && cp -a /opt/model-cache/. /root/.u2net/ \
      && echo "rembg model ${REMBG_MODEL} cached into the image" ; } \
 || echo "WARNING: could not pre-cache the rembg model — the app will download it on first use"

# The project itself, last: this is the layer that SHOULD bust on every
# release, and it is cheap (measured 6.5s) because the venv above already
# satisfies the lock. --frozen only, no fallback: a lock/manifest mismatch must
# FAIL the release build, not silently resolve fresh unpinned versions (S12).
# Run `uv lock` and commit uv.lock if this errors.
COPY pyproject.toml uv.lock* ./
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ============================================================ #
# Stage 3 — Runtime (non-root)
# ============================================================ #
FROM base AS runtime
# Re-declare so the chosen model reaches THIS stage: `ARG` is scoped per stage,
# and hardcoding u2netp here silently discarded the build arg — the image then
# carried a pre-downloaded model it would never load.
ARG REMBG_MODEL=isnet-general-use
# `U2NET_HOME` is what makes the baked model FOUND. rembg 2.0.81 resolves its
# home to `~/.rembg` unless `U2NET_HOME` (or `REMBG_HOME`) is set, and reads
# the legacy `~/.u2net` only for the old flat `<name>.onnx` layout — which the
# bake above does not produce (it writes `models/<name>/<name>.onnx`). So the
# image carried 179 MB of weights at a path nothing looked in, every container
# fetched them again from GitHub on its first analysis (into the writable
# layer, so again after every rebuild), and an offline Pi could not analyze at
# all. Verified with `--network none`: without this line `new_session()`
# raises ConnectionError; with it, the session loads. CI now runs that exact
# probe, because `/health/ready` passing says nothing about the model.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HEADROOM_UPLOAD_DIR=/data/uploads \
    HEADROOM_DATABASE_URL=sqlite+aiosqlite:////data/headroom.db \
    HEADROOM_REMBG_MODEL=${REMBG_MODEL} \
    U2NET_HOME=/home/headroom/.u2net

# Create unprivileged user so the container does not run as root
RUN groupadd --system --gid 1000 headroom \
    && useradd --system --uid 1000 --gid headroom --home-dir /home/headroom --create-home headroom

# Bring in venv + cached rembg model + source + built SPA + seed assets.
#
# Root-owned, deliberately. These used to be `--chown=headroom` plus a
# `chown -R headroom /app`, which made the app's own code, the SPA bundle and
# the 179 MB model WRITABLE by the runtime user — so a remote code execution
# or a malicious dependency could edit `app.py` in place and survive every
# restart the watchdog and autoheal issue. Nothing under `/app` or the model
# directory is written at runtime (verified: the container boots and passes
# readiness under `--read-only --tmpfs /tmp`), so only `/data` is the app's
# to write. "Runs as non-root" is half the hardening it reads as when
# non-root owns the code.
#
# `pyproject.toml` is NOT copied: the venv carries the installed
# distribution's metadata and nothing in `src/` reads the file.
COPY --from=python-base /opt/venv /opt/venv
COPY --from=python-base /root/.u2net /home/headroom/.u2net
COPY --from=python-base /app/src /app/src
COPY --from=frontend /build/dist /app/frontend/dist
COPY seed /app/seed

WORKDIR /app
RUN mkdir -p /data/uploads/hats /data/uploads/branding \
    && chown -R headroom:headroom /data /home/headroom \
    && chmod -R a+rX /app /home/headroom/.u2net

USER headroom

VOLUME ["/data"]
EXPOSE 8000

# The same probe `docker-compose.yml` runs, for `docker run` users and CI:
# without it `docker inspect` reported no healthcheck at all outside compose.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=30s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready', timeout=5).status==200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
# --proxy-headers honors X-Forwarded-* so session cookies get the `secure`
# flag behind the Caddy HTTPS overlay. Which peers are TRUSTED to send those
# headers is controlled by uvicorn's FORWARDED_ALLOW_IPS env var — default
# 127.0.0.1, so clients hitting :8000 directly cannot spoof their IP (which
# would defeat login rate limiting). The Let's Encrypt overlay pins it to the
# compose network's own subnet (172.31.71.0/24, docker-compose.https.yml), so
# only the Caddy container beside it is trusted; the LAN overlays keep loopback.
CMD ["uvicorn", "headroom.app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers"]
