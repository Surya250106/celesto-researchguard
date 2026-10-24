"""Automated test suite validating all 9 hackathon machine-readable reports and logs."""

import json
import math
import os
import re
from pathlib import Path
import pytest

REPORTS_DIR = Path("reports")
LOGS_DIR = Path("logs")
README_PATH = Path("README.md")
SANDBOX_NAME_RE = re.compile(r"^sbx-[a-z0-9]{8,}$")

REQUIRED_README_PHRASES = [
    "Problem statement",
    "How I used Celesto",
    "Eval report",
    "Containment test",
    "State and failure design",
    "Setup",
]


def test_problem_report_exists_and_valid():
    """Verify reports/problem.json schema and required fields."""
    path = REPORTS_DIR / "problem.json"
    assert path.exists(), "reports/problem.json must exist"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert "who_has_problem" in data and len(data["who_has_problem"]) > 20
    assert "what_agent_does" in data and len(data["what_agent_does"]) > 20
    assert "proof_of_work" in data and len(data["proof_of_work"]) > 20
    assert data.get("idea_source") in ["idea_bank", "original"]


def test_capabilities_report_ids_and_evidence():
    """Verify capabilities have allowed IDs, rationale >= 80 chars, and evidence paths exist."""
    path = REPORTS_DIR / "capabilities.json"
    assert path.exists(), "reports/capabilities.json must exist"
    data = json.loads(path.read_text(encoding="utf-8"))

    capabilities = data.get("capabilities", data if isinstance(data, list) else [])
    assert len(capabilities) >= 2, "Must specify at least two supported capabilities"

    allowed_ids = {
        "persistence",
        "snapshots",
        "celestofs",
        "browser",
        "published_ports",
        "network_policy",
        "safety_hooks",
        "host_mounts",
        "coding_agent_preset",
        "agentor_durable",
    }

    seen_ids = set()
    for cap in capabilities:
        cap_id = cap.get("id") or cap.get("capability_id")
        assert cap_id in allowed_ids, f"Capability ID '{cap_id}' must be in allowed list"
        assert cap_id not in seen_ids, f"Duplicate capability ID '{cap_id}' found"
        seen_ids.add(cap_id)

        rationale = cap.get("rationale", "")
        assert len(rationale) >= 80, f"Capability '{cap_id}' rationale must be at least 80 chars; got {len(rationale)}"

        evidence_path = Path(cap.get("evidence_path", ""))
        assert evidence_path.exists(), f"Evidence path '{evidence_path}' does not exist for capability '{cap_id}'"


def test_lifecycle_report_flags_and_names():
    """Verify lifecycle cleanup flags and unique valid sandbox names."""
    path = REPORTS_DIR / "lifecycle.json"
    assert path.exists(), "reports/lifecycle.json must exist"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data.get("cleanup_on_success") is True
    assert data.get("cleanup_on_failure") is True
    assert data.get("cleanup_on_interrupt") is True

    names = data.get("sandbox_names", [])
    assert len(names) > 0, "Lifecycle sandbox_names must not be empty"
    assert len(names) == len(set(names)), "sandbox_names must be unique"
    for name in names:
        assert SANDBOX_NAME_RE.match(name), f"Sandbox name '{name}' does not match required regex"


def test_reliability_report_arithmetic_and_ordering():
    """Verify reliability report arithmetic, ordering by wall_clock_s, and postmortem reference."""
    path = REPORTS_DIR / "reliability.json"
    assert path.exists(), "reports/reliability.json must exist"
    data = json.loads(path.read_text(encoding="utf-8"))

    runs = data.get("runs", [])
    if data.get("partial"):
        assert len(runs) == data.get("run_count")
        assert len(runs) > 0, "Partial report must contain at least one completed run"
        assert data.get("planned_runs", 20) >= 20
        assert data.get("interrupted") is True
    else:
        assert len(runs) >= 20, f"Reliability evaluation must have at least 20 runs, found {len(runs)}"
        assert data.get("run_count") == len(runs)

    # Verify sorted ascending by wall_clock_s
    wall_clocks = [r["wall_clock_s"] for r in runs]
    assert wall_clocks == sorted(wall_clocks), "Runs must be sorted by wall_clock_s ascending"

    # Verify every run is marked fresh
    for r in runs:
        assert r.get("fresh") is True, f"Run {r.get('sandbox_name')} must be marked fresh"
        assert SANDBOX_NAME_RE.match(r.get("sandbox_name", ""))

    # Verify median calculation (even n is average of two central)
    n = len(wall_clocks)
    mid = n // 2
    expected_median_wall = (
        wall_clocks[mid] if n % 2 == 1 else (wall_clocks[mid - 1] + wall_clocks[mid]) / 2.0
    )
    assert abs(data.get("median_wall_clock_s") - expected_median_wall) < 1e-3

    # Verify p90 calculation (1-based rank ceil(0.90 * n))
    rank_p90 = math.ceil(0.90 * n)
    expected_p90_wall = wall_clocks[rank_p90 - 1]
    assert abs(data.get("p90_wall_clock_s") - expected_p90_wall) < 1e-3

    # Verify total cost calculation: when costs are available, sum must match; when unavailable, must be None
    costs = [r.get("cost_usd") for r in runs if r.get("cost_usd") is not None]
    if costs:
        total_cost = sum(costs)
        assert abs(data.get("total_cost_usd") - total_cost) < 1e-4
    else:
        assert data.get("total_cost_usd") is None or data.get("total_cost_usd") == 0.0

    # Verify postmortem reference
    assert data.get("postmortem_path") == "reports/postmortem.md"
    postmortem_file = Path(data.get("postmortem_path"))
    assert postmortem_file.exists(), "postmortem_path file must exist"
    content = postmortem_file.read_text(encoding="utf-8")
    assert len(content) >= 200, f"Postmortem must be at least 200 characters, got {len(content)}"


