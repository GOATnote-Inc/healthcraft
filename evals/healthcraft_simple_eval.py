#!/usr/bin/env python3
"""HealthCraft grader entrypoint -- simple-evals compatible.

Mirrors HealthBench's grader interface so that frontier labs can plug
HealthCraft into their existing evaluation harnesses with one command.

Usage::

    python evals/healthcraft_simple_eval.py \\
        --dataset data/huggingface_release/healthcraft_consensus.jsonl \\
        --agent-model claude-opus-4-7 \\
        --judge-mode ensemble \\
        --judge-models gpt-5.4,claude-opus-4-7,gemini-3.1-pro \\
        --trajectories-dir results/simple_eval_<timestamp> \\
        --trials 3 \\
        [--replay-from results/pilot-v8-claude-opus] \\
        [--limit N] \\
        [--dry-run]

Two grading modes:

  * ``--judge-mode ensemble`` (default): three cross-vendor judges vote
    independently; supermajority (``min_agreement=2``) decides each
    ``llm_judge`` verdict. Same-vendor judges are auto-filtered.
  * ``--judge-mode single``: one cross-vendor judge per criterion,
    selected via :func:`healthcraft.llm.judge.select_judge_model`. This
    is the V8-compatible mode.

Execution path (against a fresh ``--agent-model``) is **not** wired in v1.0.
The reference surface in v1.0 is replay: the grader re-scores saved
trajectories from ``--replay-from`` and reports aggregate metrics. Execution
will arrive in a follow-up release together with the RL rollout harness.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DatasetTask:
    """Minimal view of a task record from the release JSONL."""

    task_id: str
    category: str
    criteria: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class _TrialVerdict:
    """One (task, trial) verdict derived from replay."""

    task_id: str
    trial: int
    reward: float
    passed: bool
    safety_gate_passed: bool
    # ensemble-only: mean agreement_score across judged criteria on this trial
    judge_agreement: float | None
    ambiguous_criteria: int


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def _load_dataset(path: Path) -> list[_DatasetTask]:
    """Load a HealthCraft release JSONL (full / consensus / hard)."""
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    tasks: list[_DatasetTask] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        tid = row.get("task_id")
        if not isinstance(tid, str):
            continue
        tasks.append(
            _DatasetTask(
                task_id=tid,
                category=str(row.get("category", "unknown")),
                criteria=tuple(row.get("criteria", [])),
            )
        )
    return tasks


# ---------------------------------------------------------------------------
# Replay discovery
# ---------------------------------------------------------------------------


def _iter_trajectory_files(root: Path) -> list[Path]:
    tdir = root / "trajectories"
    if not tdir.exists():
        # Accept the root being the trajectories dir itself.
        tdir = root
    if not tdir.exists():
        return []
    return sorted(tdir.rglob("*.json"))


def _parse_trial_from_path(path: Path) -> int:
    """Best-effort: extract trial number from a ``..._tN.json`` filename."""
    stem = path.stem
    # Trajectories from the orchestrator end with ``_<seed>_t<N>``.
    parts = stem.rsplit("_t", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 1


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _pass_at_k(by_task: dict[str, list[_TrialVerdict]], k: int) -> float:
    """Fraction of tasks passed on at least one of k trials."""
    if not by_task:
        return 0.0
    wins = 0
    for trials in by_task.values():
        sub = trials[:k]
        if any(v.passed for v in sub):
            wins += 1
    return wins / len(by_task)


def _pass_caret_k(by_task: dict[str, list[_TrialVerdict]], k: int) -> float:
    """Fraction of tasks passed on ALL k trials (worst-case reliability)."""
    if not by_task:
        return 0.0
    wins = 0
    for trials in by_task.values():
        sub = trials[:k]
        if len(sub) < k:
            continue
        if all(v.passed for v in sub):
            wins += 1
    return wins / len(by_task)


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


# ---------------------------------------------------------------------------
# Replay driver (lazy imports so --help works without API keys)
# ---------------------------------------------------------------------------


def _run_replay(
    dataset_tasks: list[_DatasetTask],
    replay_root: Path,
    *,
    rubric_channel: str,
    trials: int,
    limit: int | None,
) -> list[_TrialVerdict]:
    """Replay saved trajectories against the current evaluator.

    LLM judge verdicts are taken from the saved trajectory (see
    :func:`healthcraft.tasks.evaluator.replay_from_trajectory`). Neither
    ensemble nor single-judge modes re-call the judge API during replay --
    that would cost money and break determinism. Ensemble mode is still
    meaningful here because the saved trajectories may carry
    ensemble-derived criteria_results when produced by the ensemble
    orchestrator path.
    """
    from healthcraft.tasks.evaluator import replay_from_trajectory
    from healthcraft.tasks.loader import load_tasks

    # Load task definitions once so we have the full rubric for replay.
    all_tasks = load_tasks(_PROJECT_ROOT / "configs" / "tasks")
    task_map = {t.id: t for t in all_tasks}

    dataset_ids = {t.task_id for t in dataset_tasks}
    trajectory_paths = _iter_trajectory_files(replay_root)

    verdicts: list[_TrialVerdict] = []
    for path in trajectory_paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        tid = data.get("task_id")
        if not isinstance(tid, str) or tid not in dataset_ids:
            continue
        task = task_map.get(tid)
        if task is None:
            continue
        trial = _parse_trial_from_path(path)
        if trial > trials:
            continue
        result = replay_from_trajectory(data, task, rubric_channel=rubric_channel)

        # Ambiguity count from saved trajectory (if the orchestrator wrote one).
        ambiguous = 0
        for cr in data.get("criteria_results", []):
            if cr.get("ambiguous"):
                ambiguous += 1
        agreement = data.get("judge_agreement_mean")
        verdicts.append(
            _TrialVerdict(
                task_id=tid,
                trial=trial,
                reward=float(result.reward),
                passed=bool(result.passed),
                safety_gate_passed=bool(result.safety_gate_passed),
                judge_agreement=(float(agreement) if isinstance(agreement, (int, float)) else None),
                ambiguous_criteria=ambiguous,
            )
        )

        if limit is not None and len({v.task_id for v in verdicts}) >= limit:
            break

    return verdicts


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _build_report(
    *,
    agent_model: str,
    dataset_name: str,
    verdicts: list[_TrialVerdict],
    trials: int,
    judge_mode: str,
) -> dict[str, Any]:
    by_task: dict[str, list[_TrialVerdict]] = defaultdict(list)
    for v in verdicts:
        by_task[v.task_id].append(v)
    for tid in by_task:
        by_task[tid].sort(key=lambda v: v.trial)

    pass_at_1 = _pass_at_k(by_task, 1)
    pass_at_3 = _pass_at_k(by_task, min(trials, 3))
    pass_caret_3 = _pass_caret_k(by_task, min(trials, 3))

    mean_reward = _mean(v.reward for v in verdicts)
    safety_pass_rate = _mean(1.0 if v.safety_gate_passed else 0.0 for v in verdicts)
    ambiguous_total = sum(v.ambiguous_criteria for v in verdicts)
    agreements = [v.judge_agreement for v in verdicts if v.judge_agreement is not None]
    judge_agreement_mean = _mean(agreements) if agreements else 0.0

    return {
        "agent_model": agent_model,
        "dataset": dataset_name,
        "judge_mode": judge_mode,
        "n_tasks": len(by_task),
        "n_trials_total": len(verdicts),
        "pass_at_1": round(pass_at_1, 4),
        "pass_at_k": {
            "1": round(pass_at_1, 4),
            "3": round(pass_at_3, 4),
        },
        "pass_caret_3": round(pass_caret_3, 4),
        "mean_reward": round(mean_reward, 4),
        "safety_gate_pass_rate": round(safety_pass_rate, 4),
        "ambiguous_criteria_encountered": ambiguous_total,
        "judge_agreement_mean": round(judge_agreement_mean, 4),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_judge_models(raw: str) -> list[str]:
    return [m.strip() for m in raw.split(",") if m.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Release JSONL (full / consensus / hard).",
    )
    p.add_argument(
        "--agent-model",
        type=str,
        required=True,
        help="Model identifier for the agent under evaluation.",
    )
    p.add_argument(
        "--judge-mode",
        choices=("ensemble", "single"),
        default="ensemble",
        help="Ensemble (default) or single cross-vendor judge.",
    )
    p.add_argument(
        "--judge-models",
        type=str,
        default="gpt-5.4,claude-opus-4-7,gemini-3.1-pro",
        help="Comma-separated judge-pool for ensemble mode.",
    )
    p.add_argument(
        "--trajectories-dir",
        type=Path,
        default=None,
        help="Where to write new trajectories (execution mode, not yet wired).",
    )
    p.add_argument(
        "--trials",
        type=int,
        default=3,
        help="Trials per task (default 3).",
    )
    p.add_argument(
        "--replay-from",
        type=Path,
        default=None,
        help=(
            "Replay saved trajectories under this dir instead of executing. "
            "v1.0 only supports this path."
        ),
    )
    p.add_argument(
        "--rubric-channel",
        type=str,
        default="v10",
        help="Rubric channel for replay (default v10).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit to the first N tasks (cost bound).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan; do not write or fetch anything.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    dataset_tasks = _load_dataset(args.dataset)
    if not dataset_tasks:
        print(f"ERROR: dataset empty: {args.dataset}", file=sys.stderr)
        return 1

    judge_pool = _parse_judge_models(args.judge_models)
    if args.judge_mode == "ensemble" and len(judge_pool) < 2:
        print(
            "ERROR: ensemble mode requires at least 2 judges in --judge-models",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print(
            f"[dry-run] agent={args.agent_model} dataset={args.dataset.name} "
            f"n_tasks={len(dataset_tasks)} judge_mode={args.judge_mode} "
            f"judges={judge_pool} trials={args.trials} "
            f"replay_from={args.replay_from} limit={args.limit}"
        )
        return 0

    if args.replay_from is None:
        print(
            "ERROR: Execution mode not yet implemented in v1.0; use "
            "--replay-from against existing trajectories.",
            file=sys.stderr,
        )
        return 1

    if not args.replay_from.exists():
        print(f"ERROR: --replay-from path does not exist: {args.replay_from}", file=sys.stderr)
        return 1

    verdicts = _run_replay(
        dataset_tasks,
        args.replay_from,
        rubric_channel=args.rubric_channel,
        trials=args.trials,
        limit=args.limit,
    )
    if not verdicts:
        print(
            f"ERROR: no replayable trajectories under {args.replay_from} for the given dataset",
            file=sys.stderr,
        )
        return 1

    report = _build_report(
        agent_model=args.agent_model,
        dataset_name=args.dataset.stem,
        verdicts=verdicts,
        trials=args.trials,
        judge_mode=args.judge_mode,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
