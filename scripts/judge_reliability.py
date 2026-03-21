#!/usr/bin/env python3
"""Judge inter-rater reliability analysis.

Re-judges a sample of trajectories multiple times with fresh API calls
to measure LLM judge consistency. Reports Cohen's kappa and agreement
rate, stratified by trajectory length and criterion dimension.

Requires API keys loaded: set -a && source .env && set +a

Usage:
    python scripts/judge_reliability.py \
        --results results/pilot-v8-claude-opus results/pilot-v8-gpt54 \
        --sample 100 --repeats 3

    # Dry run: show what would be judged without making API calls
    python scripts/judge_reliability.py \
        --results results/pilot-v8-claude-opus --sample 50 --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

# ── Cohen's kappa ───────────────────────────────────────────────────


def cohens_kappa(judgments: list[list[bool]]) -> float:
    """Compute Cohen's kappa for multiple judgments of the same items.

    Args:
        judgments: List of judgment lists. Each inner list has one bool
                   per repeat for the same criterion evaluation.

    Returns:
        kappa value in [-1, 1]. 1 = perfect agreement, 0 = chance.
    """
    if not judgments:
        return 0.0

    n = len(judgments)
    k = len(judgments[0])
    if k < 2:
        return 1.0

    # Compute observed agreement (fraction of pairs that agree)
    agree_count = 0
    pair_count = 0
    for item_judgments in judgments:
        for i in range(k):
            for j in range(i + 1, k):
                pair_count += 1
                if item_judgments[i] == item_judgments[j]:
                    agree_count += 1

    if pair_count == 0:
        return 0.0

    p_o = agree_count / pair_count

    # Compute expected agreement by chance
    all_pos = sum(sum(j) for j in judgments)
    all_total = n * k
    p_pos = all_pos / all_total if all_total else 0.5
    p_neg = 1 - p_pos
    p_e = p_pos**2 + p_neg**2

    if abs(p_e - 1.0) < 1e-10:
        return 1.0

    return (p_o - p_e) / (1 - p_e)


# ── Sample selection ────────────────────────────────────────────────


def select_sample(
    results_dirs: list[Path],
    sample_size: int,
    seed: int = 42,
) -> list[dict]:
    """Select a stratified random sample of (trajectory, criterion) pairs.

    Stratifies by:
    - Model (equal representation)
    - Trajectory length (short <15 turns, medium 15-40, long >40)
    - Criterion dimension

    Returns list of dicts with trajectory path, criterion info, and
    original verdict.
    """
    rng = random.Random(seed)
    candidates = []

    for results_dir in results_dirs:
        traj_dir = results_dir / "trajectories"
        if not traj_dir.exists():
            continue

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

                turns = traj.get("turns", [])
                n_turns = len(turns)
                length_bucket = "short" if n_turns < 15 else "medium" if n_turns <= 40 else "long"

                for cr in traj.get("criteria_results", []):
                    # Only re-judge llm_judge criteria (world_state is deterministic)
                    evidence = cr.get("evidence", "")
                    # Heuristic: llm_judge criteria have model name in evidence
                    if not any(m in evidence for m in ["claude", "gpt", "gemini", "grok", "Judge"]):
                        continue

                    candidates.append(
                        {
                            "trajectory_path": str(path),
                            "model": model,
                            "task_id": traj.get("task_id", "unknown"),
                            "criterion_id": cr.get("criterion_id", cr.get("id", "")),
                            "original_satisfied": cr.get("satisfied", False),
                            "dimension": cr.get("dimension", "unknown"),
                            "n_turns": n_turns,
                            "length_bucket": length_bucket,
                        }
                    )

    rng.shuffle(candidates)
    return candidates[:sample_size]


# ── Report generation ───────────────────────────────────────────────


def generate_dry_run_report(sample: list[dict]) -> str:
    """Generate a dry-run report showing what would be judged."""
    lines = [
        "=" * 70,
        "  Judge Reliability Study -- Dry Run",
        "=" * 70,
        "",
        f"Sample size: {len(sample)} criterion evaluations",
        "",
    ]

    # Breakdown by model
    model_counts = defaultdict(int)
    for s in sample:
        model_counts[s["model"]] += 1
    lines.append("By model:")
    for m, c in sorted(model_counts.items()):
        lines.append(f"  {m}: {c}")
    lines.append("")

    # Breakdown by length bucket
    length_counts = defaultdict(int)
    for s in sample:
        length_counts[s["length_bucket"]] += 1
    lines.append("By trajectory length:")
    for b in ["short", "medium", "long"]:
        lines.append(f"  {b}: {length_counts.get(b, 0)}")
    lines.append("")

    # Breakdown by dimension
    dim_counts = defaultdict(int)
    for s in sample:
        dim_counts[s["dimension"]] += 1
    lines.append("By dimension:")
    for d, c in sorted(dim_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {d}: {c}")
    lines.append("")

    # Original verdict distribution
    sat = sum(1 for s in sample if s["original_satisfied"])
    unsat = len(sample) - sat
    lines.append(f"Original verdicts: {sat} satisfied, {unsat} unsatisfied")
    lines.append("")

    # Estimated API calls
    lines.append("To run with --repeats 3:")
    lines.append(f"  API calls: {len(sample) * 3}")
    lines.append(f"  Estimated cost: ~${len(sample) * 3 * 0.02:.2f} (rough)")
    lines.append(f"  Estimated time: ~{len(sample) * 3 * 3 / 60:.0f} min")
    lines.append("")

    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HEALTHCRAFT judge inter-rater reliability analysis",
    )
    parser.add_argument(
        "--results",
        "-r",
        nargs="+",
        required=True,
        help="Results directories containing trajectories",
    )
    parser.add_argument(
        "--sample",
        "-n",
        type=int,
        default=100,
        help="Number of criterion evaluations to sample (default: 100)",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of re-judgments per criterion (default: 3)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for sample selection (default: 42)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show sample composition without making API calls",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write report to file",
    )
    args = parser.parse_args()

    results_dirs = [Path(d) for d in args.results]

    sample = select_sample(results_dirs, args.sample, seed=args.seed)
    print(f"Selected {len(sample)} criterion evaluations", file=sys.stderr)

    if args.dry_run:
        report = generate_dry_run_report(sample)
        print(report)
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
            print(f"Report written to {args.output}", file=sys.stderr)
        return

    # Full run requires API keys and healthcraft imports
    try:
        from healthcraft.llm.clients import create_client

        from healthcraft.llm.judge import LLMJudge, select_judge_model
        from healthcraft.tasks.rubrics import Criterion, VerificationMethod
    except ImportError as e:
        print(
            f"Import error: {e}\n"
            "Install healthcraft first: pip install -e '.[dev]'\n"
            "And load API keys: set -a && source .env && set +a",
            file=sys.stderr,
        )
        sys.exit(1)

    # Group sample by model to use appropriate judge
    by_model: dict[str, list[dict]] = defaultdict(list)
    for s in sample:
        by_model[s["model"]].append(s)

    all_judgments: dict[str, list[list[bool]]] = defaultdict(list)
    results_data = []

    for model, items in by_model.items():
        judge_model = select_judge_model(model)
        print(f"Judging {len(items)} criteria for {model} with {judge_model}", file=sys.stderr)

        client = create_client(judge_model)
        judge = LLMJudge(client, judge_model=judge_model)

        for item in items:
            traj_path = Path(item["trajectory_path"])
            traj = json.loads(traj_path.read_text(encoding="utf-8"))
            turns = traj.get("turns", [])

            # Find the criterion definition
            cid = item["criterion_id"]
            # Build a minimal Criterion object
            criterion = Criterion(
                id=cid,
                assertion=next(
                    (
                        cr.get("assertion", "")
                        for cr in traj.get("criteria_results", [])
                        if cr.get("criterion_id", cr.get("id", "")) == cid
                    ),
                    "",
                ),
                dimension="unknown",
                verification=VerificationMethod.LLM_JUDGE,
                safety_critical=False,
            )

            repeat_verdicts = []
            for r in range(args.repeats):
                result = judge.evaluate_criterion(criterion, turns)
                repeat_verdicts.append(result.satisfied)

            all_judgments[item["length_bucket"]].append(repeat_verdicts)

            results_data.append(
                {
                    **item,
                    "repeat_verdicts": repeat_verdicts,
                    "agreement": len(set(repeat_verdicts)) == 1,
                    "judge_model": judge_model,
                }
            )

            # Progress
            done = len(results_data)
            total = len(sample)
            if done % 10 == 0:
                print(f"  {done}/{total} complete", file=sys.stderr)

    # Compute metrics
    all_items = [r["repeat_verdicts"] for r in results_data]
    overall_kappa = cohens_kappa(all_items)
    overall_agreement = sum(1 for r in results_data if r["agreement"]) / len(results_data)

    lines = [
        "=" * 70,
        "  HEALTHCRAFT Judge Reliability Analysis",
        "=" * 70,
        "",
        f"Sample: {len(results_data)} criterion evaluations",
        f"Repeats: {args.repeats} per criterion",
        f"Total API calls: {len(results_data) * args.repeats}",
        "",
        f"Overall agreement rate: {overall_agreement:.1%}",
        f"Overall Cohen's kappa: {overall_kappa:.3f}",
        "",
    ]

    # Stratified by trajectory length
    lines.append("By trajectory length:")
    for bucket in ["short", "medium", "long"]:
        bucket_items = [r for r in results_data if r["length_bucket"] == bucket]
        if not bucket_items:
            continue
        bucket_agree = sum(1 for r in bucket_items if r["agreement"]) / len(bucket_items)
        bucket_kappa = cohens_kappa([r["repeat_verdicts"] for r in bucket_items])
        lines.append(
            f"  {bucket:<8} n={len(bucket_items):<4} "
            f"agreement={bucket_agree:.1%}  kappa={bucket_kappa:.3f}"
        )
    lines.append("")

    # Stratified by dimension
    lines.append("By dimension:")
    dim_groups = defaultdict(list)
    for r in results_data:
        dim_groups[r["dimension"]].append(r)
    for dim in sorted(dim_groups, key=lambda d: -len(dim_groups[d])):
        items = dim_groups[dim]
        agree = sum(1 for r in items if r["agreement"]) / len(items)
        kappa = cohens_kappa([r["repeat_verdicts"] for r in items])
        lines.append(f"  {dim:<30} n={len(items):<4} agreement={agree:.1%}  kappa={kappa:.3f}")
    lines.append("")

    # Flip analysis: cases where judge disagreed with itself
    flips = [r for r in results_data if not r["agreement"]]
    lines.append(f"Judge self-disagreements: {len(flips)} / {len(results_data)}")
    if flips:
        lines.append("")
        lines.append(f"  {'Criterion':<16} {'Task':<10} {'Model':<18} {'Verdicts'}")
        lines.append("  " + "-" * 70)
        for r in flips[:30]:
            verdicts = ", ".join("S" if v else "U" for v in r["repeat_verdicts"])
            lines.append(
                f"  {r['criterion_id']:<16} {r['task_id']:<10} {r['model']:<18} [{verdicts}]"
            )
        if len(flips) > 30:
            lines.append(f"  ... and {len(flips) - 30} more")
    lines.append("")

    report = "\n".join(lines)
    print(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}", file=sys.stderr)

        json_path = output_path.with_suffix(".json")
        json_data = {
            "sample_size": len(results_data),
            "repeats": args.repeats,
            "overall_agreement": overall_agreement,
            "overall_kappa": overall_kappa,
            "results": results_data,
        }
        json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
        print(f"JSON written to {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
