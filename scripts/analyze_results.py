"""Analyze HEALTHCRAFT evaluation results and generate findings report.

Reads experiment logs from results directories and computes:
- Pass@1, Pass@3, Pass^3 metrics (τ²-Bench methodology)
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

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from healthcraft.llm.checkpoint import (  # noqa: E402
    load_latest_summary,
    selected_experiment_entries,
)
from healthcraft.trajectory import is_unassessed_experiment  # noqa: E402


def load_experiments(results_dir: Path) -> list[dict]:
    """Load each trial's newest attempt, retaining its original log position."""
    log_path = results_dir / "experiments.jsonl"
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text().strip().split("\n"):
        if line.strip():
            entries.append(json.loads(line))
    entries = selected_experiment_entries(entries)
    # Early profile logs did not retain their markers. A flagged run summary
    # must still prevent their compatibility zeros becoming benchmark scores.
    summary = load_latest_summary(results_dir)
    if summary is not None and is_unassessed_experiment(summary):
        entries = [dict(entry, benchmark_comparable=False) for entry in entries]
    return entries


def compute_pass_at_k(task_trials: list[bool], k: int) -> float:
    """Compute Pass@k: fraction of tasks where at least 1 of k trials passed."""
    if not task_trials or k <= 0:
        return 0.0
    return 1.0 if any(task_trials[:k]) else 0.0


def compute_pass_k(task_trials: list[bool], k: int) -> float:
    """Compute Pass^k: fraction of tasks where ALL k trials passed."""
    if not task_trials or k <= 0 or len(task_trials) < k:
        return 0.0
    return 1.0 if all(task_trials[:k]) else 0.0


def analyze_model(
    entries: list[dict], model_name: str, *, scheduled_runs: int | None = None
) -> dict:
    """Analyze results for a single model."""
    if not entries:
        return {"model": model_name, "error": "No data"}

    counts = {
        "scheduled_runs": scheduled_runs,
        # Entries have already selected each trial's latest attempt. These
        # counts include failed starts, not just successful executions.
        "attempted_runs": len(entries),
        "completed_runs": sum(
            entry.get("execution_completed") is True and entry.get("error") is None
            for entry in entries
        ),
        "unknown_completion_runs": sum(
            entry.get("execution_completed") is None and entry.get("error") is None
            for entry in entries
        ),
        "error_runs": sum(entry.get("error") is not None for entry in entries),
        "unassessed_runs": sum(is_unassessed_experiment(entry) for entry in entries),
    }
    if counts["unassessed_runs"]:
        # Do not silently discard unassessed trials and improve the denominator
        # of a mixed cohort. The entire requested cohort remains unscored.
        return {
            "model": model_name,
            "total_tasks": len({entry["task_id"] for entry in entries}),
            "total_trials": len(entries),
            **counts,
            "benchmark_comparable": False,
            "grading_complete": False,
            "benchmark_score": None,
            **dict.fromkeys(
                (
                    "total_passed",
                    "pass_rate",
                    "pass_at_1",
                    "pass_at_3",
                    "pass_5",
                    "avg_reward",
                    "safety_failures",
                    "safety_failure_rate",
                    "safety_failures_excl_errors",
                    "safety_failure_rate_excl_errors",
                )
            ),
            "n_error": counts["error_runs"],
            "tasks_with_safety_failures": [],
            "dimension_scores": {},
            "per_task": [],
            "per_category": [],
        }

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
    # Error trajectories are graded fail-closed and counted in
    # total_safety_fail; surface them separately so infra errors are never
    # silently conflated with model safety failures.
    n_error = sum(1 for e in entries if e.get("error"))
    safety_fail_model_only = sum(
        1 for e in entries if not e.get("safety_gate_passed", True) and not e.get("error")
    )
    rewards = [e.get("reward", 0.0) for e in entries]
    avg_reward = sum(rewards) / len(rewards) if rewards else 0.0

    # Pass@1, Pass@3, Pass^3
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
        # Pass^3: passed on ALL 3 (matches the 3-trial pilot trial count)
        pass_5_values.append(compute_pass_k(passes, 3))

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
        **counts,
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
        "n_error": n_error,
        "safety_failures_excl_errors": safety_fail_model_only,
        "safety_failure_rate_excl_errors": (
            safety_fail_model_only / total_trials if total_trials else 0
        ),
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
        ("Scheduled trials", "scheduled_runs"),
        ("Attempted trials", "attempted_runs"),
        ("Completed trials", "completed_runs"),
        ("Completion unknown", "unknown_completion_runs"),
        ("Execution errors", "error_runs"),
        ("Unassessed trials", "unassessed_runs"),
        ("Pass Rate", "pass_rate"),
        ("Pass@1", "pass_at_1"),
        ("Pass@3", "pass_at_3"),
        ("Pass^3", "pass_5"),
        ("Avg Reward", "avg_reward"),
        ("Safety Failures", "safety_failure_rate"),
    ]

    for label, key in metrics:
        vals = []
        for a in analyses:
            v = a.get(key, 0)
            if v is None:
                vals.append("Unknown" if key == "scheduled_runs" else "Not assessed")
            elif isinstance(v, float):
                if key in ("pass_rate", "pass_at_1", "pass_at_3", "pass_5", "safety_failure_rate"):
                    vals.append(f"{v * 100:.1f}%")
                else:
                    vals.append(f"{v:.3f}")
            else:
                vals.append(str(v))
        lines.append(f"| {label} | " + " | ".join(vals) + " |")

    if any(a.get("benchmark_comparable") is False for a in analyses):
        lines.extend(
            [
                "",
                "Cohorts containing unassessed trials have no benchmark or safety metrics. "
                "All selected attempts, including execution errors, remain in the counts; "
                "no unassessed trials were dropped to improve a score. Completed trials "
                "require recorded execution-completion evidence. Scheduled counts are "
                "unknown when no run plan is available.",
            ]
        )
    analyses = [a for a in analyses if a.get("benchmark_comparable") is not False]
    if not analyses:
        report = "\n".join(lines)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")
        return report

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

        summary = load_latest_summary(results_dir)
        if summary is not None:
            model_name = summary.get("agent_model", results_dir.name)
        elif entries:
            model_name = entries[0].get("model", results_dir.name)
        else:
            model_name = results_dir.name
        if not entries:
            print(f"Warning: no experiments in {d}, skipping", file=sys.stderr)
            continue

        scheduled = None
        if summary is not None:
            scheduled = summary.get("scheduled_runs")
            if scheduled is None:
                tasks, trials = summary.get("total_tasks"), summary.get("trials")
                if type(tasks) is int and type(trials) is int and tasks >= 0 and trials >= 0:
                    scheduled = tasks * trials
        analysis = analyze_model(entries, model_name, scheduled_runs=scheduled)
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
