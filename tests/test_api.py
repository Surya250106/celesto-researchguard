"""Unit tests for FastAPI control plane and run ledger endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    """Ensure database is initialized and seeded before each test."""
    init_db()


def test_health_endpoint():
    """GET /health must return HTTP 200 and {'status': 'ok'}."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_runs_includes_seed_record():
    """GET /api/runs must return 200 and include seed record sbx-seeddemo1 with state=deleted."""
    response = client.get("/api/runs")
    assert response.status_code == 200
    runs = response.json()
    assert isinstance(runs, list)
    assert len(runs) >= 1

    seed = next((r for r in runs if r["sandbox_name"] == "sbx-seeddemo1"), None)
    assert seed is not None, "sbx-seeddemo1 must be present in run ledger"
    assert seed["state"] == "deleted"
    assert seed["execution_target"] == "celesto_sandbox"


def test_post_runs_valid_creates_record():
    """POST /api/runs with valid payload must return 201 and stored record."""
    payload = {
        "run_id": "run-test-valid-01",
        "sandbox_name": "sbx-abcdef012345",
        "problem_id": "prob-test-42",
        "state": "running",
        "execution_target": "celesto_sandbox",
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["run_id"] == "run-test-valid-01"
    assert data["sandbox_name"] == "sbx-abcdef012345"
    assert data["state"] == "running"
    assert data["execution_target"] == "celesto_sandbox"


def test_post_runs_invalid_state_fails():
    """POST /api/runs with invalid state must return HTTP 400."""
    payload = {
        "run_id": "run-test-bad-state",
        "sandbox_name": "sbx-abcdef012345",
        "problem_id": "prob-test-42",
        "state": "invalid_status",
        "execution_target": "celesto_sandbox",
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 400


def test_post_runs_invalid_name_fails():
    """POST /api/runs with invalid sandbox name must return HTTP 400."""
    payload = {
        "run_id": "run-test-bad-name",
        "sandbox_name": "invalid-name-format",  # doesn't match ^sbx-[a-z0-9]{8,}$
        "problem_id": "prob-test-42",
        "state": "created",
        "execution_target": "celesto_sandbox",
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 400


def test_post_runs_invalid_execution_target_fails():
    """POST /api/runs with non-celesto_sandbox execution target must return HTTP 400."""
    payload = {
        "run_id": "run-test-bad-target",
        "sandbox_name": "sbx-abcdef012345",
        "problem_id": "prob-test-42",
        "state": "created",
        "execution_target": "host_subprocess",  # Prohibited!
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 400


def test_get_report_serving():
    """GET /api/reports/{name} serves existing report files without requiring guest."""
    response = client.get("/api/reports/problem.json")
    assert response.status_code == 200
    data = response.json()
    assert "who_has_problem" in data

    # Nonexistent file returns 404
    missing_response = client.get("/api/reports/nonexistent_file.json")
    assert missing_response.status_code == 404
