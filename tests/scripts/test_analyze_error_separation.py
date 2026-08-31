"""Infra errors must be reported separately from model safety failures.

Audit finding P2-2: error trajectories are graded fail-closed (reward=0,
safety_gate_passed=False) and counted in ``safety_failures`` -- correct --
but nothing separated them, so an infra outage silently inflated the
model's measured safety-failure rate. ``analyze_model`` now surfaces
``n_error`` and ``safety_failures_excl_errors`` alongside the unchanged
fail-closed totals.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_AR = Path(__file__).resolve().parents[2] / "scripts" / "analyze_results.py"


def _analyze_model():
    spec = importlib.util.spec_from_file_location("_analyze_results_err", _AR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.analyze_model


def _entry(task_id: str, *, passed: bool, safety: bool, error: str | None = None) -> dict:
    return {
        "task_id": task_id,
        "model": "m",
        "seed": 42,
        "reward": 1.0 if passed else 0.0,
        "passed": passed,
        "safety_gate_passed": safety,
        "total_tool_calls": 0,
        "duration_seconds": 0.0,
        "trajectory_path": "trajectories/clinical_reasoning/x.json",
        "error": error,
    }


def test_errors_counted_fail_closed_but_reported_separately() -> None:
    analyze = _analyze_model()
    entries = [
        _entry("T1", passed=True, safety=True),
        _entry("T2", passed=False, safety=False),  # genuine model safety failure
        _entry("T3", passed=False, safety=False, error="API timeout"),  # infra error
    ]
    result = analyze(entries, "m")
    # Fail-closed totals unchanged: the error IS a safety failure.
    assert result["safety_failures"] == 2
    # But the infra/model split is explicit.
    assert result["n_error"] == 1
    assert result["safety_failures_excl_errors"] == 1
    assert result["safety_failure_rate_excl_errors"] == 1 / 3


def test_no_errors_means_identical_rates() -> None:
    analyze = _analyze_model()
    entries = [
        _entry("T1", passed=False, safety=False),
        _entry("T2", passed=True, safety=True),
    ]
    result = analyze(entries, "m")
    assert result["n_error"] == 0
    assert result["safety_failures"] == result["safety_failures_excl_errors"] == 1
    assert result["safety_failure_rate"] == result["safety_failure_rate_excl_errors"]
