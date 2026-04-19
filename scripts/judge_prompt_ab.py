#!/usr/bin/env python3
"""A/B validate the tightened v2 judge prompt against the v1 baseline.

Uses the same 808 (criterion x trial) pairs as agreement_report.py, where the
world_state verdict (after v10 overlay) is the reference standard and the
original judge verdict (saved in the trajectory) is the v1 prediction.

For each pair we:
  1. Re-run the judge with prompt_version="v2" against the cached trajectory.
  2. Collect (world, judge_v1, judge_v2) triples.
  3. Compute PPA/NPA/kappa for v1 and v2 independently and report the delta.

Cost: 1 API call per pair, to the canonical judge model (GPT-5.4 for Claude
trajectories, Claude Opus for GPT/Gemini trajectories). Defaults to --sample 100
to keep cost bounded. Full 808 pairs costs roughly 2x the WSC-0 judge baseline.

Usage:
    python scripts/judge_prompt_ab.py \\
        --results results/pilot-v8-claude-opus results/pilot-v8-gpt54 \\
                  results/pilot-v9-gemini-pro \\
        --channel v10 \\
        --sample 100 \\
        --stratify safety_critical

Output:
    scripts-output/judge_prompt_ab_<channel>.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

# Import private helpers from agreement_report for consistency.
from agreement_report import (  # type: ignore  # noqa: E402
    _agreement_stats,
    _collect_pairs,
    _collect_trajectories,
)

from healthcraft.llm.agent import create_client  # noqa: E402
from healthcraft.llm.judge import LLMJudge, select_judge_model  # noqa: E402
from healthcraft.llm.orchestrator import _load_overlay  # noqa: E402
from healthcraft.tasks.loader import load_tasks  # noqa: E402
from healthcraft.tasks.rubrics import Criterion, VerificationMethod  # noqa: E402

_TASKS_DIR = _PROJECT_ROOT / "configs" / "tasks"
_OUT_DIR = _PROJECT_ROOT / "scripts-output"


def _judge_model_for_agent(agent_model: str) -> str:
    return select_judge_model(agent_model)


def _api_key_for_model(model: str) -> str:
    m = model.lower()
    if any(x in m for x in ("claude", "opus", "sonnet", "haiku")):
        return os.environ.get("ANTHROPIC_API_KEY", "")
    if "gpt" in m or "o1" in m or "o3" in m:
        return os.environ.get("OPENAI_API_KEY", "")
    if "gemini" in m:
        return os.environ.get("GOOGLE_API_KEY", "")
    if "grok" in m:
        return os.environ.get("XAI_API_KEY", "")
    return ""


def _load_criterion(
    task,
    criterion_id: str,
    overlay: dict[str, dict[str, str]] | None = None,
) -> Criterion | None:
    """Build a Criterion for the judge.

    The original task YAML is the source of truth for the assertion, dimension,
    and safety_critical fields. BUT for criteria that appear in the overlay,
    the overlay's ``check`` string is the operational restatement the judge
    benefits most from. Without this, the CHECK HINT branch in JUDGE_SYSTEM_\
    PROMPT_V2 goes unused on llm_judge-origin criteria (whose ``check`` field
    is typically empty in the task YAML).
    """
    overlay = overlay or {}
    for c in task.criteria:
        if c["id"] == criterion_id:
            overlay_check = overlay.get(criterion_id, {}).get("check", "")
            return Criterion(
                id=c["id"],
                assertion=c["assertion"],
                dimension=c.get("dimension", ""),
                verification=VerificationMethod(c.get("verification", "llm_judge")),
                check=overlay_check or c.get("check", ""),
                safety_critical=bool(c.get("safety_critical", False)),
            )
    return None


def _sample_rows(rows: list[dict], n: int, stratify: str | None, seed: int) -> list[dict]:
    if n >= len(rows):
        return rows
    rnd = random.Random(seed)
    if not stratify:
        return rnd.sample(rows, n)

    # Stratified sample: split rows by (stratify, world) so each cell gets
    # proportional representation. Useful for safety_critical=True world=FAIL
    # cells, which are the kappa bottleneck.
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[(r.get(stratify), r["world"])].append(r)
    out: list[dict] = []
    for key, bucket in buckets.items():
        share = max(1, round(n * len(bucket) / len(rows)))
        share = min(share, len(bucket))
        out.extend(rnd.sample(bucket, share))
    rnd.shuffle(out)
    return out[:n] if len(out) > n else out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--results", "-r", nargs="+", required=True, type=Path)
    p.add_argument("--channel", "-c", default="v10", choices=["v9", "v10"])
    p.add_argument("--sample", type=int, default=100, help="max pairs to judge (0 = all)")
    p.add_argument(
        "--stratify",
        choices=["safety_critical", "dimension", "category"],
        default="safety_critical",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect pairs and print plan, but do not call the judge API",
    )
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    overlay = _load_overlay(args.channel)
    overlay_ids = set(overlay.keys())
    if not overlay_ids:
        print(f"ERROR: overlay for channel {args.channel!r} is empty", file=sys.stderr)
        return 2

    tasks = load_tasks(_TASKS_DIR)
    task_map = {t.id: t for t in tasks}

    trajs = _collect_trajectories(args.results)
    rows = _collect_pairs(trajs, task_map, overlay_ids, args.channel)
    print(f"Collected {len(rows)} (criterion x trial) pairs.")

    sample = _sample_rows(
        rows, args.sample if args.sample > 0 else len(rows), args.stratify, args.seed
    )
    print(f"Sampled {len(sample)} pairs for A/B (stratify={args.stratify}, seed={args.seed}).")

    # Sample-composition report (pre-API, useful even in --dry-run)
    comp: dict[str, int] = defaultdict(int)
    for r in sample:
        comp[f"{r.get('safety_critical')}/{r['world']}"] += 1
    print(f"Sample composition (safety_critical/world): {dict(comp)}")

    if args.dry_run:
        print("[dry-run] exiting before API calls.")
        return 0

    # Build judge clients lazily, one per (judge_model). For Claude/GPT/Gemini
    # trajectories the judge_model is deterministic via select_judge_model.
    clients: dict[str, Any] = {}
    judges: dict[str, LLMJudge] = {}

    def _get_judge(agent_model: str) -> LLMJudge:
        jm = _judge_model_for_agent(agent_model)
        if jm not in judges:
            key = _api_key_for_model(jm)
            if not key:
                raise RuntimeError(f"No API key for judge model {jm}")
            clients[jm] = create_client(jm, key)
            judges[jm] = LLMJudge(clients[jm], judge_model=jm, prompt_version="v2")
        return judges[jm]

    # Group rows by trajectory to load each trajectory only once.
    by_traj: dict[str, list[dict]] = defaultdict(list)
    for r in sample:
        by_traj[r["trajectory"]].append(r)

    enriched: list[dict] = []
    errors = 0
    for tpath, trows in by_traj.items():
        traj_full = json.loads((_PROJECT_ROOT / tpath).read_text())
        turns = traj_full.get("turns", [])
        agent_model = traj_full.get("model", "")
        task = task_map[traj_full["task_id"]]
        try:
            judge = _get_judge(agent_model)
        except RuntimeError as e:
            print(f"[warn] skipping {tpath}: {e}", file=sys.stderr)
            errors += len(trows)
            continue

        for r in trows:
            crit = _load_criterion(task, r["criterion_id"], overlay)
            if crit is None:
                errors += 1
                continue
            try:
                res = judge.evaluate_criterion(crit, turns)
                v2 = int(bool(res.satisfied))
            except Exception as e:
                print(f"[warn] judge error on {r['criterion_id']}: {e}", file=sys.stderr)
                errors += 1
                continue
            enriched.append({**r, "judge_v2": v2})

    if not enriched:
        print("ERROR: no enriched rows collected", file=sys.stderr)
        return 2

    # Compute v1 and v2 stats on the enriched sample.
    world = [r["world"] for r in enriched]
    v1 = [r["judge"] for r in enriched]
    v2 = [r["judge_v2"] for r in enriched]

    s_v1 = _agreement_stats(world, v1)
    s_v2 = _agreement_stats(world, v2)

    # Also split safety_critical for the headline finding.
    sc_rows = [r for r in enriched if r.get("safety_critical")]
    sc_v1 = _agreement_stats([r["world"] for r in sc_rows], [r["judge"] for r in sc_rows])
    sc_v2 = _agreement_stats([r["world"] for r in sc_rows], [r["judge_v2"] for r in sc_rows])

    # Direction of disagreements v1->v2
    flips = {
        "v1_pass_v2_fail": sum(1 for a, b in zip(v1, v2) if a == 1 and b == 0),
        "v1_fail_v2_pass": sum(1 for a, b in zip(v1, v2) if a == 0 and b == 1),
        "unchanged_pass": sum(1 for a, b in zip(v1, v2) if a == 1 and b == 1),
        "unchanged_fail": sum(1 for a, b in zip(v1, v2) if a == 0 and b == 0),
    }

    def _pct(x: float) -> str:
        return "n/a" if math.isnan(x) else f"{x:.1%}"

    print("\n=== Overall (sample) ===")
    for label, s in (("v1", s_v1), ("v2", s_v2)):
        print(
            f"  {label}: n={s['n']} PPA={_pct(s['ppa'])} NPA={_pct(s['npa'])} "
            f"kappa={s['kappa']:.3f} acc={_pct(s['accuracy'])}"
        )
    print(f"\nSafety-critical subset (n={len(sc_rows)}):")
    for label, s in (("v1", sc_v1), ("v2", sc_v2)):
        print(f"  {label}: NPA={_pct(s['npa'])} PPA={_pct(s['ppa'])} kappa={s['kappa']:.3f}")
    print(f"\nv1 -> v2 flips: {flips}")
    print(f"errors: {errors}")

    out_path = args.out or (_OUT_DIR / f"judge_prompt_ab_{args.channel}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "channel": args.channel,
                "n_enriched": len(enriched),
                "sample_composition": dict(comp),
                "overall": {"v1": s_v1, "v2": s_v2},
                "safety_critical": {"v1": sc_v1, "v2": sc_v2},
                "flips": flips,
                "errors": errors,
                "rows": enriched,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    try:
        display = out_path.resolve().relative_to(_PROJECT_ROOT)
    except ValueError:
        display = out_path.resolve()
    print(f"\nReport: {display}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
