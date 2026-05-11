"""Coverage for the governance-/judging-aligned additions.

These tests target the hackathon's privacy/safety/regulatory and
real-world-fit criteria specifically:

- ``to_cds_hooks_card`` shape matches CDS Hooks 1.0 (the EHR-side standard).
- ``scrub_bundle`` removes high-risk PHI before LLM extraction without
  destroying clinical signal (DOB / vitals / Conditions survive).
- ``TriagePlan`` always exposes ``advisory_only`` and
  ``requires_physician_review`` so downstream consumers cannot mistake
  it for an autonomous order.
- The labeled demo bundles round-trip through the validation harness
  with the expected aggregate metrics.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

import pytest

from healthcraft.agents_assemble.agent_triage.agent import (
    TriagePlan,
    create_triage_agent,
)
from healthcraft.agents_assemble.agent_triage.cds_hooks import (
    to_cds_hooks_card,
    to_cds_hooks_response,
)
from healthcraft.agents_assemble.demo.bundles import SCENARIOS, load_scenario
from healthcraft.agents_assemble.superpower_decision_rules.phi_scrubber import (
    scrub_bundle,
    scrub_resource,
)
from healthcraft.entities.decision_rules import load_decision_rules
from healthcraft.world.state import WorldState

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def world() -> WorldState:
    w = WorldState()
    for rid, rule in load_decision_rules().items():
        w.put_entity("decision_rule", rid, rule)
    w.put_entity(
        "patient",
        "PAT-001",
        {"id": "PAT-001", "entity_type": "patient", "birthDate": "1958-03-12"},
    )
    w.put_entity(
        "resource",
        "BED-1",
        {
            "id": "BED-1",
            "resource_type": "bed",
            "status": "available",
            "zone": "main",
            "name": "Bed 1",
        },
    )
    return w


# ---------------------------------------------------------------------------
# CDS Hooks adapter
# ---------------------------------------------------------------------------


def test_cds_hooks_card_high_risk_renders_critical(world: WorldState) -> None:
    scenario = load_scenario("sepsis")
    agent = create_triage_agent(world)
    plan = agent.run(scenario.bundle, sharp={"contextId": "ctx-x", "correlationId": "corr-x"})

    card = to_cds_hooks_card(plan)
    assert card["indicator"] == "critical"
    assert "qSOFA" in card["summary"]
    assert "physician review required" in card["summary"].lower()
    assert "advisory only" in card["detail"].lower()
    assert card["uuid"] == "corr-x"
    assert card["suggestions"][0]["uuid"] == "corr-x"
    # CDS Hooks 1.0 envelope.
    response = to_cds_hooks_response(plan)
    assert response == {"cards": [card]}


def test_cds_hooks_card_low_risk_renders_info(world: WorldState) -> None:
    scenario = load_scenario("pe_low")
    agent = create_triage_agent(world)
    plan = agent.run(scenario.bundle)

    card = to_cds_hooks_card(plan)
    assert card["indicator"] in {"info", "warning"}
    # No safety violation -> no "SAFETY GATE TRIPPED" string.
    assert "safety gate tripped" not in card["summary"].lower()


def test_cds_hooks_card_safety_violation_forces_critical(world: WorldState) -> None:
    """If a downstream layer mutates the rubric to fail the safety gate,
    the card must be flagged critical regardless of risk level."""
    scenario = load_scenario("pe_low")  # low-risk bundle
    agent = create_triage_agent(world)
    plan = agent.run(scenario.bundle)

    plan_dict = asdict(plan)
    plan_dict["rubric_self_evaluation"][-1]["satisfied"] = False  # trip TRG-C05
    card = to_cds_hooks_card(plan_dict)
    assert card["indicator"] == "critical"
    assert "safety gate tripped" in card["summary"].lower()


# ---------------------------------------------------------------------------
# PHI scrubber
# ---------------------------------------------------------------------------


def test_phi_scrubber_drops_names_and_identifiers() -> None:
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "p1",
                    "name": [{"family": "Smith", "given": ["Jane"]}],
                    "telecom": [{"system": "phone", "value": "+1 415-555-0123"}],
                    "address": [{"line": ["123 Main St"], "city": "SF"}],
                    "identifier": [{"system": "ssn", "value": "123-45-6789"}],
                    "birthDate": "1958-03-12",
                }
            }
        ],
    }
    out = scrub_bundle(bundle)
    patient = out["entry"][0]["resource"]
    assert "name" not in patient
    assert "telecom" not in patient
    assert "address" not in patient
    assert "identifier" not in patient
    # Clinical signal preserved.
    assert patient["birthDate"] == "1958-03-12"


def test_phi_scrubber_redacts_in_free_text() -> None:
    note = (
        "Patient SSN 123-45-6789, mobile 415-555-0123, email j.doe@example.com, "
        "MRN: 12345678 — chest pain x 2h, troponin 2.5x ULN."
    )
    out = scrub_resource({"resourceType": "Observation", "note": [{"text": note}]})
    blob = out["note"][0]["text"]
    assert "123-45-6789" not in blob
    assert "@example.com" not in blob
    assert re.search(r"MRN.*12345678", blob) is None
    assert "[REDACTED-SSN]" in blob
    assert "[REDACTED-EMAIL]" in blob
    assert "troponin 2.5x ULN" in blob  # clinical signal preserved


def test_phi_scrubber_does_not_mutate_input() -> None:
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "entry": [{"resource": {"resourceType": "Patient", "id": "p1", "name": [{"family": "X"}]}}],
    }
    snapshot = json.dumps(bundle, sort_keys=True)
    scrub_bundle(bundle)
    assert json.dumps(bundle, sort_keys=True) == snapshot


def test_phi_scrubber_handles_none() -> None:
    assert scrub_bundle(None) is None


# ---------------------------------------------------------------------------
# Advisory framing
# ---------------------------------------------------------------------------


def test_triage_plan_is_advisory_by_default(world: WorldState) -> None:
    agent = create_triage_agent(world)
    plan: TriagePlan = agent.run(load_scenario("stemi").bundle)
    assert plan.advisory_only is True
    assert plan.requires_physician_review is True


# ---------------------------------------------------------------------------
# Demo bundles + validation harness
# ---------------------------------------------------------------------------


def test_all_demo_scenarios_round_trip() -> None:
    """Every scenario id loads and produces an independent copy on each load."""
    for sid in SCENARIOS:
        s1 = load_scenario(sid)
        s2 = load_scenario(sid)
        assert s1.id == s2.id
        # Mutating one must not leak to the next loader call.
        s1.bundle["entry"].append({"resource": {"resourceType": "Marker"}})
        assert s2.bundle != s1.bundle


def test_validation_harness_metrics_match_expectations(world: WorldState) -> None:
    """The harness must score 4/4 on rule, 4/4 on disposition, sensitivity 1.0
    for HIGH risk, and trigger the safety gate for the 3 elevated-risk cases."""
    from scripts.validate_agents_assemble import _aggregate, _evaluate_scenario

    results = [_evaluate_scenario(world, load_scenario(sid)) for sid in SCENARIOS]
    summary = _aggregate(results)

    assert summary["rule_match"] == "4/4"
    assert summary["disposition_match"] == "4/4"
    assert summary["high_risk_sensitivity"] == 1.0
    assert summary["safety_gate_blocks_forced_discharge_for_high_or_moderate"] == "3/3"
