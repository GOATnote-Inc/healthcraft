#!/usr/bin/env python3
"""HealthCraft-Consensus builder: compute-consensus criterion filter.

The compute-consensus subset is the HealthCraft equivalent of HealthBench's
physician-applicability filter. For every ``llm_judge`` criterion exercised
by the V8/V9 trajectories, a three-judge ensemble (see
``healthcraft.llm.ensemble_judge``) votes independently. We then compute:

  * per-criterion mean agreement across trajectories
  * per-criterion Fleiss' kappa across judges
  * overall Fleiss' kappa over the flattened (criterion, trajectory) matrix
  * slice breakdowns by safety_critical / dimension / category

The Consensus subset is the set of criteria with mean agreement
>= ``--min-agreement`` across >= ``--min-trajectories`` trajectories.

Artifacts emitted:
  * ``<output>.jsonl``   -- one line per eligible criterion
  * ``<manifest>.yaml``  -- structured run manifest with dropped-criterion log

Usage::

    python scripts/build_consensus.py \\
        --results results/pilot-v8-claude-opus \\
                  results/pilot-v8-gpt54 \\
                  results/pilot-v9-gemini-pro \\
        --min-agreement 0.85 \\
        --min-trajectories 3 \\
        --output data/consensus/healthcraft_consensus_v1.jsonl \\
        --manifest data/consensus/consensus_criteria.yaml

With only ``--dry-run`` (or no ``--output``), no API calls are made: we walk
the ensemble cache only and report hit/miss counts. Exit 0 if overall Fleiss'
kappa >= 0.70, exit 1 otherwise (CI gate).
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

from healthcraft.llm.ensemble_judge import EnsembleJudge  # noqa: E402
from healthcraft.tasks.loader import Task, load_tasks  # noqa: E402
from healthcraft.tasks.rubrics import Criterion, VerificationMethod  # noqa: E402

_TASKS_DIR = _PROJECT_ROOT / "configs" / "tasks"
_DEFAULT_CACHE_DIR = _PROJECT_ROOT / "results" / "ensemble_cache"
_KAPPA_GATE = 0.70


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _fleiss_kappa(votes: list[list[int]]) -> float:
    """Compute Fleiss' kappa for a (subjects x raters) binary vote matrix.

    Implements the standard formula for k=2 categories::

        P_i    = (1 / (n(n-1))) * sum_j n_ij * (n_ij - 1)
        P_bar  = mean(P_i)
        p_j    = (1 / (N * n)) * sum_i n_ij
        P_e    = sum_j p_j^2
        kappa  = (P_bar - P_e) / (1 - P_e)

    Degenerate inputs -- fewer than two subjects, uneven row widths, or
    P_e == 1 (every rater unanimous across all subjects) -- return ``nan``.

    Args:
        votes: ``[[0/1, 0/1, ...], ...]``. Each row is one subject, each
            column is one rater. Every row must share the same length.

    Returns:
        Fleiss' kappa in roughly ``[-1, 1]``, or ``nan`` for degenerate input.
    """
    n_subjects = len(votes)
    if n_subjects < 2:
        return math.nan

    n_raters = len(votes[0])
    if n_raters < 2:
        return math.nan
    for row in votes:
        if len(row) != n_raters:
            return math.nan

    # n_ij counts: per subject, how many raters voted category j (j in {0, 1}).
    # Per-subject agreement P_i = sum_j n_ij(n_ij - 1) / (n(n-1)).
    denom_subject = n_raters * (n_raters - 1)
    p_i_values: list[float] = []
    n_j_total = [0, 0]  # total votes for category 0, category 1 across all subjects
    for row in votes:
        n1 = sum(row)
        n0 = n_raters - n1
        n_j_total[0] += n0
        n_j_total[1] += n1
        p_i = (n0 * (n0 - 1) + n1 * (n1 - 1)) / denom_subject
        p_i_values.append(p_i)

    p_bar = sum(p_i_values) / n_subjects
    grand_total = n_subjects * n_raters
    p_j = [n_j_total[0] / grand_total, n_j_total[1] / grand_total]
    p_e = p_j[0] ** 2 + p_j[1] ** 2

    if p_e >= 1.0:
        return math.nan
    return (p_bar - p_e) / (1.0 - p_e)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Verdict:
    """One ensemble result tied to a trajectory plus static criterion metadata."""

    criterion_id: str
    task_id: str
    assertion: str
    dimension: str
    safety_critical: bool
    category: str
    trajectory_id: str
    votes: tuple[int, ...]  # in judge-pool order
    agreement_score: float
    ensemble_satisfied: bool


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


def _load_trajectory(path: Path) -> dict | None:
    """Load a trajectory JSON; return None for errors/unreadable files."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[warn] skipping {path}: {e}", file=sys.stderr)
        return None
    if data.get("error"):
        return None
    if data.get("reward") is None:
        return None
    return data


