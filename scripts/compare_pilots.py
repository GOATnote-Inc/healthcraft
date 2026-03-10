#!/usr/bin/env python3
"""Cross-version pilot comparison for HEALTHCRAFT evaluation.

Compares v2, v3, v4 pilot results and generates findings.

Usage:
    python scripts/compare_pilots.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

PILOTS = {
    "v2-claude": "results/pilot-claude-opus",
    "v3-claude": "results/pilot-v3-claude-opus",
    "v3-gpt": "results/pilot-v3-gpt54",
    "v4-claude": "results/pilot-v4-claude-opus",
    "v4-gpt": "results/pilot-v4-gpt54",
}


def load_pilot(base_dir: str) -> dict[str, list[dict]]:
    """Load all trajectories from a pilot directory, grouped by task."""
    base = Path(base_dir) / "trajectories"
    if not base.exists():
        return {}
    task_data: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(base.rglob("*.json")):
        data = json.loads(f.read_text())
        tid = data.get("task_id", "")
        task_data[tid].append(
            {
                "file": f.name,
                "reward": data.get("reward", 0),
                "tools": data.get("total_tool_calls", 0),
                "safety": data.get("safety_gate_passed", True),
                "passed": data.get("passed", False),
                "criteria": data.get("criteria_results", []),
            }
        )
    return dict(task_data)


def print_task_comparison(all_data: dict[str, dict[str, list[dict]]]) -> None:
    """Print per-task comparison across pilot versions."""
    all_tasks = sorted(set().union(*[d.keys() for d in all_data.values()]))
    pilot_labels = [k for k in PILOTS if k in all_data]

    # Header
    header = f"{'Task':<10}"
    for label in pilot_labels:
        header += f" | {label:>18}"
    print("=" * len(header))
    print(header)
    print("=" * len(header))

    totals: dict[str, dict] = {
        k: {"rewards": [], "tools": [], "safety_fails": 0, "n": 0, "passed": 0}
        for k in pilot_labels
    }

    for tid in all_tasks:
        row = f"{tid:<10}"
        for label in pilot_labels:
            trials = all_data.get(label, {}).get(tid, [])
            if trials:
                avg_r = sum(t["reward"] for t in trials) / len(trials)
                sf = sum(1 for t in trials if not t["safety"])
                row += f" | {avg_r:.3f} n={len(trials):>2}"
                totals[label]["rewards"].append(avg_r)
                totals[label]["tools"].extend(t["tools"] for t in trials)
                totals[label]["safety_fails"] += sf
                totals[label]["n"] += len(trials)
                totals[label]["passed"] += sum(1 for t in trials if t["passed"])
            else:
                row += f" | {'—':>18}"
        print(row)

    print("=" * len(header))

    # Aggregates
    print("\nAGGREGATES:")
    for label in pilot_labels:
        t = totals[label]
        if t["rewards"]:
            avg_r = sum(t["rewards"]) / len(t["rewards"])
            avg_tools = sum(t["tools"]) / len(t["tools"]) if t["tools"] else 0
            sf_rate = t["safety_fails"] / t["n"] if t["n"] else 0
            pass_rate = t["passed"] / t["n"] if t["n"] else 0
            print(
                f"  {label}: avg_reward={avg_r:.3f}, "
                f"pass_rate={pass_rate:.1%}, "
                f"tasks={len(t['rewards'])}, "
                f"trials={t['n']}, "
                f"avg_tools={avg_tools:.0f}, "
                f"safety_fail={sf_rate:.0%}"
            )


def print_v3_v4_deltas(all_data: dict[str, dict[str, list[dict]]]) -> None:
    """Print v3 → v4 deltas for tasks with data in both versions."""
    print("\n\nV3 → V4 DELTAS (judge formatting + entity ordering fixes):")
    print("=" * 70)

    for model in ["claude", "gpt"]:
        v3_key = f"v3-{model}"
        v4_key = f"v4-{model}"
        v3 = all_data.get(v3_key, {})
        v4 = all_data.get(v4_key, {})

        shared_tasks = sorted(set(v3.keys()) & set(v4.keys()))
        if not shared_tasks:
            continue

        print(f"\n  {model.upper()}:")
        total_delta = 0
        count = 0
        for tid in shared_tasks:
            v3_avg = sum(t["reward"] for t in v3[tid]) / len(v3[tid])
            v4_avg = sum(t["reward"] for t in v4[tid]) / len(v4[tid])
            delta = v4_avg - v3_avg
            sign = "+" if delta >= 0 else ""
            marker = " ***" if abs(delta) > 0.1 else ""
            print(f"    {tid}: {v3_avg:.3f} → {v4_avg:.3f} ({sign}{delta:.3f}){marker}")
            total_delta += delta
            count += 1

        if count > 0:
            print(f"    MEAN DELTA: {total_delta / count:+.3f}")


def print_safety_analysis(all_data: dict[str, dict[str, list[dict]]]) -> None:
    """Print safety criterion analysis."""
    print("\n\nSAFETY GATE ANALYSIS:")
    print("=" * 70)

    for label, task_data in sorted(all_data.items()):
        safety_crit_stats: dict[str, dict] = defaultdict(
            lambda: {"pass": 0, "fail": 0}
        )
        for tid, trials in task_data.items():
            for trial in trials:
                for cr in trial["criteria"]:
                    cid = cr["id"]
                    # Only track criteria that caused safety gate failures
                    if cr["satisfied"]:
                        safety_crit_stats[cid]["pass"] += 1
                    else:
                        safety_crit_stats[cid]["fail"] += 1

        # Find criteria with high failure rates
        problem_criteria = []
        for cid, stats in safety_crit_stats.items():
            total = stats["pass"] + stats["fail"]
            if total > 0 and stats["fail"] / total > 0.5:
                problem_criteria.append(
                    (cid, stats["fail"], total, stats["fail"] / total)
                )

        if problem_criteria:
            problem_criteria.sort(key=lambda x: -x[3])
            print(f"\n  {label} — criteria with >50% failure rate:")
            for cid, fails, total, rate in problem_criteria[:10]:
                print(f"    {cid}: {fails}/{total} fail ({rate:.0%})")


def main() -> None:
    all_data = {}
    for label, base_dir in PILOTS.items():
        data = load_pilot(base_dir)
        if data:
            all_data[label] = data

    if not all_data:
        print("No pilot data found.")
        sys.exit(1)

    print_task_comparison(all_data)
    print_v3_v4_deltas(all_data)
    print_safety_analysis(all_data)


if __name__ == "__main__":
    main()
