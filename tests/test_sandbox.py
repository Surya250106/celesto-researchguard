"""Unit tests for Celesto Sandbox Manager lifecycle, naming, and error handling."""

import os
import re
import pytest

from app.sandbox import (
    CelestoCredentialsMissingError,
    SandboxManager,
    generate_unique_sandbox_name,
)

SANDBOX_NAME_RE = re.compile(r"^sbx-[a-z0-9]{8,}$")


def test_unique_sandbox_name_format():
    """Verify generated sandbox names conform to required regex and have high entropy."""
    names = [generate_unique_sandbox_name() for _ in range(50)]
    assert len(set(names)) == 50, "Sandbox names must be strictly unique"
    for name in names:
        assert SANDBOX_NAME_RE.match(name), f"Sandbox name '{name}' does not match regex ^sbx-[a-z0-9]{{8,}}$"


def test_sandbox_manager_rejects_invalid_name():
    """Verify SandboxManager constructor rejects names not matching regular expression."""
    with pytest.raises(ValueError):
        SandboxManager(sandbox_name="bad-name", simulate_offline=True)


def test_missing_credentials_fails_clearly():
    """Verify live cloud sandbox creation without CELESTO_API_KEY raises CelestoCredentialsMissingError."""
    # Ensure CELESTO_API_KEY is unset
    old_key = os.environ.pop("CELESTO_API_KEY", None)
    try:
        manager = SandboxManager(
            sandbox_name="sbx-testcreds01",
            provider="cloud",
            simulate_offline=False,
        )
        with pytest.raises(CelestoCredentialsMissingError) as exc_info:
            manager.start()
        assert "CELESTO_API_KEY" in str(exc_info.value)
    finally:
        if old_key is not None:
            os.environ["CELESTO_API_KEY"] = old_key


def test_sandbox_manager_offline_lifecycle():
    """Verify start, command execution, and cleanup in offline mode."""
    sbx_name = generate_unique_sandbox_name()
    manager = SandboxManager(sandbox_name=sbx_name, simulate_offline=True)

    boot_time = manager.start()
    assert boot_time is not None and boot_time >= 0.0
    assert manager._is_ready is True

    res = manager.run_command("echo 'test_probe'")
    assert res.ok is True
    assert "test_probe" in res.stdout

    manager.cleanup()
    assert manager._is_deleted is True
    assert manager._is_ready is False
