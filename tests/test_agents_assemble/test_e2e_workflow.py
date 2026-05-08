"""End-to-end medical workflow tests for the Agents Assemble submission.

Each test represents an actual ED clinical scenario routed through the
full agentic call chain:

    FHIR Bundle (ingested at registration)
       |
       v
    Triage Agent  ----(SHARP envelope)---->  Decision-Rule Superpower
       |                                            |
       |  <----(SHARP reply, score+risk)------------+
       v
    Disposition Agent (admit / discharge / transfer)
       |
       v
    TriagePlan with binary-criteria rubric self-evaluation

The Bundles use realistic FHIR R4 shapes: Patient with birthDate, Encounter
with ESI level + reasonCode, Conditions with SNOMED-coded diagnoses,
Observations with LOINC codes and ``valueQuantity`` (vitals, labs), and
free-text DocumentReference notes that exercise the LLM path.

Why these scenarios:

1. **STEMI rule-out (HEART pathway)** — chest pain in an older patient
   with risk factors and elevated troponin. Tests the high-frequency ED
   workflow where ED docs apply HEART ~5x/shift; misuse drives
   unnecessary admit/CT. We verify HIGH risk -> admit and that the
   safety gate would catch a discharge.
2. **PE rule-out (Wells pathway)** — pleuritic chest pain after a long
   flight. Tests a non-HEART pathway and verifies the deterministic
   extractor parses Observation.valueQuantity (HR), not just text.
3. **Sepsis screening (qSOFA)** — fever + AMS + hypotension. Tests
   multi-LOINC extraction (RR, SBP, GCS) and the high-risk -> admit
   path. Demonstrates the safety gate firing on attempted discharge
   override.
4. **Low-risk PE screen** — sharp pleuritic pain, no DVT signs, normal
   HR. Tests low-risk -> discharge eligibility.
5. **SHARP propagation** — verifies contextId / correlationId /
   bundleSha256 thread end-to-end through every agent hop.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from healthcraft.agents_assemble.agent_triage.agent import (
    DifferentialItem,
    create_triage_agent,
)
from healthcraft.agents_assemble.superpower_decision_rules.server import create_superpower
from healthcraft.agents_assemble.superpower_decision_rules.sharp import bundle_hash
from healthcraft.entities.decision_rules import load_decision_rules
from healthcraft.world.state import WorldState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def world() -> WorldState:
    """Minimal Mercy Point world with rules + a couple of beds + a patient."""
    w = WorldState()
    for rule_id, rule in load_decision_rules().items():
        w.put_entity("decision_rule", rule_id, rule)
    w.put_entity(
        "patient",
        "PAT-001",
        {
            "id": "PAT-001",
            "entity_type": "patient",
            "birthDate": "1958-03-12",
            "allergies": ["Penicillin"],
            "medications": ["Aspirin 81mg", "Metformin 1000mg"],
        },
    )
    w.put_entity(
        "insurance",
        "INS-001",
        {"id": "INS-001", "patient_id": "PAT-001", "payer": "Medicare", "active": True},
    )
    for i in range(2):
        w.put_entity(
            "resource",
            f"BED-{i + 1}",
            {
                "id": f"BED-{i + 1}",
                "resource_type": "bed",
                "status": "available",
                "zone": "main",
                "name": f"Bed {i + 1}",
            },
        )
    return w


# ---------------------------------------------------------------------------
# FHIR Bundle builders (realistic shapes)
# ---------------------------------------------------------------------------


def _patient(pid: str, birth: str, sex: str = "male") -> dict[str, Any]:
    return {
        "resourceType": "Patient",
        "id": pid,
        "birthDate": birth,
        "gender": sex,
    }


def _encounter(eid: str, pid: str, complaint: str, esi: int = 2) -> dict[str, Any]:
    return {
        "resourceType": "Encounter",
        "id": eid,
        "status": "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER"},
        "subject": {"reference": f"Patient/{pid}"},
        "reasonCode": [{"text": complaint}],
        "priority": {"text": f"ESI-{esi}"},
    }


def _condition(cid: str, pid: str, text: str, snomed: str | None = None) -> dict[str, Any]:
    coding = []
    if snomed:
        coding.append({"system": "http://snomed.info/sct", "code": snomed, "display": text})
    return {
        "resourceType": "Condition",
        "id": cid,
        "subject": {"reference": f"Patient/{pid}"},
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": coding, "text": text},
    }


def _vital(
    oid: str,
    pid: str,
    eid: str,
    *,
    loinc: str,
    display: str,
    value: float,
    unit: str,
    component_loinc: str | None = None,
    components: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": oid,
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                    }
                ]
            }
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": loinc, "display": display}],
            "text": display,
        },
        "subject": {"reference": f"Patient/{pid}"},
        "encounter": {"reference": f"Encounter/{eid}"},
    }
    if components:
        obs["component"] = components
    else:
        obs["valueQuantity"] = {"value": value, "unit": unit}
    return obs


def _bp(oid: str, pid: str, eid: str, sbp: float, dbp: float) -> dict[str, Any]:
    return _vital(
        oid,
        pid,
        eid,
        loinc="85354-9",
        display="Blood pressure panel",
        value=0,
        unit="",
        components=[
            {
                "code": {
                    "coding": [
                        {"system": "http://loinc.org", "code": "8480-6", "display": "Systolic"}
                    ]
                },
                "valueQuantity": {"value": sbp, "unit": "mmHg"},
            },
            {
                "code": {
                    "coding": [
                        {"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic"}
                    ]
                },
                "valueQuantity": {"value": dbp, "unit": "mmHg"},
            },
        ],
    )


def _doc(did: str, pid: str, eid: str, hpi: str) -> dict[str, Any]:
    return {
        "resourceType": "DocumentReference",
        "id": did,
        "status": "current",
        "type": {"text": "ED HPI / Physician Note"},
        "subject": {"reference": f"Patient/{pid}"},
        "context": {"encounter": [{"reference": f"Encounter/{eid}"}]},
        "content": [{"attachment": {"contentType": "text/plain", "title": "HPI", "data": hpi}}],
        "text": {"status": "generated", "div": hpi},
    }


def _bundle(*resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{"resource": r} for r in resources],
    }


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def _scenario_stemi() -> dict[str, Any]:
    """67yo male, chest pain radiating to jaw, HTN+DM, troponin 2.5x ULN."""
    pid = "PAT-001"
    eid = "ENC-STEMI"
    return _bundle(
        _patient(pid, "1958-03-12", "male"),
        _encounter(eid, pid, "chest pain radiating to jaw", esi=2),
        _condition("C-DM", pid, "Type 2 diabetes mellitus", snomed="44054006"),
        _condition("C-HTN", pid, "Essential hypertension", snomed="59621000"),
        _vital("V-HR", pid, eid, loinc="8867-4", display="Heart rate", value=98, unit="/min"),
        _bp("V-BP", pid, eid, sbp=148, dbp=92),
        {
            "resourceType": "Observation",
            "id": "L-TROPI",
            "status": "final",
            "code": {
                "coding": [
                    {"system": "http://loinc.org", "code": "6598-7", "display": "Troponin I"}
                ],
                "text": "Troponin I",
            },
            "subject": {"reference": f"Patient/{pid}"},
            "encounter": {"reference": f"Encounter/{eid}"},
            "valueQuantity": {"value": 0.85, "unit": "ng/mL"},
            "referenceRange": [{"high": {"value": 0.04, "unit": "ng/mL"}}],
            "note": [{"text": "Troponin 2.5x upper limit of normal at 0h."}],
        },
        _doc(
            "D-HPI",
            pid,
            eid,
            "67yo male with HTN, T2DM presents with substernal chest pressure x 2h "
            "radiating to left jaw, diaphoresis, exertional onset. Family hx of MI.",
        ),
    )


def _scenario_pe_high() -> dict[str, Any]:
    """52yo female, pleuritic chest pain after long flight, HR 118, hemoptysis."""
    pid = "PAT-PE"
    eid = "ENC-PE"
    return _bundle(
        _patient(pid, "1973-08-04", "female"),
        _encounter(eid, pid, "pleuritic chest pain and dyspnea", esi=2),
        _condition("C-HEMOP", pid, "Hemoptysis", snomed="66857006"),
        _vital("V-HR", pid, eid, loinc="8867-4", display="Heart rate", value=118, unit="/min"),
        _bp("V-BP", pid, eid, sbp=124, dbp=78),
        _doc(
            "D-HPI",
            pid,
            eid,
            "52yo female on day 2 post 14h long-haul flight, sudden pleuritic chest pain, "
            "dyspnea, mild hemoptysis. PE likely on differential. No leg swelling.",
        ),
    )


def _scenario_pe_low() -> dict[str, Any]:
    """28yo female, pleuritic pain, no risk factors, HR 88."""
    pid = "PAT-PE-LOW"
    eid = "ENC-PE-LOW"
    return _bundle(
        _patient(pid, "1997-11-21", "female"),
        _encounter(eid, pid, "pleuritic chest pain", esi=3),
        _vital("V-HR", pid, eid, loinc="8867-4", display="Heart rate", value=88, unit="/min"),
        _bp("V-BP", pid, eid, sbp=118, dbp=72),
        _doc(
            "D-HPI",
            pid,
            eid,
            "28yo otherwise healthy female with sharp left-sided pleuritic chest pain "
            "after weight lifting yesterday. No leg swelling, no recent travel/surgery, "
            "no malignancy, no hemoptysis. Reproducible with chest wall palpation.",
        ),
    )


def _scenario_sepsis() -> dict[str, Any]:
    """78yo male, fever, hypotension, AMS — high qSOFA."""
    pid = "PAT-SEPSIS"
    eid = "ENC-SEPSIS"
    return _bundle(
        _patient(pid, "1947-09-14", "male"),
        _encounter(eid, pid, "fever and altered mental status", esi=1),
        _condition("C-AMS", pid, "Altered mental status", snomed="419284004"),
        _vital("V-RR", pid, eid, loinc="9279-1", display="Respiratory rate", value=26, unit="/min"),
        _vital(
            "V-TEMP",
            pid,
            eid,
            loinc="8310-5",
            display="Body temperature",
            value=39.4,
            unit="Cel",
        ),
        _bp("V-BP", pid, eid, sbp=88, dbp=54),
        _vital(
            "V-GCS",
            pid,
            eid,
            loinc="9269-2",
            display="Glasgow Coma Score",
            value=13,
            unit="{score}",
        ),
        _doc(
            "D-HPI",
            pid,
            eid,
            "78yo male brought from SNF with 2-day fever, productive cough, now confused "
            "and lethargic. Vitals: T 39.4C, BP 88/54, RR 26, GCS 13. Suspected sepsis.",
        ),
    )


# ---------------------------------------------------------------------------
# E2E tests
# ---------------------------------------------------------------------------


def test_e2e_stemi_admit_pathway(world: WorldState) -> None:
    """ACS workup: HEART pathway returns moderate/high risk -> admit, bed available."""
    bundle = _scenario_stemi()
    agent = create_triage_agent(world)
    plan = agent.run(bundle, sharp={"contextId": "ctx-stemi", "correlationId": "corr-stemi"})

    assert "chest pain" in plan.chief_complaint.lower()
    assert any("acute_coronary_syndrome" == d.condition for d in plan.differential)

    # Decision rule fires + risk-level is non-low.
    assert plan.rule_result is not None
    assert plan.rule_result["rule"] == "HEART Score"
    rule_result = plan.rule_result["result"]
    assert rule_result["risk_level"] in {"moderate", "high"}
    assert rule_result["score"] >= 4

    # The disposition agent translates risk -> admit and reports a real bed.
    assert plan.disposition["recommendation"] == "admit"
    assert plan.disposition["bed_available"] is True
    # Insurance was looked up via patient_id from the Bundle.
    assert plan.disposition["insurance_summary"] is not None

    # The full sub-agent trace fired in order.
    tools = [t["tool"] for t in plan.trace]
    # Reasoner now sits between the differential and the rule call; assert
    # the legacy hop names are present and in order rather than equality.
    for name in ("differentialAgent", "reasoner", "decisionRuleAgent", "dispositionAgent"):
        assert name in tools, f"missing trace hop: {name}"
    assert (
        tools.index("differentialAgent")
        < tools.index("reasoner")
        < tools.index("decisionRuleAgent")
        < tools.index("dispositionAgent")
    )

    # The rubric self-evaluation is fully satisfied (no safety gate violation).
    assert all(c["satisfied"] for c in plan.rubric_self_evaluation)


def test_e2e_pe_high_pathway_extracts_hr_from_loinc(world: WorldState) -> None:
    """Wells PE: HR 118 must be parsed from Observation.valueQuantity (LOINC 8867-4)."""
    bundle = _scenario_pe_high()
    agent = create_triage_agent(world)
    plan = agent.run(bundle, sharp={"contextId": "ctx-pe", "correlationId": "corr-pe"})

    assert plan.rule_result is not None
    assert plan.rule_result["rule"] == "Wells Criteria for PE"
    rule_result = plan.rule_result["result"]
    # HR>100 (1.5) + Hemoptysis (1) + PE-likely text (3) + long flight (1.5) = 7
    assert rule_result["score"] >= 6.5
    assert rule_result["risk_level"] in {"moderate", "high"}

    # The extractor's HR rationale must mention the numeric vital, not text guess.
    extraction = plan.rule_result["extraction"]
    assert "rationale" in extraction
    assert any("HR=" in v for v in extraction["rationale"].values())

    # SHARP correlation propagated through the superpower call.
    assert plan.sharp["bundleSha256"] == bundle_hash(bundle)


def test_e2e_pe_low_supports_discharge(world: WorldState) -> None:
    """Healthy 28yo with reproducible pleuritic pain -> low Wells -> discharge OK."""
    bundle = _scenario_pe_low()
    agent = create_triage_agent(world)
    plan = agent.run(bundle)

    assert plan.rule_result is not None
    rule_result = plan.rule_result["result"]
    assert rule_result["risk_level"] == "low"
    assert plan.disposition["recommendation"] == "discharge"
    # Safety gate (TRG-C05) holds: low-risk discharge is appropriate.
    safety = next(c for c in plan.rubric_self_evaluation if c["id"] == "TRG-C05")
    assert safety["satisfied"]


def test_e2e_sepsis_triggers_admit_via_qsofa(world: WorldState) -> None:
    """Sepsis with qSOFA 3 -> high -> admit. Multi-LOINC extraction (RR, SBP, GCS)."""
    bundle = _scenario_sepsis()
    agent = create_triage_agent(world)
    plan = agent.run(bundle)

    assert plan.rule_result is not None
    assert plan.rule_result["rule"] == "qSOFA"
    rule_result = plan.rule_result["result"]
    # All 3 qSOFA criteria positive: RR=26, SBP=88, AMS via Condition + GCS=13.
    assert rule_result["score"] == 3
    assert rule_result["risk_level"] == "high"
    assert plan.disposition["recommendation"] == "admit"

    # Each rule input has a concrete vital-derived rationale (not a "missing" placeholder).
    rationales = plan.rule_result["extraction"]["rationale"]
    assert any("RR=" in v for v in rationales.values())
    assert any("SBP=" in v for v in rationales.values())


def test_e2e_safety_gate_catches_discharge_after_high_risk(world: WorldState) -> None:
    """If the disposition layer is forced to discharge a HIGH-risk patient, TRG-C05 fails.

    The safety gate is the rubric criterion that mirrors HEALTHCRAFT's
    safety_critical contract (any safety_critical = false -> reward 0).
    """
    bundle = _scenario_sepsis()
    agent = create_triage_agent(world)
    plan = agent.run(bundle)
    # Mutate the disposition (simulate a downstream agent that ignored the rule)
    # and re-run only the rubric self-eval helper.
    from healthcraft.agents_assemble.agent_triage.agent import _self_evaluate

    overridden_disposition = dict(plan.disposition)
    overridden_disposition["recommendation"] = "discharge"
    rubric = _self_evaluate(
        plan.chief_complaint,
        [DifferentialItem(d.condition, d.rationale, d.decision_rule) for d in plan.differential],
        plan.rule_result,
        overridden_disposition,
    )
    safety = next(c for c in rubric if c.get("safety_critical"))
    assert safety["satisfied"] is False, "HIGH-risk + discharge MUST violate the safety gate"


def test_e2e_sharp_propagates_across_call_chain(world: WorldState) -> None:
    """Caller's SHARP IDs survive every hop; superpower trace records the bundle hash."""
    bundle = _scenario_stemi()
    expected_hash = bundle_hash(bundle)

    superpower = create_superpower(world)

    # Direct superpower call: hash + IDs round-trip.
    direct = superpower.call(
        "applyDecisionRule",
        {
            "ruleName": "HEART Score",
            "bundle": bundle,
            "contextId": "ctx-shared",
            "correlationId": "corr-shared",
        },
    )
    assert direct["sharp"]["contextId"] == "ctx-shared"
    assert direct["sharp"]["correlationId"] == "corr-shared"
    assert direct["sharp"]["trace"][0]["bundleSha256"] == expected_hash
    assert direct["sharp"]["trace"][0]["detail"]["extractionMethod"] == "deterministic"

    # End-to-end via the agent: same IDs, same hash, three sub-agent hops.
    agent = create_triage_agent(world, extractor=None)
    plan = agent.run(bundle, sharp={"contextId": "ctx-shared", "correlationId": "corr-shared"})
    assert plan.sharp["contextId"] == "ctx-shared"
    assert plan.sharp["correlationId"] == "corr-shared"
    assert plan.sharp["bundleSha256"] == expected_hash
    assert all(t["contextId"] == "ctx-shared" for t in plan.trace)


def test_e2e_run_is_deterministic_for_identical_bundle(world: WorldState) -> None:
    """Two identical Bundles -> identical bundleHash, score, and disposition.

    Determinism is a required Corecraft invariant: same input must produce
    same scoring and rubric verdict, every time. This is what makes the
    submission reproducible for judges.
    """
    bundle = _scenario_stemi()
    agent = create_triage_agent(world)

    plan_a = agent.run(bundle, sharp={"contextId": "ctx-A", "correlationId": "corr-A"})
    plan_b = agent.run(bundle, sharp={"contextId": "ctx-B", "correlationId": "corr-B"})

    assert plan_a.sharp["bundleSha256"] == plan_b.sharp["bundleSha256"]
    assert plan_a.rule_result["result"]["score"] == plan_b.rule_result["result"]["score"]
    assert plan_a.rule_result["result"]["risk_level"] == plan_b.rule_result["result"]["risk_level"]
    assert plan_a.disposition["recommendation"] == plan_b.disposition["recommendation"]
    # Bundle hash equals an externally-computed SHA-256 of the canonicalized JSON.
    expected = hashlib.sha256(
        json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert plan_a.sharp["bundleSha256"] == expected
