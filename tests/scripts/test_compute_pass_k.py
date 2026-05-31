"""compute_pass_k must not inflate Pass^k for empty/partial runs.

Pass^k = P(all k trials pass). The old guard returned 1.0 for an empty trial
list and for n<k all-pass (e.g. 3 trials scored at k=5), silently inflating the
primary deployment metric. These lock the correct arithmetic.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_AR = Path(__file__).resolve().parents[2] / "scripts" / "analyze_results.py"


def _compute_pass_k():
    spec = importlib.util.spec_from_file_location("_analyze_results", _AR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compute_pass_k


def test_empty_and_partial_runs_are_zero_not_one() -> None:
    pk = _compute_pass_k()
    assert pk([], 5) == 0.0  # was 1.0
    assert pk([True, True, True], 5) == 0.0  # n<k all-pass was 1.0
    assert pk([True, False, True], 3) == 0.0  # a fail -> 0
    assert pk([True] * 5, 5) == 1.0  # genuine all-pass
    assert pk([True, True, True], 3) == 1.0  # exactly k all-pass
