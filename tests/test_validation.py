"""Validation tests for the injector.world QA/UX audit toolchain.

Covers three gates:

  1.  Every module in scripts/ imports cleanly.
  2.  The UX validator gate passes (subprocess, exit 0 + "ALL CHECKS PASSED").
  3.  The QA validator gate passes (subprocess, exit 0).

The validator subprocesses run from the repository root, matching how the
scripts are invoked in CI. They depend only on data/ and reports/ (tracked),
so the tests stay green even when the gitignored evidence/ directory is absent.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Modules in scripts/ that must import without raising.
SCRIPTS_MODULES = [
    "build_seed",
    "harness",
    "report_builder",
    "rubric",
    "smoke_test",
    "ux_harness",
    "ux_report_builder",
    "ux_rubric",
    "validate_reports",
    "validate_ux_reports",
]


def run_script(*args: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(a) for a in args)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@pytest.mark.parametrize("module_name", SCRIPTS_MODULES)
def test_scripts_modules_import(module_name: str) -> None:
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        __import__(module_name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


def test_ux_validator_gate() -> None:
    result = run_script("scripts/validate_ux_reports.py")
    assert result.returncode == 0, (
        f"UX validator exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ALL CHECKS PASSED" in result.stdout


def test_qa_validator_gate() -> None:
    result = run_script("scripts/validate_reports.py")
    assert result.returncode == 0, (
        f"QA validator exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ALL CHECKS PASSED" in result.stdout