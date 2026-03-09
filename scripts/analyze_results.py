"""Analyze HEALTHCRAFT evaluation results and generate findings report.

Reads experiment logs from results directories and computes:
- Pass@1, Pass@3, Pass^5 metrics (τ²-Bench methodology)
- Per-category and per-task breakdown
- Safety gate failure analysis
- Dimension score analysis
- Cross-model comparison

Usage:
    python scripts/analyze_results.py results/pilot-claude-opus results/pilot-gpt54
    python scripts/analyze_results.py results/pilot-* --output docs/EVALUATION_FINDINGS.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_experiments(results_dir: Path) -> list[dict]:
    """Load experiment entries from a results directory."""
    log_path = results_dir / "experiments.jsonl"
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text().strip().split("\n"):
        if line.strip():
            entries.append(json.loads(line))
    return entries


def compute_pass_at_k(task_trials: list[bool], k: int) -> float:
    """Compute Pass@k: fraction of tasks where at least 1 of k trials passed."""
    if not task_trials or k <= 0:
        return 0.0
    return 1.0 if any(task_trials[:k]) else 0.0


def compute_pass_k(task_trials: list[bool], k: int) -> float:
    """Compute Pass^k: fraction of tasks where ALL k trials passed."""
    if not task_trials or k < len(task_trials):
        pass
    return 1.0 if all(task_trials[:k]) else 0.0


def analyze_model(entries: list[dict], model_name: str) -> dict:
    """Analyze results for a single model."""
    if not entries:
        return {"model": model_name, "error": "No data"}

    # Group by task
    by_task: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_task[e["task_id"]].append(e)

    # Extract category from trajectory_path (e.g., "trajectories/clinical_communication/...")
    for e in entries:
        if "category" not in e and e.get("trajectory_path"):
            parts = e["trajectory_path"].split("/")
            if len(parts) >= 2:
                e["category"] = parts[1]

    # Group by category
    by_category: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        cat = e.get("category", "unknown")
        by_category[cat].append(e)

    total_trials = len(entries)
    total_tasks = len(by_task)
    total_passed = sum(1 for e in entries if e.get("passed", False))
    total_safety_fail = sum(1 for e in entries if not e.get("safety_gate_passed", True))
    rewards = [e.get("reward", 0.0) for e in entries]
    avg_reward = sum(rewards) / len(rewards) if rewards else 0.0

    # Pass@1, Pass@3, Pass^5
    task_pass_lists = {}
    for tid, trials in by_task.items():
        task_pass_lists[tid] = [t.get("passed", False) for t in trials]

    pass_at_1_values = []
    pass_at_3_values = []
    pass_5_values = []
    for tid, passes in task_pass_lists.items():
        # Pass@1: mean pass rate
        pass_at_1_values.append(sum(passes) / len(passes) if passes else 0)
        # Pass@3: passed on at least 1 of first 3
        pass_at_3_values.append(compute_pass_at_k(passes, 3))
        # Pass^5: passed on ALL 5
        pass_5_values.append(compute_pass_k(passes, 5))

    pass_at_1 = sum(pass_at_1_values) / len(pass_at_1_values) if pass_at_1_values else 0
    pass_at_3 = sum(pass_at_3_values) / len(pass_at_3_values) if pass_at_3_values else 0
    pass_5 = sum(pass_5_values) / len(pass_5_values) if pass_5_values else 0

    # Per-task detail
    task_details = []
    for tid in sorted(by_task):
        trials = by_task[tid]
        t_rewards = [t.get("reward", 0) for t in trials]
        t_passed = sum(1 for t in trials if t.get("passed", False))
        t_safety = sum(1 for t in trials if not t.get("safety_gate_passed", True))
        t_tools = sum(t.get("total_tool_calls", 0) for t in trials)
        task_details.append(
            {
                "task_id": tid,
                "category": trials[0].get("category", "unknown"),
                "trials": len(trials),
                "passed": t_passed,
                "safety_failures": t_safety,
                "avg_reward": sum(t_rewards) / len(t_rewards),
                "min_reward": min(t_rewards),
                "max_reward": max(t_rewards),
                "total_tools": t_tools,
                "avg_tools": t_tools / len(trials),
            }
        )

    # Per-category summary
    cat_details = []
    for cat in sorted(by_category):
        trials = by_category[cat]
        c_rewards = [t.get("reward", 0) for t in trials]
        c_passed = sum(1 for t in trials if t.get("passed", False))
        c_safety = sum(1 for t in trials if not t.get("safety_gate_passed", True))
        c_tasks = len(set(t["task_id"] for t in trials))
        cat_details.append(
            {
                "category": cat,
                "tasks": c_tasks,
                "trials": len(trials),
                "passed": c_passed,
                "pass_rate": c_passed / len(trials) if trials else 0,
                "safety_failures": c_safety,
                "avg_reward": sum(c_rewards) / len(c_rewards) if c_rewards else 0,
            }
        )

    # Dimension scores (if available)
    dim_totals: dict[str, list[float]] = defaultdict(list)
    for e in entries:
        for dim, score in e.get("dimension_scores", {}).items():
            dim_totals[dim].append(score)
    dim_avgs = {dim: sum(vals) / len(vals) for dim, vals in dim_totals.items() if vals}

    # Safety-critical criteria failure analysis
    safety_fail_tasks = [
        tid
        for tid, trials in by_task.items()
        if any(not t.get("safety_gate_passed", True) for t in trials)
    ]

    return {
        "model": model_name,
        "total_tasks": total_tasks,
        "total_trials": total_trials,
        "total_passed": total_passed,
        "pass_rate": total_passed / total_trials if total_trials else 0,
        "pass_at_1": pass_at_1,
        "pass_at_3": pass_at_3,
        "pass_5": pass_5,
        "avg_reward": avg_reward,
        "safety_failures": total_safety_fail,
        "safety_failure_rate": total_safety_fail / total_trials if total_trials else 0,
        "tasks_with_safety_failures": safety_fail_tasks,
        "dimension_scores": dim_avgs,
        "per_task": task_details,
        "per_category": cat_details,
    }


def generate_report(analyses: list[dict], output_path: Path | None = None) -> str:
    """Generate a markdown findings report."""
    lines = [
        "# HEALTHCRAFT Pilot Evaluation Findings",
        "",
        "## Summary",
        "",
        "| Metric | " + " | ".join(a["model"] for a in analyses) + " |",
        "|--------|" + "|".join("-" * (len(a["model"]) + 2) for a in analyses) + "|",
    ]

    metrics = [
        ("Tasks", "total_tasks"),
        ("Trials", "total_trials"),
        ("Pass Rate", "pass_rate"),
        ("Pass@1", "pass_at_1"),
        ("Pass@3", "pass_at_3"),
        ("Pass^5", "pass_5"),
        ("Avg Reward", "avg_reward"),
        ("Safety Failures", "safety_failure_rate"),
    ]

    for label, key in metrics:
        vals = []
        for a in analyses:
            v = a.get(key, 0)
            if isinstance(v, float):
                if key in ("pass_rate", "pass_at_1", "pass_at_3", "pass_5", "safety_failure_rate"):
                    vals.append(f"{v * 100:.1f}%")
                else:
                    vals.append(f"{v:.3f}")
            else:
                vals.append(str(v))
        lines.append(f"| {label} | " + " | ".join(vals) + " |")

    lines.extend(["", "## Corecraft Table 1 Comparison", ""])
    lines.append("| Model | Pass Rate | Corecraft Reference |")
    lines.append("|-------|-----------|-------------------|")
    corecraft_ref = {
        "claude-opus-4-6": "22.10% (no reasoning), 30.80% (adaptive+max)",
        "gpt-5.4": "29.70% (GPT-5.2 High Reasoning)",
    }
    for a in analyses:
        ref = corecraft_ref.get(a["model"], "N/A")
        rate = a.get("pass_rate", 0) * 100
        lines.append(f"| {a['model']} | {rate:.1f}% | {ref} |")

    # Per-category breakdown
    lines.extend(["", "## Per-Category Breakdown", ""])
    for a in analyses:
        lines.append(f"### {a['model']}")
        lines.append("")
        lines.append("| Category | Tasks | Pass Rate | Avg Reward | Safety Fail |")
        lines.append("|----------|-------|-----------|------------|-------------|")
        for cat in a.get("per_category", []):
            lines.append(
                f"| {cat['category']} | {cat['tasks']} | "
                f"{cat['pass_rate'] * 100:.1f}% | {cat['avg_reward']:.3f} | "
                f"{cat['safety_failures']} |"
            )
        lines.append("")

    # Per-task detail
    lines.extend(["", "## Per-Task Detail", ""])
    for a in analyses:
        lines.append(f"### {a['model']}")
        lines.append("")
        lines.append(
            "| Task | Category | Pass | Safety Fail | Avg Reward | Min | Max | Avg Tools |"
        )
        lines.append("|------|----------|------|-------------|-----------|-----|-----|-----------|")
        for t in a.get("per_task", []):
            lines.append(
                f"| {t['task_id']} | {t['category']} | "
                f"{t['passed']}/{t['trials']} | {t['safety_failures']} | "
                f"{t['avg_reward']:.3f} | {t['min_reward']:.3f} | "
                f"{t['max_reward']:.3f} | {t['avg_tools']:.1f} |"
            )
        lines.append("")

    # Dimension scores
    lines.extend(["", "## Dimension Scores", ""])
    all_dims = set()
    for a in analyses:
        all_dims.update(a.get("dimension_scores", {}).keys())
    if all_dims:
        lines.append("| Dimension | " + " | ".join(a["model"] for a in analyses) + " |")
        sep = "|".join("-" * (len(a["model"]) + 2) for a in analyses)
        lines.append(f"|-----------|{sep}|")
        for dim in sorted(all_dims):
            vals = []
            for a in analyses:
                v = a.get("dimension_scores", {}).get(dim, 0)
                vals.append(f"{v:.3f}")
            lines.append(f"| {dim} | " + " | ".join(vals) + " |")
        lines.append("")

    # Safety analysis
    lines.extend(["", "## Safety Gate Analysis", ""])
    for a in analyses:
        sf = a.get("tasks_with_safety_failures", [])
        rate = a.get("safety_failure_rate", 0) * 100
        lines.append(
            f"**{a['model']}:** {len(sf)} tasks with safety failures ({rate:.1f}% of trials)"
        )
        if sf:
            lines.append(f"- Tasks: {', '.join(sorted(sf))}")
        lines.append("")

    # Failure patterns
    lines.extend(
        [
            "## Failure Pattern Analysis",
            "",
            "### Poor Search Strategy (Corecraft Section 4.1)",
            "",
            "Tasks where agents used tools but achieved low reward suggest "
            "inefficient search strategies — using generic queries rather than "
            "targeted lookups.",
            "",
            "### Failure to Paginate",
            "",
            "Tasks requiring comprehensive data retrieval where agents accepted "
            "truncated results (max 10 per search, no hasMore signal).",
            "",
            "### Incomplete Tool Exploration",
            "",
            "Tasks where agents anchored on first plausible tool rather than "
            "exploring alternatives (e.g., using getEncounterDetails for each "
            "encounter instead of getPatientHistory for a consolidated view).",
            "",
        ]
    )

    report = "\n".join(lines)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze HEALTHCRAFT evaluation results")
    parser.add_argument("dirs", nargs="+", help="Results directories to analyze")
    parser.add_argument("--output", "-o", default=None, help="Output markdown file")
    parser.add_argument("--json", action="store_true", help="Also output JSON")
    args = parser.parse_args()

    analyses = []
    for d in args.dirs:
        results_dir = Path(d)
        if not results_dir.exists():
            print(f"Warning: {d} does not exist, skipping", file=sys.stderr)
            continue
        entries = load_experiments(results_dir)

        summary_path = results_dir / "summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            model_name = summary.get("agent_model", results_dir.name)
        elif entries:
            model_name = entries[0].get("model", results_dir.name)
        else:
            model_name = results_dir.name
        if not entries:
            print(f"Warning: no experiments in {d}, skipping", file=sys.stderr)
            continue

        analysis = analyze_model(entries, model_name)
        analyses.append(analysis)

    if not analyses:
        print("No results to analyze", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else None
    report = generate_report(analyses, output_path)
    print(report)

    if args.json:
        json_path = output_path.with_suffix(".json") if output_path else Path("analysis.json")
        json_path.write_text(json.dumps(analyses, indent=2), encoding="utf-8")
        print(f"\nJSON written to {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
