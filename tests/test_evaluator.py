"""Unit tests for Evaluator execution modes, live prerequisite enforcement, and offline verification."""

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

from app.evaluator import (
    calculate_median,
    calculate_p90,
    run_containment_evaluation,
    run_concurrency_evaluation,
    run_reliability_evaluation,
    run_step7_failure_evaluation,
    validate_live_prerequisites,
)
from app.sandbox import CelestoCredentialsMissingError


def test_calculate_median_and_p90():
    """Verify median and p90 calculations conform to exact specification."""
    # Odd count
    vals_odd = [0.1, 0.2, 0.3]
    assert calculate_median(vals_odd) == 0.2

    # Even count (average of two central)
    vals_even = [0.1, 0.2, 0.3, 0.4]
    assert calculate_median(vals_even) == 0.25

    # P90 using ceil(0.90 * n)
    # n=10, 0.90 * 10 = 9 (1-based index 9, 0-based index 8)
    vals_10 = [float(i) for i in range(1, 11)]
    assert calculate_p90(vals_10) == 9.0


def test_validate_live_prerequisites_missing_api_key():
    """Verify validate_live_prerequisites fails clearly when CELESTO_API_KEY is missing."""
    old_key = os.environ.pop("CELESTO_API_KEY", None)
    try:
        with pytest.raises(CelestoCredentialsMissingError) as exc_info:
            validate_live_prerequisites(provider="cloud")
        assert "CELESTO_API_KEY is missing or invalid" in str(exc_info.value)
    finally:
        if old_key is not None:
            os.environ["CELESTO_API_KEY"] = old_key


def test_validate_live_prerequisites_placeholder_api_key():
    """Verify validate_live_prerequisites fails clearly when CELESTO_API_KEY is placeholder."""
    old_key = os.environ.get("CELESTO_API_KEY")
    os.environ["CELESTO_API_KEY"] = "your_celesto_api_key_here"
    try:
        with pytest.raises(CelestoCredentialsMissingError) as exc_info:
            validate_live_prerequisites(provider="cloud")
        assert "CELESTO_API_KEY is missing or invalid" in str(exc_info.value)
    finally:
        if old_key is not None:
            os.environ["CELESTO_API_KEY"] = old_key
        else:
            os.environ.pop("CELESTO_API_KEY", None)


def test_validate_live_prerequisites_invalid_provider():
    """Verify validate_live_prerequisites rejects unsupported providers."""
    with pytest.raises(ValueError) as exc_info:
        validate_live_prerequisites(provider="unsupported_provider")
    assert "Unknown Celesto provider" in str(exc_info.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific local provider check")
def test_validate_live_prerequisites_local_provider_on_windows():
    """Verify local provider fails clearly on Windows."""
    with pytest.raises(RuntimeError) as exc_info:
        validate_live_prerequisites(provider="local")
    assert "not supported directly on Windows hosts" in str(exc_info.value)


def test_live_evaluation_functions_fail_without_credentials():
    """Verify all evaluation suites fail clearly before running if live mode is requested without credentials."""
    old_key = os.environ.pop("CELESTO_API_KEY", None)
    try:
        with pytest.raises(CelestoCredentialsMissingError):
            run_reliability_evaluation(trial_count=1, simulate_offline=False)

        with pytest.raises(CelestoCredentialsMissingError):
            run_containment_evaluation(simulate_offline=False)

        with pytest.raises(CelestoCredentialsMissingError):
            run_concurrency_evaluation(job_count=1, simulate_offline=False)

        with pytest.raises(CelestoCredentialsMissingError):
            run_step7_failure_evaluation(simulate_offline=False)
    finally:
        if old_key is not None:
            os.environ["CELESTO_API_KEY"] = old_key


def test_evaluator_cli_requires_explicit_mode():
    """Verify running python -m app.evaluator without arguments exits with code 1 and error."""
    res = subprocess.run(
        [sys.executable, "-m", "app.evaluator"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "Execution mode must be explicitly specified" in res.stderr


def test_evaluator_cli_live_fails_without_credentials():
    """Verify running python -m app.evaluator --live without credentials exits with fatal error (code 2)."""
    env = os.environ.copy()
    env.pop("CELESTO_API_KEY", None)
    res = subprocess.run(
        [sys.executable, "-m", "app.evaluator", "--live"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 2
    assert "Live execution check failed" in res.stderr
    assert "CELESTO_API_KEY is missing or invalid" in res.stderr


def test_offline_containment_evaluation(tmp_path):
    """Verify offline containment evaluation marks live_execution=False and host canary untouched."""
    res = run_containment_evaluation(simulate_offline=True, reports_dir=tmp_path)
    assert res["attack"] == "destructive_command"
    assert res["blocked"] is True
    assert res["host_untouched"] is True
    assert res["live_execution"] is False
    assert res["execution_mode"] == "offline_simulation"
    assert "not performed live" in res["containment_scope"]


def test_offline_concurrency_runs_concurrently(tmp_path):
    """Verify offline concurrency runs multiple jobs concurrently and records outcomes."""
    res = run_concurrency_evaluation(job_count=2, simulate_offline=True, reports_dir=tmp_path)
    assert len(res["jobs"]) == 2
    assert res["concurrency_execution"] == "concurrent_threads"
    assert res["live_execution"] is False
    assert res["execution_mode"] == "offline_simulation"
    for job in res["jobs"]:
        assert job["sandbox_name"].startswith("sbx-")
        assert job["state"] == "succeeded"


def test_offline_step7_recovery(tmp_path):
    """Verify offline step-7 recovery provisions fresh sandbox and verifies recovery."""
    res = run_step7_failure_evaluation(simulate_offline=True, reports_dir=tmp_path)
    assert res["failed_step"] == 7
    assert res["policy"] == "fresh"
    assert res["fresh_recovery_verified"] is True
    assert res["initial_sandbox_name"] != res["recovered_sandbox_name"]
    assert res["live_execution"] is False
    assert res["execution_mode"] == "offline_simulation"


def test_offline_reliability_evaluation(tmp_path):
    """Verify offline reliability marks cost unavailable and measures timings."""
    res = run_reliability_evaluation(trial_count=2, simulate_offline=True, reports_dir=tmp_path)
    assert res["run_count"] == 2
    assert res["cost_status"] == "unavailable"
    assert res["total_cost_usd"] is None
    assert res["live_execution"] is False
    assert res["execution_mode"] == "offline_simulation"
    for r in res["runs"]:
        assert r["cost_usd"] is None
        assert r["fresh"] is True
        assert r["wall_clock_s"] >= 0.0
