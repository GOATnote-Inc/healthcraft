"""Overlay-channel verdict-lock — v9/v10/v11 reproducibility.

Companion to ``test_golden_trajectory_replay.py`` (which locks V8). The V8 lock
pins "replay reproduces what V8 wrote to disk"; this one pins "replay at the
v9/v10/v11 OVERLAY channels reproduces the frozen verdict" — closing the gap the
2026-05-31 audit flagged: only V8 was locked, so a change to an overlay file,
``em_vocab``, a qualifier map, or the matcher could silently shift the
paper-metrics v10 numbers (the unguarded MW-003 flip).

The lock set is 91 trajectories = the 30 stratified V8 goldens UNION one pilot
trajectory per overlay-promoted task (so every promoted criterion is exercised;
the 30 goldens alone diverged from V8 on only 1-2 cases). 12/91 v10 verdicts
genuinely differ from V8 — the lock pins behavior the V8 lock cannot see.

What turns this red: any change that shifts a v9/v10/v11 verdict on a locked
trajectory (overlay edit, em_vocab class change, matcher change, qualifier-map
change). That is INTENDED to be loud. If the change is deliberate, re-freeze:
    python scripts/freeze_goldens_channels.py
and review the manifest diff (it IS the re-grade record) — do NOT regenerate
just to make a red test green.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from healthcraft.llm.orchestrator import _load_overlay
from healthcraft.tasks.evaluator import replay_from_trajectory
from healthcraft.tasks.loader import Task, load_tasks

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "tests" / "fixtures" / "golden_trajectories" / "index_channels.json"
TASK_DIR = REPO_ROOT / "configs" / "tasks"
_REWARD_TOL = 1e-9


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        pytest.skip(
            f"Channel manifest not found at {MANIFEST}. "
            f"Regenerate with: python scripts/freeze_goldens_channels.py"
        )
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tasks_by_id() -> dict[str, Task]:
    return {t.id: t for t in load_tasks(TASK_DIR)}


def _canonical_hash(cr_list: list[dict[str, Any]]) -> str:
    """Byte-identical to scripts/freeze_goldens_channels.py and the V8 lock."""
    canonical = sorted((str(c["id"]), bool(c["satisfied"])) for c in cr_list)
    blob = json.dumps(canonical, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _overlay_task_ids() -> set[str]:
    return {cid.rsplit("-C", 1)[0] for cid in _load_overlay("v11")}


def test_manifest_shape(manifest: dict[str, Any]) -> None:
    assert manifest["version"] == 1
    assert manifest["channels"] == ["v9", "v10", "v11"]
    assert manifest["n_trajectories"] == len(manifest["trajectories"]) >= 50


def test_every_locked_trajectory_file_exists(manifest: dict[str, Any]) -> None:
    missing = [
        e["trajectory_path"]
        for e in manifest["trajectories"]
        if not (REPO_ROOT / e["trajectory_path"]).exists()
    ]
    assert not missing, "locked channel trajectories missing from disk:\n  " + "\n  ".join(missing)


def test_overlay_coverage_is_complete_and_not_stale(manifest: dict[str, Any]) -> None:
    """Every task with a v9/v10/v11 overlay entry must be in the locked set.

    Recomputed LIVE, so adding/removing an overlay entry without re-freezing
    (the silent-drift risk) turns this red.
    """
    live = _overlay_task_ids()
    assert manifest["overlay_tasks_total"] == len(live), (
        f"overlay set changed ({len(live)} tasks live vs {manifest['overlay_tasks_total']} "
        f"in manifest) — re-freeze: python scripts/freeze_goldens_channels.py"
    )
    assert manifest["overlay_tasks_uncovered"] == [], manifest["overlay_tasks_uncovered"]
    locked = {e["task_id"] for e in manifest["trajectories"]}
    uncovered = sorted(live - locked)
    assert not uncovered, (
        f"{len(uncovered)} overlay task(s) not in the lock set — re-freeze. {uncovered}"
    )


def test_all_channels_replay_bit_identical(
    manifest: dict[str, Any], tasks_by_id: dict[str, Task]
) -> None:
    """Every locked trajectory replays to the frozen verdict at v9/v10/v11."""
    failures: list[str] = []
    for entry in manifest["trajectories"]:
        task = tasks_by_id[entry["task_id"]]
        traj = json.loads((REPO_ROOT / entry["trajectory_path"]).read_text(encoding="utf-8"))
        for channel in manifest["channels"]:
            result = replay_from_trajectory(traj, task, rubric_channel=channel)
            cr = [{"id": c.criterion_id, "satisfied": c.satisfied} for c in result.criteria_results]
            obs_hash = _canonical_hash(cr)
            exp = entry[channel]
            mism: list[str] = []
            if abs(result.reward - exp["reward"]) > _REWARD_TOL:
                mism.append(f"reward {result.reward!r} vs {exp['reward']!r}")
            if result.passed != exp["passed"]:
                mism.append(f"passed {result.passed!r} vs {exp['passed']!r}")
            if result.safety_gate_passed != exp["safety_gate"]:
                mism.append(f"safety {result.safety_gate_passed!r} vs {exp['safety_gate']!r}")
            if obs_hash != exp["criteria_results_hash"]:
                mism.append(f"hash {obs_hash[:12]} vs {exp['criteria_results_hash'][:12]}")
            if mism:
                name = Path(entry["trajectory_path"]).name
                failures.append(f"{entry['task_id']} [{channel}] ({name}): " + "; ".join(mism))

    if failures:
        pytest.fail(
            f"{len(failures)} overlay-channel verdict(s) drifted from the lock. If deliberate, "
            f"re-freeze with `python scripts/freeze_goldens_channels.py` and review the manifest "
            f"diff (the re-grade record); do NOT regenerate just to go green.\n\n"
            + "\n".join(failures)
        )
