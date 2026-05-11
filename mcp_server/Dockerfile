# syntax=docker/dockerfile:1.7

# Multi-stage build for the property_maintenance_mcp server.
# Stage 1 installs dependencies with uv into a venv, stage 2 copies the venv
# and source into a slim runtime image and runs as a non-root user.

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.5.11

# ---------- builder ----------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install uv (pinned)
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Install build deps for any wheels we need to compile (asyncpg, greenlet, etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Resolve and install Python dependencies first (cache-friendly)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy source and install the project itself
COPY agent ./agent
COPY mcp_server ./mcp_server
COPY main.py ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ---------- runtime ----------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

WORKDIR /app

# Non-root user
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home-dir /app --shell /sbin/nologin app

COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

# FastMCP exposes /mcp on the configured port when running streamable-http.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
req=urllib.request.Request('http://127.0.0.1:${MCP_PORT}/mcp', method='GET'); \
sys.exit(0 if urllib.request.urlopen(req, timeout=3).status < 500 else 1)" || exit 1

CMD ["python", "-m", "mcp_server.server"]
