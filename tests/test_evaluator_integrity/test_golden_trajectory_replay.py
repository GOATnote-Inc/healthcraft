"""Golden-trajectory replay test — V8 reward/pass/safety-gate stability.

This is the most important test in the evaluator-integrity suite. It reads
the 30-trajectory manifest at ``tests/fixtures/golden_trajectories/index.json``
(frozen in Phase 0 by ``scripts/freeze_goldens.py``) and asserts that
``replay_from_trajectory`` re-derives the exact ``(reward, passed,
safety_gate_passed)`` tuple AND the exact canonical criteria-results hash
that V8 wrote to disk.

What the contract is:
    Given the same audit log (reconstructed from saved tool_calls) AND the
    same llm_judge verdicts (read from saved ``criteria_results``), the
    evaluator produces bit-identical scores. This locks down the
    deterministic channels — world_state and pattern — while allowing the
    non-deterministic judge channel to be carried forward from the saved
    run.

What would make this test go red:
    * A silent change to ``_verify_world_state`` parsing (e.g. AND/OR split
      heuristic, qualifier map, tool_name case handling).
    * A change to ``compute_reward`` / ``check_safety_gate`` / dimension
      scoring that alters the aggregation.
    * A regression in ``_split_compound`` or ``_expand_tool_alternatives``.
    * A change to the audit-log ingest path that the replay uses
      (``WorldState.record_audit``).
    * Genuine V8 nondeterminism (per the plan's anticipated pitfall #1,
      document in ``docs/PAPER_REVISION_NOTES.md`` — do NOT silently
      "fix" the score).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from healthcraft.tasks.evaluator import replay_from_trajectory
from healthcraft.tasks.loader import Task, load_tasks

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "tests" / "fixtures" / "golden_trajectories" / "index.json"
TASK_DIR = REPO_ROOT / "configs" / "tasks"

# Tolerance for reward floating-point comparison. Eq. 1 is a rational of
# small integers so 1e-9 is plenty; 1e-12 would also work. Anything larger
# would mask a real regression in aggregation.
_REWARD_TOL = 1e-9


# ---------------------------------------------------------------------------
# Module-level fixtures (expensive to build once per call)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    """The frozen 30-trajectory manifest from Phase 0."""
    if not MANIFEST.exists():
        pytest.skip(
            f"Golden manifest not found at {MANIFEST}. "
            f"Regenerate with: python scripts/freeze_goldens.py "
            f"--output {MANIFEST.relative_to(REPO_ROOT)}"
        )
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tasks_by_id() -> dict[str, Task]:
    """All tasks, indexed by task.id for O(1) lookup."""
    return {t.id: t for t in load_tasks(TASK_DIR)}


# ---------------------------------------------------------------------------
# Hash computation — must match scripts/freeze_goldens.py::criteria_results_hash
# ---------------------------------------------------------------------------


def _canonical_hash(cr_list: list[dict[str, Any]]) -> str:
    """SHA256 over the canonical sorted (id, satisfied) tuples.

    Must be bit-identical to scripts/freeze_goldens.py. Excludes ``evidence``
    because evidence strings can contain LLM-judge prose that varies across
    channels; the contract we lock is "criterion X reaches verdict Y".
    """
    canonical = sorted((str(c["id"]), bool(c["satisfied"])) for c in cr_list)
    blob = json.dumps(canonical, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Manifest sanity
# ---------------------------------------------------------------------------


def test_manifest_has_expected_shape(manifest: dict[str, Any]) -> None:
    """Manifest sanity: version, 30 entries, 5 per category."""
    assert manifest["version"] == 1
    assert manifest["n_trajectories"] == len(manifest["trajectories"]) == 30
    # 5 per category × 6 categories = 30
    by_cat: dict[str, int] = {}
    for entry in manifest["trajectories"]:
        by_cat[entry["category"]] = by_cat.get(entry["category"], 0) + 1
    assert all(v == 5 for v in by_cat.values()), f"Per-category distribution is not 5: {by_cat}"
    assert set(by_cat.keys()) == {
        "clinical_reasoning",
        "multi_step_workflows",
        "information_retrieval",
        "clinical_communication",
        "safety_critical_judgment",
        "temporal_reasoning",
    }


def test_every_manifest_task_id_resolves(
    manifest: dict[str, Any], tasks_by_id: dict[str, Task]
) -> None:
    """Every manifest entry references a task that exists in configs/tasks."""
    missing = sorted({e["task_id"] for e in manifest["trajectories"]} - set(tasks_by_id))
    assert not missing, (
        f"Manifest references {len(missing)} task(s) not found in configs/tasks: "
        f"{missing}. Either regenerate the manifest or restore the task YAML(s)."
    )


def test_every_manifest_trajectory_file_exists(manifest: dict[str, Any]) -> None:
    """Every manifest entry's trajectory_path resolves to a file on disk.

    Guards against `results/` pruning. If a golden trajectory was deleted,
    the replay contract is gone — refuse to skip, fail loudly instead.
    """
    missing: list[str] = []
    for entry in manifest["trajectories"]:
        p = REPO_ROOT / entry["trajectory_path"]
        if not p.exists():
            missing.append(entry["trajectory_path"])
    assert not missing, (
        f"{len(missing)} golden trajectory file(s) missing from disk:\n  " + "\n  ".join(missing)
    )


# ---------------------------------------------------------------------------
# The core replay test — aggregated failure report
# ---------------------------------------------------------------------------


def test_all_goldens_replay_bit_identical(
    manifest: dict[str, Any], tasks_by_id: dict[str, Task]
) -> None:
    """All 30 golden trajectories replay to byte-identical verdicts.

    We aggregate failures across all 30 trajectories rather than stopping
    at the first one. If V8 has drift, the distribution of failures is
    diagnostic (e.g. "only long trajectories" vs. "only compound-clause
    criteria" vs. "one specific task"). Failing fast would hide that signal.

    The report format is designed for direct action:
      TASK_ID (model)
        reward   : observed vs expected
        passed   : observed vs expected
        safety   : observed vs expected
        hash     : first 12 chars (full hashes are in the manifest)
    """
    failures: list[str] = []

    for entry in manifest["trajectories"]:
        task_id = entry["task_id"]
        model = entry["model"]
        task = tasks_by_id[task_id]
        traj_path = REPO_ROOT / entry["trajectory_path"]
        traj = json.loads(traj_path.read_text(encoding="utf-8"))

        result = replay_from_trajectory(traj, task)

        cr_dicts = [
            {"id": cr.criterion_id, "satisfied": cr.satisfied} for cr in result.criteria_results
        ]
        observed_hash = _canonical_hash(cr_dicts)

        mismatches: list[str] = []
        if abs(result.reward - entry["expected_reward"]) > _REWARD_TOL:
            mismatches.append(f"reward   : {result.reward!r} vs {entry['expected_reward']!r}")
        if result.passed != entry["expected_passed"]:
            mismatches.append(f"passed   : {result.passed!r} vs {entry['expected_passed']!r}")
        if result.safety_gate_passed != entry["expected_safety_gate"]:
            mismatches.append(
                f"safety   : {result.safety_gate_passed!r} vs {entry['expected_safety_gate']!r}"
            )
        if observed_hash != entry["criteria_results_hash"]:
            mismatches.append(
                f"hash     : {observed_hash[:12]} vs {entry['criteria_results_hash'][:12]}"
            )

        if mismatches:
            failures.append(
                f"{task_id} ({model}, {Path(entry['trajectory_path']).name}):\n    "
                + "\n    ".join(mismatches)
            )

    if failures:
        pytest.fail(
            f"{len(failures)}/{len(manifest['trajectories'])} golden trajectories "
            f"failed bit-identical replay. "
            f"If this is the first red on this test, per the plan's anticipated "
            f"pitfall #1: document in docs/PAPER_REVISION_NOTES.md, do NOT silently "
            f"fix.\n\n" + "\n\n".join(failures)
        )


# ---------------------------------------------------------------------------
# Criterion-count sanity (cheap pre-check before the expensive replay)
# ---------------------------------------------------------------------------


def test_criterion_counts_match_tasks(
    manifest: dict[str, Any], tasks_by_id: dict[str, Task]
) -> None:
    """Manifest n_criteria matches len(task.criteria).

    Catches the case where a task was edited (criterion added/removed) after
    the manifest was frozen — the replay would still pass if the remaining
    criteria all match, but the scores would silently diverge from V8.
    """
    drift: list[str] = []
    for entry in manifest["trajectories"]:
        task = tasks_by_id[entry["task_id"]]
        if len(task.criteria) != entry["n_criteria"]:
            drift.append(
                f"{entry['task_id']}: task has {len(task.criteria)} criteria, "
                f"manifest expected {entry['n_criteria']}"
            )
    assert not drift, "Task criterion counts drifted from manifest:\n  " + "\n  ".join(drift)
