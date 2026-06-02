"""Smoke test proving the skeleton boots + the test harness runs.
Replaced/expanded by per-module suites starting at LLD 01."""
from fastapi.testclient import TestClient

from app.main import app


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
