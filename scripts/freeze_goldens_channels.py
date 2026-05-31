"""Freeze v9/v10/v11 overlay-channel verdicts for the golden trajectories.

Reproducibility lock for the overlay channels (follow-up #2 of the 2026-05-31
grader audit). The V8 lock (``freeze_goldens.py`` + ``test_golden_trajectory_
replay.py``) pins that replay reproduces what V8 wrote to disk. The overlay
channels have NO on-disk baseline — the pilots were V8 runs and v9/v10/v11 are
deterministic re-grades — so this script REPLAYS each golden trajectory at each
overlay channel once and pins the resulting ``(reward, passed, safety_gate,
criteria-hash)``.

The companion test (``test_golden_trajectory_replay_channels.py``) re-replays
and asserts byte-identical, so any later change to an overlay file, ``em_vocab``,
a qualifier map, or the matcher that shifts a v9/v10/v11 verdict turns CI red —
forcing a deliberate, reviewed re-freeze (the manifest diff IS the re-grade
record) instead of the silent drift the audit flagged (the unguarded MW-003
flip). Re-freezing after a deliberate grader change is the intended workflow;
do NOT regenerate to make a red test green without reviewing the diff.

Reads the SAME trajectory set selected by ``freeze_goldens.py`` (from
``index.json``), so the V8 and overlay-channel locks cover an identical set.

Usage:
    python scripts/freeze_goldens_channels.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from healthcraft.llm.orchestrator import _load_overlay
from healthcraft.tasks.evaluator import replay_from_trajectory
from healthcraft.tasks.loader import load_tasks

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "golden_trajectories" / "index.json"
DEFAULT_OUTPUT = REPO_ROOT / "tests" / "fixtures" / "golden_trajectories" / "index_channels.json"
TASK_DIR = REPO_ROOT / "configs" / "tasks"
PILOT_DIRS = (
    REPO_ROOT / "results" / "pilot-v8-claude-opus",
    REPO_ROOT / "results" / "pilot-v8-gpt54",
)
CHANNELS = ("v9", "v10", "v11")


def _task_id_of(criterion_id: str) -> str:
    """`MW-016-C02` -> `MW-016` (criterion ids are `<TASK>-C<NN>`)."""
    return criterion_id.rsplit("-C", 1)[0]


def overlay_task_ids() -> set[str]:
    """Every task whose v9/v10/v11-channel verdict depends on an overlay entry.

    Uses the v11 channel (= v9 + v10 + v11) so the lock covers every promoted
    criterion across all overlay channels.
    """
    return {_task_id_of(cid) for cid in _load_overlay("v11")}


def find_pilot_trajectory(task_id: str, category: str) -> Path | None:
    """First (deterministic) V8 pilot trajectory for a task, claude-opus first."""
    for root in PILOT_DIRS:
        cat_dir = root / "trajectories" / category
        if not cat_dir.is_dir():
            continue
        matches = sorted(cat_dir.glob(f"{task_id}_*.json"))
        if matches:
            return matches[0]
    return None


def criteria_results_hash(criteria_results: list[dict[str, Any]]) -> str:
    """SHA256 over canonical sorted (id, satisfied) tuples.

    Byte-identical to scripts/freeze_goldens.py and the replay tests.
    """
    canonical = sorted((str(c["id"]), bool(c["satisfied"])) for c in criteria_results)
    blob = json.dumps(canonical, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def channel_verdict(trajectory: dict[str, Any], task: Any, channel: str) -> dict[str, Any]:
    result = replay_from_trajectory(trajectory, task, rubric_channel=channel)
    cr = [{"id": c.criterion_id, "satisfied": c.satisfied} for c in result.criteria_results]
    return {
        "reward": result.reward,
        "passed": result.passed,
        "safety_gate": result.safety_gate_passed,
        "criteria_results_hash": criteria_results_hash(cr),
    }


def build_channel_manifest(source: dict[str, Any], tasks_by_id: dict[str, Any]) -> dict[str, Any]:
    """Lock = the 30 stratified goldens UNION one pilot trajectory per
    overlay-promoted task, so every promoted criterion is exercised by >=1
    locked trajectory (a 30-golden-only lock leaves most overlay entries
    unguarded — measured 1-2/30 divergence)."""
    selected: dict[str, dict[str, str]] = {}
    for entry in source["trajectories"]:
        selected[entry["trajectory_path"]] = {
            "task_id": entry["task_id"],
            "category": entry["category"],
            "trajectory_path": entry["trajectory_path"],
            "source": "golden",
        }

    ov_tasks = overlay_task_ids()
    covered = {row["task_id"] for row in selected.values()}
    uncovered: list[str] = []
    for task_id in sorted(ov_tasks):
        if task_id in covered:
            continue
        task = tasks_by_id.get(task_id)
        if task is None:
            uncovered.append(f"{task_id} (no task def)")
            continue
        path = find_pilot_trajectory(task_id, task.category)
        if path is None:
            uncovered.append(f"{task_id} (no pilot trajectory)")
            continue
        rel = str(path.relative_to(REPO_ROOT))
        selected.setdefault(
            rel,
            {
                "task_id": task_id,
                "category": task.category,
                "trajectory_path": rel,
                "source": "overlay-coverage",
            },
        )
        covered.add(task_id)

    trajectories: list[dict[str, Any]] = []
    for row in selected.values():
        task = tasks_by_id[row["task_id"]]
        traj = json.loads((REPO_ROOT / row["trajectory_path"]).read_text(encoding="utf-8"))
        out: dict[str, Any] = dict(row)
        for channel in CHANNELS:
            out[channel] = channel_verdict(traj, task, channel)
        trajectories.append(out)

    trajectories.sort(key=lambda t: (t["category"], t["task_id"], t["trajectory_path"]))
    return {
        "version": 1,
        "source_manifest": str(SOURCE_MANIFEST.relative_to(REPO_ROOT)),
        "channels": list(CHANNELS),
        "n_trajectories": len(trajectories),
        "overlay_tasks_total": len(ov_tasks),
        "overlay_tasks_covered": len(ov_tasks & {t["task_id"] for t in trajectories}),
        "overlay_tasks_uncovered": sorted(uncovered),
        "trajectories": trajectories,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source", type=Path, default=SOURCE_MANIFEST)
    args = parser.parse_args()

    if not args.source.exists():
        print(f"[freeze_channels] source manifest not found: {args.source}")
        print("[freeze_channels] run scripts/freeze_goldens.py first.")
        return 1

    source = json.loads(args.source.read_text(encoding="utf-8"))
    tasks_by_id = {t.id: t for t in load_tasks(TASK_DIR)}
    manifest = build_channel_manifest(source, tasks_by_id)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=False)
        fh.write("\n")

    print(
        f"[freeze_channels] wrote {manifest['n_trajectories']} locked trajectories x {list(CHANNELS)}"
    )
    print(
        f"  overlay-task coverage: {manifest['overlay_tasks_covered']}/"
        f"{manifest['overlay_tasks_total']}"
    )
    for u in manifest["overlay_tasks_uncovered"]:
        print(f"    UNCOVERED: {u}")
    # Divergence from the V8 verdict (replay at v8 on the fly) proves the lock is
    # overlay-sensitive — i.e. it pins something the V8 lock does not.
    for channel in CHANNELS:
        diverged = 0
        for row in manifest["trajectories"]:
            task = tasks_by_id[row["task_id"]]
            traj = json.loads((REPO_ROOT / row["trajectory_path"]).read_text(encoding="utf-8"))
            v8 = channel_verdict(traj, task, "v8")
            if row[channel]["criteria_results_hash"] != v8["criteria_results_hash"]:
                diverged += 1
        print(f"  {channel}: {diverged}/{manifest['n_trajectories']} diverge from V8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
