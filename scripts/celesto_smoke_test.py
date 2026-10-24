#!/usr/bin/env python3
"""Celesto Cloud Computer Integration Smoke Test.

Creates exactly one temporary cloud computer, executes a harmless guest command,
verifies the output, and ensures clean resource deletion using the official SDK lifecycle.

NEVER prints secrets or API keys.
"""

from __future__ import annotations

import os
import sys
import time


def mask_key(key: str) -> str:
    """Return a masked representation of a key (e.g. 'sk-***...[len=32]')."""
    if not key:
        return "<not set>"
    if len(key) <= 6:
        return f"***[len={len(key)}]"
    return f"{key[:3]}...{key[-3:]}[len={len(key)}]"


def run_smoke_test() -> int:
    print("=" * 60)
    print("Celesto Cloud Computer SDK Smoke Test")
    print("=" * 60)

    # 1. Validate environment configuration
    provider = os.environ.get("CELESTO_PROVIDER", "cloud").strip()
    api_key = os.environ.get("CELESTO_API_KEY", "").strip()

    print(f"Selected Provider : {provider}")
    print(f"API Key Status    : {'Configured (' + mask_key(api_key) + ')' if api_key and api_key != 'your_celesto_api_key_here' and api_key != 'celesto_api_key_placeholder' else 'MISSING / PLACEHOLDER'}")

    if provider != "cloud":
        print(f"[ERROR] Smoke test requires provider='cloud', found '{provider}'.", file=sys.stderr)
        return 1

    if not api_key or api_key in ("your_celesto_api_key_here", "celesto_api_key_placeholder"):
        print(
            "\n[FATAL] CELESTO_API_KEY is not configured or contains a placeholder.\n"
            "Configure a valid Celesto API key in your .env file or environment before running.",
            file=sys.stderr,
        )
        return 1

    # 2. Import Celesto SDK
    try:
        from celesto import Computer
        from celesto.exceptions import CelestoError, CloudAPIError
    except ImportError as e:
        print(f"\n[FATAL] Failed to import Celesto SDK: {e}", file=sys.stderr)
        print("Ensure 'celesto' package is installed in this Python environment.", file=sys.stderr)
        return 1

    # 3. Create exactly one temporary cloud computer with documented lifecycle
    computer = None
    exit_code = 0
    start_mono = time.monotonic()

    try:
        print("\n[Step 1/3] Initializing Celesto Cloud Computer handle...")
        computer = Computer(provider="cloud", api_key=api_key, lifetime="ephemeral")

        print("Provisioning remote microVM in Celesto Cloud...")
        computer.start()
        boot_duration = round(time.monotonic() - start_mono, 3)
        computer_id = getattr(computer, "id", "unknown")
        print(f"Cloud Computer '{computer_id}' successfully booted and ready in {boot_duration}s.")

        # 4. Execute harmless command inside the guest
        print("\n[Step 2/3] Executing harmless probe command inside guest...")
        test_marker = f"smoke_test_ok_{int(time.time())}"
        probe_cmd = f"echo '{test_marker}' && uname -s -m -r"
        print(f"Command: {probe_cmd}")

        res = computer.run(probe_cmd, timeout=30)
        print(f"Guest Exit Code: {res.exit_code}")
        print(f"Guest Output   :\n{res.stdout.strip()}")

        # 5. Verify output
        if res.exit_code != 0:
            print(f"[ERROR] Guest command returned nonzero exit code: {res.exit_code}", file=sys.stderr)
            if res.stderr:
                print(f"Guest Stderr: {res.stderr.strip()}", file=sys.stderr)
            exit_code = 2
        elif test_marker not in res.stdout:
            print(f"[ERROR] Verification failed: marker '{test_marker}' not found in guest stdout.", file=sys.stderr)
            exit_code = 3
        else:
            print("\n[Step 3/3] In-guest verification SUCCEEDED!")

    except CloudAPIError as api_err:
        print(f"\n[ERROR] Celesto Cloud API returned an error: {api_err}", file=sys.stderr)
        exit_code = 4
    except CelestoError as cel_err:
        print(f"\n[ERROR] Celesto error: {cel_err}", file=sys.stderr)
        exit_code = 5
    except Exception as exc:
        print(f"\n[ERROR] Unexpected error during smoke test: {exc}", file=sys.stderr)
        exit_code = 6
    finally:
        # 6. Ensure clean deletion
        if computer is not None:
            comp_id = getattr(computer, "id", "unknown")
            print(f"\nCleaning up Cloud Computer '{comp_id}'...")
            try:
                computer.delete()
                print(f"Cloud Computer '{comp_id}' deleted successfully.")
            except Exception as cleanup_err:
                print(f"[WARNING] Error during computer deletion: {cleanup_err}", file=sys.stderr)
                if exit_code == 0:
                    exit_code = 7

    total_duration = round(time.monotonic() - start_mono, 3)
    print("=" * 60)
    if exit_code == 0:
        print(f"Smoke test PASSED in {total_duration}s. Exactly one temporary cloud computer was created, verified, and cleaned up.")
    else:
        print(f"Smoke test FAILED (exit_code={exit_code}) in {total_duration}s.")
    print("=" * 60)

    return exit_code


if __name__ == "__main__":
    sys.exit(run_smoke_test())
