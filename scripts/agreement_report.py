#!/usr/bin/env python3
"""Judge-vs-world_state agreement report: raw agreement, PPA, NPA, 2x2, kappa.

For every trajectory under --results whose task has a criterion listed in the
chosen overlay channel, we pair two verdicts:

  * judge   = the saved llm_judge verdict from the trajectory's criteria_results
  * world   = the re-derived world_state verdict from the reconstructed audit
              log after applying the overlay (v9 or v10)

Because the world_state verdict is a deterministic function of the audit log,
we treat it as the reference standard. Output:

  * Raw agreement      = (TP + TN) / N
  * PPA (sensitivity)  = TP / (TP + FN)   -- among world=PASS cases, how often
                                             does the judge also say PASS?
  * NPA (specificity)  = TN / (TN + FP)   -- among world=FAIL cases, how often
                                             does the judge also say FAIL?
  * 2x2 confusion      = [[TP, FN], [FP, TN]]  rows=world, cols=judge
  * Cohen's kappa (chance-corrected agreement)
  * PABAK (prevalence- and bias-adjusted kappa)

Splits: overall + per-category + per-dimension + per-safety_critical.

No API calls. Uses cached trajectories only.

Usage:
    # Full v10 report over 1,780 V8 + V9 trajectories
    python scripts/agreement_report.py \\
        --results results/pilot-v8-claude-opus \\
                  results/pilot-v8-gpt54 \\
                  results/pilot-v9-gemini-pro \\
        --channel v10

    # Compare v9 baseline (existing gate semantics)
    python scripts/agreement_report.py \\
        --results results/pilot-v8-claude-opus \\
        --channel v9
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from healthcraft.llm.orchestrator import _load_overlay  # noqa: E402
from healthcraft.tasks.evaluator import replay_from_trajectory  # noqa: E402
from healthcraft.tasks.loader import load_tasks  # noqa: E402

_TASKS_DIR = _PROJECT_ROOT / "configs" / "tasks"
_OUT_DIR = _PROJECT_ROOT / "scripts-output"


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _cohen_kappa(reference: list[int], predicted: list[int]) -> float:
    n = len(reference)
    if n == 0:
        return math.nan
    po = sum(1 for a, b in zip(reference, predicted) if a == b) / n
    p1_r = sum(reference) / n
    p1_p = sum(predicted) / n
    pe = p1_r * p1_p + (1 - p1_r) * (1 - p1_p)
    if pe >= 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def _pabak(reference: list[int], predicted: list[int]) -> float:
    n = len(reference)
    if n == 0:
        return math.nan
    po = sum(1 for a, b in zip(reference, predicted) if a == b) / n
    return 2 * po - 1


def _agreement_stats(reference: list[int], predicted: list[int]) -> dict:
    """Treat reference (world_state) as the gold standard and predicted (judge)
    as the test. Return PPA, NPA, accuracy, kappa, PABAK, and the 2x2."""
    n = len(reference)
    if n == 0:
        return {
            "n": 0,
            "tp": 0,
            "fn": 0,
            "fp": 0,
            "tn": 0,
            "accuracy": math.nan,
            "ppa": math.nan,
            "npa": math.nan,
            "kappa": math.nan,
            "pabak": math.nan,
            "prevalence_world": math.nan,
            "prevalence_judge": math.nan,
        }

    tp = sum(1 for r, p in zip(reference, predicted) if r == 1 and p == 1)
    fn = sum(1 for r, p in zip(reference, predicted) if r == 1 and p == 0)
    fp = sum(1 for r, p in zip(reference, predicted) if r == 0 and p == 1)
    tn = sum(1 for r, p in zip(reference, predicted) if r == 0 and p == 0)

    ppa = tp / (tp + fn) if (tp + fn) else math.nan
    npa = tn / (tn + fp) if (tn + fp) else math.nan
    acc = (tp + tn) / n

    return {
        "n": n,
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "accuracy": acc,
        "ppa": ppa,
        "npa": npa,
        "kappa": _cohen_kappa(reference, predicted),
        "pabak": _pabak(reference, predicted),
        "prevalence_world": sum(reference) / n,
        "prevalence_judge": sum(predicted) / n,
    }


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


def _collect_trajectories(results_dirs: list[Path]) -> list[tuple[Path, dict]]:
    pairs: list[tuple[Path, dict]] = []
    for rd in results_dirs:
        tdir = rd / "trajectories"
        if not tdir.exists():
            print(f"[warn] no trajectories dir under {rd}", file=sys.stderr)
            continue
        for path in sorted(tdir.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                print(f"[warn] skipping {path}: {e}", file=sys.stderr)
                continue
            if data.get("error"):
                continue
            pairs.append((path, data))
    return pairs


def _collect_pairs(
    trajs: list[tuple[Path, dict]],
    task_map: dict,
    overlay_ids: set[str],
    channel: str,
) -> list[dict]:
    """For each trajectory x overlaid criterion, produce (world, judge) rows.

    ``world`` comes from replay_from_trajectory(..., rubric_channel=channel):
    for overlaid criteria the overlay rewrites llm_judge -> world_state and
    the audit log is consulted.

    ``judge`` comes from the saved criteria_results entry in the trajectory
    (i.e., the verdict the judge delivered during the pilot).
    """
    rows: list[dict] = []
    skipped_no_task = 0
    skipped_no_overlap = 0
    replay_errors = 0

    for path, traj in trajs:
        task_id = traj.get("task_id", "")
        task = task_map.get(task_id)
        if task is None:
            skipped_no_task += 1
            continue

        task_crit_ids = {c["id"] for c in task.criteria}
        affected = task_crit_ids & overlay_ids
        if not affected:
            skipped_no_overlap += 1
            continue

        try:
            res = replay_from_trajectory(traj, task, rubric_channel=channel)
        except Exception as e:
            print(f"[warn] replay {path.name}: {e}", file=sys.stderr)
            replay_errors += 1
            continue

        # Saved per-criterion judge verdicts (original llm_judge output).
        saved = {cr["id"]: bool(cr.get("satisfied")) for cr in traj.get("criteria_results", [])}
        # Re-derived per-criterion world_state verdicts after overlay.
        fresh = {cr.criterion_id: cr.satisfied for cr in res.criteria_results}

        # Criterion metadata lookup for slice labels.
        crit_meta = {c["id"]: c for c in task.criteria}

        for cid in affected:
            if cid not in saved or cid not in fresh:
                continue
            meta = crit_meta[cid]
            # Only the criteria whose ORIGINAL verification was llm_judge
            # measure judge reliability. world_state -> world_state overlays
            # (rare) would be tautological here.
            if meta.get("verification") != "llm_judge":
                continue

            rows.append(
                {
                    "task_id": task_id,
                    "criterion_id": cid,
                    "category": getattr(task, "category", "unknown"),
                    "dimension": meta.get("dimension", "unknown"),
                    "safety_critical": bool(meta.get("safety_critical", False)),
                    "model": traj.get("model", ""),
                    "world": int(fresh[cid]),
                    "judge": int(saved[cid]),
                    "trajectory": str(path.resolve().relative_to(_PROJECT_ROOT)),
                }
            )

    if skipped_no_task:
        print(f"[info] skipped {skipped_no_task} trajectories with unknown task_id")
    if skipped_no_overlap:
        print(f"[info] skipped {skipped_no_overlap} trajectories with no overlaid criterion")
    if replay_errors:
        print(f"[warn] {replay_errors} replay errors")
    return rows


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _group_stats(rows: list[dict], key: str) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[str(r[key])].append(r)
    out: dict[str, dict] = {}
    for k, rs in grouped.items():
        out[k] = _agreement_stats(
            [r["world"] for r in rs],
            [r["judge"] for r in rs],
        )
    return out


def _fmt_pct(x: float) -> str:
    if math.isnan(x):
        return "  n/a"
    return f"{x:6.1%}"


def _fmt_flt(x: float) -> str:
    if math.isnan(x):
        return "  n/a"
    return f"{x:6.3f}"


def _print_slice_table(title: str, stats: dict[str, dict], sort_by: str = "n") -> None:
    print(f"\n=== {title} ===")
    print(
        f"{'slice':<30} {'n':>5} {'TP':>4} {'FN':>4} {'FP':>4} {'TN':>4} "
        f"{'PPA':>7} {'NPA':>7} {'acc':>7} {'kappa':>7} {'pabak':>7}"
    )
    print("-" * 98)

    if sort_by == "n":
        ordered = sorted(stats.items(), key=lambda kv: -kv[1]["n"])
    else:
        ordered = sorted(stats.items(), key=lambda kv: kv[0])

    for name, s in ordered:
        print(
            f"{name[:30]:<30} {s['n']:>5} {s['tp']:>4} {s['fn']:>4} {s['fp']:>4} {s['tn']:>4} "
            f"{_fmt_pct(s['ppa'])} {_fmt_pct(s['npa'])} {_fmt_pct(s['accuracy'])} "
            f"{_fmt_flt(s['kappa'])} {_fmt_flt(s['pabak'])}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--results", "-r", nargs="+", required=True, type=Path)
    p.add_argument("--channel", "-c", default="v10", choices=["v9", "v10"])
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON output path (default: scripts-output/agreement_report_<channel>.json)",
    )
    args = p.parse_args()

    overlay = _load_overlay(args.channel)
    overlay_ids = set(overlay.keys())
    if not overlay_ids:
        print(f"ERROR: overlay for channel {args.channel!r} is empty", file=sys.stderr)
        return 2

    tasks = load_tasks(_TASKS_DIR)
    task_map = {t.id: t for t in tasks}

    trajs = _collect_trajectories(args.results)
    if not trajs:
        print("ERROR: no trajectories loaded", file=sys.stderr)
        return 2

    print(
        f"Loaded {len(trajs)} trajectories. "
        f"Overlay channel {args.channel}: {len(overlay_ids)} criteria."
    )

    rows = _collect_pairs(trajs, task_map, overlay_ids, args.channel)
    if not rows:
        print("ERROR: no (world, judge) pairs collected", file=sys.stderr)
        return 2

    print(f"Collected {len(rows)} (criterion x trial) pairs with llm_judge origin.\n")

    # Overall
    overall = _agreement_stats([r["world"] for r in rows], [r["judge"] for r in rows])
    print("=== Overall ===")
    print(f"  n             = {overall['n']}")
    print(f"  TP / FN       = {overall['tp']} / {overall['fn']}")
    print(f"  FP / TN       = {overall['fp']} / {overall['tn']}")
    print(f"  Accuracy      = {_fmt_pct(overall['accuracy'])}")
    print(f"  PPA (sens)    = {_fmt_pct(overall['ppa'])}")
    print(f"  NPA (spec)    = {_fmt_pct(overall['npa'])}")
    print(f"  Cohen's kappa = {_fmt_flt(overall['kappa'])}")
    print(f"  PABAK         = {_fmt_flt(overall['pabak'])}")
    print(f"  prev(world)   = {_fmt_pct(overall['prevalence_world'])}")
    print(f"  prev(judge)   = {_fmt_pct(overall['prevalence_judge'])}")

    by_cat = _group_stats(rows, "category")
    by_dim = _group_stats(rows, "dimension")
    by_sc = _group_stats(rows, "safety_critical")
    by_model = _group_stats(rows, "model")
    by_crit = _group_stats(rows, "criterion_id")

    _print_slice_table("Per category", by_cat)
    _print_slice_table("Per dimension", by_dim)
    _print_slice_table("Per safety_critical", by_sc, sort_by="key")
    _print_slice_table("Per model", by_model)

    # Top noisy criteria (lowest kappa with enough observations)
    noisy = [
        (cid, s)
        for cid, s in by_crit.items()
        if s["n"] >= 3 and not math.isnan(s["kappa"]) and s["kappa"] < 0.5
    ]
    noisy.sort(key=lambda kv: (kv[1]["kappa"], -kv[1]["n"]))
    if noisy:
        print(f"\n=== {len(noisy)} per-criterion slices with kappa < 0.5 (n>=3) ===")
        print(f"{'criterion_id':<15} {'n':>4} {'PPA':>7} {'NPA':>7} {'kappa':>7}")
        for cid, s in noisy[:25]:
            print(
                f"{cid:<15} {s['n']:>4} {_fmt_pct(s['ppa'])} {_fmt_pct(s['npa'])} "
                f"{_fmt_flt(s['kappa'])}"
            )

    # Emit JSON
    out_path = args.out or (_OUT_DIR / f"agreement_report_{args.channel}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "channel": args.channel,
        "results_dirs": [str(r) for r in args.results],
        "n_trajectories": len(trajs),
        "n_pairs": len(rows),
        "overall": overall,
        "by_category": by_cat,
        "by_dimension": by_dim,
        "by_safety_critical": by_sc,
        "by_model": by_model,
        "by_criterion": by_crit,
        "noisy_criteria": [{"criterion_id": cid, **s} for cid, s in noisy],
    }
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nReport: {out_path.relative_to(_PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