def _stable_trajectory_id(path: Path) -> str:
    """Trajectory id used as ensemble cache key -- path relative to repo root."""
    try:
        rel = path.resolve().relative_to(_PROJECT_ROOT)
    except ValueError:
        rel = path.resolve()
    return str(rel)


# ---------------------------------------------------------------------------
# Criteria
# ---------------------------------------------------------------------------


def _llm_judge_criteria(task: Task) -> list[Criterion]:
    """Materialise the ``llm_judge`` criteria on a task as ``Criterion`` objects."""
    out: list[Criterion] = []
    for raw in task.criteria:
        if raw.get("verification") != "llm_judge":
            continue
        out.append(
            Criterion(
                id=raw["id"],
                assertion=raw.get("assertion", ""),
                dimension=raw.get("dimension", "unknown"),
                verification=VerificationMethod.LLM_JUDGE,
                check=raw.get("check", ""),
                safety_critical=bool(raw.get("safety_critical", False)),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _build_ensembles(
    agent_models: Iterable[str],
    cache_dir: Path,
) -> dict[str, EnsembleJudge]:
    """Pre-build one ``EnsembleJudge`` per distinct agent model.

    The ensemble filters same-vendor judges automatically, so we key by model.
    """
    ensembles: dict[str, EnsembleJudge] = {}
    for model in agent_models:
        if model in ensembles:
            continue
        ensembles[model] = EnsembleJudge(
            agent_model=model,
            cache_dir=cache_dir,
        )
    return ensembles


def _collect_verdicts(
    trajectory_paths: list[Path],
    task_map: dict[str, Task],
    cache_dir: Path,
    dry_run: bool,
    limit_trajectories: int | None,
) -> tuple[list[_Verdict], dict[str, int], list[str]]:
    """Materialise one verdict per (trajectory, llm_judge criterion).

    In ``dry_run`` mode we read the ensemble cache only and skip any criterion
    whose judges are not all cached -- no API calls.

    Returns:
        ``(verdicts, stats, judge_pool)`` where ``stats`` counts
        ``trajectories_seen``, ``trajectories_used``, ``criteria_evaluated``,
        ``cache_hits``, ``cache_misses``, ``dry_run_skipped``.
    """
    verdicts: list[_Verdict] = []
    stats: dict[str, int] = {
        "trajectories_seen": 0,
        "trajectories_used": 0,
        "trajectories_skipped_error": 0,
        "trajectories_skipped_no_task": 0,
        "criteria_evaluated": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "dry_run_skipped": 0,
    }
    judge_pool: list[str] = []

    ensembles: dict[str, EnsembleJudge] = {}
    used = 0

    for path in trajectory_paths:
        if limit_trajectories is not None and used >= limit_trajectories:
            break
        stats["trajectories_seen"] += 1
        traj = _load_trajectory(path)
        if traj is None:
            stats["trajectories_skipped_error"] += 1
            continue

        task_id = traj.get("task_id", "")
        task = task_map.get(task_id)
        if task is None:
            stats["trajectories_skipped_no_task"] += 1
            continue

        llm_criteria = _llm_judge_criteria(task)
        if not llm_criteria:
            continue

        agent_model = traj.get("model", "")
        if not agent_model:
            stats["trajectories_skipped_error"] += 1
            continue

        if agent_model not in ensembles:
            try:
                ensembles[agent_model] = EnsembleJudge(
                    agent_model=agent_model,
                    cache_dir=cache_dir,
                )
            except (ValueError, RuntimeError) as e:
                if not dry_run:
                    raise
                # Dry-run: fall back to synthesising judge pool from default.
                print(f"[info] dry-run: {agent_model}: {e}", file=sys.stderr)
                continue

        ensemble = ensembles[agent_model]
        if not judge_pool:
            judge_pool = list(ensemble.judge_models)

        trajectory_id = _stable_trajectory_id(path)
        turns = traj.get("turns", [])
        used_this_trajectory = False

        for crit in llm_criteria:
            if dry_run:
                # Only use the criterion if every judge has a cached verdict.
                all_cached = True
                per_judge_votes: list[int] = []
                for judge_model in ensemble.judge_models:
                    cache_entry = _read_ensemble_cache_entry(
                        cache_dir=cache_dir,
                        judge_model=judge_model,
                        trajectory_id=trajectory_id,
                        criterion_id=crit.id,
                        prompt_version="v2",
                    )
                    if cache_entry is None:
                        all_cached = False
                        stats["cache_misses"] += 1
                        break
                    stats["cache_hits"] += 1
                    per_judge_votes.append(1 if cache_entry["satisfied"] else 0)
                if not all_cached:
                    stats["dry_run_skipped"] += 1
                    continue
                agreement_score = _agreement_from_votes(per_judge_votes)
                ensemble_satisfied = sum(per_judge_votes) >= 2
                verdicts.append(
                    _Verdict(
                        criterion_id=crit.id,
                        task_id=task.id,
                        assertion=crit.assertion,
                        dimension=crit.dimension,
                        safety_critical=crit.safety_critical,
                        category=task.category,
                        trajectory_id=trajectory_id,
                        votes=tuple(per_judge_votes),
                        agreement_score=agreement_score,
                        ensemble_satisfied=ensemble_satisfied,
                    )
                )
                stats["criteria_evaluated"] += 1
                used_this_trajectory = True
                continue

            # Live path: run the ensemble -- its own cache will prevent API
            # calls for already-seen (judge, trajectory, criterion) tuples.
            result = ensemble.evaluate_criterion(crit, turns, trajectory_id)
            votes = tuple(
                1 if result.per_judge.get(jm, False) else 0 for jm in ensemble.judge_models
            )
            verdicts.append(
                _Verdict(
                    criterion_id=crit.id,
                    task_id=task.id,
                    assertion=crit.assertion,
                    dimension=crit.dimension,
                    safety_critical=crit.safety_critical,
                    category=task.category,
                    trajectory_id=trajectory_id,
                    votes=votes,
                    agreement_score=float(result.agreement_score),
                    ensemble_satisfied=bool(result.satisfied),
                )
            )
            stats["criteria_evaluated"] += 1
            used_this_trajectory = True

        if used_this_trajectory:
            stats["trajectories_used"] += 1
            used += 1

    return verdicts, stats, judge_pool


def _agreement_from_votes(votes: list[int]) -> float:
    """Majority-size / n, matching the ensemble's own agreement score."""
    n = len(votes)
    if n == 0:
        return 0.0
    trues = sum(votes)
    falses = n - trues
    return max(trues, falses) / n


def _read_ensemble_cache_entry(
    *,
    cache_dir: Path,
    judge_model: str,
    trajectory_id: str,
    criterion_id: str,
    prompt_version: str,
) -> dict | None:
    """Read one per-judge cache entry. Returns None on miss / version skew."""
    safe_model = judge_model.replace("/", "_")
    safe_traj = trajectory_id.replace("/", "_")
    safe_crit = criterion_id.replace("/", "_")
    path = cache_dir / safe_model / safe_traj / f"{safe_crit}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("prompt_version") != prompt_version:
        return None
    if "satisfied" not in data:
        return None
    return data


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _per_criterion_stats(verdicts: list[_Verdict]) -> dict[str, dict]:
    """Group verdicts by criterion_id and compute summary stats."""
    groups: dict[str, list[_Verdict]] = defaultdict(list)
    for v in verdicts:
        groups[v.criterion_id].append(v)

    out: dict[str, dict] = {}
    for cid, items in groups.items():
        n = len(items)
        mean_agreement = sum(v.agreement_score for v in items) / n
        votes_matrix = [list(v.votes) for v in items]
        kappa = _fleiss_kappa(votes_matrix)
        pass_rate = sum(1 for v in items if v.ensemble_satisfied) / n
        sample = items[0]
        out[cid] = {
            "criterion_id": cid,
            "task_id": sample.task_id,
            "assertion": sample.assertion,
            "dimension": sample.dimension,
            "safety_critical": sample.safety_critical,
            "category": sample.category,
            "n_trajectories": n,
            "mean_agreement": mean_agreement,
            "fleiss_kappa": kappa,
            "ensemble_verdict_pass_rate": pass_rate,
        }
    return out


def _slice_kappa(verdicts: list[_Verdict], key: str) -> dict[str, dict]:
    """Fleiss' kappa + count for each value of ``key`` (e.g. dimension)."""
    groups: dict[str, list[_Verdict]] = defaultdict(list)
    for v in verdicts:
        groups[str(getattr(v, key))].append(v)
    out: dict[str, dict] = {}
    for label, items in groups.items():
        matrix = [list(v.votes) for v in items]
        out[label] = {
            "n": len(items),
            "fleiss_kappa": _fleiss_kappa(matrix),
        }
    return out


def _overall_kappa(verdicts: list[_Verdict]) -> float:
    if not verdicts:
        return math.nan
    return _fleiss_kappa([list(v.votes) for v in verdicts])


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _nan_to_str(x: float) -> float | str:
    """Render ``nan`` as the string ``"nan"`` per the manifest contract."""
    if isinstance(x, float) and math.isnan(x):
        return "nan"
    return x


def _atomic_write(path: Path, payload: str) -> None:
    """Write ``payload`` atomically (tmp in same dir, then os.replace)."""
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


def _emit_jsonl(
    output: Path,
    eligible: list[dict],
) -> None:
    lines: list[str] = []
    for entry in eligible:
        line = {
            "criterion_id": entry["criterion_id"],
            "task_id": entry["task_id"],
            "assertion": entry["assertion"],
            "dimension": entry["dimension"],
            "safety_critical": entry["safety_critical"],
            "n_trajectories": entry["n_trajectories"],
            "mean_agreement": round(entry["mean_agreement"], 4),
            "fleiss_kappa": _nan_to_str(round(entry["fleiss_kappa"], 4))
            if not math.isnan(entry["fleiss_kappa"])
            else "nan",
            "ensemble_verdict_pass_rate": round(entry["ensemble_verdict_pass_rate"], 4),
        }
        lines.append(json.dumps(line, ensure_ascii=False, sort_keys=True))
    _atomic_write(output, "\n".join(lines) + ("\n" if lines else ""))


def _emit_manifest(
    manifest: Path,
    *,
    results_dirs: list[Path],
    min_agreement: float,
    min_trajectories: int,
    n_trajectories_total: int,
    judge_pool: list[str],
    prompt_version: str,
    per_criterion: dict[str, dict],
    eligible_ids: set[str],
    dropped: list[dict],
    overall_kappa: float,
    by_safety_critical: dict[str, dict],
    by_dimension: dict[str, dict],
    by_category: dict[str, dict],
    n_ambiguous_dropped: int,
) -> None:
    def _stringify_slice(raw: dict[str, dict]) -> dict[str, dict]:
        return {
            key: {"n": val["n"], "fleiss_kappa": _nan_to_str(val["fleiss_kappa"])}
            for key, val in raw.items()
        }

    payload: dict[str, Any] = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "results_dirs": [str(r) for r in results_dirs],
            "n_trajectories_total": n_trajectories_total,
            "min_agreement": min_agreement,
            "min_trajectories": min_trajectories,
        },
        "ensemble": {
            "judge_pool": judge_pool,
            "prompt_version": prompt_version,
        },
        "stats": {
            "n_llm_judge_criteria_evaluated": len(per_criterion),
            "n_consensus_eligible": len(eligible_ids),
            "n_ambiguous_dropped": n_ambiguous_dropped,
            "overall_fleiss_kappa": _nan_to_str(overall_kappa),
            "by_safety_critical": _stringify_slice(by_safety_critical),
            "by_dimension": _stringify_slice(by_dimension),
            "by_category": _stringify_slice(by_category),
        },
        "dropped_criteria": dropped,
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
        "--min-agreement",
        type=float,
        default=0.85,
        help="Mean-agreement threshold for consensus eligibility (default 0.85).",
    )
    p.add_argument(
        "--min-trajectories",
        type=int,
        default=3,
        help="Minimum trajectories per criterion for consensus eligibility (default 3).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination JSONL for eligible criteria. Omitting implies --dry-run.",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Destination YAML for the run manifest (default: alongside --output).",
    )
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=_DEFAULT_CACHE_DIR,
        help=f"Ensemble per-judge cache root (default {_DEFAULT_CACHE_DIR}).",
    )
    p.add_argument(
        "--limit-trajectories",
        type=int,
        default=None,
        help="Process at most N trajectories across all --results (cost bound).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Never call APIs. Use ensemble cache only; count hits / misses.",
    )
    p.add_argument(
        "--tasks-dir",
        type=Path,
        default=_TASKS_DIR,
        help=f"Task YAML directory (default {_TASKS_DIR}).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    dry_run = args.dry_run or args.output is None
    if dry_run and args.output is None:
        print("[info] no --output given; running in dry-run mode (no API calls).")

    tasks = load_tasks(args.tasks_dir)
    task_map: dict[str, Task] = {t.id: t for t in tasks}

    trajectory_paths = _iter_trajectory_files(args.results)
    if not trajectory_paths:
        print("ERROR: no trajectories found under --results", file=sys.stderr)
        return 2

    verdicts, stats, judge_pool = _collect_verdicts(
        trajectory_paths=trajectory_paths,
        task_map=task_map,
        cache_dir=args.cache_dir,
        dry_run=dry_run,
        limit_trajectories=args.limit_trajectories,
    )

    if not verdicts:
        print(
            "[warn] no verdicts collected -- either cache is empty for dry-run "
            "or no llm_judge criteria were exercised.",
            file=sys.stderr,
        )

    per_criterion = _per_criterion_stats(verdicts)

    eligible: list[dict] = []
    dropped: list[dict] = []
    n_ambiguous_dropped = 0
    for cid, row in per_criterion.items():
        if row["n_trajectories"] < args.min_trajectories:
            dropped.append(
                {
                    "criterion_id": cid,
                    "reason": "insufficient_trajectories",
                    "n_trajectories": row["n_trajectories"],
                    "mean_agreement": round(row["mean_agreement"], 4),
                }
            )
            continue
        if row["mean_agreement"] < args.min_agreement:
            dropped.append(
                {
                    "criterion_id": cid,
                    "reason": "mean_agreement_below_threshold",
                    "n_trajectories": row["n_trajectories"],
                    "mean_agreement": round(row["mean_agreement"], 4),
                }
            )
            n_ambiguous_dropped += 1
            continue
        eligible.append(row)

    eligible_ids = {row["criterion_id"] for row in eligible}

    overall_kappa = _overall_kappa(verdicts)
    by_sc = _slice_kappa(verdicts, "safety_critical")
    by_dim = _slice_kappa(verdicts, "dimension")
    by_cat = _slice_kappa(verdicts, "category")

    if args.output is not None:
        _emit_jsonl(args.output, eligible)
        manifest_path = args.manifest or args.output.with_suffix(".yaml")
        _emit_manifest(
            manifest=manifest_path,
            results_dirs=list(args.results),
            min_agreement=args.min_agreement,
            min_trajectories=args.min_trajectories,
            n_trajectories_total=stats["trajectories_used"],
            judge_pool=judge_pool,
            prompt_version="v2",
            per_criterion=per_criterion,
            eligible_ids=eligible_ids,
            dropped=dropped,
            overall_kappa=overall_kappa,
            by_safety_critical=by_sc,
            by_dimension=by_dim,
            by_category=by_cat,
            n_ambiguous_dropped=n_ambiguous_dropped,
        )
        print(f"[ok] wrote JSONL:    {args.output}")
        print(f"[ok] wrote manifest: {manifest_path}")

    kappa_str = "nan" if math.isnan(overall_kappa) else f"{overall_kappa:.3f}"
    print(
        f"N criteria evaluated={len(per_criterion)}, "
        f"K eligible={len(eligible)} (overall Fleiss kappa={kappa_str}), "
        f"dropped {n_ambiguous_dropped} for ambiguity, "
        f"{len(dropped) - n_ambiguous_dropped} for insufficient trajectories."
    )
    print(
        f"trajectories_used={stats['trajectories_used']}/{stats['trajectories_seen']} "
        f"criteria_evaluated={stats['criteria_evaluated']} "
        f"cache_hits={stats['cache_hits']} cache_misses={stats['cache_misses']} "
        f"dry_run_skipped={stats['dry_run_skipped']}"
    )

    if math.isnan(overall_kappa) or overall_kappa < _KAPPA_GATE:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
