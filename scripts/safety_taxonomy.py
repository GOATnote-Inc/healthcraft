#!/usr/bin/env python3
"""Safety failure taxonomy: categorize safety gate violations by type.

Reads V8 trajectories and task YAMLs, identifies all safety_critical
criterion violations, and categorizes them by failure type.

Categories (derived from criterion assertion text):
  - contraindication: Drug/treatment contraindicated for this condition
  - diagnostic: Incorrect or missed diagnosis
  - protocol: Protocol violation (wrong sequence, missing step)
  - temporal: Time-critical action delayed or misordered
  - documentation: Safety-relevant documentation failure
  - omission: Failed to perform a required safety action
  - commission: Performed a harmful action

Usage:
    python scripts/safety_taxonomy.py \
        --results results/pilot-v8-claude-opus results/pilot-v8-gpt54

    python scripts/safety_taxonomy.py \
        --results results/pilot-v8-claude-opus results/pilot-v8-gpt54 \
        --output docs/SAFETY_TAXONOMY.md --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

# ── Classification patterns ─────────────────────────────────────────

# Order matters: first match wins. More specific categories before general.
CLASSIFICATION_RULES: list[tuple[str, list[str]]] = [
    (
        "contraindication",
        [
            r"did NOT (?:order|administer|give|prescribe)"
            r".*(?:heparin|anticoagul|tpa|thrombolytic|aspirin|nsaid|contrast)",
            r"did NOT.*(?:contraindicated|allergic|allergy)",
            r"avoided.*(?:medication|drug|treatment).*contraindicated",
        ],
    ),
    (
        "temporal",
        [
            r"(?:before|prior to|within|after).*(?:minute|hour|time|door-to)",
            r"(?:ordered|administered|gave).*(?:before|prior to|within)",
            r"BEFORE",
            r"completed.*(?:before|within|prior)",
        ],
    ),
    (
        "diagnostic",
        [
            r"(?:identified|recognized|diagnosed|considered)"
            r".*(?:as |diagnosis|differential|condition|finding)",
            r"(?:cancel|stopped|held).*(?:stemi|cath lab|tpa|thrombolytic)",
            r"did NOT.*(?:miss|overlook|ignore).*diagnosis",
            r"recognized.*(?:signs|symptoms|presentation|worsening|deteriorat)",
        ],
    ),
    (
        "protocol",
        [
            r"(?:followed|adhered|complied).*(?:protocol|guideline|bundle|pathway)",
            r"(?:emtala|consent|ama|against medical advice|capacity)",
            r"(?:blood type|crossmatch|verify|confirm).*(?:before|prior)",
            r"(?:activated|initiated).*(?:protocol|code|alert|mtp|massive)",
            r"(?:transfer|transported).*(?:burn center|trauma center|stroke|pci)",
            r"ensured.*(?:observation|monitoring|sitter|1:1)",
        ],
    ),
    (
        "commission",
        [
            r"did NOT (?:order|administer|give|perform|initiate|start)",
            r"did NOT.*(?:activate|alert|call|page)",
            r"did NOT (?:discharge|release|send home)",
        ],
    ),
    (
        "omission",
        [
            r"(?:assessed|evaluated|checked|monitored|obtained|ordered|performed)",
            r"(?:included|documented|addressed|communicated|notified)",
            r"(?:ordered|administered|gave|started|initiated)",
        ],
    ),
    (
        "documentation",
        [
            r"(?:documented|recorded|noted|charted|included in.*note)",
            r"(?:discharge|transfer|handoff).*(?:instruction|summary|documentation)",
        ],
    ),
]


def classify_criterion(assertion: str) -> str:
    """Classify a safety criterion assertion into a failure category."""
    for category, patterns in CLASSIFICATION_RULES:
        for pattern in patterns:
            if re.search(pattern, assertion, re.IGNORECASE):
                return category
    return "other"


# ── Data loading ────────────────────────────────────────────────────


def load_safety_criteria(tasks_dir: Path) -> dict[str, dict]:
    """Load all safety_critical criteria from task YAMLs.

    Returns dict mapping criterion_id to {assertion, dimension, task_id, category, ...}.
    """
    criteria = {}
    for yaml_path in sorted(tasks_dir.rglob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if not data or "criteria" not in data:
            continue

        task_id = data.get("id", yaml_path.stem)
        task_category = data.get("category", "unknown")

        for c in data["criteria"]:
            if c.get("safety_critical", False):
                cid = c["id"]
                criteria[cid] = {
                    "criterion_id": cid,
                    "task_id": task_id,
                    "task_category": task_category,
                    "assertion": c["assertion"],
                    "dimension": c.get("dimension", "safety"),
                    "verification": c.get("verification", "unknown"),
                    "failure_type": classify_criterion(c["assertion"]),
                }
    return criteria


def load_safety_violations(
    results_dirs: list[Path],
    safety_criteria: dict[str, dict],
) -> list[dict]:
    """Load all safety criterion violations from trajectory files.

    Returns list of violation dicts with model, task, criterion, and type info.
    """
    violations = []
    for results_dir in results_dirs:
        traj_dir = results_dir / "trajectories"
        if not traj_dir.exists():
            continue

        # Infer model name
        summary_path = results_dir / "summary.json"
        model = results_dir.name
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            model = summary.get("agent_model", model)

        for cat_dir in sorted(traj_dir.iterdir()):
            if not cat_dir.is_dir():
                continue
            for path in sorted(cat_dir.glob("*.json")):
                try:
                    traj = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue

                if traj.get("safety_gate_passed", True):
                    continue  # No safety violation

                task_id = traj.get("task_id", "unknown")
                for cr in traj.get("criteria_results", []):
                    cid = cr.get("criterion_id", cr.get("id", ""))
                    if cid in safety_criteria and not cr.get("satisfied", True):
                        info = safety_criteria[cid]
                        violations.append(
                            {
                                "model": model,
                                "task_id": task_id,
                                "task_category": info["task_category"],
                                "criterion_id": cid,
                                "assertion": info["assertion"],
                                "dimension": info["dimension"],
                                "failure_type": info["failure_type"],
                                "verification": info["verification"],
                            }
                        )
    return violations


# ── Report generation ───────────────────────────────────────────────


def generate_report(
    safety_criteria: dict[str, dict],
    violations: list[dict],
    results_dirs: list[Path],
) -> str:
    """Generate safety taxonomy report."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("  HEALTHCRAFT Safety Failure Taxonomy")
    lines.append("=" * 70)
    lines.append("")

    # Summary
    models = sorted(set(v["model"] for v in violations))
    lines.append(f"Safety-critical criteria: {len(safety_criteria)}")
    lines.append(f"Total violations: {len(violations)}")
    lines.append(f"Models: {', '.join(models)}")
    lines.append("")

    # By failure type
    lines.append("Violations by Failure Type:")
    lines.append("")
    type_counts: dict[str, Counter] = defaultdict(Counter)
    for v in violations:
        type_counts[v["failure_type"]][v["model"]] += 1

    header = f"  {'Type':<20}"
    for m in models:
        header += f" {m:>20}"
    header += f" {'Total':>8}"
    lines.append(header)
    lines.append("  " + "-" * (20 + 21 * len(models) + 9))

    all_types = sorted(type_counts.keys())
    for ftype in all_types:
        row = f"  {ftype:<20}"
        total = 0
        for m in models:
            count = type_counts[ftype][m]
            total += count
            row += f" {count:>20}"
        row += f" {total:>8}"
        lines.append(row)
    lines.append("")

    # By task category
    lines.append("Violations by Task Category:")
    lines.append("")
    cat_counts: dict[str, Counter] = defaultdict(Counter)
    for v in violations:
        cat_counts[v["task_category"]][v["model"]] += 1

    header = f"  {'Task Category':<30}"
    for m in models:
        header += f" {m:>20}"
    header += f" {'Total':>8}"
    lines.append(header)
    lines.append("  " + "-" * (30 + 21 * len(models) + 9))

    for cat in sorted(cat_counts.keys()):
        row = f"  {cat:<30}"
        total = 0
        for m in models:
            count = cat_counts[cat][m]
            total += count
            row += f" {count:>20}"
        row += f" {total:>8}"
        lines.append(row)
    lines.append("")

    # Cross-tabulation: failure type x task category
    lines.append("Failure Type x Task Category (all models):")
    lines.append("")
    cross: dict[tuple[str, str], int] = Counter()
    for v in violations:
        cross[(v["failure_type"], v["task_category"])] += 1

    cats = sorted(set(v["task_category"] for v in violations))
    header = f"  {'Type':<20}"
    for cat in cats:
        header += f" {cat[:12]:>12}"
    lines.append(header)
    lines.append("  " + "-" * (20 + 13 * len(cats)))
    for ftype in all_types:
        row = f"  {ftype:<20}"
        for cat in cats:
            row += f" {cross[(ftype, cat)]:>12}"
        lines.append(row)
    lines.append("")

    # Top violated criteria (most frequently failed)
    lines.append("Most Frequently Violated Safety Criteria:")
    lines.append("")
    crit_counts: Counter = Counter()
    for v in violations:
        crit_counts[v["criterion_id"]] += 1

    lines.append(f"  {'Criterion':<16} {'Type':<16} {'Count':>5}  Assertion")
    lines.append("  " + "-" * 90)
    for cid, count in crit_counts.most_common(20):
        info = safety_criteria.get(cid, {})
        ftype = info.get("failure_type", "?")
        assertion = info.get("assertion", "?")[:55]
        lines.append(f"  {cid:<16} {ftype:<16} {count:>5}  {assertion}")
    lines.append("")

    # Per-model summary
    for m in models:
        m_violations = [v for v in violations if v["model"] == m]
        m_types = Counter(v["failure_type"] for v in m_violations)
        lines.append(f"{m}: {len(m_violations)} safety violations")
        for ftype in sorted(m_types, key=m_types.get, reverse=True):
            pct = m_types[ftype] / len(m_violations) * 100
            lines.append(f"  {ftype:<20} {m_types[ftype]:>4} ({pct:.1f}%)")
        lines.append("")

    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HEALTHCRAFT safety failure taxonomy",
    )
    parser.add_argument(
        "--results",
        "-r",
        nargs="+",
        required=True,
        help="Results directories to analyze",
    )
    parser.add_argument(
        "--tasks-dir",
        "-t",
        default="configs/tasks",
        help="Task definitions directory (default: configs/tasks)",
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
        help="Also write JSON data alongside report",
    )
    args = parser.parse_args()

    tasks_dir = Path(args.tasks_dir)
    if not tasks_dir.exists():
        print(f"Tasks directory not found: {tasks_dir}", file=sys.stderr)
        sys.exit(1)

    results_dirs = [Path(d) for d in args.results]

    # Load safety criteria from task definitions
    safety_criteria = load_safety_criteria(tasks_dir)
    print(f"Loaded {len(safety_criteria)} safety-critical criteria", file=sys.stderr)

    # Load violations from trajectories
    violations = load_safety_violations(results_dirs, safety_criteria)
    print(f"Found {len(violations)} safety violations", file=sys.stderr)

    report = generate_report(safety_criteria, violations, results_dirs)
    print(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"\nReport written to {output_path}", file=sys.stderr)

    if args.json:
        json_path = (
            Path(args.output).with_suffix(".json") if args.output else Path("safety_taxonomy.json")
        )
        json_data = {
            "total_safety_criteria": len(safety_criteria),
            "total_violations": len(violations),
            "criteria": list(safety_criteria.values()),
            "violations": violations,
        }
        json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
        print(f"JSON written to {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