def test_containment_report_and_evidence():
    """Verify containment report properties and evidence files existence."""
    path = REPORTS_DIR / "containment.json"
    assert path.exists(), "reports/containment.json must exist"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data.get("attack") == "destructive_command"
    assert data.get("blocked") is True
    assert data.get("host_untouched") is True

    evidence_paths = data.get("evidence_paths", [])
    assert len(evidence_paths) >= 2, "Must contain at least 2 evidence paths"
    for ep in evidence_paths:
        p = Path(ep)
        assert p.exists(), f"Containment evidence file '{ep}' does not exist"
        assert p.stat().st_size > 0, f"Evidence file '{ep}' cannot be empty"


def test_failure_policy_and_trace():
    """Verify failure policy config and trace events for step 7 fresh recovery."""
    policy_path = REPORTS_DIR / "failure_policy.json"
    trace_path = REPORTS_DIR / "failure_trace.jsonl"
    assert policy_path.exists(), "failure_policy.json must exist"
    assert trace_path.exists(), "failure_trace.jsonl must exist"

    data = json.loads(policy_path.read_text(encoding="utf-8"))
    assert data.get("failed_step") == 7
    assert data.get("total_steps") == 10
    assert data.get("policy") == "fresh"
    assert len(data.get("rationale", "")) >= 200, "Rationale must be >= 200 chars"
    assert data.get("trace_path") == "reports/failure_trace.jsonl"

    # Verify trace lines
    trace_lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").strip().splitlines() if line.strip()]
    assert len(trace_lines) > 0, "failure_trace.jsonl must contain events"

    # Must contain object with event="policy_applied" and policy="fresh"
    policy_applied_events = [e for e in trace_lines if e.get("event") == "policy_applied" and e.get("policy") == "fresh"]
    assert len(policy_applied_events) >= 1, "Must contain event=policy_applied with policy=fresh in trace"


def test_concurrency_report_jobs_and_notes():
    """Verify concurrency report contains 5+ jobs, valid timestamps, and breakage_notes >= 40 chars."""
    path = REPORTS_DIR / "concurrency.json"
    assert path.exists(), "reports/concurrency.json must exist"
    data = json.loads(path.read_text(encoding="utf-8"))

    jobs = data.get("jobs", [])
    assert len(jobs) >= 5, f"Must record 5 or more concurrency jobs, found {len(jobs)}"

    seen_names = set()
    for job in jobs:
        sbx_name = job.get("sandbox_name", "")
        assert SANDBOX_NAME_RE.match(sbx_name), f"Sandbox name '{sbx_name}' must match regex"
        assert sbx_name not in seen_names, f"Duplicate sandbox name '{sbx_name}' in concurrency jobs"
        seen_names.add(sbx_name)
        assert "started_at" in job and len(job["started_at"]) >= 10

    notes = data.get("breakage_notes", "")
    assert len(notes) >= 40, f"Breakage notes must be >= 40 chars; got {len(notes)}"


def test_commands_log_schema():
    """Verify logs/commands.jsonl exists, every line has ts, valid sandbox_name, command, decision, and target."""
    log_path = LOGS_DIR / "commands.jsonl"
    assert log_path.exists(), "logs/commands.jsonl must exist"

    lines = [json.loads(l) for l in log_path.read_text(encoding="utf-8").strip().splitlines() if l.strip()]
    assert len(lines) > 0, "logs/commands.jsonl must not be empty"

    for entry in lines:
        assert "ts" in entry and len(entry["ts"]) >= 10
        assert SANDBOX_NAME_RE.match(entry.get("sandbox_name", "")), f"Invalid sandbox_name in log: {entry.get('sandbox_name')}"
        assert entry.get("command") and len(entry["command"].strip()) > 0
        assert entry.get("decision") in ["allow", "block"]
        assert entry.get("execution_target") == "celesto_sandbox"


def test_readme_required_phrases():
    """Verify README.md exists and contains every required phrase as a heading or label."""
    assert README_PATH.exists(), "README.md must exist in root"
    content = README_PATH.read_text(encoding="utf-8")
    for phrase in REQUIRED_README_PHRASES:
        assert phrase in content, f"README.md must contain required phrase: '{phrase}'"
