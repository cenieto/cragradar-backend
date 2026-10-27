from fastapi import FastAPI
from fastapi.testclient import TestClient

from cragradar_backend.api.main import app as api_app
from cragradar_backend.tiles.main import app as tiles_app


def assert_healthy(app: FastAPI, health_path: str) -> None:
    response = TestClient(app).get(health_path)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_is_healthy() -> None:
    assert_healthy(api_app, "/api/healthz")


def test_tiles_is_healthy() -> None:
    assert_healthy(tiles_app, "/tiles/healthz")
