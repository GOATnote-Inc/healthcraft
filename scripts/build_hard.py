#!/usr/bin/env python3
"""HealthCraft-Hard builder: bottom-quantile frontier-failure task subset.

HealthCraft-Hard mirrors HealthBench-Hard: the bottom fraction of tasks ranked
by mean frontier-agent reward. These are the tasks that current frontier
models fail on most -- the bench-saturation reserve.

For every task_id with >= ``--min-trials-per-task`` successful (non-error)
trajectories across the ``--results`` pilot dirs, we compute:

  * ``n_trials_total``        -- non-error trials across all models
  * ``models_covered``        -- distinct models with >= 1 non-error trial
  * ``mean_reward``           -- simple mean of reward across non-error trials
  * ``pass_rate``             -- mean of ``passed`` flags
  * ``safety_gate_pass_rate`` -- mean of ``safety_gate_passed`` flags
  * ``per_model``             -- per-model n / mean_reward / pass_rate

Tasks below ``--min-trials-per-task`` are skipped as insufficient-signal and
emitted to the dropped list with reason ``insufficient_trials``. Eligible
tasks are ranked ascending by ``mean_reward`` (tiebreak: ``pass_rate`` asc,
then ``task_id`` lex) and the bottom ``--quantile`` fraction is taken.

Artifacts emitted:
  * ``<output>.jsonl``   -- one line per HARD task, hardest first
  * ``<manifest>.yaml``  -- structured run manifest with dropped-task log

Usage::

    python scripts/build_hard.py \\
        --results results/pilot-v8-claude-opus \\
                  results/pilot-v8-gpt54 \\
                  results/pilot-v9-gemini-pro \\
        --quantile 0.20 \\
        --min-trials-per-task 6 \\
        --output data/hard/healthcraft_hard_v1.jsonl \\
        --manifest data/hard/hard_tasks.yaml

With only ``--dry-run`` (or no ``--output``), no files are written -- we walk
the trajectories and print stats. Exit 0 iff the mean pass rate on the
selected HARD subset is <= 0.35 (HealthBench-Hard parity: o3 scored 32% on
HealthBench-Hard). Exit 1 otherwise -- this is the CI gate.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from healthcraft.tasks.loader import Task, load_tasks  # noqa: E402

_TASKS_DIR = _PROJECT_ROOT / "configs" / "tasks"
_HARDNESS_GATE = 0.35  # HealthBench-Hard parity: o3 ~ 32%


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TrialRecord:
    """One non-error trajectory's reducible summary."""

    task_id: str
    model: str
    reward: float
    passed: bool
    safety_gate_passed: bool


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _iter_trajectory_files(results_dirs: Iterable[Path]) -> list[Path]:
    """Walk ``<dir>/trajectories/**/*.json`` under each results dir."""
    paths: list[Path] = []
    for rd in results_dirs:
        tdir = rd / "trajectories"
        if not tdir.exists():
            print(f"[warn] no trajectories dir under {rd}", file=sys.stderr)
            continue
        for path in sorted(tdir.rglob("*.json")):
            paths.append(path)
    return paths


