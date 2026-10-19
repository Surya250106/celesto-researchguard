# Celesto ResearchGuard: 3-Minute Demo Walkthrough Script

**Target Duration:** 2 minutes 45 seconds (<= 180 seconds maximum)  
**Presenter:** Founder / Lead Systems Engineer  
**Goal:** Demonstrate the trusted control plane, pre-execution safety callbacks, sandboxed research execution, containment barriers, step-7 failure recovery, and run ledger persistence.

---

## Timeline & Scene-by-Scene Breakdown

### Scene 1: Problem Statement & Architecture Overview (0:00 - 0:30)
- **Visual:** Terminal showing `docker-compose.yml` and repository root; browser showing Mermaid architecture diagram.
- **Narration:**
  > "Autonomous AI agents need to browse documentation and execute code to conduct research. However, giving an untrusted agent arbitrary shell access or browser access on host infrastructure invites credential theft, drive-by malware, and runaway destructive operations.
  > Celesto ResearchGuard solves this by decoupling the trusted control plane (FastAPI and PostgreSQL run ledger) from the execution zone. Every shell command, browser action, and file operation executes exclusively inside disposable Celesto microVM computers with a pre-execution safety callback that vetoes dangerous commands before they ever reach the guest."

### Scene 2: Control Plane & Health Check (0:30 - 0:50)
- **Command:**
  ```bash
  curl -s http://localhost:8080/health
  curl -s http://localhost:8080/api/runs | jq .
  ```
- **Visual:** Terminal showing `{"status":"ok"}` and the initial seeded ledger record `sbx-seeddemo1` in state `deleted` with `execution_target: "celesto_sandbox"`.
- **Narration:**
  > "The trusted API and PostgreSQL ledger run independently. As required by the hackathon specification, the ledger initializes idempotently with `sbx-seeddemo1`. The stack remains completely healthy and serves existing reports even when cloud credentials are not active."

### Scene 3: Pre-Execution Safety Barrier & Containment Test (0:50 - 1:25)
- **Command:**
  ```bash
  python -m pytest tests/test_safety.py -v
  cat reports/containment.json
  cat reports/evidence/containment_audit.json
  ```
- **Visual:** Terminal showing `ResearchSafetyGuardCallback` intercepting `rm -rf /` and credential exfiltration attempts; audit log recording `decision: "block"`.
- **Narration:**
  > "Rather than relying on probabilistic LLM system prompts, ResearchGuard implements a deterministic Celesto `Callback.on_pre_run` hook. When an agent attempts `rm -rf /` or credential theft via `/etc/shadow`, the safety guard vetoes the command before guest dispatch. Our containment evaluation confirms `blocked: true` and `host_untouched: true` with host canary files remaining completely untouched."

### Scene 4: 10-Step Research Workflow & In-Guest Artifact Verification (1:25 - 2:05)
- **Command:**
  ```bash
  curl -X POST http://localhost:8080/api/research \
    -H "Content-Type: application/json" \
    -d '{"topic": "Celesto MicroVM Architecture", "permitted_urls": ["https://celesto.ai/docs"]}'
  ```
- **Visual:** Real-time log showing Steps 1 through 10: booting `sbx-...`, readiness probe in ~0.05s, bounded URL validation, browser context initialization, and SHA-256 verification of the Markdown report inside the guest.
- **Narration:**
  > "When a research task begins, the orchestrator provisions a uniquely named microVM `sbx-xxxxxxxxxxxx`. It performs bounded research across allowlisted domains, synthesizes a sourced Markdown document inside the guest, computes a cryptographic checksum probe, and logs every execution step to `logs/commands.jsonl`."

### Scene 5: Step-7 Failure Recovery & Fresh Sandbox Policy (2:05 - 2:30)
- **Command:**
  ```bash
  python -m pytest tests/test_recovery.py -v
  cat reports/failure_policy.json
  tail -n 3 reports/failure_trace.jsonl
  ```
- **Visual:** Terminal showing controlled failure injected at Step 7, triggering the `fresh` recovery policy, deleting the tainted guest, spawning a pristine replacement microVM, and restarting from Step 1.
- **Narration:**
  > "If verification fails at Step 7, attempting in-place repairs risks compounding silent corruption. Our state machine enforces a 'fresh' recovery policy: the compromised guest is immediately purged, a pristine sandbox is booted from base templates, and execution restarts cleanly from Step 1. Both events are cryptographically recorded in `reports/failure_trace.jsonl`."

### Scene 6: Concurrency, Reliability Results & Conclusion (2:30 - 2:45)
- **Command:**
  ```bash
  cat reports/reliability.json | jq '{run_count, success_rate, median_wall_clock_s, p90_wall_clock_s, total_cost_usd}'
  ```
- **Visual:** Summary of 20 fresh evaluation trials (100% success rate, median 0.10s, total cost $0.002) and 5 concurrent isolated jobs.
- **Narration:**
  > "In summary, Celesto ResearchGuard delivers a complete, containment-tested, audit-logged research agent framework backed by Celesto microVMs and a hardened PostgreSQL ledger. Ready for production deployment."

---

## Instructions for Screen Recording on Windows

1. **Prerequisites:**
   - Install OBS Studio (`winget install OBSProject.OBSStudio`) or use Windows Game Bar (`Win + Alt + R`).
2. **Setup:**
   - Open VS Code / Terminal on the left half of the display.
   - Open the Celesto Web Dashboard or Browser viewer on the right half.
3. **Execution:**
   - Follow the script prompts above, executing the commands in order.
   - Verify total recording time is under 180 seconds.
4. **Saving:**
   - Save the finalized video file to `demo/walkthrough.mp4`.
   *(Note: As specified in hackathon guidelines, do not commit empty or synthetic dummy video files. If live recording is pending local screen capture, the repository documentation marks the walkthrough as ready for capture).*
