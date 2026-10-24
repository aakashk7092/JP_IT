"""Unit tests for api_server.py verifying REST API endpoints and safety guards."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api_server import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "Recruitment" in data["system"]


def test_status_endpoint(client: TestClient):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "credentials" in data
    assert "stats" in data
    assert "registered_candidates" in data["stats"]
    assert data["stats"]["registered_candidates"] >= 1


def test_candidates_endpoint(client: TestClient):
    resp = client.get("/api/candidates")
    assert resp.status_code == 200
    candidates = resp.json()
    assert isinstance(candidates, list)
    assert len(candidates) >= 1
    assert candidates[0]["id"] == "alex_johnson_dummy"
    assert "skills" in candidates[0]


def test_recruiters_endpoint_and_pagination(client: TestClient):
    resp = client.get("/api/recruiters?page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "recruiters" in data
    assert isinstance(data["recruiters"], list)


def test_history_endpoint(client: TestClient):
    resp = client.get("/api/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "history" in data


def test_suppression_list_crud(client: TestClient):
    # Add
    test_email = "test_opt_out@agency.com"
    resp = client.post("/api/suppression/add", json={"email": test_email, "reason": "Test opt-out"})
    assert resp.status_code == 200

    # Verify present
    resp_list = client.get("/api/suppression")
    assert any(s.get("recruiter_email") == test_email for s in resp_list.json())

    # Remove
    resp_del = client.delete(f"/api/suppression/remove?email={test_email}")
    assert resp_del.status_code == 200

    # Verify removed
    resp_list_after = client.get("/api/suppression")
    assert not any(s.get("recruiter_email") == test_email for s in resp_list_after.json())


def test_live_send_rejected_without_send_token(client: TestClient, monkeypatch):
    # Simulate LIVE OUTREACH mode
    monkeypatch.setenv("TEST_MODE", "false")

    resp = client.post("/api/outreach/send", json={
        "candidate_id": "alex_johnson_dummy",
        "confirm_token": "WRONG_TOKEN",
    })
    # Must be rejected by safety gate
    assert resp.status_code == 403
    assert "LIVE MODE PROTECTION" in resp.json()["detail"]


def test_test_mode_toggle(client: TestClient):
    resp = client.post("/api/settings/test-mode", json={"test_mode": True})
    assert resp.status_code == 200
    assert resp.json()["test_mode"] is True


def test_analytics_metrics_endpoint(client: TestClient):
    resp = client.get("/api/analytics/metrics")
    assert resp.status_code == 200
    metrics = resp.json()
    assert "total_recruiters" in metrics
    assert "reply_rate_pct" in metrics
    assert "sent_outreach" in metrics


def test_diff_reports_endpoint(client: TestClient):
    resp = client.get("/api/customizer/diffs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_settings_endpoint(client: TestClient):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    settings = resp.json()
    assert "gemini_model" in settings
    assert "groq_model" in settings
    assert "test_mode" in settings


def test_favicon_endpoint(client: TestClient):
    resp = client.get("/favicon.ico")
    assert resp.status_code in (200, 204)


def test_demo_session_endpoint(client: TestClient):
    resp = client.post("/api/linkedin/demo-session")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["session_active"] is True
    assert data["loaded_leads"] >= 1

