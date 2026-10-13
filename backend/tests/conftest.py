import pytest
from app import settings
from app.db import initialize
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA", tmp_path)
    monkeypatch.setattr(settings, "DB", tmp_path / "test.sqlite3")
    monkeypatch.setattr(settings, "KEY", tmp_path / "master.key")
    monkeypatch.setattr(settings, "COOKIE_SECURE", False)
    monkeypatch.setattr(settings, "DEMO", True)
    monkeypatch.setenv("TM_ADMIN_PASSWORD", "development-only-password")
    initialize()
    return tmp_path


@pytest.fixture
def client(environment):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def admin(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "development-only-password"},
    )
    assert response.status_code == 200
    client.headers["x-csrf-token"] = response.json()["csrf"]
    return client
