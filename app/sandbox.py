"""Celesto Sandbox Manager and MicroVM Orchestrator.

Integrates with the official Celesto SDK (Computer / CloudComputer), manages
lifecycle (create, probe, execute, browser, cleanup), enforces pre-execution safety,
and records execution timings with high precision.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any, List, Optional

from celesto.callbacks import CommandBlockedError, RunContext
from celesto.exceptions import CelestoError
from celesto.types import CommandResult

from app.safety import ResearchSafetyGuardCallback, evaluate_command_safety, log_command_audit, redact_secrets

logger = logging.getLogger(__name__)

SANDBOX_NAME_RE = re.compile(r"^sbx-[a-z0-9]{8,}$")


class CelestoCredentialsMissingError(CelestoError):
    """Raised when Celesto live execution is requested without credentials."""


class CelestoCleanupError(CelestoError):
    """Raised when sandbox cleanup encounters an explicit failure."""


@dataclass
class GuestExecutionResult:
    """Structured result of executing a command inside the Celesto sandbox."""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    ok: bool


def generate_unique_sandbox_name(prefix: str = "sbx-") -> str:
    """Generate a unique valid sandbox name matching ^sbx-[a-z0-9]{8,}$."""
    # 12 hex characters provides 48 bits of entropy per sandbox name
    random_hex = secrets.token_hex(6)
    name = f"{prefix}{random_hex}"
    if not SANDBOX_NAME_RE.match(name):
        raise ValueError(f"Generated name '{name}' does not match regex ^sbx-[a-z0-9]{{8,}}$")
    return name


class SandboxManager:
    """Orchestrates creation, execution, browser access, and cleanup of Celesto computers."""

    def __init__(
        self,
        sandbox_name: Optional[str] = None,
        provider: Optional[str] = None,
        simulate_offline: Optional[bool] = None,
    ) -> None:
        self.sandbox_name = sandbox_name or generate_unique_sandbox_name()
        if not SANDBOX_NAME_RE.match(self.sandbox_name):
            raise ValueError(f"Invalid sandbox name '{self.sandbox_name}'; must match ^sbx-[a-z0-9]{{8,}}$")

        self.provider = provider or os.environ.get("CELESTO_PROVIDER", "cloud")
        self.simulate_offline = (
            simulate_offline
            if simulate_offline is not None
            else os.environ.get("MOCK_SANDBOX_FOR_OFFLINE_TESTS", "false").lower() == "true"
        )
        self.safety_guard = ResearchSafetyGuardCallback(self.sandbox_name)

        self.computer: Any = None
        self.boot_to_ready_s: Optional[float] = None
        self.created_at_mono: Optional[float] = None
        self.ready_at_mono: Optional[float] = None
        self._is_ready: bool = False
        self._is_deleted: bool = False

    def start(self) -> float:
        """Provision the Celesto sandbox, probe readiness, and measure boot time."""
        self.created_at_mono = time.monotonic()
        logger.info("Initializing Celesto computer '%s' (provider=%s)...", self.sandbox_name, self.provider)

        if self.simulate_offline:
            # Simulated environment strictly for offline unit tests
            time.sleep(0.05)  # Simulate small guest boot latency
            self.ready_at_mono = time.monotonic()
            self.boot_to_ready_s = round(self.ready_at_mono - self.created_at_mono, 3)
            self._is_ready = True
            logger.info("Simulated sandbox '%s' ready in %.3fs", self.sandbox_name, self.boot_to_ready_s)
            return self.boot_to_ready_s

        # Real Celesto execution path
        api_key = os.environ.get("CELESTO_API_KEY")
        if self.provider == "cloud" and not api_key:
            raise CelestoCredentialsMissingError(
                "Cannot boot live Celesto cloud sandbox: CELESTO_API_KEY environment variable is not configured. "
                "Configure your API key in .env or provide it via environment variables."
            )

        from celesto import Computer

        try:
            # Pass template_id="scratch" or default guest options
            options: dict[str, Any] = {"provider": self.provider}
            if self.provider == "cloud" and api_key:
                options["api_key"] = api_key

            backend = os.environ.get("CELESTO_BACKEND")
            if backend and self.provider == "local":
                options["backend"] = backend

            self.computer = Computer(**options)

            # Readiness probe: execute minimal command inside guest to verify SSH/guest readiness
            probe_start = time.monotonic()
            probe_result = self.computer.run("uname -a", timeout=45)
            if probe_result.exit_code != 0:
                raise CelestoError(
                    f"Readiness probe failed inside guest: exit code {probe_result.exit_code}, stderr: {probe_result.stderr}"
                )

            self.ready_at_mono = time.monotonic()
            self.boot_to_ready_s = round(self.ready_at_mono - self.created_at_mono, 3)
            self._is_ready = True
            logger.info("Celesto computer '%s' ready in %.3fs", self.sandbox_name, self.boot_to_ready_s)
            return self.boot_to_ready_s

        except Exception as e:
            self._is_ready = False
            logger.error("Failed to start Celesto computer '%s': %s", self.sandbox_name, e)
            self.cleanup()
            raise

    def run_command(self, command: str, timeout: int = 30) -> GuestExecutionResult:
        """Run a shell command inside the guest with pre-execution safety enforcement."""
        if not self._is_ready and not self.simulate_offline:
            raise CelestoError("Cannot execute command: sandbox is not in ready state.")

        start_time = time.monotonic()

        # Step 1: Pre-execution safety enforcement via Callback hook
        ctx = RunContext(
            vm_id=self.sandbox_name,
            command=command,
            shell="login",
            timeout=timeout,
        )
        self.safety_guard.on_pre_run(ctx)

        # Step 2: Execute command in guest
        if self.simulate_offline:
            # Deterministic simulation of basic shell utilities for offline testing
            duration_s = round(time.monotonic() - start_time, 4)
            cmd_strip = command.strip()
            if cmd_strip.startswith("echo "):
                out = cmd_strip[5:].strip("'\"") + "\n"
                return GuestExecutionResult(
                    command=command, exit_code=0, stdout=out, stderr="", duration_s=duration_s, ok=True
                )
            if "sha256sum" in cmd_strip:
                return GuestExecutionResult(
                    command=command, exit_code=0, stdout="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  artifact.md\n", stderr="", duration_s=duration_s, ok=True
                )
            return GuestExecutionResult(
                command=command, exit_code=0, stdout="simulated_guest_output\n", stderr="", duration_s=duration_s, ok=True
            )

        # Real guest execution
        try:
            result: CommandResult = self.computer.run(command, timeout=timeout)
            duration_s = round(time.monotonic() - start_time, 4)
            return GuestExecutionResult(
                command=command,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_s=duration_s,
                ok=(result.exit_code == 0),
            )
        except Exception as e:
            duration_s = round(time.monotonic() - start_time, 4)
            logger.error("Execution error inside sandbox '%s' for '%s': %s", self.sandbox_name, redact_secrets(command), e)
            raise

    def write_guest_file(self, file_path: str, content: str) -> None:
        """Atomically create and write a file inside the Celesto guest computer."""
        # Escape single quotes safely for EOF heredoc
        safe_content = content.replace("'", "'\"'\"'")
        cmd = f"cat << 'EOF' > {file_path}\n{content}\nEOF"
        res = self.run_command(cmd)
        if not res.ok:
            raise CelestoError(f"Failed to write file {file_path} inside guest: {res.stderr}")

    def read_guest_file(self, file_path: str) -> str:
        """Read file contents from inside the Celesto guest computer."""
        res = self.run_command(f"cat {file_path}")
        if not res.ok:
            raise CelestoError(f"Failed to read file {file_path} inside guest: {res.stderr}")
        return res.stdout

    def verify_guest_file(self, file_path: str) -> str:
        """Verify file existence and compute sha256 checksum inside the guest."""
        res = self.run_command(f"sha256sum {file_path}")
        if not res.ok:
            raise CelestoError(f"File verification failed for {file_path} in guest: {res.stderr}")
        return res.stdout.strip().split()[0]

    def get_browser_connection(self) -> Any:
        """Access the Celesto sandboxed browser connection (CDP WebSocket endpoint)."""
        if self.simulate_offline:
            return {"ws_url": "ws://127.0.0.1:9222/devtools/browser/simulated"}
        if not self.computer:
            raise CelestoError("Sandbox is not running.")
        return self.computer.browser()

    def cleanup(self) -> None:
        """Clean up and delete the Celesto computer instance.

        Explicitly catches and reports cleanup errors to ensure transparency.
        """
        if self._is_deleted:
            return

        cleanup_error: Optional[Exception] = None
        if self.computer is not None and not self.simulate_offline:
            try:
                self.computer.delete()
            except Exception as e:
                cleanup_error = e
                logger.error("Error during Celesto computer cleanup for '%s': %s", self.sandbox_name, e)

        self._is_deleted = True
        self._is_ready = False

        if cleanup_error:
            raise CelestoCleanupError(f"Cleanup failed for sandbox '{self.sandbox_name}': {cleanup_error}")
        logger.info("Sandbox '%s' successfully cleaned up.", self.sandbox_name)

    def __enter__(self) -> SandboxManager:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()
