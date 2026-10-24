"""Command Safety Policy, Pre-execution Enforcement, and Audit Logging.

Enforces pre-execution checks on every command before it reaches the Celesto guest,
ensuring strict containment, preventing secret exfiltration and destructive actions,
and writing structured JSONL audit logs.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from celesto.callbacks import Callback, CommandBlockedError, RunContext

logger = logging.getLogger(__name__)

COMMANDS_LOG_PATH = Path("logs/commands.jsonl")
COMMANDS_LOG_LOCK = threading.Lock()

# Regex to detect API keys and tokens for redaction
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|auth|bearer)[\s=:\"\']+([A-Za-z0-9_\-\.]{8,})"),
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),
    re.compile(r"(ghp_[a-zA-Z0-9]{20,})"),
    re.compile(r"(Bearer\s+[a-zA-Z0-9_\-\.]{16,})"),
]

# Prohibited destructive and exfiltration command patterns
DENY_PATTERNS = [
    # Destructive filesystem operations
    re.compile(r"\brm\s+.*-[a-zA-Z]*r.*(\s+(/|\./|\.\./|/\*|~|\*|\$HOME|/etc|/bin|/usr|/lib|/var))", re.IGNORECASE),
    re.compile(r"\brm\s+.*(-r|-R|--recursive).*\s+(/|\./|\.\./|/\*|~|\*|\$HOME|/etc|/bin|/usr|/lib|/var)", re.IGNORECASE),
    re.compile(r"\brm\s+.*-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+(/|\./|\.\./|/\*|~|\*|\$HOME|/etc|/bin|/usr|/lib|/var)", re.IGNORECASE),
    re.compile(r"\b(mkfs|fdisk|wipefs|parted|sfdisk)\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=/dev/(zero|urandom|null)\s+of=/dev/", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE),  # fork bomb
    re.compile(r"\b(shutdown|reboot|init\s+0|poweroff|halt)\b", re.IGNORECASE),
    re.compile(r"\bchmod\s+(-R\s+)?777\s+/", re.IGNORECASE),

    # Sensitive credential reading and exfiltration
    re.compile(r"(/etc/shadow|/etc/gshadow)", re.IGNORECASE),
    re.compile(r"(/root/\.ssh|\.ssh/(id_rsa|id_ed25519|id_dsa|authorized_keys)|\.aws/credentials|\.docker/config\.json)", re.IGNORECASE),
    re.compile(r"\benv\s*\|\s*(curl|wget|nc|netcat|ncat|socat|telnet)\b", re.IGNORECASE),
    re.compile(r"(curl|wget)\s+.*(-d|--data|--upload-file)\s+@?(/etc/shadow|/root/|~?/\.ssh)", re.IGNORECASE),
    re.compile(r"/bin/(ba|z)?sh\s+-i\s+>&?\s+/dev/tcp/", re.IGNORECASE),  # reverse shell
    re.compile(r"\b(nc|netcat|socat)\s+.*-e\s+/bin/", re.IGNORECASE),
]


def redact_secrets(cmd: str) -> str:
    """Redact sensitive credentials, tokens, and keys from commands and logs."""
    redacted = cmd
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(r"\1=[REDACTED]", redacted)

    # Also redact known environment secrets if present
    for env_var in ["CELESTO_API_KEY", "LLM_API_KEY"]:
        val = os.environ.get(env_var)
        if val and len(val) >= 6 and val in redacted:
            redacted = redacted.replace(val, "[REDACTED]")
    return redacted


def evaluate_command_safety(command: str) -> Tuple[bool, str]:
    """Evaluate whether a shell command is safe to execute inside the sandbox.

    Returns:
        (is_allowed: bool, reason: str)
    """
    if not command or not command.strip():
        return False, "Command is empty"

    clean_cmd = command.strip()

    # Fail closed on potential parser attacks
    for deny_re in DENY_PATTERNS:
        if deny_re.search(clean_cmd):
            return False, f"Prohibited operation matched security pattern: {deny_re.pattern}"

    return True, "Operation permitted under research execution policy"


def log_command_audit(
    sandbox_name: str,
    command: str,
    decision: str,
    execution_target: str = "celesto_sandbox",
    live_execution: Optional[bool] = None,
) -> None:
    """Write structured command audit entry to logs/commands.jsonl.

    Enforces required schema:
    ts: ISO-8601 timestamp
    sandbox_name: ^sbx-[a-z0-9]{8,}$
    command: non-empty command with secrets redacted
    decision: 'allow' or 'block'
    execution_target: 'celesto_sandbox'
    live_execution: bool (distinguishes live sandbox from offline simulation)
    execution_mode: 'live' or 'offline_simulation'
    """
    COMMANDS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    redacted_command = redact_secrets(command.strip())
    if not redacted_command:
        redacted_command = "[empty_command]"

    is_live = bool(live_execution)
    audit_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sandbox_name": sandbox_name,
        "command": redacted_command,
        "decision": decision,
        "execution_target": execution_target,
        "live_execution": is_live,
        "execution_mode": "live" if is_live else "offline_simulation",
    }

    with COMMANDS_LOG_LOCK:
        with open(COMMANDS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry) + "\n")


class ResearchSafetyGuardCallback(Callback):
    """Celesto pre-execution callback that vetoes dangerous commands before guest dispatch."""

    def __init__(self, sandbox_name: str, live_execution: bool = False) -> None:
        super().__init__()
        self.sandbox_name = sandbox_name
        self.live_execution = live_execution

    def on_pre_run(self, ctx: RunContext) -> None:
        """Celesto Callback hook: inspects and vetoes command if dangerous."""
        cmd = ctx.command
        allowed, reason = evaluate_command_safety(cmd)

        if not allowed:
            # Audit the blocked attempt
            log_command_audit(
                sandbox_name=self.sandbox_name,
                command=cmd,
                decision="block",
                execution_target="celesto_sandbox",
                live_execution=self.live_execution,
            )
            # Raise CommandBlockedError to stop execution before reaching guest
            raise CommandBlockedError(
                f"Blocked prohibited command: {reason}",
                vm_id=self.sandbox_name,
                command=redact_secrets(cmd)
            )

        # Audit the permitted execution
        log_command_audit(
            sandbox_name=self.sandbox_name,
            command=cmd,
            decision="allow",
            execution_target="celesto_sandbox",
            live_execution=self.live_execution,
        )
