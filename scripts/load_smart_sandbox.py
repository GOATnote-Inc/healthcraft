"""Pull a synthetic patient from the SMART Health IT sandbox and route them
through the agent end-to-end.

The SMART sandbox at ``https://r4.smarthealthit.org/`` is the canonical
public FHIR R4 endpoint used by the academic MCP-FHIR framework
(arXiv:2506.13800), the SMART on FHIR app gallery, and most healthcare
hackathons. Pulling a real Bundle from it (rather than a hand-crafted
fixture) is the cleanest demonstration that the Superpower works on
real-shaped FHIR data, not just curated test scenarios.

The script:

1. Lists patients (defaults to a few well-known synthetic patients with
   ED-like presentations), or accepts ``--patient <id>``.
2. Fetches Patient + Encounter + Conditions + recent Observations.
3. Composes them into a single Bundle.
4. Runs the triage agent and prints the resulting CDS Hooks card.

Stdlib-only (urllib + json). Requires network. Skip on CI; meant for the
live demo video and Devpost write-up.

Usage:

    python scripts/load_smart_sandbox.py
    python scripts/load_smart_sandbox.py --patient 0489f6a3-9ed5-475c-9d62-243a93f72b14
    python scripts/load_smart_sandbox.py --json

References:
- https://r4.smarthealthit.org/
- https://arxiv.org/abs/2506.13800 (uses this sandbox for evaluation)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import urllib.error
import urllib.request
from typing import Any

from healthcraft.agents_assemble.agent_triage.agent import create_triage_agent
from healthcraft.agents_assemble.agent_triage.cds_hooks import to_cds_hooks_card
from healthcraft.entities.decision_rules import load_decision_rules
from healthcraft.world.state import WorldState

SANDBOX_BASE = "https://r4.smarthealthit.org"
DEFAULT_PATIENTS = (
    # A small set of synthetic patients with multiple Conditions/Observations,
    # picked because they reliably exercise the chest-pain / dyspnea pathways.
    "0489f6a3-9ed5-475c-9d62-243a93f72b14",
    "1d604da9-9a81-4ba9-80c2-de3375d59b40",
    "16cabfa6-c4b5-4e2e-9f95-91a7ed7f5bc8",
)


def _fetch(url: str, timeout: float = 15.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/fhir+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        e["resource"]
        for e in (bundle.get("entry") or [])
        if isinstance(e, dict) and isinstance(e.get("resource"), dict)
    ]


def _build_bundle(patient_id: str) -> dict[str, Any]:
    """Compose a minimal-but-realistic Bundle from the SMART sandbox."""
    resources: list[dict[str, Any]] = []

    patient = _fetch(f"{SANDBOX_BASE}/Patient/{patient_id}")
    resources.append(patient)

    encounter_search = _fetch(
        f"{SANDBOX_BASE}/Encounter?subject=Patient/{patient_id}&_count=1&_sort=-date"
    )
    encounters = _entries(encounter_search)
    if encounters:
        resources.append(encounters[0])

    conditions = _entries(
        _fetch(f"{SANDBOX_BASE}/Condition?subject=Patient/{patient_id}&_count=20")
    )
    resources.extend(conditions)

    observations = _entries(
        _fetch(f"{SANDBOX_BASE}/Observation?subject=Patient/{patient_id}&_sort=-date&_count=20")
    )
    resources.extend(observations)

    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{"resource": r} for r in resources],
    }


def _build_world() -> WorldState:
    w = WorldState()
    for rid, rule in load_decision_rules().items():
        w.put_entity("decision_rule", rid, rule)
    return w


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--patient",
        default=None,
        help=(
            "SMART sandbox Patient/<id>. If omitted, tries each entry in "
            "DEFAULT_PATIENTS until one returns data."
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="exit without calling the network (smoke test)",
    )
    args = parser.parse_args(argv)

    if args.no_network:
        json.dump({"status": "skipped", "reason": "no-network"}, sys.stdout)
        sys.stdout.write("\n")
        return 0

    candidates = [args.patient] if args.patient else list(DEFAULT_PATIENTS)
    bundle: dict[str, Any] | None = None
    chosen: str | None = None
    last_err: str | None = None
    for pid in candidates:
        try:
            bundle = _build_bundle(pid)
            if bundle.get("entry") or []:
                chosen = pid
                break
        except urllib.error.URLError as exc:
            last_err = str(exc)
            continue
        except Exception as exc:  # noqa: BLE001 — we tried each patient
            last_err = repr(exc)
            continue

    if bundle is None or chosen is None:
        print(
            f"could not fetch any patient from {SANDBOX_BASE}: {last_err}",
            file=sys.stderr,
        )
        return 1

    world = _build_world()
    agent = create_triage_agent(world)
    plan = agent.run(
        bundle,
        sharp={
            "contextId": f"smart-{chosen}",
            "correlationId": f"smart-{chosen}",
        },
    )
    plan_dict = dataclasses.asdict(plan)
    card = to_cds_hooks_card(plan_dict)

    if args.json:
        json.dump(
            {"patient_id": chosen, "plan": plan_dict, "cds_hooks_card": card},
            sys.stdout,
            indent=2,
            default=str,
        )
        sys.stdout.write("\n")
        return 0

    print(f"SMART sandbox patient: {chosen}")
    print(f"  resources fetched: {len(bundle['entry'])}")
    print(f"  chief complaint:   {plan.chief_complaint or '(empty)'}")
    print(
        f"  rule fired:        "
        f"{(plan.rule_result or {}).get('rule', '(none)') if plan.rule_result else '(none)'}"
    )
    rule_result = (plan.rule_result or {}).get("result") if plan.rule_result else None
    if rule_result:
        print(f"  score / risk:      {rule_result.get('score')} / {rule_result.get('risk_level')}")
    print(f"  disposition:       {plan.disposition.get('recommendation')}")
    print(f"  bundleSha256:      {plan.sharp.get('bundleSha256', '')[:16]}…")
    print(f"  CDS Hooks indicator: {card['indicator']}")
    print(f"  CDS Hooks summary:   {card['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