def _load_trajectory(
    path: Path,
    *,
    exclude_error: bool,
) -> tuple[dict | None, str]:
    """Load a trajectory JSON. Return ``(data_or_None, status)``.

    Status is one of: ``"ok"``, ``"unreadable"``, ``"error_flag"``,
    ``"missing_reward"``. ``data`` is returned on ``"ok"`` only.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[warn] skipping {path}: {e}", file=sys.stderr)
        return None, "unreadable"
    if exclude_error and data.get("error"):
        return None, "error_flag"
    if data.get("reward") is None:
        return None, "missing_reward"
    return data, "ok"


def _record_from_trajectory(data: dict) -> _TrialRecord | None:
    """Pull the reducible fields off a trajectory dict."""
    task_id = data.get("task_id")
    model = data.get("model")
    reward = data.get("reward")
    if not isinstance(task_id, str) or not isinstance(model, str):
        return None
    if not isinstance(reward, (int, float)):
        return None
    passed = bool(data.get("passed", False))
    safety = bool(data.get("safety_gate_passed", False))
    return _TrialRecord(
        task_id=task_id,
        model=model,
        reward=float(reward),
        passed=passed,
        safety_gate_passed=safety,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _group_records(
    records: Iterable[_TrialRecord],
) -> dict[str, dict[str, list[_TrialRecord]]]:
    """Group by task_id -> model -> [records]."""
    grouped: dict[str, dict[str, list[_TrialRecord]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        grouped[r.task_id][r.model].append(r)
    return grouped


def _mean(values: list[float]) -> float:
    n = len(values)
    if n == 0:
        return math.nan
    return sum(values) / n


def _task_summary(
    task_id: str,
    by_model: dict[str, list[_TrialRecord]],
    task: Task | None,
) -> dict[str, Any]:
    """Compute the per-task summary dict used for ranking and emission."""
    all_records: list[_TrialRecord] = []
    per_model: dict[str, dict[str, float | int]] = {}
    for model, recs in by_model.items():
        all_records.extend(recs)
        per_model[model] = {
            "n": len(recs),
            "mean_reward": _mean([r.reward for r in recs]),
            "pass_rate": _mean([1.0 if r.passed else 0.0 for r in recs]),
        }

    n_total = len(all_records)
    mean_reward = _mean([r.reward for r in all_records])
    pass_rate = _mean([1.0 if r.passed else 0.0 for r in all_records])
    safety_rate = _mean([1.0 if r.safety_gate_passed else 0.0 for r in all_records])

    criteria = task.criteria if task is not None else ()
    criteria_count = len(criteria)
    safety_critical_count = sum(
        1 for c in criteria if isinstance(c, dict) and c.get("safety_critical")
    )
    category = task.category if task is not None else "unknown"

    return {
        "task_id": task_id,
        "category": category,
        "n_trials": n_total,
        "models_covered": sorted(by_model.keys()),
        "mean_reward": mean_reward,
        "pass_rate": pass_rate,
        "safety_gate_pass_rate": safety_rate,
        "per_model": per_model,
        "criteria_count": criteria_count,
        "safety_critical_count": safety_critical_count,
    }


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _rank_and_select(
    summaries: list[dict[str, Any]],
    quantile: float,
) -> tuple[list[dict[str, Any]], float | None]:
    """Rank ascending by (mean_reward, pass_rate, task_id); take bottom ``quantile``.

    Returns ``(hard_summaries, threshold_mean_reward)``. ``threshold_mean_reward``
    is the largest ``mean_reward`` in the selected bottom subset (the cutoff
    below which -- inclusive -- tasks are considered hard), or ``None`` when
    the selection is empty.
    """
    if not summaries or quantile <= 0:
        return [], None

    ranked = sorted(
        summaries,
        key=lambda s: (s["mean_reward"], s["pass_rate"], s["task_id"]),
    )
    n_hard = max(1, math.ceil(len(ranked) * quantile))
    n_hard = min(n_hard, len(ranked))
    selected = ranked[:n_hard]
    threshold = selected[-1]["mean_reward"] if selected else None
    return selected, threshold


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, payload: str) -> None:
    """Write ``payload`` atomically (tmp in same dir, then ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _round_or_nan(x: float, ndigits: int = 4) -> float:
    if isinstance(x, float) and math.isnan(x):
        return x
    return round(float(x), ndigits)


def _emit_jsonl(output: Path, hard: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    for rank, entry in enumerate(hard, start=1):
        per_model_out: dict[str, dict[str, float | int]] = {}
        for model, stats in entry["per_model"].items():
            per_model_out[model] = {
                "n": int(stats["n"]),
                "mean_reward": _round_or_nan(float(stats["mean_reward"])),
                "pass_rate": _round_or_nan(float(stats["pass_rate"])),
            }
        line = {
            "task_id": entry["task_id"],
            "category": entry["category"],
            "rank": rank,
            "n_trials": entry["n_trials"],
            "models_covered": entry["models_covered"],
            "mean_reward": _round_or_nan(entry["mean_reward"]),
            "pass_rate": _round_or_nan(entry["pass_rate"]),
            "safety_gate_pass_rate": _round_or_nan(entry["safety_gate_pass_rate"]),
            "per_model": per_model_out,
            "criteria_count": entry["criteria_count"],
            "safety_critical_count": entry["safety_critical_count"],
        }
        lines.append(json.dumps(line, ensure_ascii=False, sort_keys=True))
    _atomic_write(output, "\n".join(lines) + ("\n" if lines else ""))


def _emit_manifest(
    manifest: Path,
    *,
    results_dirs: list[Path],
    quantile: float,
    min_trials_per_task: int,
    exclude_error: bool,
    n_tasks_total: int,
    n_eligible: int,
    hard: list[dict[str, Any]],
    threshold_mean_reward: float | None,
    overall_pass_rate: float,
    by_category: dict[str, int],
    dropped: list[dict[str, Any]],
    trajectory_stats: dict[str, int],
) -> None:
    payload: dict[str, Any] = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "results_dirs": [str(r) for r in results_dirs],
            "quantile": quantile,
            "min_trials_per_task": min_trials_per_task,
            "exclude_error_trajectories": exclude_error,
        },
        "stats": {
            "n_tasks_total": n_tasks_total,
            "n_eligible": n_eligible,
            "n_hard": len(hard),
            "threshold_mean_reward": (
                _round_or_nan(threshold_mean_reward) if threshold_mean_reward is not None else None
            ),
            "overall_frontier_pass_rate_on_hard": _round_or_nan(overall_pass_rate),
            "by_category": dict(sorted(by_category.items())),
            "trajectories_seen": trajectory_stats["seen"],
            "trajectories_used": trajectory_stats["used"],
            "trajectories_error": trajectory_stats["error"],
            "trajectories_unreadable": trajectory_stats["unreadable"],
            "trajectories_missing_reward": trajectory_stats["missing_reward"],
        },
        "dropped_tasks": dropped,
    }
    _atomic_write(manifest, yaml.safe_dump(payload, sort_keys=False))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--results",
        "-r",
        nargs="+",
        required=True,
        type=Path,
        help="One or more pilot trajectory dirs; each must contain trajectories/.",
    )
    p.add_argument(
        "--quantile",
        type=float,
        default=0.20,
        help="Bottom-quantile fraction of tasks to select as HARD (default 0.20).",
    )
    p.add_argument(
        "--min-trials-per-task",
        type=int,
        default=6,
        help="Minimum non-error trials per task to be eligible (default 6).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination JSONL for the HARD subset. Omitting implies --dry-run.",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Destination YAML for the run manifest (default: alongside --output).",
    )
    p.add_argument(
        "--tasks-dir",
        type=Path,
        default=_TASKS_DIR,
        help=f"Task YAML directory (default {_TASKS_DIR}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print stats; do not write artifacts.",
    )
    p.add_argument(
        "--exclude-error-trajectories",
        dest="exclude_error",
        action="store_true",
        default=True,
        help="Exclude trajectories with an 'error' field (default: True).",
    )
    p.add_argument(
        "--include-error-trajectories",
        dest="exclude_error",
        action="store_false",
        help="Count error trajectories as reward=0 trials instead of skipping.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    dry_run = args.dry_run or args.output is None
    if dry_run and args.output is None:
        print("[info] no --output given; running in dry-run mode (no files written).")

    if args.quantile <= 0.0 or args.quantile > 1.0:
        print(
            f"ERROR: --quantile must be in (0, 1]; got {args.quantile}",
            file=sys.stderr,
        )
        return 2

    tasks = load_tasks(args.tasks_dir)
    task_map: dict[str, Task] = {t.id: t for t in tasks}

    trajectory_paths = _iter_trajectory_files(args.results)
    if not trajectory_paths:
        print("ERROR: no trajectories found under --results", file=sys.stderr)
        return 2

    records: list[_TrialRecord] = []
    trajectory_stats = {
        "seen": 0,
        "used": 0,
        "error": 0,
        "unreadable": 0,
        "missing_reward": 0,
    }
    for path in trajectory_paths:
        trajectory_stats["seen"] += 1
        data, status = _load_trajectory(path, exclude_error=args.exclude_error)
        if status == "unreadable":
            trajectory_stats["unreadable"] += 1
            continue
        if status == "error_flag":
            trajectory_stats["error"] += 1
            continue
        if status == "missing_reward":
            trajectory_stats["missing_reward"] += 1
            continue
        assert data is not None  # for type-checkers
        rec = _record_from_trajectory(data)
        if rec is None:
            trajectory_stats["missing_reward"] += 1
            continue
        records.append(rec)
        trajectory_stats["used"] += 1

    if not records:
        print("ERROR: no usable trajectories after filtering", file=sys.stderr)
        return 2

    grouped = _group_records(records)

    # Build per-task summaries, partitioning into eligible vs dropped.
    summaries: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for task_id in sorted(grouped.keys()):
        by_model = grouped[task_id]
        task = task_map.get(task_id)
        summary = _task_summary(task_id, by_model, task)
        if summary["n_trials"] < args.min_trials_per_task:
            dropped.append(
                {
                    "task_id": task_id,
                    "reason": "insufficient_trials",
                    "n_trials": summary["n_trials"],
                    "models_covered": summary["models_covered"],
                }
            )
            continue
        summaries.append(summary)

    n_tasks_total = len(grouped)
    n_eligible = len(summaries)

    hard, threshold = _rank_and_select(summaries, args.quantile)

    # Category breakdown of HARD subset.
    by_category: dict[str, int] = defaultdict(int)
    for entry in hard:
        by_category[entry["category"]] += 1

    # Overall frontier pass rate on HARD -- trial-weighted across all models.
    total_trials = sum(e["n_trials"] for e in hard)
    if total_trials > 0:
        overall_pass_rate = sum(e["pass_rate"] * e["n_trials"] for e in hard) / total_trials
    else:
        overall_pass_rate = math.nan

    if not dry_run and args.output is not None:
        _emit_jsonl(args.output, hard)
        manifest_path = args.manifest or args.output.with_suffix(".yaml")
        _emit_manifest(
            manifest_path,
            results_dirs=list(args.results),
            quantile=args.quantile,
            min_trials_per_task=args.min_trials_per_task,
            exclude_error=args.exclude_error,
            n_tasks_total=n_tasks_total,
            n_eligible=n_eligible,
            hard=hard,
            threshold_mean_reward=threshold,
            overall_pass_rate=overall_pass_rate,
            by_category=dict(by_category),
            dropped=dropped,
            trajectory_stats=trajectory_stats,
        )
        print(f"[ok] wrote JSONL:    {args.output}")
        print(f"[ok] wrote manifest: {manifest_path}")

    # Stdout summary.
    pass_rate_str = "nan" if math.isnan(overall_pass_rate) else f"{overall_pass_rate:.3f}"
    threshold_str = "n/a" if threshold is None else f"{threshold:.3f}"
    print(
        f"tasks_total={n_tasks_total} eligible={n_eligible} hard={len(hard)} "
        f"(quantile={args.quantile}, min_trials={args.min_trials_per_task}), "
        f"threshold_mean_reward={threshold_str}, "
        f"overall_frontier_pass_rate_on_hard={pass_rate_str}"
    )
    print(
        f"trajectories_seen={trajectory_stats['seen']} "
        f"used={trajectory_stats['used']} "
        f"error={trajectory_stats['error']} "
        f"unreadable={trajectory_stats['unreadable']} "
        f"missing_reward={trajectory_stats['missing_reward']}"
    )
    if by_category:
        cats = ", ".join(f"{k}={v}" for k, v in sorted(by_category.items()))
        print(f"by_category: {cats}")
    if dropped:
        print(f"dropped: {len(dropped)} task(s) for insufficient_trials")

    if math.isnan(overall_pass_rate):
        # Empty HARD subset cannot pass the gate.
        return 1
    if overall_pass_rate <= _HARDNESS_GATE:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
