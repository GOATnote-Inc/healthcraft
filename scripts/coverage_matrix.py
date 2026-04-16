"""Generate a conditions x stratification-axes coverage matrix.

Reads all task YAMLs in configs/tasks/ and optionally the OpenEM condition
corpus to produce a JSON matrix showing which conditions are covered, by
which task categories, at which difficulty levels.

Usage:
  python scripts/coverage_matrix.py --output docs/coverage_matrix.json
  python scripts/coverage_matrix.py --summary   # text summary to stdout
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO / "configs" / "tasks"

# OpenEM condition count (v0.5.1)
OPENEM_TOTAL = 370

# ESI-to-acuity mapping for stratification
LEVEL_TO_ACUITY = {
    1: "novice",
    2: "intermediate",
    3: "advanced",
    4: "expert",
    5: "expert",
}

# Workflow complexity from category
CATEGORY_WORKFLOW = {
    "information_retrieval": "single",
    "clinical_communication": "single",
    "clinical_reasoning": "single",
    "safety_critical_judgment": "single",
    "temporal_reasoning": "multi",
    "multi_step_workflows": "multi",
}


def load_tasks() -> list[dict]:
    """Load all task YAML files."""
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML required. pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    tasks = []
    for path in sorted(glob.glob(str(TASKS_DIR / "**" / "*.yaml"), recursive=True)):
        with open(path) as f:
            task = yaml.safe_load(f)
        task["_path"] = path
        tasks.append(task)
    return tasks


def build_matrix(tasks: list[dict]) -> dict:
    """Build the coverage matrix."""
    # Condition -> list of task summaries
    by_condition: dict[str, list[dict]] = collections.defaultdict(list)
    # Category counts
    by_category: dict[str, int] = collections.Counter()
    # Level distribution
    by_level: dict[int, int] = collections.Counter()
    # Workflow type
    by_workflow: dict[str, int] = collections.Counter()
    # Conditions per category
    conditions_per_category: dict[str, set] = collections.defaultdict(set)
    # Unmapped tasks
    unmapped: list[str] = []

    for task in tasks:
        task_id = task.get("id", "unknown")
        category = task.get("category", "unknown")
        level = task.get("level", 0)
        meta = task.get("metadata", {})
        condition = meta.get("openem_condition", "")

        by_category[category] += 1
        by_level[level] += 1

        workflow = CATEGORY_WORKFLOW.get(category, "unknown")
        by_workflow[workflow] += 1

        if condition:
            by_condition[condition].append(
                {
                    "task_id": task_id,
                    "category": category,
                    "level": level,
                    "confusion_pair": meta.get("confusion_pair", ""),
                }
            )
            conditions_per_category[category].add(condition)
        else:
            unmapped.append(task_id)

    # Covered vs uncovered
    covered_conditions = sorted(by_condition.keys())
    coverage_pct = len(covered_conditions) / OPENEM_TOTAL * 100

    # Level distribution across covered conditions
    level_dist = {}
    for condition, task_list in by_condition.items():
        levels = [t["level"] for t in task_list]
        level_dist[condition] = {
            "min_level": min(levels),
            "max_level": max(levels),
            "task_count": len(task_list),
        }

    # Conditions with only 1 task (thin coverage)
    thin_coverage = sorted(c for c, tl in by_condition.items() if len(tl) == 1)

    # Categories with unique conditions
    category_condition_counts = {cat: len(conds) for cat, conds in conditions_per_category.items()}

    return {
        "summary": {
            "total_tasks": len(tasks),
            "total_conditions_covered": len(covered_conditions),
            "total_conditions_available": OPENEM_TOTAL,
            "coverage_pct": round(coverage_pct, 1),
            "unmapped_tasks": len(unmapped),
            "thin_coverage_conditions": len(thin_coverage),
        },
        "by_category": dict(sorted(by_category.items())),
        "by_level": {str(k): v for k, v in sorted(by_level.items())},
        "by_workflow": dict(sorted(by_workflow.items())),
        "category_condition_counts": dict(sorted(category_condition_counts.items())),
        "conditions": {c: by_condition[c] for c in covered_conditions},
        "thin_coverage": thin_coverage,
        "unmapped_task_ids": unmapped,
    }


def print_summary(matrix: dict) -> None:
    """Print a human-readable summary."""
    s = matrix["summary"]
    print(
        f"Coverage: {s['total_conditions_covered']}/{s['total_conditions_available']}"
        f" ({s['coverage_pct']}%)"
    )
    print(f"Tasks: {s['total_tasks']}")
    print(f"Unmapped: {s['unmapped_tasks']}")
    print(f"Thin coverage (1 task only): {s['thin_coverage_conditions']}")
    print()

    print("By category:")
    for cat, count in matrix["by_category"].items():
        cond_count = matrix["category_condition_counts"].get(cat, 0)
        print(f"  {cat}: {count} tasks, {cond_count} conditions")
    print()

    print("By level:")
    for level, count in matrix["by_level"].items():
        print(f"  Level {level}: {count} tasks")
    print()

    print("By workflow type:")
    for wf, count in matrix["by_workflow"].items():
        print(f"  {wf}: {count} tasks")
    print()

    gap = s["total_conditions_available"] - s["total_conditions_covered"]
    print(f"Gap: {gap} conditions uncovered ({100 - s['coverage_pct']:.1f}%)")
    print()

    # Expansion targets
    targets = [
        (230, "v0.2 (+100 tasks)"),
        (330, "v0.3 (+200 tasks)"),
        (370, "v0.4 (+240 tasks, full coverage)"),
    ]
    print("Expansion targets:")
    for target, label in targets:
        delta = target - s["total_conditions_covered"]
        if delta > 0:
            print(
                f"  {target}/{s['total_conditions_available']}"
                f" ({target / s['total_conditions_available'] * 100:.0f}%)"
                f" -- need {delta} new conditions -- {label}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate coverage matrix")
    parser.add_argument("--output", type=str, help="Output JSON path")
    parser.add_argument("--summary", action="store_true", help="Print text summary to stdout")
    args = parser.parse_args()

    if not args.output and not args.summary:
        args.summary = True

    tasks = load_tasks()
    matrix = build_matrix(tasks)

    if args.summary:
        print_summary(matrix)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(matrix, indent=2) + "\n")
        print(f"\nWrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
