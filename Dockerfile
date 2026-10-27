# syntax=docker/dockerfile:1
# Stages: `dev` (used by Tilt and the dev container) and `prod` (published image).
# The same image runs every process; the Kubernetes Deployment chooses the command.
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
# UID 1000 matches the WSL user, so files written into bind mounts stay owned by the developer.
RUN useradd --uid 1000 --create-home app \
    && mkdir /opt/venv /app \
    && chown app:app /opt/venv /app
USER app
WORKDIR /app

FROM base AS dev
COPY --chown=app pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000 uv sync --frozen --no-install-project
COPY --chown=app . .
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000 uv sync --frozen
# uvicorn reads its options from UVICORN_* variables: dev images reload on code changes.
ENV UVICORN_RELOAD=true UVICORN_RELOAD_DIRS=/app/src
CMD ["uvicorn", "cragradar_backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS prod
ENV UV_COMPILE_BYTECODE=1
COPY --chown=app pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000 uv sync --frozen --no-dev --no-install-project
COPY --chown=app . .
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000 uv sync --frozen --no-dev --no-editable
CMD ["uvicorn", "cragradar_backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
