"""Unit tests for Step-7 Failure Injection and Fresh Sandbox Recovery Policy."""

import json
from pathlib import Path
import pytest

from app.agent import FAILURE_TRACE_PATH, ResearchAgent
from app.database import SessionLocal, init_db


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


def test_step7_failure_recovery_creates_fresh_guest():
    """Verify injected Step 7 failure triggers fresh policy, deletes tainted guest, and restarts."""
    db = SessionLocal()
    agent = ResearchAgent(
        topic="Recovery Policy Verification",
        db_session=db,
        simulate_offline=True,
        inject_step7_failure=True,
    )
    original_sandbox_name = agent.sandbox_name

    result = agent.execute_with_recovery()
    db.close()

    assert result["state"] == "succeeded"
    # Result sandbox should be the newly provisioned fresh sandbox
    assert result["sandbox_name"] != original_sandbox_name
    assert result["sandbox_name"].startswith("sbx-")

    # Inspect failure trace
    assert FAILURE_TRACE_PATH.exists()
    lines = [json.loads(l) for l in FAILURE_TRACE_PATH.read_text(encoding="utf-8").strip().splitlines() if l.strip()]

    # Find the policy_applied event for the original sandbox
    policy_events = [
        e for e in lines
        if e.get("sandbox_name") == original_sandbox_name and e.get("event") == "policy_applied"
    ]
    assert len(policy_events) >= 1
    assert policy_events[0]["policy"] == "fresh"
    assert policy_events[0]["step"] == 7
