"""V9 overlay kappa validation gate.

Re-grades cached V8 trajectories under `rubric_channel=v9` and compares
deterministic world_state verdicts against the original V8 llm_judge
verdicts for each overlaid criterion. Emits Cohen's kappa per category.

Gate: ship the overlay iff every category with >= 10 observations has
kappa >= --min-kappa AND no safety_critical criterion inverts its verdict.

All computation is local -- no API calls. Uses cached trajectories only.

Usage:
    python scripts/kappa_validation.py
    python scripts/kappa_validation.py --results-dir results/pilot-v8-claude-opus
    python scripts/kappa_validation.py --min-kappa 0.80 --min-n 10
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import replace as dc_replace
from pathlib import Path

import yaml

from healthcraft.tasks.evaluator import (
    _audit_entry_matches_params,
    _build_agent_output,
    _build_replay_world,
    _extract_tool_and_params,
    evaluate_task,
)
from healthcraft.tasks.loader import load_task

# ---------------------------------------------------------------------------
# Disagreement classifier
# ---------------------------------------------------------------------------
#
# For every (criterion x trial) where v8 and v9 disagree, label the cause so
# we can separate "overlay is wrong" from "judge is wrong" from "simulator is
# wrong" from "the check can't express this reasoning". Ship decisions and
# the paper both need this split, not a single kappa number.
#
# Labels are evaluated in priority order -- the first matching rule wins.
# Order is chosen so higher-certainty structural diagnoses beat heuristic
# fallbacks.

_LABELS = (
    "overlay_wrong_entity",
    "infrastructure_error",
    "judge_hallucination",
    "intent_execution_split",
    "conditional_logic",
    "vocab_gap",
    "unknown",
)

# When an overlay check targets order_type=X but the assertion is actually
# about a different order family (auto-migration confusion). Each target
# maps to (substring_in_assertion, short_reason).
_WRONG_ENTITY_HINTS: dict[str, list[tuple[str, str]]] = {
    "blood_product": [
        ("blood culture", "assertion is about blood cultures (lab) not blood products"),
        ("blood gas", "assertion is about blood gas (lab) not blood products"),
        ("coag panel", "assertion is about coagulation labs not blood products"),
        ("coagulation panel", "assertion is about coagulation labs not blood products"),
        ("teg", "assertion is about TEG (lab) not blood products"),
        ("rotem", "assertion is about ROTEM (lab) not blood products"),
    ],
    "imaging": [
        ("transfusion", "assertion is about transfusion not imaging"),
        ("blood product", "assertion is about blood products not imaging"),
    ],
    "lab": [
        ("transfusion", "assertion is about transfusion not lab"),
        ("ct scan", "assertion is about imaging not lab"),
        ("mri", "assertion is about imaging not lab"),
        ("ultrasound", "assertion is about imaging not lab"),
    ],
    "medication": [
        ("transfusion", "assertion is about transfusion not medication"),
        ("blood product", "assertion is about blood products not medication"),
    ],
}

_CONDITIONAL_MARKERS = (
    " if ",
    "only if",
    "unless ",
    "provided that",
    "as long as",
    "contingent",
    "whichever",
)

_ACTION_VERBS = (
    "ordered",
    "administered",
    "documented",
    "requested",
    "initiated",
    "obtained",
    "applied",
    "activated",
    "prescribed",
    "performed",
    "placed",
)


def _parse_check_target(check: str) -> tuple[str, dict]:
    """Extract the tool name + match params from an overlay check string.

    Tries keywords in specificity order: ``attempt at`` first (it is a
    substring of ``contains`` so it must win), then ``contains`` / negations.
    """
    lc = check.lower()
    for keyword in ("attempt at", "does not contain", "not contain", "contains"):
        if keyword in lc:
            tool, params = _extract_tool_and_params(check, keyword)
            if tool:
                return tool, params
    return "", {}


def _classify_disagreement(
    overlay_entry: dict,
    assertion: str,
    v8_verdict: bool,
    v9_verdict: bool,
    audit_log: list,
) -> dict:
    """Label the cause of one v8/v9 disagreement on one trajectory.

    Returns a dict with the label, a short reason, and two counts used
    downstream for aggregate reporting.
    """
    check = overlay_entry.get("check", "")
    assertion_lc = (assertion or "").lower()
    tool, params = _parse_check_target(check)

    relevant_all = [e for e in audit_log if tool and e.tool_name.lower() == tool]
    relevant_matching = [e for e in relevant_all if _audit_entry_matches_params(e.params, params)]
    relevant_failed = [e for e in relevant_matching if e.result_summary == "error"]
    # After the `attempt at` tightening, only simulator-side failed calls
    # are legitimately "rescued" by v9. Agent-side failures (missing_param,
    # invalid_params, etc.) fall through to judge_hallucination.
    from healthcraft.tasks.evaluator import SIMULATOR_SIDE_ERROR_CODES

    sim_failed = [
        e for e in relevant_failed if getattr(e, "error_code", "") in SIMULATOR_SIDE_ERROR_CODES
    ]

    feats = {
        "relevant_tool_calls_found": len(relevant_all),
        "relevant_failed_calls_found": len(relevant_failed),
        "relevant_sim_side_failed_calls_found": len(sim_failed),
    }

    target = params.get("order_type") or params.get("_match") or params.get("_qualifier") or ""
    target_lc = str(target).lower().strip()

    # 1. overlay_wrong_entity -- the check targets the wrong bucket vs assertion.
    if target_lc in _WRONG_ENTITY_HINTS:
        for hint, reason in _WRONG_ENTITY_HINTS[target_lc]:
            if hint in assertion_lc:
                return {"label": "overlay_wrong_entity", "reason_short": reason, **feats}

    # 2. infrastructure_error -- narrow: a simulator-side failed call was
    # rescued by v9 "attempt at" semantics (v9=PASS). Agent-side malformed
    # calls are NOT infrastructure errors; those fall through below.
    if sim_failed and v9_verdict:
        codes = sorted({e.error_code for e in sim_failed})
        return {
            "label": "infrastructure_error",
            "reason_short": (
                f"{len(sim_failed)} simulator-side failed {tool} call(s) "
                f"rescued by v9 'attempt at' (codes={codes})"
            ),
            **feats,
        }

    # 3. judge_hallucination -- v8 PASS but no *successful* matching call exists.
    # Even when the agent tried and errored (malformed args), v8 credits the
    # agent's text over tool results -- that is judge confabulation.
    relevant_ok = [e for e in relevant_matching if e.result_summary == "ok"]
    if v8_verdict and not v9_verdict and not relevant_ok:
        if not relevant_all:
            reason = f"v8 PASS but zero {tool} calls in audit log"
        else:
            reason = (
                f"v8 PASS but no successful matching {tool} call "
                f"({len(relevant_failed)} failed, {len(relevant_all)} total)"
            )
        return {"label": "judge_hallucination", "reason_short": reason, **feats}

    # 4. intent_execution_split -- tool succeeded but structured param mismatch.
    if target_lc:
        ok_wrong_params = [
            e
            for e in relevant_all
            if e.result_summary == "ok" and not _audit_entry_matches_params(e.params, params)
        ]
        for e in ok_wrong_params:
            if target_lc in str(e.params).lower():
                return {
                    "label": "intent_execution_split",
                    "reason_short": (
                        f"{tool} succeeded but structured '{target}' did not match "
                        f"(found in free-form params)"
                    ),
                    **feats,
                }

    # 5. conditional_logic -- assertion encodes structure the overlay can't express.
    padded = f" {assertion_lc} "
    if any(m in padded for m in _CONDITIONAL_MARKERS):
        return {
            "label": "conditional_logic",
            "reason_short": "assertion contains conditional marker (if/unless/only if/...)",
            **feats,
        }
    if v8_verdict and not v9_verdict and " and " in assertion_lc:
        verb_hits = sum(
            1 for v in _ACTION_VERBS if f" {v} " in padded or padded.lstrip().startswith(v + " ")
        )
        if verb_hits >= 2:
            return {
                "label": "conditional_logic",
                "reason_short": "compound assertion (multiple action verbs) collapsed to single check",
                **feats,
            }

    # 6. vocab_gap -- target concept appears in audit but didn't structurally match.
    if target_lc:
        for e in audit_log:
            if target_lc in str(e.params).lower():
                return {
                    "label": "vocab_gap",
                    "reason_short": f"'{target}' appears in audit params but didn't match",
                    **feats,
                }

    return {"label": "unknown", "reason_short": "no classification rule matched", **feats}


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = PROJECT_ROOT / "configs" / "tasks"
OVERLAY_PATH = PROJECT_ROOT / "configs" / "rubrics" / "v9_deterministic_overlay.yaml"
DEFAULT_V8_DIRS = [
    PROJECT_ROOT / "results" / "pilot-v8-claude-opus",
    PROJECT_ROOT / "results" / "pilot-v8-gpt54",
]
REPORT_DIR = PROJECT_ROOT / "scripts-output"


def _cohen_kappa(y_true: list[int], y_pred: list[int]) -> float:
    """Cohen's kappa for binary labels. Returns NaN if undefined."""
    n = len(y_true)
    if n == 0:
        return math.nan
    po = sum(1 for a, b in zip(y_true, y_pred) if a == b) / n
    p1_t = sum(y_true) / n
    p1_p = sum(y_pred) / n
    pe = p1_t * p1_p + (1 - p1_t) * (1 - p1_p)
    if pe >= 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def _pabak(y_true: list[int], y_pred: list[int]) -> float:
    """Prevalence- and bias-adjusted kappa: 2*p_o - 1.
    Reports raw agreement rescaled to [-1, 1]. Unaffected by marginal
    prevalence -- useful when one class dominates (the 'kappa paradox').
    """
    n = len(y_true)
    if n == 0:
        return math.nan
    po = sum(1 for a, b in zip(y_true, y_pred) if a == b) / n
    return 2 * po - 1


