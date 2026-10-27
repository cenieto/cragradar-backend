# cragradar-backend

FastAPI backend of CragRadar. Published to PyPI (Python package) and to GHCR (container image).
Deployment manifests live in `cragradar-backend-service`, not here.

## Processes

The same package runs as three processes, each with its own entrypoint:

| Process | Entrypoint | Role |
| --- | --- | --- |
| `api` | `uvicorn cragradar_backend.api.main:app` | Resumable uploads (tus) under `/api/uploads`, images under `/api/images`, and `/api/authz/tiles`, called by the nginx tile cache to authorize every tile request. |
| `tiles` | `uvicorn cragradar_backend.tiles.main:app` | Deep Zoom descriptor and tiles of ready images, cut on the fly by pyvips from their pyramidal TIFF: `/tiles/<id>/v<version>/image.dzi`. |
| `worker` | `cragradar-worker` | Converts each complete upload once to a pyramidal tiled TIFF, then stores the original and the pyramid. |

`cragradar-migrate` runs Alembic on the packaged migrations, with the arguments of the `alembic`
command (`upgrade head`, `revision --autogenerate -m "..."`).

## Image lifecycle

`uploading` (tus chunks arriving) → `uploaded` (queued) → `processing` (a worker holds its lease)
→ `ready` (tiles served) or `failed` (`error` tells why). The `images` table is the job queue.

## Configuration

pydantic-settings (`cragradar_backend.core.settings`), from highest to lowest priority:

1. `CRAGRADAR_*` environment variables, nested with `__`, such as `CRAGRADAR_OIDC__ISSUER` and
   `CRAGRADAR_DATABASE__URL`.
2. The YAML file named by `CRAGRADAR_SETTINGS_FILE`, mounted from the `backend-settings`
   ConfigMap of `cragradar-backend-service`.

`repository` and `tiler` are built by `racker` from their `type:` configuration, as in
`crag-radar-back`, and are only read from the file.

## Layout

```
src/cragradar_backend/
  racker/     class <-> config registry (from crag-radar-back)
  repos/      file repositories and path generators (from crag-radar-back)
  tiler/      Deep Zoom tiler (from crag-radar-back)
  core/       settings, database, token validation, cragradar-migrate
  models/     SQLAlchemy models
  api/        routers: authz, uploads (tus), images
  tiles/      tile ASGI app
  ingest/     pyramid builder, staging paths
  worker/     job queue and entrypoint
  migrations/ Alembic
test/         mirrors src/; uses SQLite, so it runs without PostgreSQL
```

## Stack

Python 3.12+, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 (async, asyncpg) + Alembic,
PyJWT, pyvips. Tooling: uv, ruff, mypy (strict, on `src`), pytest.

## Develop

Nothing is installed on the laptop. Two complementary ways to work, both using the `dev` stage of
the `Dockerfile`:

- **Run:** `tilt up` from the umbrella `cragradar` repository runs this app in the local cluster and
  syncs code edits into the running container.
- **Edit:** open this folder in VS Code and choose **Reopen in Container** for autocompletion,
  type checking and tests in the editor. Tests, ruff and mypy also run from the `checks` button in the Tilt
  dashboard.
