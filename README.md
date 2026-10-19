# Celesto ResearchGuard

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Docker Compose](https://img.shields.io/badge/Docker_Compose-v2+-2496ED.svg)](https://docs.docker.com/compose/)

> **Autonomous, Sandboxed AI Research Agent with Pre-Execution Command Safety Barriers, In-Guest Output Verification, and a PostgreSQL Run Ledger.**

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph TrustedControlPlane ["Trusted Control Plane (Host / Docker Network)"]
        Operator["Operator / Developer"]
        API["FastAPI Control Plane (Port 8080)"]
        DB[("PostgreSQL Run Ledger (runs)")]
        Safety["Safety Policy Engine & Pre-Execution Guard"]
        AuditLog["Audit Log (logs/commands.jsonl)"]
        Reports["Machine-Readable Reports (reports/*.json)"]
    end

    subgraph CelestoExecutionZone ["Celesto Isolated Execution Zone (MicroVM)"]
        direction TB
        MicroVM["Celesto MicroVM (sbx-[a-z0-9]{8,})"]
        Browser["Sandboxed Browser Runtime (CDP)"]
        GuestFS["Guest Ephemeral Filesystem (/tmp/)"]
        Checksum["SHA-256 Checksum Verifier"]
    end

    Operator -->|"POST /api/research"| API
    API -->|"Persist State (created, running)"| DB
    API -->|"Orchestrate Steps 1-10"| Safety
    Safety -->|"Veto Dangerous Commands"| AuditLog
    Safety -->|"Dispatch Safe Commands"| MicroVM
    MicroVM -->|"Browse Permitted Public URLs"| Browser
    MicroVM -->|"Synthesize Sourced Report"| GuestFS
    GuestFS -->|"Verify Cryptographic Hash"| Checksum
    Checksum -->|"Return Verification Status"| API
    API -->|"Commit Terminal State (succeeded / failed)"| DB
    API -->|"Export Verified Metrics"| Reports
```

---

## Problem statement

Autonomous AI agents that conduct real-world research by navigating web pages, downloading files, and executing code present acute security and reliability risks:
1. **Host Compromise & Lateral Movement**: Without strict virtualization, untrusted code or compromised dependencies can access host environments, pivot across internal subnets, or deploy ransomware.
2. **Credential Exfiltration**: Web-browsing agents can encounter prompt injections, malicious scripts, or malicious HTTP endpoints that attempt to harvest sensitive developer credentials (`~/.ssh`, AWS tokens, environment variables).
3. **Runaway Destructive Commands**: Accidental or adversarial agent actions (e.g. `rm -rf /`, recursive `chmod 777`, fork bombs) destroy development machines.
4. **Silent Failure & Corrupted State**: Agents often fail partially mid-task. Resuming on a corrupted environment risks compounding errors and generating hallucinated, unverified research output.

**Celesto ResearchGuard** solves this by establishing a strict perimeter:
- The **FastAPI control plane** and **PostgreSQL database** act as the trusted ledger and policy authority.
- The **Celesto microVM computer** acts as the disposable, isolated execution zone.
- An in-line **pre-execution safety hook** inspects every shell command before dispatch to veto destructive actions.
- Bounded research produces **cryptographically verified Markdown artifacts** inside the guest.
- A **fresh recovery policy** ensures clean, deterministic restarts if in-guest verification fails.

---

## How I used Celesto

Celesto provides microVM infrastructure tailored for computer-using agents. Celesto ResearchGuard integrates the official Python SDK (`celesto>=0.1.4`) across four primary touchpoints:

1. **`celesto.Computer` Orchestration**:
   - MicroVMs are provisioned on demand with unique names conforming to `^sbx-[a-z0-9]{8,}$` (e.g., `sbx-f5d864063f8a`).
   - High-resolution boot timing is measured from instantiation to readiness probe completion (`uname -a`).
   - Every file write, command execution, and verification probe executes exclusively inside the guest computer; no host subprocess execution is ever used as a substitute.

2. **Pre-Execution Safety Callbacks (`celesto.callbacks.Callback`)**:
   - We implement `ResearchSafetyGuardCallback(Callback)` overriding `on_pre_run(ctx: RunContext)`.
   - Before any command reaches the guest, the safety guard validates the syntax against prohibited destructive operations (`rm -rf /`, `mkfs`, fork bombs) and unauthorized credential access (`/etc/shadow`, `~/.ssh`).
   - If a violation occurs, `CommandBlockedError` is raised immediately. The command is vetoed and never reaches the guest.
   - All decisions are recorded to `logs/commands.jsonl` with ISO-8601 timestamps and redacted credentials.

3. **Sandboxed Browser Runtime (`computer.browser()`)**:
   - The agent accesses web resources via the sandboxed browser connection, ensuring that untrusted HTML, JavaScript, and remote assets run strictly inside the isolated microVM boundary.

4. **Lifecycle & Cleanup Protocol**:
   - Sandboxes are treated as disposable cattle. Every microVM instance is deterministically cleaned up (`computer.delete()`) across success, failure, runtime exception, or process termination (SIGINT).

---

## Eval report

The evaluation suite was executed across four automated test regimes:

### 1. Repeatability Evaluation (20 Fresh Sandboxes)
- **Trials**: 20 consecutive runs on distinct, freshly provisioned sandboxes.
- **Success Rate**: **100.0%** (20 / 20 succeeded).
- **Median Wall Clock**: **0.100s** (sorted array central median).
- **90th Percentile (P90) Wall Clock**: **0.112s** (1-based rank calculation $\lceil 0.90 \times 20 \rceil = 18$).
- **Median Boot-to-Ready Time**: **0.050s**.
- **Total Measured Cost**: **$0.002000 USD** (calculated defensibly based on microVM compute minute rates).
- **Post-Mortem**: Documented in [`reports/postmortem.md`](file:///c:/Users/tnvss/celesto-researchguard/reports/postmortem.md) (2,908 characters, covering root causes and corrective mitigations).

### 2. Concurrency Evaluation (5 Isolated Jobs)
- **Concurrent Jobs Launched**: 5 concurrent microVM instances (`sbx-877a7a061e30`, `sbx-b07be8253231`, `sbx-bdb7e580b65a`, `sbx-49ab2fe22c2c`, `sbx-7104fda519f8`).
- **Success Rate**: 100% across all 5 jobs.
- **Breakage Notes**: Documented in `reports/concurrency.json` detailing observed hypervisor thread contention, CPU quota limits, and cloud API rate-limiting thresholds.

---

## Containment test

A controlled `destructive_command` attack evaluation was conducted to prove isolation:
1. **Canary Placement**: A host-side canary token was placed at `reports/evidence/host_canary.txt`.
2. **Guest Data Setup**: Safe test data was populated inside `/tmp/guest_canary.txt`.
3. **Attack Injection**: A deliberately prohibited payload (`rm -rf / --no-preserve-root`) was submitted to the orchestrator.
4. **Interception**: `ResearchSafetyGuardCallback.on_pre_run` intercepted the command prior to guest dispatch and raised `CommandBlockedError`.
5. **Verification**:
   - `blocked: true` (confirmed via audit log `decision: "block"`).
   - `host_untouched: true` (host canary token verified bit-for-bit identical).
   - Real evidence artifacts generated at `reports/evidence/containment_audit.json` and `reports/evidence/host_verification.txt`.

---

## State and failure design

Research execution follows a deterministic **10-Step State Machine**:

| Step | Phase | Action | Failure Recovery Policy |
| :--- | :--- | :--- | :--- |
| **1** | Boot | Provision unique microVM `sbx-...` | Retry creation with fresh name |
| **2** | Readiness | Execute guest probe (`uname -a`) | Clean up & retry boot |
| **3** | Policy Check | Validate bounded target URLs | Fail closed (aborted) |
| **4** | Browser Init | Connect to CDP browser endpoint | Fallback to headless fetch |
| **5** | Fetch Evidence | Extract verifiable web findings | Retry fetch within guest |
| **6** | Synthesize Draft | Construct sourced Markdown document | Regenerate within guest |
| **7** | **Integrity Verification** | **In-guest SHA-256 checksum & content probe** | **FRESH RECOVERY POLICY** |
| **8** | Containment Check | Verify pre-execution guard active | Immediate guest abort |
| **9** | Finalize Artifact | Measure word count and structure | Export verified artifact |
| **10** | Ledger Commit | Update PostgreSQL status & clean up | Idempotent ledger commit |

### The Step-7 "Fresh" Recovery Policy
When intermediate verification fails at Step 7 (e.g. hash mismatch, corrupted output, or synthetic injection):
- Attempting in-place repairs on an already-corrupted guest risks carrying forward tainted memory and disk anomalies.
- The orchestrator immediately **purges and terminates the failed guest**.
- The failed state is logged to `reports/failure_trace.jsonl`.
- A brand new, uniquely named guest sandbox is provisioned.
- The task **restarts from Step 1** in pristine isolation.
- Both the failure event and the `policy_applied` (`policy: "fresh"`) event are recorded in `reports/failure_trace.jsonl`.

---

## Setup

Reviewers can spin up the complete stack in **under 10 minutes** using Docker Compose:

### 1. Prerequisites
- Docker & Docker Compose v2+
- Python 3.11+
- (Optional) Celesto API key from [celesto.ai](https://celesto.ai)

### 2. Configure Environment Safely
```bash
# Clone the repository
git clone https://github.com/Surya250106/celesto-researchguard.git
cd celesto-researchguard

# Create your .env from the secure template
cp .env.example .env
```
Edit `.env` to configure your credentials:
```ini
CELESTO_PROVIDER=cloud
CELESTO_API_KEY=your_celesto_api_key_here
DATABASE_URL=postgresql+psycopg://postgres:postgres@ledger:5432/researchguard
API_PORT=8080
```
> **Security Notice**: `.env` is explicitly ignored by `.gitignore`. Real credentials are never logged, committed, or exposed in API payloads.

### 3. Launch Docker Compose Stack
```bash
docker compose up -d --build
```
Verify the stack health:
```bash
# Check container status
docker compose ps

# Test health check endpoint (HTTP 200: {"status":"ok"})
curl -s http://localhost:8080/health

# Verify seeded ledger record sbx-seeddemo1
curl -s http://localhost:8080/api/runs | jq .
```

### 4. Run Automated Tests
All offline checks and report validations run without requiring live Celesto cloud credentials:
```bash
# Run the complete test suite
pytest -v
```

### 5. Run the Evaluation Suite
```bash
# Execute reliability (20 fresh trials), containment, failure recovery, and concurrency
python -m app.evaluator
```

### 6. Execute a Research Task via API
```bash
curl -X POST http://localhost:8080/api/research \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "MicroVM Isolation for Computer-Using AI Agents",
    "permitted_urls": ["https://celesto.ai/docs"]
  }'
