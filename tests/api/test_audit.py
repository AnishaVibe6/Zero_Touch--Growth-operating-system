from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_supabase(mocker):
    mocker.patch("app.services.supabase_client.supabase_client.create_audit")
    mocker.patch("app.services.supabase_client.supabase_client.update_audit_status")


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_start_audit_returns_202():
    with patch("app.api.routes.audit.launch_audit", return_value="test-uuid-1234"):
        resp = client.post("/audit", json={
            "business_name": "Sharma Electronics",
            "website_url": "https://sharma.com",
            "location": "Delhi",
        })
    assert resp.status_code == 202
    assert resp.json()["audit_id"] == "test-uuid-1234"
    assert resp.json()["status"] == "pending"


def test_get_audit_not_found():
    with patch("app.api.routes.audit.supabase_client.get_audit", return_value=None):
        resp = client.get("/audit/nonexistent-id")
    assert resp.status_code == 404


def test_get_report_not_ready():
    with patch("app.api.routes.audit.supabase_client.get_report", return_value=None):
        resp = client.get("/audit/some-id/report")
    assert resp.status_code == 404
