"""ASGI app of the CragRadar tile server. All routes live under ``/tiles``."""

from fastapi import FastAPI

app: FastAPI = FastAPI(title="CragRadar tiles", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/tiles/healthz")
def read_health() -> dict[str, str]:
    """Liveness and readiness probe."""
    return {"status": "ok", "service": "tiles"}