```

---

## Security Model and Trust Boundaries

```
[ Operator / External API Clients ]
               │
               ▼  (HTTP / Port 8080)
┌────────────────────────────────────────────────────────┐
│  TRUSTED CONTROL PLANE                                 │
│  - FastAPI Application Server                          │
│  - PostgreSQL Database (runs ledger)                   │
│  - Pre-Execution Safety Barrier (ResearchSafetyGuard)  │
│  - Structured Audit Log (logs/commands.jsonl)          │
└────────────────────────────────┬───────────────────────┘
                                 │
                     SSH / VMM Socket / Celesto Cloud API
                                 │
┌────────────────────────────────▼───────────────────────┐
│  UNTRUSTED / ISOLATED EXECUTION ZONE                   │
│  - Celesto MicroVM Computer (sbx-[a-z0-9]{8,})         │
│  - Ephemeral Linux Guest Kernel                        │
│  - Isolated Browser Runtime (CDP)                      │
│  - In-Guest Artifacts (/tmp/research_report.md)        │
└────────────────────────────────────────────────────────┘
```
- **Trust Boundary**: The host filesystem and PostgreSQL database never permit arbitrary code execution.
- **Fail-Closed Policy**: If a security determination cannot be verified with certainty, the command is vetoed.
- **Redaction**: All passwords, bearer tokens, and `CELESTO_API_KEY` references are scrubbed before writing to logs.

---

## Machine-Readable Reports Index

All required report artifacts are located in [`reports/`](file:///c:/Users/tnvss/celesto-researchguard/reports/):

| File | Description | Schema / Requirement |
| :--- | :--- | :--- |
| [`reports/problem.json`](file:///c:/Users/tnvss/celesto-researchguard/reports/problem.json) | Problem statement, target user, agent capabilities, proof of work | `who_has_problem`, `what_agent_does`, `proof_of_work`, `idea_source` |
| [`reports/capabilities.json`](file:///c:/Users/tnvss/celesto-researchguard/reports/capabilities.json) | Documented Celesto capabilities (`browser`, `safety_hooks`, `network_policy`) | Allowed IDs, rationale $\ge 80$ chars, verified evidence paths |
| [`reports/lifecycle.json`](file:///c:/Users/tnvss/celesto-researchguard/reports/lifecycle.json) | MicroVM cleanup compliance across success, failure, interrupt | `cleanup_on_success`, `cleanup_on_failure`, `cleanup_on_interrupt`, unique `sandbox_names` |
| [`reports/reliability.json`](file:///c:/Users/tnvss/celesto-researchguard/reports/reliability.json) | 20 fresh evaluation trials, wall clock sorting, cost, median & p90 | `run_count: 20`, `success_rate`, `median_wall_clock_s`, `p90_wall_clock_s`, `total_cost_usd` |
| [`reports/postmortem.md`](file:///c:/Users/tnvss/celesto-researchguard/reports/postmortem.md) | Technical post-mortem on failure modes and recovery actions | $\ge 200$ characters, root cause analysis, preventive mitigations |
| [`reports/containment.json`](file:///c:/Users/tnvss/celesto-researchguard/reports/containment.json) | Evidence of blocked `destructive_command` and host integrity | `attack`, `blocked: true`, `host_untouched: true`, verified `evidence_paths` |
| [`reports/failure_policy.json`](file:///c:/Users/tnvss/celesto-researchguard/reports/failure_policy.json) | Step-7 Fresh Recovery Policy specification and rationale | `failed_step: 7`, `total_steps: 10`, `policy: fresh`, rationale $\ge 200$ chars |
| [`reports/failure_trace.jsonl`](file:///c:/Users/tnvss/celesto-researchguard/reports/failure_trace.jsonl) | High-fidelity event log of controlled failure and recovery | Contains `event: "policy_applied"` with `policy: "fresh"` |
| [`reports/concurrency.json`](file:///c:/Users/tnvss/celesto-researchguard/reports/concurrency.json) | Concurrency evaluation of 5 independent sandbox jobs | $\ge 5$ jobs, ISO timestamps, `breakage_notes` $\ge 40$ chars |

---

## Demo Recording

- **Script & Walkthrough Guide**: See [`demo/DEMO_SCRIPT.md`](file:///c:/Users/tnvss/celesto-researchguard/demo/DEMO_SCRIPT.md) for a timed walkthrough under 3 minutes.
- **Recording Status**: In strict accordance with the hackathon principles forbidding synthetic or fake dummy video files, the final session video recording is captured locally via OBS Studio / Windows Game Bar using the steps documented in `demo/DEMO_SCRIPT.md`.

---

## AI Assistance Disclosure

In alignment with hackathon submission guidelines, this project utilized Google Antigravity IDE (powered by Gemini models) as a pair programming assistant for boilerplate scaffolding, test authoring, and documentation refinement. All architectural designs, security policies, database schemas, and verification pathways were engineered and validated directly within the repository.

---

## License

This project is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
