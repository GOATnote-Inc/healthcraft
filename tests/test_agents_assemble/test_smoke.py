"""Smoke tests for the Agents Assemble hackathon submissions.

These tests exercise the Superpower (``applyDecisionRule``) and the Full
Agent (``mercy-point-triage``) end-to-end against a minimal seeded world.
No network, no LLM keys — the FHIR variable extractor's deterministic
fallback handles HEART Score; the LLM-driven path is exercised separately
via a stub client.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from healthcraft.agents_assemble.agent_triage.agent import create_triage_agent
from healthcraft.agents_assemble.superpower_decision_rules.fhir_extractor import (
    FhirVariableExtractor,
)
from healthcraft.agents_assemble.superpower_decision_rules.server import create_superpower
from healthcraft.agents_assemble.superpower_decision_rules.sharp import (
    SharpEnvelope,
    bundle_hash,
    reply_envelope,
)
from healthcraft.entities.decision_rules import load_decision_rules
from healthcraft.world.state import WorldState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def world() -> WorldState:
    """Minimal world with decision rules loaded."""
    w = WorldState()
    for rule_id, rule in load_decision_rules().items():
        w.put_entity("decision_rule", rule_id, rule)
    # One patient + insurance so the disposition agent has something to read.
    patient = {
        "id": "PAT-DEADBEEF",
        "entity_type": "patient",
        "birthDate": "1958-03-12",
        "allergies": [],
        "medications": [],
    }
    w.put_entity("patient", "PAT-DEADBEEF", patient)
    w.put_entity(
        "insurance",
        "INS-001",
        {"id": "INS-001", "patient_id": "PAT-DEADBEEF", "payer": "Medicare", "active": True},
    )
    # One available bed so the disposition path with a bed-available branch is covered.
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


@pytest.fixture
def chest_pain_bundle() -> dict[str, Any]:
    """FHIR R4 Bundle for a 67-year-old with chest pain + HTN/DM + troponin."""
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "PAT-DEADBEEF",
                    "birthDate": "1958-03-12",
                    "gender": "male",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "ENC-1",
                    "subject": {"reference": "Patient/PAT-DEADBEEF"},
                    "reasonCode": [{"text": "chest pain radiating to jaw"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "C1",
                    "subject": {"reference": "Patient/PAT-DEADBEEF"},
                    "code": {"text": "Type 2 diabetes mellitus"},
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "C2",
                    "subject": {"reference": "Patient/PAT-DEADBEEF"},
                    "code": {"text": "Essential hypertension"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "O1",
                    "subject": {"reference": "Patient/PAT-DEADBEEF"},
                    "code": {"text": "Troponin I"},
                    "note": [{"text": "Troponin 2.5x upper limit of normal at 0h."}],
                }
            },
        ],
    }


# ---------------------------------------------------------------------------
# SHARP helpers
# ---------------------------------------------------------------------------


def test_sharp_envelope_roundtrip(chest_pain_bundle: dict[str, Any]) -> None:
    inbound = SharpEnvelope.from_dict(
        {"contextId": "ctx-1", "correlationId": "corr-1", "bundle": chest_pain_bundle}
    )
    out = reply_envelope(inbound, {"foo": "bar"}, tool_name="dummy", trace_detail={"x": 1})

    assert out["sharp"]["contextId"] == "ctx-1"
    assert out["sharp"]["correlationId"] == "corr-1"
    assert out["sharp"]["trace"][0]["tool"] == "dummy"
    assert out["sharp"]["trace"][0]["bundleSha256"] == bundle_hash(chest_pain_bundle)
    assert out["sharp"]["trace"][0]["detail"] == {"x": 1}
    assert out["data"] == {"foo": "bar"}


def test_sharp_envelope_assigns_ids_when_missing() -> None:
    inbound = SharpEnvelope.from_dict({})
    out = reply_envelope(inbound, {}, tool_name="dummy")
    assert out["sharp"]["contextId"]
    assert out["sharp"]["correlationId"]


# ---------------------------------------------------------------------------
# FHIR extractor (deterministic path)
# ---------------------------------------------------------------------------


def test_deterministic_extractor_heart_score(
    world: WorldState, chest_pain_bundle: dict[str, Any]
) -> None:
    rules = world.list_entities("decision_rule")
    heart = next(r for r in rules.values() if r.name == "HEART Score")
    extractor = FhirVariableExtractor()
    from dataclasses import asdict

    result = extractor.extract("HEART Score", list(asdict(heart)["variables"]), chest_pain_bundle)
    assert result.method == "deterministic"
    assert result.variables["Age"] == 2  # 1958 -> ~67yo
    assert result.variables["Risk factors"] == 1  # 2 risk Conditions
    assert result.variables["Troponin"] == 2  # "2.5x upper limit"
    # HPI / ECG aren't in the deterministic table and remain None.
    assert "History" in result.missing
    assert "ECG" in result.missing


def test_llm_extractor_uses_client_when_available(
    world: WorldState, chest_pain_bundle: dict[str, Any]
) -> None:
    """LLM path: a stub client returns deterministic JSON; we just verify routing."""

    class _StubClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def complete(self, prompt: str, model: str, temperature: float) -> str:
            self.calls.append(prompt)
            assert temperature == 0.0
            return json.dumps(
                {
                    "History": {"value": 2, "rationale": "stub"},
                    "ECG": {"value": 1, "rationale": "stub"},
                    "Age": {"value": 2, "rationale": "stub"},
                    "Risk factors": {"value": 1, "rationale": "stub"},
                    "Troponin": {"value": 2, "rationale": "stub"},
                }
            )

    rules = world.list_entities("decision_rule")
    heart = next(r for r in rules.values() if r.name == "HEART Score")
    from dataclasses import asdict

    client = _StubClient()
    extractor = FhirVariableExtractor(llm_client=client)
    result = extractor.extract("HEART Score", list(asdict(heart)["variables"]), chest_pain_bundle)
    assert client.calls, "LLM client should have been called"
    assert result.method == "llm"
    assert result.variables["History"] == 2
    assert result.missing == []


# ---------------------------------------------------------------------------
# Superpower: applyDecisionRule
# ---------------------------------------------------------------------------


def test_apply_decision_rule_returns_high_risk_for_acs_pattern(
    world: WorldState, chest_pain_bundle: dict[str, Any]
) -> None:
    superpower = create_superpower(world)
    out = superpower.call(
        "applyDecisionRule",
        {
            "ruleName": "HEART Score",
            "bundle": chest_pain_bundle,
            "contextId": "ctx-42",
            "correlationId": "corr-42",
        },
    )
    assert out["sharp"]["contextId"] == "ctx-42"
    data = out["data"]
    assert data["status"] == "ok"
    result = data["result"]
    # 67yo (2) + 2 risk factors (1) + troponin >ULN (2) = 5; missing History/ECG default to 0.
    assert result["score"] == 5
    assert result["risk_level"] in {"moderate", "high"}
    assert "extraction" in data
    assert data["extraction"]["method"] == "deterministic"


def test_apply_decision_rule_unknown_rule(world: WorldState) -> None:
    superpower = create_superpower(world)
    out = superpower.call("applyDecisionRule", {"ruleName": "Nonexistent Rule"})
    assert out["data"]["status"] == "error"
    assert out["data"]["code"] == "rule_not_found"


def test_apply_decision_rule_missing_rule_name(world: WorldState) -> None:
    superpower = create_superpower(world)
    out = superpower.call("applyDecisionRule", {})
    assert out["data"]["code"] == "missing_param"


# ---------------------------------------------------------------------------
# Full agent: triage end-to-end
# ---------------------------------------------------------------------------


def test_triage_agent_chest_pain_pipeline(
    world: WorldState, chest_pain_bundle: dict[str, Any]
) -> None:
    agent = create_triage_agent(world)
    plan = agent.run(chest_pain_bundle, sharp={"contextId": "ctx-7", "correlationId": "corr-7"})

    assert "chest pain" in plan.chief_complaint.lower()
    assert any("acute_coronary" in d.condition for d in plan.differential)
    assert plan.rule_result is not None
    assert plan.rule_result["result"]["score"] >= 5
    assert plan.disposition["recommendation"] in {"admit", "discharge", "observation"}

    # SHARP IDs propagate end-to-end.
    assert plan.sharp["contextId"] == "ctx-7"
    assert plan.sharp["correlationId"] == "corr-7"
    assert plan.sharp["bundleSha256"] == bundle_hash(chest_pain_bundle)

    # Trace records every sub-agent hop.
    tools_called = [t["tool"] for t in plan.trace]
    assert "differentialAgent" in tools_called
    assert "decisionRuleAgent" in tools_called
    assert "dispositionAgent" in tools_called

    # Rubric self-evaluation is structurally correct and the safety gate holds.
    assert len(plan.rubric_self_evaluation) >= 5
    safety_gate = next(c for c in plan.rubric_self_evaluation if c.get("safety_critical"))
    assert safety_gate["satisfied"], "Safety gate must hold: HIGH risk -> not discharge"


def test_triage_agent_handles_no_keyword_match(world: WorldState) -> None:
    agent = create_triage_agent(world)
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "ENC-X",
                    "reasonCode": [{"text": "left wrist swelling after fall"}],
                }
            }
        ],
    }
    plan = agent.run(bundle)
    assert plan.differential[0].condition == "nonspecific_undifferentiated"
    assert plan.rule_result is None
    # No rule fired, so the protocol-adherence criterion still passes.
    rules_criterion = next(c for c in plan.rubric_self_evaluation if c["id"] == "TRG-C03")
    assert rules_criterion["satisfied"]
