"""Automated unit test suite for HTTP 501, HTTP 429, interrupted evaluations, and cleanup failures."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from celesto.exceptions import CelestoError
from app.agent import ResearchAgent
from app.evaluator import run_concurrency_evaluation, run_reliability_evaluation
from app.sandbox import CelestoCleanupError, SandboxManager


def test_browser_http_501_transparently_handled():
    """Verify that HTTP 501 from cloud browser endpoint is transparently reported without crashing or fabricating browser connection."""
    manager = SandboxManager(sandbox_name="sbx-test501error", simulate_offline=False)
    manager._is_ready = True

    # Mock computer handle whose .browser() raises HTTP 501
    mock_computer = MagicMock()
    mock_computer.browser.side_effect = CelestoError("Cloud API returned HTTP 501: Not Implemented")
    manager.computer = mock_computer

    conn = manager.get_browser_connection()
    assert conn is None
    assert manager.browser_error is not None
    assert "501" in manager.browser_error
    assert "Not Implemented" in manager.browser_error


def test_agent_completes_via_guest_commands_when_browser_returns_501():
    """Verify ResearchAgent completes research evidence collection via guest commands when browser returns 501."""
    agent = ResearchAgent(
        topic="HTTP 501 Fallback Test",
        simulate_offline=True,
    )
    # Simulate browser connection returning None due to 501
    with patch.object(SandboxManager, "get_browser_connection", return_value=None):
        res = agent.execute_10_steps()
        assert res["state"] == "succeeded"
        assert res["findings_count"] == 2
        assert res["artifact_checksum"] is not None


def test_concurrency_http_429_recorded_without_retries(tmp_path):
    """Verify HTTP 429 rate limit errors are accurately recorded as failed jobs without spawning retry loops."""
    # Patch ResearchAgent.execute_10_steps to simulate HTTP 429 on one job
    original_execute = ResearchAgent.execute_10_steps

    def mock_execute(self):
        if "Job 2" in self.topic:
            raise CelestoError("Cloud API returned HTTP 429. Check the request and cloud dashboard before retrying.")
        return original_execute(self)

    with patch.object(ResearchAgent, "execute_10_steps", mock_execute):
        res = run_concurrency_evaluation(job_count=2, simulate_offline=True, reports_dir=tmp_path)

        assert len(res["jobs"]) == 2
        job1 = res["jobs"][0]
        job2 = res["jobs"][1]

        assert job1["state"] == "succeeded"
        assert job2["state"] == "failed"
        assert "HTTP 429" in job2["error"]


def test_reliability_interrupted_evaluation_preserves_partial_report(tmp_path):
    """Verify KeyboardInterrupt (Ctrl+C) during reliability evaluation preserves partial results without fabricating remaining trials."""
    trial_counter = 0
    original_execute = ResearchAgent.execute_10_steps

    def mock_execute_interrupt(self):
        nonlocal trial_counter
        trial_counter += 1
        if trial_counter > 2:
            raise KeyboardInterrupt("Simulated Ctrl+C interrupt")
        return original_execute(self)

    with patch.object(ResearchAgent, "execute_10_steps", mock_execute_interrupt):
        res = run_reliability_evaluation(trial_count=5, simulate_offline=True, reports_dir=tmp_path)

        # Must report partial and interrupted flags
        assert res["interrupted"] is True
        assert res["partial"] is True
        assert res["run_count"] == 2
        assert res["planned_runs"] == 5
        assert len(res["runs"]) == 2

        # Verify saved report files on disk
        rel_path = tmp_path / "reliability.json"
        assert rel_path.exists()
        saved_rel = json.loads(rel_path.read_text(encoding="utf-8"))
        assert saved_rel["interrupted"] is True
        assert saved_rel["run_count"] == 2
        assert "interrupted by user" in saved_rel["interrupt_notes"]

        life_path = tmp_path / "lifecycle.json"
        assert life_path.exists()
        saved_life = json.loads(life_path.read_text(encoding="utf-8"))
        assert saved_life["interrupted"] is True
        assert saved_life["cleanup_on_interrupt"] is True


def test_cleanup_failure_recorded_in_lifecycle(tmp_path):
    """Verify cleanup errors mark _cleanup_succeeded=False and are tracked in lifecycle reporting."""
    manager = SandboxManager(sandbox_name="sbx-testcleanupfail", simulate_offline=False)
    manager._is_ready = True
    mock_comp = MagicMock()
    mock_comp.delete.side_effect = RuntimeError("Simulated API transport error during delete")
    manager.computer = mock_comp

    with pytest.raises(CelestoCleanupError) as exc_info:
        manager.cleanup()

    assert manager._cleanup_succeeded is False
    assert "Cleanup failed for sandbox" in str(exc_info.value)
