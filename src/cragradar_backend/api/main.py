"""ASGI app of the CragRadar API. All routes live under ``/api``."""

from fastapi import FastAPI

from cragradar_backend.api import authz

app: FastAPI = FastAPI(title="CragRadar API", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(authz.router)


@app.get("/api/healthz")
def read_health() -> dict[str, str]:
    """Liveness and readiness probe."""
    return {"status": "ok", "service": "api"}
