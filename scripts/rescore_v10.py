#!/usr/bin/env python3
"""Offline re-scorer: replay trajectories with the v10 deterministic overlay.

Promotes 95 negation criteria (44 from v9 + 51 new in v10) from llm_judge
verification to world_state verification by rewriting each criterion's
check expression, then re-grades against the reconstructed audit log.

This is the WSA-4 step: measure the impact of promoting 51 additional
"did NOT <action>" criteria to deterministic verification before running
a full V10 pilot. If the promoted criteria flip judge PASSes to
world_state FAILs (or vice-versa), that's exactly the signal we want —
it surfaces safety-critical errors the judge missed or validated falsely.

Usage:
    python scripts/rescore_v10.py \\
        --results results/pilot-v9-gemini-pro \\
                  results/pilot-v8-claude-opus \\
                  results/pilot-v8-gpt54 \\
        --channel v10

    # Compare v8 -> v9 (baseline sanity check)
    python scripts/rescore_v10.py \\
        --results results/pilot-v8-claude-opus \\
        --channel v9

Outputs:
  - Per-category summary: mean reward, pass rate, safety gate pass rate.
  - Per-criterion flip count: how many trajectories changed for each
    overlay criterion (split by old_sat -> new_sat direction).
  - JSON summary to results/rescore-v10/<channel>/summary.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from healthcraft.tasks.evaluator import replay_from_trajectory  # noqa: E402
from healthcraft.tasks.loader import load_tasks  # noqa: E402

_TASKS_DIR = _PROJECT_ROOT / "configs" / "tasks"
_OUT_DIR = _PROJECT_ROOT / "results" / "rescore-v10"


def _collect_trajectories(results_dirs: list[Path]) -> list[tuple[Path, dict]]:
    """Load every trajectory JSON under results_dirs/trajectories/*/."""
    pairs: list[tuple[Path, dict]] = []
    for rd in results_dirs:
        tdir = rd / "trajectories"
        if not tdir.exists():
            print(f"[warn] no trajectories dir under {rd}", file=sys.stderr)
            continue
        for path in sorted(tdir.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                print(f"[warn] skipping {path}: {e}", file=sys.stderr)
                continue
            if data.get("error"):
                continue
            pairs.append((path, data))
    return pairs


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--results", "-r", nargs="+", required=True, help="Pilot trajectory dirs to replay"
    )
    p.add_argument(
        "--channel",
        "-c",
        default="v10",
        choices=["v9", "v10"],
        help="Overlay channel (default: v10)",
    )
    p.add_argument(
        "--out", type=Path, default=None, help="Output dir (default: results/rescore-<channel>)"
    )
    p.add_argument("--max-trajectories", type=int, default=None, help="Cap for quick smoke runs")
    args = p.parse_args()

    out_dir = args.out or (_OUT_DIR.parent / f"rescore-{args.channel}")
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = load_tasks(_TASKS_DIR)
    task_map = {t.id: t for t in tasks}

    results_dirs = [Path(r) for r in args.results]
    trajs = _collect_trajectories(results_dirs)
    if args.max_trajectories:
        trajs = trajs[: args.max_trajectories]

    print(f"Replaying {len(trajs)} trajectories with channel={args.channel}")

    reward_delta_by_cat: dict[str, list[float]] = defaultdict(list)
    pass_flip_by_cat: dict[str, Counter] = defaultdict(Counter)
    safety_flip_by_cat: dict[str, Counter] = defaultdict(Counter)
    criterion_flips: dict[str, Counter] = defaultdict(Counter)

    mean_old_by_cat: dict[str, list[float]] = defaultdict(list)
    mean_new_by_cat: dict[str, list[float]] = defaultdict(list)

    unknown_task: Counter[str] = Counter()
    processed = 0
    for path, traj in trajs:
        task_id = traj.get("task_id", "")
        task = task_map.get(task_id)
        if task is None:
            unknown_task[task_id] += 1
            continue
        category = task.category

        try:
            new_res = replay_from_trajectory(traj, task, rubric_channel=args.channel)
        except Exception as e:
            print(f"[warn] replay failed {path}: {e}", file=sys.stderr)
            continue

        old_reward = float(traj.get("reward", 0.0))
        old_passed = bool(traj.get("passed", False))
        old_safety = bool(traj.get("safety_gate_passed", True))
        old_crit = {cr["id"]: bool(cr["satisfied"]) for cr in traj.get("criteria_results", [])}

        reward_delta_by_cat[category].append(new_res.reward - old_reward)
        mean_old_by_cat[category].append(old_reward)
        mean_new_by_cat[category].append(new_res.reward)

        pass_key = (old_passed, new_res.passed)
        pass_flip_by_cat[category][pass_key] += 1
        safety_key = (old_safety, new_res.safety_gate_passed)
        safety_flip_by_cat[category][safety_key] += 1

        for cr in new_res.criteria_results:
            old_sat = old_crit.get(cr.criterion_id)
            if old_sat is None or old_sat == cr.satisfied:
                continue
            criterion_flips[cr.criterion_id][(old_sat, cr.satisfied)] += 1

        processed += 1

    if unknown_task:
        print(
            f"[warn] {sum(unknown_task.values())} trajectories had unknown task_ids "
            f"({len(unknown_task)} distinct); skipped"
        )

    print(f"\nProcessed: {processed}")
    print("\n=== Per-category reward ===")
    print(f"{'category':<28} {'n':>5} {'old':>8} {'new':>8} {'delta':>8}")
    for cat in sorted(mean_old_by_cat):
        n = len(mean_old_by_cat[cat])
        old_m = sum(mean_old_by_cat[cat]) / n if n else 0.0
        new_m = sum(mean_new_by_cat[cat]) / n if n else 0.0
        print(f"{cat:<28} {n:>5} {old_m:>8.3f} {new_m:>8.3f} {new_m - old_m:>+8.3f}")

    print("\n=== Pass flip matrix (old, new) -> count ===")
    for cat in sorted(pass_flip_by_cat):
        print(f"  {cat}:")
        for (a, b), c in sorted(pass_flip_by_cat[cat].items()):
            print(f"    {a!s:>5} -> {b!s:<5}: {c}")

    print("\n=== Safety-gate flip matrix (old, new) -> count ===")
    for cat in sorted(safety_flip_by_cat):
        print(f"  {cat}:")
        for (a, b), c in sorted(safety_flip_by_cat[cat].items()):
            print(f"    {a!s:>5} -> {b!s:<5}: {c}")

    print("\n=== Top criterion flips ===")
    ranked = sorted(criterion_flips.items(), key=lambda kv: -sum(kv[1].values()))[:30]
    for crit_id, cnts in ranked:
        direction = ", ".join(f"{a}->{b}:{c}" for (a, b), c in sorted(cnts.items()))
        print(f"  {crit_id}: {direction}")

    summary = {
        "channel": args.channel,
        "results_dirs": [str(r) for r in results_dirs],
        "processed": processed,
        "per_category": {
            cat: {
                "n": len(mean_old_by_cat[cat]),
                "old_mean_reward": sum(mean_old_by_cat[cat]) / len(mean_old_by_cat[cat]),
                "new_mean_reward": sum(mean_new_by_cat[cat]) / len(mean_new_by_cat[cat]),
                "pass_flips": {f"{a}->{b}": c for (a, b), c in pass_flip_by_cat[cat].items()},
                "safety_flips": {f"{a}->{b}": c for (a, b), c in safety_flip_by_cat[cat].items()},
            }
            for cat in mean_old_by_cat
        },
        "criterion_flips": {
            cid: {f"{a}->{b}": c for (a, b), c in cnts.items()}
            for cid, cnts in criterion_flips.items()
        },
    }
    out_path = out_dir / "summary.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nWrote summary: {out_path}")


if __name__ == "__main__":
    main()
