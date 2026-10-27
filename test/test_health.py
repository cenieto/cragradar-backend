"""Health endpoints, used by the Kubernetes probes."""

from fastapi.testclient import TestClient

from cragradar_backend.api.main import app as api_app
from cragradar_backend.tiles.main import app as tiles_app


def test_api_is_healthy() -> None:
    """Check that the API answers its probe without settings or database."""
    assert TestClient(api_app).get("/api/healthz").json()["status"] == "ok"


def test_tiles_is_healthy() -> None:
    """Check that the tile server answers its probe without settings or database."""
    assert TestClient(tiles_app).get("/tiles/healthz").json()["status"] == "ok"
