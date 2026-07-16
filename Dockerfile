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
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
# .git never enters the build context, so the footer's build SHA must be
# injected via this arg (empty → footer hides it).
ARG HEADROOM_BUILD_SHA=""
ENV HEADROOM_BUILD_SHA=$HEADROOM_BUILD_SHA
RUN npx tsc -b --noEmit && npx vite build

# ============================================================ #
# Stage 2 — Python deps via uv (also pre-caches the rembg model)
# ============================================================ #
FROM python:3.12-slim-bookworm AS python-base
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# rembg + Pillow + onnxruntime need a few system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libheif1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
# --frozen only, no fallback: a lock/manifest mismatch must FAIL the release
# build, not silently resolve fresh unpinned versions (S12). Run `uv lock`
# and commit uv.lock if this errors.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Pre-cache the rembg model so the Pi doesn't have to download on first photo
ARG REMBG_MODEL=u2netp
ENV HEADROOM_REMBG_MODEL=${REMBG_MODEL}
RUN /opt/venv/bin/python -c "from rembg import new_session; new_session('${REMBG_MODEL}')"

# ============================================================ #
# Stage 3 — Runtime (non-root)
# ============================================================ #
FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HEADROOM_UPLOAD_DIR=/data/uploads \
    HEADROOM_DATABASE_URL=sqlite+aiosqlite:////data/headroom.db \
    HEADROOM_REMBG_MODEL=u2netp

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libheif1 tini \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged user so the container does not run as root
RUN groupadd --system --gid 1000 headroom \
    && useradd --system --uid 1000 --gid headroom --home-dir /home/headroom --create-home headroom

# Bring in venv + cached rembg model + source + built SPA + seed assets
COPY --from=python-base /opt/venv /opt/venv
COPY --from=python-base --chown=headroom:headroom /root/.u2net /home/headroom/.u2net
COPY --from=python-base --chown=headroom:headroom /app/src /app/src
COPY --from=frontend --chown=headroom:headroom /build/dist /app/frontend/dist
COPY --chown=headroom:headroom pyproject.toml /app/
COPY --chown=headroom:headroom seed /app/seed

WORKDIR /app
RUN mkdir -p /data/uploads/cases /data/uploads/hats /data/uploads/branding \
    && chown -R headroom:headroom /data /app

USER headroom

VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
# --proxy-headers honors X-Forwarded-* so session cookies get the `secure`
# flag behind the Caddy HTTPS overlay. Which peers are TRUSTED to send those
# headers is controlled by uvicorn's FORWARDED_ALLOW_IPS env var — default
# 127.0.0.1, so clients hitting :8000 directly cannot spoof their IP (which
# would defeat login rate limiting). The HTTPS overlay sets it to "*" only
# because it stops publishing :8000 — then only in-network Caddy can connect.
CMD ["uvicorn", "headroom.app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers"]