def _load_overlay_raw() -> dict[str, dict]:
    """Read overlay YAML and return full entries (including review flags)."""
    data = yaml.safe_load(OVERLAY_PATH.read_text())
    return {e["criterion_id"]: e for e in data.get("overlays", [])}


def _find_task(task_id: str, cache: dict):
    if task_id in cache:
        return cache[task_id]
    for yaml_path in sorted(TASKS_DIR.rglob("*.yaml")):
        raw = yaml.safe_load(yaml_path.read_text())
        if raw.get("id") == task_id:
            cache[task_id] = load_task(yaml_path)
            return cache[task_id]
    cache[task_id] = None
    return None


def _criterion_meta(task, crit_id: str) -> dict:
    for c in task.criteria:
        if c["id"] == crit_id:
            return {
                "safety_critical": c.get("safety_critical", False),
                "dimension": c.get("dimension", ""),
                "original_verification": c.get("verification", ""),
                "original_check": c.get("check", ""),
                "assertion": c.get("assertion", ""),
            }
    return {
        "safety_critical": False,
        "dimension": "",
        "original_verification": "",
        "original_check": "",
        "assertion": "",
    }


def _apply_overlay(task, overlay: dict[str, dict]):
    """Rewrite matching criteria from llm_judge -> world_state.

    Mirrors orchestrator.py logic (lines 366-383): for each criterion with
    an overlay entry, replace verification + check. Non-overlaid criteria
    are untouched. Returns a new task object (frozen-dataclass-safe).
    """
    rewritten = []
    for raw in task.criteria:
        cid = raw["id"]
        if cid in overlay:
            e = overlay[cid]
            new = dict(raw)
            new["verification"] = e["verification"]
            new["check"] = e["check"]
            rewritten.append(new)
        else:
            rewritten.append(raw)
    return dc_replace(task, criteria=tuple(rewritten))


