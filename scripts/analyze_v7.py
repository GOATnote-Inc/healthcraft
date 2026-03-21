#!/usr/bin/env python3
"""Analysis pipeline for HEALTHCRAFT evaluation results.

Reads trajectory JSONs directly from results directories and produces:
- Per-category breakdown (tasks, pass rate, avg reward, safety failures)
- Pass^k metrics (k=3) for deployment reliability
- Hardest tasks (both models fail all trials)
- Model divergence (one passes, other fails)
- Corecraft Table 1 parity comparison
- Optional delta analysis (--compare)

Usage:
    # Basic analysis
    python scripts/analyze_v7.py \
        --results results/pilot-v8-claude-opus results/pilot-v8-gpt54

    # With previous version comparison
    python scripts/analyze_v7.py \
        --results results/pilot-v8-claude-opus results/pilot-v8-gpt54 \
        --compare results/pilot-v7-claude-opus results/pilot-v7-gpt54

    # Output to file
    python scripts/analyze_v7.py \
        --results results/pilot-v8-claude-opus results/pilot-v8-gpt54 \
        --output docs/V8_ANALYSIS.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# ── Trajectory loading ───────────────────────────────────────────────


def load_trajectories(results_dir: Path) -> list[dict]:
    """Load all trajectory JSONs from a results directory.

    Trajectories are stored in category subdirectories:
        results_dir/trajectories/{category}/{task_id}_{model}_{seed}_t{trial}.json

    Returns a list of dicts with trajectory data plus inferred 'category' and 'trial' fields.
    """
    traj_dir = results_dir / "trajectories"
    if not traj_dir.exists():
        return []

    trajectories = []
    for cat_dir in sorted(traj_dir.iterdir()):
        if not cat_dir.is_dir():
            continue
        category = cat_dir.name
        for path in sorted(cat_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                print(f"Warning: skipping {path}: {e}", file=sys.stderr)
                continue
            data["category"] = category
            # Extract trial number from filename: {task_id}_{model}_{seed}_t{trial}.json
            stem = path.stem
            if "_t" in stem:
                try:
                    data["trial"] = int(stem.rsplit("_t", 1)[1])
                except (ValueError, IndexError):
                    data["trial"] = 1
            else:
                data["trial"] = 1
            trajectories.append(data)

    return trajectories


def get_model_name(results_dir: Path, trajectories: list[dict]) -> str:
    """Infer model name from summary.json or first trajectory."""
    summary_path = results_dir / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return summary.get("agent_model", results_dir.name)
    if trajectories:
        return trajectories[0].get("model", results_dir.name)
    return results_dir.name


# ── Metrics ──────────────────────────────────────────────────────────


def analyze_model(trajectories: list[dict], model_name: str, k: int = 3) -> dict:
    """Compute all metrics for a single model's results."""
    if not trajectories:
        return {"model": model_name, "error": "No data", "per_category": [], "per_task": {}}

    # Group by task
    by_task: dict[str, list[dict]] = defaultdict(list)
    for t in trajectories:
        by_task[t["task_id"]].append(t)

    # Group by category
    by_category: dict[str, list[dict]] = defaultdict(list)
    for t in trajectories:
        by_category[t["category"]].append(t)

    total_trials = len(trajectories)
    total_tasks = len(by_task)
    total_passed = sum(1 for t in trajectories if t.get("passed", False))
    total_safety_fail = sum(1 for t in trajectories if not t.get("safety_gate_passed", True))
    rewards = [t.get("reward", 0.0) for t in trajectories]
    avg_reward = sum(rewards) / len(rewards) if rewards else 0.0
    error_count = sum(1 for t in trajectories if t.get("error"))

    # Per-task Pass@1, Pass@k, Pass^k
    task_metrics = {}
    for tid in sorted(by_task):
        trials = by_task[tid]
        passes = [t.get("passed", False) for t in trials]
        t_rewards = [t.get("reward", 0.0) for t in trials]
        safety_fails = sum(1 for t in trials if not t.get("safety_gate_passed", True))
        errors = sum(1 for t in trials if t.get("error"))

        n = len(passes)
        pass_at_1 = sum(passes) / n if n else 0.0
        pass_at_k = 1.0 if any(passes[:k]) else 0.0
        pass_k = 1.0 if all(passes[:k]) else 0.0

        task_metrics[tid] = {
            "task_id": tid,
            "category": trials[0]["category"],
            "trials": n,
            "pass_at_1": pass_at_1,
            f"pass_at_{k}": pass_at_k,
            f"pass_{k}": pass_k,
            "avg_reward": sum(t_rewards) / n if n else 0.0,
            "min_reward": min(t_rewards) if t_rewards else 0.0,
            "max_reward": max(t_rewards) if t_rewards else 0.0,
            "safety_failures": safety_fails,
            "errors": errors,
            "all_passed": all(passes),
            "all_failed": not any(passes),
        }

    # Aggregate Pass@1, Pass@k, Pass^k across tasks
    pass_at_1_vals = [m["pass_at_1"] for m in task_metrics.values()]
    pass_at_k_vals = [m[f"pass_at_{k}"] for m in task_metrics.values()]
    pass_k_vals = [m[f"pass_{k}"] for m in task_metrics.values()]

    agg_pass_at_1 = sum(pass_at_1_vals) / len(pass_at_1_vals) if pass_at_1_vals else 0.0
    agg_pass_at_k = sum(pass_at_k_vals) / len(pass_at_k_vals) if pass_at_k_vals else 0.0
    agg_pass_k = sum(pass_k_vals) / len(pass_k_vals) if pass_k_vals else 0.0

    # Per-category summary
    cat_details = []
    for cat in sorted(by_category):
        trials = by_category[cat]
        c_rewards = [t.get("reward", 0.0) for t in trials]
        c_passed = sum(1 for t in trials if t.get("passed", False))
        c_safety = sum(1 for t in trials if not t.get("safety_gate_passed", True))
        c_tasks = sorted(set(t["task_id"] for t in trials))
        cat_details.append(
            {
                "category": cat,
                "tasks": len(c_tasks),
                "trials": len(trials),
                "passed": c_passed,
                "pass_rate": c_passed / len(trials) if trials else 0.0,
                "safety_failures": c_safety,
                "safety_rate": c_safety / len(trials) if trials else 0.0,
                "avg_reward": sum(c_rewards) / len(c_rewards) if c_rewards else 0.0,
            }
        )

    return {
        "model": model_name,
        "k": k,
        "total_tasks": total_tasks,
        "total_trials": total_trials,
        "total_passed": total_passed,
        "pass_rate": total_passed / total_trials if total_trials else 0.0,
        "pass_at_1": agg_pass_at_1,
        f"pass_at_{k}": agg_pass_at_k,
        f"pass_{k}": agg_pass_k,
        "avg_reward": avg_reward,
        "safety_failures": total_safety_fail,
        "safety_rate": total_safety_fail / total_trials if total_trials else 0.0,
        "errors": error_count,
        "per_category": cat_details,
        "per_task": task_metrics,
    }


