# syntax=docker/dockerfile:1.7
# The API image. Build from the repo root:
#   docker build -f apps/api/Dockerfile -t kb-assistant-api:local .
#
# Two stages: "build" has uv and resolves the locked dependencies into /app/.venv;
# "runtime" gets only that virtualenv, runs as a non-root user and has no build tools.

# Both stages use the same Python base, so the virtualenv's interpreter link stays valid.
FROM ghcr.io/astral-sh/uv:0.11 AS uv

FROM python:3.12-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src

# 1. Third-party dependencies only. This layer is reused until uv.lock or a
#    pyproject.toml changes, so code edits rebuild in seconds. uv needs every
#    workspace member's pyproject.toml to read the workspace, hence apps/mcp too.
COPY pyproject.toml uv.lock ./
COPY packages/kb_core/pyproject.toml packages/kb_core/
COPY apps/api/pyproject.toml apps/api/
COPY apps/mcp/pyproject.toml apps/mcp/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package kb-api

# 2. Our code, installed as regular packages (not editable links to /src).
COPY packages/kb_core packages/kb_core
COPY apps/api apps/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package kb-api

FROM python:3.12-slim-bookworm AS runtime
# A fixed, unprivileged user. Files stay owned by root, so the app can't modify its own code.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /tmp --no-create-home app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp
WORKDIR /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["uvicorn", "kb_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