def collect_pairs(
    traj_path: Path,
    overlay: dict[str, dict],
    tasks_cache: dict,
) -> list[dict]:
    overlay_ids = set(overlay.keys())
    try:
        traj = json.loads(traj_path.read_text())
    except Exception as e:
        return [{"error": f"parse {traj_path.name}: {e}"}]

    # Skip error trajectories -- v8 verdicts there are also degenerate
    if traj.get("error"):
        return []

    task_id = traj.get("task_id")
    if not task_id:
        return []
    task = _find_task(task_id, tasks_cache)
    if task is None:
        return []

    task_crit_ids = {c["id"] for c in task.criteria}
    affected = task_crit_ids & overlay_ids
    if not affected:
        return []

    v8_verdicts = {r["id"]: bool(r.get("satisfied")) for r in traj.get("criteria_results", [])}

    try:
        world = _build_replay_world(traj)
        agent_output = _build_agent_output(traj)
        eval_task = _apply_overlay(task, overlay)
        v9_result = evaluate_task(eval_task, agent_output, world, rubric_channel="v9")
    except Exception as e:
        return [{"error": f"regrade {traj_path.name}: {e}"}]

    v9_verdicts = {r.criterion_id: r.satisfied for r in v9_result.criteria_results}
    audit_snapshot = list(world.audit_log)

    category = getattr(task, "category", "unknown")
    pairs = []
    for crit_id in affected:
        if crit_id not in v8_verdicts or crit_id not in v9_verdicts:
            continue
        meta = _criterion_meta(task, crit_id)
        # Original verification matters: we can only validate the overlay
        # against criteria that were originally llm_judge (that's the point
        # of overlaying them). world_state->world_state is tautological.
        v8 = v8_verdicts[crit_id]
        v9 = v9_verdicts[crit_id]
        row = {
            "task_id": task_id,
            "criterion_id": crit_id,
            "category": category,
            "safety_critical": meta["safety_critical"],
            "dimension": meta["dimension"],
            "original_verification": meta["original_verification"],
            "assertion": meta["assertion"],
            "v8": int(v8),
            "v9": int(v9),
            "agree": v8 == v9,
            "trajectory": str(traj_path.resolve().relative_to(PROJECT_ROOT)),
            "model": traj.get("model", ""),
        }
        if v8 != v9:
            cls = _classify_disagreement(
                overlay[crit_id],
                meta["assertion"],
                v8_verdict=bool(v8),
                v9_verdict=bool(v9),
                audit_log=audit_snapshot,
            )
            row.update(cls)
        pairs.append(row)
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results-dir", action="append", type=Path, default=None)
    parser.add_argument("--min-kappa", type=float, default=0.80)
    parser.add_argument(
        "--min-n",
        type=int,
        default=10,
        help="Skip kappa gate for categories with fewer observations (too noisy)",
    )
    parser.add_argument("--report", type=Path, default=REPORT_DIR / "kappa_report.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    results_dirs = args.results_dir or DEFAULT_V8_DIRS
    overlay = _load_overlay_raw()
    overlay_ids = set(overlay.keys())
    flagged_ids = {cid for cid, e in overlay.items() if e.get("migration_review_needed")}

    traj_files: list[Path] = []
    for d in results_dirs:
        traj_dir = d / "trajectories"
        if not traj_dir.exists():
            print(f"WARN: missing {traj_dir}", file=sys.stderr)
            continue
        traj_files.extend(sorted(traj_dir.rglob("*.json")))

    if not traj_files:
        print("ERROR: no trajectories found", file=sys.stderr)
        return 2

    print(f"Scanning {len(traj_files)} trajectories from {len(results_dirs)} dirs")
    print(f"Overlay: {len(overlay_ids)} criteria ({len(flagged_ids)} flagged for review)")

    tasks_cache: dict = {}
    pairs: list[dict] = []
    errors: list[str] = []
    for tf in traj_files:
        out = collect_pairs(tf, overlay, tasks_cache)
        for item in out:
            if "error" in item:
                errors.append(item["error"])
            else:
                pairs.append(item)

    if errors and args.verbose:
        print(f"\n{len(errors)} trajectories had errors (first 5):")
        for e in errors[:5]:
            print(f"  {e}")

    if not pairs:
        print("ERROR: no overlapping overlaid criteria in V8 trajectories", file=sys.stderr)
        return 2

    print(f"Collected {len(pairs)} (criterion x trial) observations")
    print(
        f"  Agreement: {sum(1 for p in pairs if p['agree'])}/{len(pairs)} = "
        f"{sum(1 for p in pairs if p['agree']) / len(pairs):.1%}\n"
    )

    # Overall kappa
    overall_kappa = _cohen_kappa([p["v8"] for p in pairs], [p["v9"] for p in pairs])

    # Per-category
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        by_cat[p["category"]].append(p)
    cat_stats: dict[str, dict] = {}
    for cat, ps in by_cat.items():
        ys_v8 = [p["v8"] for p in ps]
        ys_v9 = [p["v9"] for p in ps]
        kk = _cohen_kappa(ys_v8, ys_v9)
        pabak = _pabak(ys_v8, ys_v9)
        n_agree = sum(1 for p in ps if p["agree"])
        cat_stats[cat] = {
            "kappa": kk,
            "pabak": pabak,
            "n": len(ps),
            "n_agree": n_agree,
            "agreement_rate": n_agree / len(ps),
            "prevalence_v8": sum(ys_v8) / len(ps),
            "prevalence_v9": sum(ys_v9) / len(ps),
        }

    # Per-criterion disagreement
    by_crit: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        by_crit[p["criterion_id"]].append(p)
    crit_disagree = []
    for cid, ps in by_crit.items():
        dis = [p for p in ps if not p["agree"]]
        if dis:
            crit_disagree.append(
                {
                    "criterion_id": cid,
                    "task_id": ps[0]["task_id"],
                    "category": ps[0]["category"],
                    "safety_critical": ps[0]["safety_critical"],
                    "flagged_for_review": cid in flagged_ids,
                    "assertion": ps[0]["assertion"][:120],
                    "n_obs": len(ps),
                    "n_disagree": len(dis),
                    "v8_yes_v9_no": sum(1 for p in dis if p["v8"] == 1 and p["v9"] == 0),
                    "v8_no_v9_yes": sum(1 for p in dis if p["v8"] == 0 and p["v9"] == 1),
                }
            )
    crit_disagree.sort(key=lambda x: (-x["n_disagree"], x["criterion_id"]))

    # Safety-critical inversions
    safety_invs = [p for p in pairs if p["safety_critical"] and not p["agree"]]

    # Disagreement classification rollups
    disagreements = [p for p in pairs if not p["agree"]]
    label_counts: dict[str, int] = {lbl: 0 for lbl in _LABELS}
    label_counts_safety: dict[str, int] = {lbl: 0 for lbl in _LABELS}
    label_by_category: dict[str, dict[str, int]] = defaultdict(lambda: {lbl: 0 for lbl in _LABELS})
    for p in disagreements:
        lbl = p.get("label", "unknown")
        label_counts[lbl] = label_counts.get(lbl, 0) + 1
        label_by_category[p["category"]][lbl] = label_by_category[p["category"]].get(lbl, 0) + 1
        if p["safety_critical"]:
            label_counts_safety[lbl] = label_counts_safety.get(lbl, 0) + 1

    # Per-criterion label set -> tier recommendation
    # Tier 1: every trial agrees -> deterministic-safe, use for reward
    # Tier 2: only judge_hallucination and/or infrastructure_error disagreements
    #   -> research_only; v9 is plausibly more correct than v8
    # Tier 3: any other label -> not reward-safe; keep as llm_judge
    tier_safe = {"judge_hallucination", "infrastructure_error"}
    per_crit_labels: dict[str, set[str]] = defaultdict(set)
    for p in disagreements:
        per_crit_labels[p["criterion_id"]].add(p.get("label", "unknown"))
    tier_assignment: dict[str, str] = {}
    for cid in overlay_ids:
        lbls = per_crit_labels.get(cid, set())
        if not lbls:
            tier_assignment[cid] = "tier_1_reward_safe"
        elif lbls.issubset(tier_safe):
            tier_assignment[cid] = "tier_2_research_only"
        else:
            tier_assignment[cid] = "tier_3_keep_llm_judge"
    tier_counts: dict[str, int] = defaultdict(int)
    for t in tier_assignment.values():
        tier_counts[t] += 1

    # Gate
    gate_kappa_pass = True
    gate_fails = []
    for cat, s in cat_stats.items():
        if s["n"] >= args.min_n and not math.isnan(s["kappa"]) and s["kappa"] < args.min_kappa:
            gate_kappa_pass = False
            gate_fails.append(cat)
    gate_safety_pass = len(safety_invs) == 0
    gate_pass = gate_kappa_pass and gate_safety_pass

    report = {
        "summary": {
            "n_trajectories": len(traj_files),
            "n_observations": len(pairs),
            "n_errors": len(errors),
            "overall_kappa": overall_kappa,
            "overall_agreement": sum(1 for p in pairs if p["agree"]) / len(pairs),
            "min_kappa_gate": args.min_kappa,
            "min_n_per_category": args.min_n,
            "gate_kappa_pass": gate_kappa_pass,
            "gate_safety_pass": gate_safety_pass,
            "gate_pass": gate_pass,
            "failed_categories": gate_fails,
            "n_safety_inversions": len(safety_invs),
        },
        "by_category": cat_stats,
        "criterion_disagreements": crit_disagree,
        "safety_inversions": safety_invs,
        "disagreement_labels": {
            "counts": label_counts,
            "counts_safety_critical": label_counts_safety,
            "by_category": {k: dict(v) for k, v in label_by_category.items()},
        },
        "tier_assignment": tier_assignment,
        "tier_counts": dict(tier_counts),
        "disagreement_rows": disagreements,
    }

    # Stdout summary
    print(
        f"Overall kappa:      {overall_kappa:.3f}  (agree {report['summary']['overall_agreement']:.1%}, n={len(pairs)})"
    )
    print(
        f"Gate: kappa >= {args.min_kappa} per category (min n={args.min_n}), zero safety inversions\n"
    )
    print(
        f"{'Category':<28} {'n':>5} {'agree':>8} {'prev_v8':>8} {'prev_v9':>8} "
        f"{'kappa':>8} {'pabak':>8}"
    )
    print("-" * 80)
    for cat, s in sorted(
        cat_stats.items(), key=lambda kv: (math.isnan(kv[1]["kappa"]), kv[1]["kappa"])
    ):
        flag = ""
        if math.isnan(s["kappa"]):
            flag = " n/a"
        elif s["n"] < args.min_n:
            flag = " (low-n)"
        elif s["kappa"] < args.min_kappa:
            flag = " FAIL"
        print(
            f"{cat:<28} {s['n']:>5} {s['agreement_rate']:>7.1%} "
            f"{s['prevalence_v8']:>7.1%} {s['prevalence_v9']:>7.1%} "
            f"{s['kappa']:>8.3f} {s['pabak']:>8.3f}{flag}"
        )

    print(f"\nCriteria with any disagreement: {len(crit_disagree)}")
    if crit_disagree:
        print(
            f"{'criterion_id':<14} {'task':<8} {'category':<24} {'sc':<3} {'flg':<4} "
            f"{'n':>3} {'dis':>3} {'v8y/v9n':>8} {'v8n/v9y':>8}"
        )
        print("-" * 90)
        for c in crit_disagree[:30]:
            sc = "Y" if c["safety_critical"] else "-"
            flg = "R" if c["flagged_for_review"] else "-"
            print(
                f"{c['criterion_id']:<14} {c['task_id']:<8} {c['category'][:24]:<24} "
                f"{sc:<3} {flg:<4} {c['n_obs']:>3} {c['n_disagree']:>3} "
                f"{c['v8_yes_v9_no']:>8} {c['v8_no_v9_yes']:>8}"
            )
        if len(crit_disagree) > 30:
            print(f"  ... +{len(crit_disagree) - 30} more")

    if safety_invs:
        print(f"\nSAFETY-CRITICAL verdict inversions: {len(safety_invs)}")
        for p in safety_invs[:10]:
            direction = "v8=PASS -> v9=FAIL" if p["v8"] == 1 else "v8=FAIL -> v9=PASS"
            lbl = p.get("label", "unlabeled")
            print(f"  {p['criterion_id']}  {direction}  [{lbl}]  {p['trajectory']}")
    else:
        print("\nZero safety-critical verdict inversions.")

    # Disagreement taxonomy
    total_dis = len(disagreements)
    if total_dis:
        print(f"\nDisagreement classification ({total_dis} disagreeing observations):")
        print(f"{'label':<24} {'all':>6} {'safety':>8}")
        print("-" * 42)
        for lbl in _LABELS:
            n = label_counts.get(lbl, 0)
            ns = label_counts_safety.get(lbl, 0)
            if n == 0 and ns == 0:
                continue
            pct = f"{n / total_dis:.0%}" if total_dis else "-"
            print(f"{lbl:<24} {n:>6} ({pct:>3})  {ns:>4}")
        print(f"\nTier assignment ({len(overlay_ids)} overlay criteria):")
        for tier in ("tier_1_reward_safe", "tier_2_research_only", "tier_3_keep_llm_judge"):
            print(f"  {tier:<28} {tier_counts.get(tier, 0):>3}")

    print(
        f"\nGate: {'PASS' if gate_pass else 'FAIL'}"
        f"  (kappa {'pass' if gate_kappa_pass else 'fail'}, "
        f"safety {'pass' if gate_safety_pass else 'fail'})"
    )

    REPORT_DIR.mkdir(exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, default=str))
    print(f"Report: {args.report.relative_to(PROJECT_ROOT)}")

    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())