# ── Delta analysis ───────────────────────────────────────────────────


def compute_delta(v7: dict, v6: dict) -> list[dict]:
    """Compute per-task reward delta between V7 and V6 for the same model.

    Returns list of dicts sorted by absolute delta (largest first).
    """
    deltas = []
    v6_tasks = v6.get("per_task", {})
    v7_tasks = v7.get("per_task", {})

    all_task_ids = sorted(set(v6_tasks) | set(v7_tasks))
    for tid in all_task_ids:
        v6_t = v6_tasks.get(tid, {})
        v7_t = v7_tasks.get(tid, {})
        v6_reward = v6_t.get("avg_reward", 0.0)
        v7_reward = v7_t.get("avg_reward", 0.0)
        delta = v7_reward - v6_reward
        deltas.append(
            {
                "task_id": tid,
                "category": v7_t.get("category", v6_t.get("category", "unknown")),
                "v6_reward": v6_reward,
                "v7_reward": v7_reward,
                "delta": delta,
                "v6_passed": v6_t.get("pass_at_1", 0.0),
                "v7_passed": v7_t.get("pass_at_1", 0.0),
            }
        )

    deltas.sort(key=lambda d: abs(d["delta"]), reverse=True)
    return deltas


# ── Report generation ────────────────────────────────────────────────


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _f3(v: float) -> str:
    return f"{v:.3f}"


