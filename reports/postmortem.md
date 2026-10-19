# Post-Mortem: Step-7 Integrity Verification & Host Linker Anomaly

**Document Path:** `reports/postmortem.md`  
**Incident Classification:** Controlled Execution Integrity Fault & Toolchain Linker Discrepancy  
**Author:** Celesto ResearchGuard Engineering Team  
**Status:** Resolved / Policy Implemented  

---

## 1. Executive Summary and Incident Overview
During initial reliability evaluations and guest microVM orchestrations, two distinct anomalies were investigated:
1. **Host-Side Build Anomaly**: When installing the `celesto-core` dependency on modern Windows development hosts with pre-release Python toolchains, `maturin` attempted native C/Rust compilation requiring `link.exe`, which failed due to missing Visual C++ build tools.
2. **Guest Verification Failure (Step 7)**: During controlled adversarial testing of research report generation inside disposable Celesto sandboxes, synthetic corruption was injected at Step 7 of the 10-step pipeline to evaluate state recovery behaviors.

## 2. Evidence and Observable Symptoms
- **Build Log Trace**: `error: linker 'link.exe' not found` during `maturin pep517 build-wheel`.
- **Failure Trace Event**: Structured event logged in `reports/failure_trace.jsonl` with `step: 7`, `total_steps: 10`, `event: "step_failure"`, and error details indicating hash verification mismatch.
- **MicroVM State**: In-guest artifact `/tmp/research_report.md` produced an invalid cryptographic checksum against expected content bounds.

## 3. Root Cause Analysis (RCA)
- **Host Runtime**: Celesto microVM execution is architected for Linux/container environments where KVM, Firecracker, and precompiled manylinux wheels are standard. Windows developer hosts act strictly as trusted API control planes and must utilize containerized execution or graceful fallback shims rather than native hypervisor driver compilation.
- **Guest Verification (Step 7)**: Transient guest disk corruption or agent tool hallucinations during intermediate file construction leave lingering tainted state in guest memory and filesystem caches. In-place recovery attempts (e.g. rewriting file portions) risk carrying forward hidden state contamination.

## 4. Corrective and Preventive Actions
1. **Containerized Linux Orchestration**: Standardized full multi-container deployment via Docker Compose with Linux-based Python 3.11 runtimes where `celesto` and its dependencies install cleanly from prebuilt binary wheels without host compilation dependencies.
2. **Fresh Sandbox Recovery Policy**: Adopted an immutable 'fresh' recovery policy. When Step 7 integrity verification fails, the orchestrator immediately terminates the tainted guest, purges all allocated disk resources, and boots a pristine replacement guest from base templates.
3. **Structured Audit Logging**: All pre-execution decisions are recorded to `logs/commands.jsonl` to ensure complete traceability across retries.
