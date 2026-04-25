"""Tests for web app factory."""
from fastapi.testclient import TestClient


def test_app_creates(client: TestClient):
    response = client.get("/api/system/doctor")
    assert response.status_code == 200


def test_api_prefix(client: TestClient):
    response = client.get("/api/system/doctor")
    assert response.json() == {"checks": []}