def generate_report(
    analyses: list[dict],
    compare_analyses: list[dict] | None = None,
) -> str:
    """Generate the full analysis report as text."""
    lines: list[str] = []
    k = analyses[0].get("k", 3) if analyses else 3

    # ── Header ──
    lines.append("=" * 70)
    lines.append("  HEALTHCRAFT Evaluation Analysis")
    lines.append("=" * 70)
    lines.append("")

    # ── Summary table ──
    lines.append("Summary:")
    lines.append("")
    header = f"  {'Metric':<25}"
    for a in analyses:
        header += f" {a['model']:>20}"
    lines.append(header)
    lines.append("  " + "-" * (25 + 21 * len(analyses)))

    summary_rows = [
        ("Tasks", lambda a: str(a["total_tasks"])),
        ("Trials", lambda a: str(a["total_trials"])),
        ("Pass Rate", lambda a: _pct(a["pass_rate"])),
        ("Pass@1", lambda a: _pct(a["pass_at_1"])),
        (f"Pass@{k}", lambda a: _pct(a.get(f"pass_at_{k}", 0))),
        (f"Pass^{k}", lambda a: _pct(a.get(f"pass_{k}", 0))),
        ("Avg Reward", lambda a: _f3(a["avg_reward"])),
        ("Safety Failures", lambda a: f"{a['safety_failures']} ({_pct(a['safety_rate'])})"),
        ("Errors", lambda a: str(a.get("errors", 0))),
    ]

    for label, fn in summary_rows:
        row = f"  {label:<25}"
        for a in analyses:
            row += f" {fn(a):>20}"
        lines.append(row)

    lines.append("")

    # ── Category breakdown ──
    lines.append("Category Breakdown:")
    lines.append("")
    for a in analyses:
        lines.append(f"  {a['model']}:")
        lines.append(
            f"    {'Category':<30} {'Tasks':>5} | {'Pass':>7} | {'Avg Reward':>10} | {'Safety':>7}"
        )
        lines.append("    " + "-" * 68)
        for cat in a["per_category"]:
            lines.append(
                f"    {cat['category']:<30} {cat['tasks']:>5} | "
                f"{_pct(cat['pass_rate']):>7} | "
                f"{_f3(cat['avg_reward']):>10} | "
                f"{_pct(cat['safety_rate']):>7}"
            )
        lines.append("")

    # ── Pass^k metrics ──
    lines.append(f"Pass^k Metrics (k={k}):")
    lines.append("")
    for a in analyses:
        lines.append(
            f"  {a['model']}: "
            f"Pass@1={_pct(a['pass_at_1'])}, "
            f"Pass@{k}={_pct(a.get(f'pass_at_{k}', 0))}, "
            f"Pass^{k}={_pct(a.get(f'pass_{k}', 0))}"
        )
    lines.append("")

    # ── Hardest tasks ──
    if len(analyses) >= 2:
        a1, a2 = analyses[0], analyses[1]
        both_fail = []
        for tid in sorted(set(a1["per_task"]) & set(a2["per_task"])):
            t1 = a1["per_task"][tid]
            t2 = a2["per_task"][tid]
            if t1["all_failed"] and t2["all_failed"]:
                avg_r = (t1["avg_reward"] + t2["avg_reward"]) / 2
                both_fail.append((tid, t1["category"], avg_r))

        if both_fail:
            lines.append(f"Hardest Tasks (both models fail all {k} trials):")
            lines.append("")
            lines.append(f"  {'Task':<12} {'Category':<30} {'Avg Reward':>10}")
            lines.append("  " + "-" * 55)
            for tid, cat, avg_r in sorted(both_fail, key=lambda x: x[2]):
                lines.append(f"  {tid:<12} {cat:<30} {_f3(avg_r):>10}")
            lines.append(f"  Total: {len(both_fail)} tasks")
            lines.append("")

        # ── Model divergence ──
        divergent = []
        for tid in sorted(set(a1["per_task"]) & set(a2["per_task"])):
            t1 = a1["per_task"][tid]
            t2 = a2["per_task"][tid]
            # One model passes majority, other fails majority
            if (t1["pass_at_1"] >= 0.5) != (t2["pass_at_1"] >= 0.5):
                divergent.append(
                    {
                        "task_id": tid,
                        "category": t1["category"],
                        f"{a1['model']}_reward": t1["avg_reward"],
                        f"{a2['model']}_reward": t2["avg_reward"],
                        "delta": t1["avg_reward"] - t2["avg_reward"],
                    }
                )

        if divergent:
            divergent.sort(key=lambda d: abs(d["delta"]), reverse=True)
            lines.append("Model Divergence (one passes majority, other fails):")
            lines.append("")
            m1, m2 = a1["model"], a2["model"]
            lines.append(
                f"  {'Task':<12} {'Category':<25} {m1[:15]:>15} {m2[:15]:>15} {'Delta':>8}"
            )
            lines.append("  " + "-" * 78)
            for d in divergent:
                lines.append(
                    f"  {d['task_id']:<12} {d['category']:<25} "
                    f"{_f3(d[f'{m1}_reward']):>15} "
                    f"{_f3(d[f'{m2}_reward']):>15} "
                    f"{d['delta']:>+8.3f}"
                )
            lines.append(f"  Total: {len(divergent)} tasks")
            lines.append("")

    # ── Corecraft parity table ──
    lines.append("Corecraft Table 1 Parity:")
    lines.append("")
    lines.append(f"  {'Model':<40} {'Pass@1':>8} {'Pass@3':>8} {'Pass^3':>8} {'Avg Reward':>11}")
    lines.append("  " + "-" * 78)
    for a in analyses:
        lines.append(
            f"  {a['model'] + ' (HEALTHCRAFT)':<40} "
            f"{_pct(a['pass_at_1']):>8} "
            f"{_pct(a.get(f'pass_at_{k}', 0)):>8} "
            f"{_pct(a.get(f'pass_{k}', 0)):>8} "
            f"{_f3(a['avg_reward']):>11}"
        )
    # Corecraft reference rows
    corecraft = [
        ("Claude Opus 4.6 (Corecraft, adaptive)", "30.8%", "—", "—", "—"),
        ("GPT-5.2 (Corecraft, high reasoning)", "29.7%", "—", "—", "—"),
        ("Gemini 3.1 Pro (Corecraft)", "27.2%", "—", "—", "—"),
    ]
    for name, p1, p3, pk, ar in corecraft:
        lines.append(f"  {name:<40} {p1:>8} {p3:>8} {pk:>8} {ar:>11}")
    lines.append("")

    # ── V6→V7 delta analysis ──
    if compare_analyses:
        lines.append("=" * 70)
        lines.append("  Previous -> Current Delta Analysis")
        lines.append("=" * 70)
        lines.append("")

        # Match V7 to V6 by model name
        v6_by_model = {a["model"]: a for a in compare_analyses}
        for v7 in analyses:
            model = v7["model"]
            v6 = v6_by_model.get(model)
            if not v6:
                lines.append(f"  {model}: no V6 comparison data")
                continue

            deltas = compute_delta(v7, v6)
            if not deltas:
                continue

            lines.append(f"  {model} (current vs previous):")
            lines.append("")

            # Summary
            improved = [d for d in deltas if d["delta"] > 0.01]
            degraded = [d for d in deltas if d["delta"] < -0.01]
            unchanged = [d for d in deltas if abs(d["delta"]) <= 0.01]
            lines.append(f"    Improved: {len(improved)} tasks")
            lines.append(f"    Degraded: {len(degraded)} tasks")
            lines.append(f"    Unchanged: {len(unchanged)} tasks")
            avg_delta = sum(d["delta"] for d in deltas) / len(deltas) if deltas else 0
            lines.append(f"    Mean reward delta: {avg_delta:+.3f}")
            lines.append("")

            # Top changes
            if improved:
                lines.append("    Largest improvements:")
                lines.append(
                    f"      {'Task':<12} {'Category':<25} {'Prev':>7} {'Curr':>7} {'Delta':>8}"
                )
                for d in improved[:15]:
                    lines.append(
                        f"      {d['task_id']:<12} {d['category']:<25} "
                        f"{_f3(d['v6_reward']):>7} {_f3(d['v7_reward']):>7} "
                        f"{d['delta']:>+8.3f}"
                    )
                lines.append("")

            if degraded:
                lines.append("    Largest degradations:")
                lines.append(
                    f"      {'Task':<12} {'Category':<25} {'Prev':>7} {'Curr':>7} {'Delta':>8}"
                )
                for d in degraded[:15]:
                    lines.append(
                        f"      {d['task_id']:<12} {d['category']:<25} "
                        f"{_f3(d['v6_reward']):>7} {_f3(d['v7_reward']):>7} "
                        f"{d['delta']:>+8.3f}"
                    )
                lines.append("")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HEALTHCRAFT evaluation analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--results",
        "-r",
        nargs="+",
        required=True,
        help="Results directories to analyze",
    )
    parser.add_argument(
        "--compare",
        "-c",
        nargs="+",
        default=None,
        help="Previous version results directories for delta comparison",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write report to file (otherwise stdout)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also write JSON analysis alongside report",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=3,
        help="Trial count for Pass^k computation (default: 3)",
    )
    args = parser.parse_args()

    # Load V7 results
    analyses = []
    for d in args.results:
        results_dir = Path(d)
        if not results_dir.exists():
            print(f"Warning: {d} does not exist, skipping", file=sys.stderr)
            continue
        trajectories = load_trajectories(results_dir)
        if not trajectories:
            print(f"Warning: no trajectories in {d}, skipping", file=sys.stderr)
            continue
        model_name = get_model_name(results_dir, trajectories)
        analysis = analyze_model(trajectories, model_name, k=args.k)
        analyses.append(analysis)

    if not analyses:
        print("No results to analyze", file=sys.stderr)
        sys.exit(1)

    # Load V6 comparison results (optional)
    compare_analyses = None
    if args.compare:
        compare_analyses = []
        for d in args.compare:
            results_dir = Path(d)
            if not results_dir.exists():
                print(f"Warning: compare dir {d} does not exist, skipping", file=sys.stderr)
                continue
            trajectories = load_trajectories(results_dir)
            if not trajectories:
                print(f"Warning: no trajectories in compare dir {d}, skipping", file=sys.stderr)
                continue
            model_name = get_model_name(results_dir, trajectories)
            analysis = analyze_model(trajectories, model_name, k=1)  # V6 has 1 trial
            compare_analyses.append(analysis)

    report = generate_report(analyses, compare_analyses)
    print(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"\nReport written to {output_path}", file=sys.stderr)

    if args.json:
        if args.output:
            json_path = Path(args.output).with_suffix(".json")
        else:
            json_path = Path("analysis.json")
        # Convert per_task dict to list for JSON serialization
        json_data = []
        for a in analyses:
            a_copy = dict(a)
            a_copy["per_task"] = list(a_copy["per_task"].values())
            json_data.append(a_copy)
        json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
        print(f"JSON written to {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
