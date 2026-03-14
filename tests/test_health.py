"""Phase 0 smoke tests — healthcheck, root, i18n."""

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_health_returns_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


def test_root_default_locale_ko():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "J.A.R.V.I.S" in resp.json()["message"]


def test_root_locale_en():
    resp = client.get("/?locale=en")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Hello, I'm J.A.R.V.I.S. How can I help you?"
