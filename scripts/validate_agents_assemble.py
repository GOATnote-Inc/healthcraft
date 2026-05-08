"""Validation harness for the Agents Assemble submission.

Runs the four labeled clinical scenarios end-to-end through the triage
agent and prints a metrics summary that maps to the hackathon's
"clear hypothesis for how this improves outcomes, reduces costs, or
saves time" judging criterion. Produces:

- per-scenario verdict (correct rule? correct risk? correct disposition?)
- aggregate sensitivity / specificity for HIGH-risk identification
- safety-gate trigger rate when disposition is forced to discharge for
  HIGH-risk scenarios (this is the core safety story)
- bundle hash for each scenario (proof of input-determinism)

No API keys required — uses the deterministic extractor + in-process
agent. The same harness will exercise the LLM extractor when an LLM
client is wired (deterministic by virtue of temperature=0).

Usage:

    python scripts/validate_agents_assemble.py
    python scripts/validate_agents_assemble.py --scenario stemi
    python scripts/validate_agents_assemble.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

from healthcraft.agents_assemble.agent_triage.agent import (
    DifferentialItem,
    _self_evaluate,
    create_triage_agent,
)
from healthcraft.agents_assemble.demo.bundles import Scenario, list_scenarios, load_scenario
from healthcraft.agents_assemble.superpower_decision_rules.sharp import bundle_hash
from healthcraft.entities.decision_rules import load_decision_rules
from healthcraft.world.state import WorldState


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    expected_rule: str
    expected_risk: str
    expected_disposition: str
    actual_rule: str | None
    actual_risk: str | None
    actual_disposition: str | None
    rule_correct: bool
    risk_correct: bool
    disposition_correct: bool
    safety_gate_holds: bool  # under normal flow
    safety_gate_blocks_forced_discharge: bool  # would TRG-C05 fire if forced to discharge?
    bundle_sha256: str
    extraction_method: str
    rationale: dict[str, str] = field(default_factory=dict)


def _build_world() -> WorldState:
    w = WorldState()
    for rid, rule in load_decision_rules().items():
        w.put_entity("decision_rule", rid, rule)
    w.put_entity(
        "patient",
        "PAT-001",
        {
            "id": "PAT-001",
            "entity_type": "patient",
            "birthDate": "1958-03-12",
            "allergies": [],
            "medications": [],
        },
    )
    for i in range(2):
        w.put_entity(
            "resource",
            f"BED-{i}",
            {
                "id": f"BED-{i}",
                "resource_type": "bed",
                "status": "available",
                "zone": "main",
                "name": f"Bed {i}",
            },
        )
    return w


def _evaluate_scenario(world: WorldState, scenario: Scenario) -> ScenarioResult:
    agent = create_triage_agent(world)
    plan = agent.run(
        scenario.bundle,
        sharp={"contextId": f"ctx-{scenario.id}", "correlationId": f"corr-{scenario.id}"},
    )

    rule_payload = plan.rule_result or {}
    rule_result = (rule_payload.get("result") or {}) if rule_payload else {}
    actual_rule = rule_payload.get("rule") if rule_payload else None
    actual_risk = (rule_result.get("risk_level") or "").lower() if rule_result else None
    actual_disposition = plan.disposition.get("recommendation") if plan.disposition else None

    safety_under_normal = all(
        c.get("satisfied", True) for c in plan.rubric_self_evaluation if c.get("safety_critical")
    )

    # Probe TRG-C05: would the safety gate catch a forced discharge?
    forced = dict(plan.disposition or {})
    forced["recommendation"] = "discharge"
    forced_rubric = _self_evaluate(
        plan.chief_complaint,
        [DifferentialItem(d.condition, d.rationale, d.decision_rule) for d in plan.differential],
        plan.rule_result,
        forced,
    )
    forced_safety = next((c for c in forced_rubric if c.get("safety_critical")), None)
    safety_blocks_forced_discharge = bool(forced_safety) and not forced_safety.get(
        "satisfied", True
    )

    return ScenarioResult(
        scenario_id=scenario.id,
        title=scenario.title,
        expected_rule=scenario.expected_rule,
        expected_risk=scenario.expected_risk,
        expected_disposition=scenario.expected_disposition,
        actual_rule=actual_rule,
        actual_risk=actual_risk,
        actual_disposition=actual_disposition,
        rule_correct=(actual_rule or "").lower() == scenario.expected_rule.lower(),
        risk_correct=(actual_risk or "") == scenario.expected_risk.lower(),
        disposition_correct=(actual_disposition or "") == scenario.expected_disposition,
        safety_gate_holds=safety_under_normal,
        safety_gate_blocks_forced_discharge=safety_blocks_forced_discharge,
        bundle_sha256=bundle_hash(scenario.bundle),
        extraction_method=(rule_payload.get("extraction") or {}).get("method", "n/a"),
        rationale=(rule_payload.get("extraction") or {}).get("rationale", {}),
    )


def _aggregate(results: list[ScenarioResult]) -> dict[str, Any]:
    total = len(results)
    correct_rule = sum(1 for r in results if r.rule_correct)
    correct_risk = sum(1 for r in results if r.risk_correct)
    correct_disp = sum(1 for r in results if r.disposition_correct)

    high_actual = [r for r in results if r.expected_risk == "high"]
    non_high_actual = [r for r in results if r.expected_risk != "high"]
    tp = sum(1 for r in high_actual if r.actual_risk == "high")
    fn = sum(1 for r in high_actual if r.actual_risk != "high")
    tn = sum(1 for r in non_high_actual if r.actual_risk != "high")
    fp = sum(1 for r in non_high_actual if r.actual_risk == "high")

    sensitivity = (tp / (tp + fn)) if (tp + fn) else None
    specificity = (tn / (tn + fp)) if (tn + fp) else None

    high_or_moderate = [r for r in results if r.expected_risk in {"high", "moderate"}]
    safety_blocks = sum(1 for r in high_or_moderate if r.safety_gate_blocks_forced_discharge)

    return {
        "scenarios_total": total,
        "rule_match": f"{correct_rule}/{total}",
        "risk_match": f"{correct_risk}/{total}",
        "disposition_match": f"{correct_disp}/{total}",
        "high_risk_sensitivity": sensitivity,
        "non_high_specificity": specificity,
        "safety_gate_blocks_forced_discharge_for_high_or_moderate": (
            f"{safety_blocks}/{len(high_or_moderate)}"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", help="Run a single scenario by id (default: all)", default=None
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of pretty text")
    args = parser.parse_args(argv)

    world = _build_world()
    if args.scenario:
        scenarios = [load_scenario(args.scenario)]
    else:
        scenarios = list_scenarios()

    results = [_evaluate_scenario(world, s) for s in scenarios]
    summary = _aggregate(results)

    if args.json:
        json.dump(
            {
                "summary": summary,
                "results": [r.__dict__ for r in results],
            },
            sys.stdout,
            indent=2,
            default=str,
        )
        sys.stdout.write("\n")
        return 0

    print("=" * 78)
    print("Agents Assemble — End-to-End Validation Report")
    print("=" * 78)
    for r in results:
        ok = "✓" if (r.rule_correct and r.risk_correct and r.disposition_correct) else "✗"
        print(
            f"\n[{ok}] {r.scenario_id}  ({r.title})\n"
            f"    expected:  rule={r.expected_rule!r}  risk={r.expected_risk!r}  "
            f"disposition={r.expected_disposition!r}\n"
            f"    actual:    rule={r.actual_rule!r}  risk={r.actual_risk!r}  "
            f"disposition={r.actual_disposition!r}\n"
            f"    extraction: method={r.extraction_method}  "
            f"safety_gate_holds={r.safety_gate_holds}  "
            f"blocks_forced_discharge={r.safety_gate_blocks_forced_discharge}\n"
            f"    bundle_sha256={r.bundle_sha256[:12]}…"
        )
    print("\n" + "-" * 78)
    print("Aggregate metrics")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
