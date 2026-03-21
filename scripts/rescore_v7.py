#!/usr/bin/env python3
"""Offline re-scorer: re-evaluate V7 trajectories with the V8 evaluator.

Reconstructs audit logs from V7 trajectory turn data, then re-evaluates all
`world_state` criteria using the V8 evaluator (which now parses parameter
qualifiers and compound AND/OR clauses). Keeps `llm_judge` and `pattern`
results from the original trajectory unchanged.

Bugs that affect re-scoring:
  - Bug 2 (parameter qualifiers): V8 enforces qualifiers — criteria that V7
    false-passed will flip to unsatisfied.
  - Bug 4 (AND/OR compounds): V8 splits compounds — criteria with AND/OR
    were unsatisfiable in V7, may now be satisfiable.

Bugs that do NOT affect re-scoring (tool/agent behavior changes):
  - Bug 1 (protocol names), Bug 3 (processTransfer), Bug 5 (prompt IDs)

Usage:
    python scripts/rescore_v7.py \\
        --results results/pilot-v7-claude-opus results/pilot-v7-gpt54

    # Verbose per-flip details
    python scripts/rescore_v7.py \\
        --results results/pilot-v7-claude-opus results/pilot-v7-gpt54 --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from healthcraft.tasks.evaluator import (  # noqa: E402
    _parse_criteria,
    _verify_world_state,
)
from healthcraft.tasks.loader import load_tasks  # noqa: E402
from healthcraft.tasks.rubrics import (  # noqa: E402
    CriterionResult,
    VerificationMethod,
    check_safety_gate,
    compute_reward,
)
from healthcraft.world.state import AuditEntry, WorldState  # noqa: E402

# Reuse load_trajectories from analyze_v7
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
from analyze_v7 import get_model_name, load_trajectories  # noqa: E402

_TASKS_DIR = _PROJECT_ROOT / "configs" / "tasks"
_RESULTS_DIR = _PROJECT_ROOT / "results" / "rescore-v7"


# ── Audit log reconstruction ────────────────────────────────────────


def reconstruct_audit_log(trajectory: dict) -> list[AuditEntry]:
    """Build AuditEntry list from trajectory turns.

    For each assistant turn with tool_calls, find the next tool turn(s)
    with the matching response. Extract:
      - tool_name from tool_call["name"]
      - params from tool_call["arguments"] (may be str or dict)
      - result_summary from response JSON .get("status", "unknown")
    """
    turns = trajectory.get("turns", [])
    entries: list[AuditEntry] = []
    now = datetime.now(timezone.utc)

    i = 0
    while i < len(turns):
        turn = turns[i]
        if turn.get("role") == "assistant" and turn.get("tool_calls"):
            tool_calls = turn["tool_calls"]
            # Collect subsequent tool-response turns
            responses: list[dict] = []
            j = i + 1
            while j < len(turns) and turns[j].get("role") == "tool":
                responses.append(turns[j])
                j += 1

            for k, tc in enumerate(tool_calls):
                tool_name = tc.get("name", "")
                raw_args = tc.get("arguments", {})
                if isinstance(raw_args, str):
                    try:
                        params = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        params = {"_raw": raw_args}
                else:
                    params = dict(raw_args) if raw_args else {}

                # Match response by position
                result_summary = "unknown"
                if k < len(responses):
                    resp_content = responses[k].get("content", "")
                    try:
                        resp_json = json.loads(resp_content)
                        result_summary = resp_json.get("status", "unknown")
                    except (json.JSONDecodeError, TypeError):
                        result_summary = "unknown"

                entries.append(
                    AuditEntry(
                        tool_name=tool_name,
                        timestamp=now,
                        params=params,
                        result_summary=result_summary,
                    )
                )
            i = j  # skip past consumed tool turns
        else:
            i += 1

    return entries


# ── Re-scoring ───────────────────────────────────────────────────────


def _attribute_bug(criterion_check: str) -> str:
    """Attribute a flip to Bug 2 (qualifier) or Bug 4 (compound), or unknown."""
    check_lower = criterion_check.lower()
    # Bug 4: compound AND/OR
    has_and = " and " in check_lower
    has_or = " or " in check_lower
    # Check if split yields valid compound (not just medical text)
    if has_and or has_or:
        # Simple heuristic: if both sides contain "contains" or "call to"
        for op in ("and", "or"):
            import re

            parts = re.split(rf"\s+{op}\s+", check_lower, flags=re.IGNORECASE)
            if len(parts) > 1:
                valid = sum(
                    1 for p in parts if "contains" in p or "call to" in p or "audit_log" in p
                )
                if valid > 1:
                    return f"bug4_compound_{op}"

    # Check for bare tool alternatives (X or Y / X and Y after "call to")
    # These are compound patterns that _expand_tool_alternatives handles.
    import re as _re

    bare_alt = _re.search(
        r"call\s+to\s+\w+\s+(?:or|and)\s+\w+\s*$",
        check_lower,
    )
    if bare_alt:
        op = "or" if " or " in bare_alt.group() else "and"
        return f"bug4_compound_{op}"

    # Bug 2: qualifier patterns
    qualifier_keywords = (
        " for ",
        " with ",
        " matching ",
        " referencing ",
        " regarding ",
        " addressing ",
        " to discontinue ",
        " to hold",
        " to stop ",
        " reviewing ",
        " related to ",
        " removing ",
        " confirming ",
        " identifying ",
    )
    if any(kw in check_lower for kw in qualifier_keywords):
        return "bug2_qualifier"

    return "unknown"


def rescore_trajectory(
    trajectory: dict,
    task_criteria: tuple[dict, ...],
) -> dict | None:
    """Re-evaluate world_state criteria for one trajectory.

    Returns a delta dict, or None if nothing changed.
    """
    # Reconstruct audit log
    audit_entries = reconstruct_audit_log(trajectory)

    # Build a minimal WorldState with just the audit log
    ws = WorldState()
    ws._audit_log = audit_entries

    # Parse criteria
    criteria = _parse_criteria(task_criteria)

    # Map original results by criterion id
    orig_results = {cr["id"]: cr for cr in trajectory.get("criteria_results", [])}

    new_results: list[CriterionResult] = []
    flips: list[dict] = []

    for criterion in criteria:
        orig = orig_results.get(criterion.id, {})
        old_satisfied = orig.get("satisfied", False)

        if criterion.verification == VerificationMethod.WORLD_STATE:
            # Re-evaluate with V8 evaluator
            result = _verify_world_state(criterion, (), ws)
            new_satisfied = result.satisfied

            if old_satisfied != new_satisfied:
                flips.append(
                    {
                        "criterion_id": criterion.id,
                        "old_satisfied": old_satisfied,
                        "new_satisfied": new_satisfied,
                        "bug_attribution": _attribute_bug(criterion.check),
                        "check": criterion.check,
                        "evidence": result.evidence,
                    }
                )

            new_results.append(result)
        else:
            # Keep original result for llm_judge and pattern
            new_results.append(
                CriterionResult(
                    criterion_id=criterion.id,
                    satisfied=old_satisfied,
                    evidence=orig.get("evidence", ""),
                )
            )

    # Recompute reward and safety gate
    new_reward = compute_reward(new_results, criteria)
    new_safety = check_safety_gate(new_results, criteria)
    new_passed = all(r.satisfied for r in new_results)

    old_reward = trajectory.get("reward", 0.0)
    old_safety = trajectory.get("safety_gate_passed", True)
    old_passed = trajectory.get("passed", False)

    if not flips and abs(new_reward - old_reward) < 1e-9:
        return None

    return {
        "task_id": trajectory["task_id"],
        "model": trajectory.get("model", "unknown"),
        "trial": trajectory.get("trial", 1),
        "old_reward": old_reward,
        "new_reward": new_reward,
        "reward_delta": new_reward - old_reward,
        "old_passed": old_passed,
        "new_passed": new_passed,
        "old_safety": old_safety,
        "new_safety": new_safety,
        "safety_flipped": old_safety != new_safety,
        "flips": flips,
    }


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-score V7 trajectories with V8 evaluator",
    )
    parser.add_argument(
        "--results",
        "-r",
        nargs="+",
        required=True,
        help="V7 results directories to re-score",
    )
    parser.add_argument(
        "--tasks-dir",
        default=str(_TASKS_DIR),
        help="Task definitions directory",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=str(_RESULTS_DIR / "rescore_report.json"),
        help="Output report path",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-flip details",
    )
    args = parser.parse_args()

    # Load task definitions
    tasks_dir = Path(args.tasks_dir)
    print(f"Loading tasks from {tasks_dir}...", file=sys.stderr)
    tasks = load_tasks(tasks_dir)
    task_map = {t.id: t for t in tasks}
    print(f"  Loaded {len(tasks)} tasks", file=sys.stderr)

    # Process each results directory
    all_deltas: list[dict] = []
    all_flips: list[dict] = []
    model_stats: dict[str, dict] = {}
    total_trajectories = 0
    skipped_no_task = 0
    skipped_error = 0

    for results_path in args.results:
        results_dir = Path(results_path)
        if not results_dir.exists():
            print(f"Warning: {results_dir} does not exist, skipping", file=sys.stderr)
            continue

        trajectories = load_trajectories(results_dir)
        model_name = get_model_name(results_dir, trajectories)
        print(
            f"Re-scoring {len(trajectories)} trajectories from {results_dir} ({model_name})...",
            file=sys.stderr,
        )

        if model_name not in model_stats:
            model_stats[model_name] = {
                "trajectories": 0,
                "old_rewards": [],
                "new_rewards": [],
                "flips_s_to_u": 0,
                "flips_u_to_s": 0,
                "safety_flips": 0,
                "old_passed": 0,
                "new_passed": 0,
            }

        for traj in trajectories:
            total_trajectories += 1
            task_id = traj.get("task_id", "")

            # Skip error trajectories
            if traj.get("error"):
                skipped_error += 1
                continue

            task = task_map.get(task_id)
            if not task:
                skipped_no_task += 1
                continue

            delta = rescore_trajectory(traj, task.criteria)
            model_stats[model_name]["trajectories"] += 1
            model_stats[model_name]["old_rewards"].append(traj.get("reward", 0.0))

            if delta:
                all_deltas.append(delta)
                model_stats[model_name]["new_rewards"].append(delta["new_reward"])
                if delta["old_passed"]:
                    model_stats[model_name]["old_passed"] += 1
                if delta["new_passed"]:
                    model_stats[model_name]["new_passed"] += 1
                if delta["safety_flipped"]:
                    model_stats[model_name]["safety_flips"] += 1

                for flip in delta["flips"]:
                    flip_record = {
                        "task_id": delta["task_id"],
                        "model": delta["model"],
                        "trial": delta["trial"],
                        **flip,
                    }
                    all_flips.append(flip_record)

                    if flip["old_satisfied"] and not flip["new_satisfied"]:
                        model_stats[model_name]["flips_s_to_u"] += 1
                    elif not flip["old_satisfied"] and flip["new_satisfied"]:
                        model_stats[model_name]["flips_u_to_s"] += 1
            else:
                # No change — carry forward original values
                model_stats[model_name]["new_rewards"].append(traj.get("reward", 0.0))
                if traj.get("passed", False):
                    model_stats[model_name]["old_passed"] += 1
                    model_stats[model_name]["new_passed"] += 1

    # Compute summary
    total_flips = len(all_flips)
    flips_s_to_u = sum(1 for f in all_flips if f["old_satisfied"] and not f["new_satisfied"])
    flips_u_to_s = sum(1 for f in all_flips if not f["old_satisfied"] and f["new_satisfied"])
    safety_flips = sum(1 for d in all_deltas if d.get("safety_flipped"))

    reward_deltas = [d["reward_delta"] for d in all_deltas]
    reward_delta_mean = sum(reward_deltas) / len(reward_deltas) if reward_deltas else 0.0

    # Per-model summary
    per_model = {}
    for model, stats in model_stats.items():
        old_r = stats["old_rewards"]
        new_r = stats["new_rewards"]
        per_model[model] = {
            "trajectories": stats["trajectories"],
            "old_reward": sum(old_r) / len(old_r) if old_r else 0.0,
            "new_reward": sum(new_r) / len(new_r) if new_r else 0.0,
            "reward_delta": (sum(new_r) / len(new_r) - sum(old_r) / len(old_r)) if old_r else 0.0,
            "old_passed": stats["old_passed"],
            "new_passed": stats["new_passed"],
            "flips_satisfied_to_unsatisfied": stats["flips_s_to_u"],
            "flips_unsatisfied_to_satisfied": stats["flips_u_to_s"],
            "safety_flips": stats["safety_flips"],
        }

    # Bug attribution breakdown
    bug_counts: dict[str, int] = {}
    for f in all_flips:
        attr = f.get("bug_attribution", "unknown")
        bug_counts[attr] = bug_counts.get(attr, 0) + 1

    report = {
        "summary": {
            "total_trajectories": total_trajectories,
            "rescored_trajectories": total_trajectories - skipped_error - skipped_no_task,
            "skipped_error": skipped_error,
            "skipped_no_task": skipped_no_task,
            "trajectories_with_changes": len(all_deltas),
            "criteria_flipped": total_flips,
            "flips_satisfied_to_unsatisfied": flips_s_to_u,
            "flips_unsatisfied_to_satisfied": flips_u_to_s,
            "reward_delta_mean": round(reward_delta_mean, 6),
            "safety_flips": safety_flips,
            "bug_attribution": bug_counts,
        },
        "per_model": per_model,
        "flipped_criteria": all_flips,
    }

    # Write report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nReport written to {output_path}", file=sys.stderr)

    # Print summary table
    print()
    print("=" * 70)
    print("  V7 → V8 Re-score Summary")
    print("=" * 70)
    print()
    print(f"  Total trajectories:         {total_trajectories}")
    print(f"  Rescored:                   {total_trajectories - skipped_error - skipped_no_task}")
    print(f"  Skipped (error):            {skipped_error}")
    print(f"  Skipped (no task def):      {skipped_no_task}")
    print(f"  Trajectories with changes:  {len(all_deltas)}")
    print()
    print(f"  Criteria flipped:           {total_flips}")
    print(f"    satisfied → unsatisfied:  {flips_s_to_u}")
    print(f"    unsatisfied → satisfied:  {flips_u_to_s}")
    print(f"  Safety gate flips:          {safety_flips}")
    print(f"  Mean reward delta:          {reward_delta_mean:+.6f}")
    print()

    if bug_counts:
        print("  Bug attribution:")
        for bug, count in sorted(bug_counts.items()):
            print(f"    {bug}: {count}")
        print()

    print("  Per-model:")
    hdr = f"    {'Model':<25} {'Old Reward':>11} {'New Reward':>11}"
    hdr += f" {'Delta':>8} {'S→U':>5} {'U→S':>5}"
    print(hdr)
    print("    " + "-" * 68)
    for model, stats in sorted(per_model.items()):
        print(
            f"    {model:<25} "
            f"{stats['old_reward']:>11.3f} "
            f"{stats['new_reward']:>11.3f} "
            f"{stats['reward_delta']:>+8.4f} "
            f"{stats['flips_satisfied_to_unsatisfied']:>5} "
            f"{stats['flips_unsatisfied_to_satisfied']:>5}"
        )
    print()

    if args.verbose and all_flips:
        print("  Flipped criteria:")
        print(
            f"    {'Task':<10} {'Criterion':<15} {'Model':<20}"
            f" {'Old':>5} {'New':>5} {'Bug':<20} Check"
        )
        print("    " + "-" * 100)
        for f in sorted(all_flips, key=lambda x: (x["task_id"], x["criterion_id"])):
            old = "pass" if f["old_satisfied"] else "fail"
            new = "pass" if f["new_satisfied"] else "fail"
            check_short = f["check"][:50] + "..." if len(f["check"]) > 50 else f["check"]
            print(
                f"    {f['task_id']:<10} {f['criterion_id']:<15} "
                f"{f['model']:<20} {old:>5} {new:>5} "
                f"{f['bug_attribution']:<20} {check_short}"
            )
        print()


if __name__ == "__main__":
    main()
