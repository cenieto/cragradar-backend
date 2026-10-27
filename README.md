# cragradar-backend

FastAPI backend of CragRadar. Published to PyPI (Python package) and to GHCR (container image).
Deployment manifests live in `cragradar-backend-service`, not here.

## Processes

The same package runs as three processes, each with its own entrypoint:

| Process | Role |
| --- | --- |
| `api` | Admin, content, locations and annotation endpoints. Also `/authz`, called by the nginx tile cache to authorize every tile request. |
| `tiles` | Read-only DeepZoom tile endpoint. Cuts tiles on the fly with pyvips from the pyramidal TIFF of each image. |
| `worker` | Background jobs: converts each uploaded image to a pyramidal tiled TIFF once. |

## Planned layout

```
src/cragradar_backend/
  core/       settings, database, JWT validation against the Keycloak JWKS
  storage/    storage interface: local filesystem now, S3 later (selected by config)
  models/     SQLAlchemy models (PostgreSQL + PostGIS)
  schemas/    Pydantic models of the API
  api/        routers: admin, users, tags, locations, images, annotations, locks, authz
  tiles/      tile ASGI app
  worker/     ingest jobs
migrations/   Alembic
test/
```

## Stack

Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + Alembic, pyvips, Redis (job queue and
authorization cache). Tooling: uv, ruff, mypy (strict), pytest.

Code from `crag-radar-back` (on-demand DeepZoom tiler, storage repositories) is meant to move here.

## Develop

Nothing is installed on the laptop. Two complementary ways to work, both using the `dev` stage of
the `Dockerfile`:

- **Run:** `tilt up` from the umbrella `cragradar` repository runs this app in the local cluster and
  syncs code edits into the running container.
- **Edit:** open this folder in VS Code and choose **Reopen in Container** for autocompletion,
  type checking and tests in the editor. Tests, ruff and mypy also run from the `checks` button in the Tilt
  dashboard.
