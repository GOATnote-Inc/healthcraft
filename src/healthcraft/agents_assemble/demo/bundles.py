"""Demo FHIR Bundles + ground-truth labels.

A "scenario" pairs a realistic ED FHIR Bundle with the clinical
ground-truth a human emergency physician would expect the agent to
return: the rule that should fire, the risk level, the safe disposition,
and whether the safety gate must trigger if disposition is forced to
discharge. The validation harness (``scripts/validate_agents_assemble.py``)
uses these labels to compute sensitivity/specificity for HIGH-risk
identification and the safety-gate trigger rate.

Bundles are intentionally minimal-but-realistic FHIR R4: Patient with
``birthDate``, Encounter with ESI level + ``reasonCode``, Conditions with
SNOMED codings, Observations with LOINC codes (incl. BP component
sub-codings), and a free-text DocumentReference HPI that exercises the
LLM extractor's path (or the deterministic-fallback regexes when no LLM
is wired).

No real patient data — all entities are fictional.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Scenario:
    """One labeled clinical scenario."""

    id: str
    title: str
    bundle: dict[str, Any]
    expected_rule: str
    expected_risk: str  # low / moderate / high
    expected_disposition: str  # admit / discharge / observation
    description: str = ""
    notes: str = ""
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# FHIR Bundle builders (kept here so demo bundles stay reproducible)
# ---------------------------------------------------------------------------


def _patient(pid: str, birth: str, sex: str = "male") -> dict[str, Any]:
    return {"resourceType": "Patient", "id": pid, "birthDate": birth, "gender": sex}


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
    coding = (
        [{"system": "http://snomed.info/sct", "code": snomed, "display": text}] if snomed else []
    )
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
        "content": [{"attachment": {"contentType": "text/plain", "title": "HPI"}}],
        "text": {"status": "generated", "div": hpi},
    }


def _bundle(*resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{"resource": r} for r in resources],
    }


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def _build_stemi() -> dict[str, Any]:
    pid, eid = "PAT-001", "ENC-STEMI"
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
                    {
                        "system": "http://loinc.org",
                        "code": "6598-7",
                        "display": "Troponin I",
                    }
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


def _build_pe_high() -> dict[str, Any]:
    pid, eid = "PAT-PE", "ENC-PE"
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


def _build_pe_low() -> dict[str, Any]:
    pid, eid = "PAT-PE-LOW", "ENC-PE-LOW"
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


def _build_sepsis() -> dict[str, Any]:
    pid, eid = "PAT-SEPSIS", "ENC-SEPSIS"
    return _bundle(
        _patient(pid, "1947-09-14", "male"),
        _encounter(eid, pid, "fever and altered mental status", esi=1),
        _condition("C-AMS", pid, "Altered mental status", snomed="419284004"),
        _vital("V-RR", pid, eid, loinc="9279-1", display="Respiratory rate", value=26, unit="/min"),
        _vital(
            "V-TEMP", pid, eid, loinc="8310-5", display="Body temperature", value=39.4, unit="Cel"
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


SCENARIOS: dict[str, Scenario] = {
    "stemi": Scenario(
        id="stemi",
        title="STEMI rule-out (HEART pathway)",
        bundle=_build_stemi(),
        expected_rule="HEART Score",
        expected_risk="moderate",
        expected_disposition="admit",
        description=(
            "67yo with HTN/T2DM, chest pain radiating to jaw, troponin 2.5x ULN. "
            "Classic ACS rule-out."
        ),
        tags=["acs", "chest_pain", "heart"],
    ),
    "pe_high": Scenario(
        id="pe_high",
        title="PE high pretest (Wells pathway)",
        bundle=_build_pe_high(),
        expected_rule="Wells Criteria for PE",
        expected_risk="high",
        expected_disposition="admit",
        description=(
            "52yo, post long-haul flight, pleuritic + dyspnea + hemoptysis + HR 118. "
            "Wells score 7+ -> high pretest probability per the rule's score ranges."
        ),
        tags=["pe", "wells", "chest_pain"],
    ),
    "pe_low": Scenario(
        id="pe_low",
        title="PE low pretest (Wells pathway)",
        bundle=_build_pe_low(),
        expected_rule="Wells Criteria for PE",
        expected_risk="low",
        expected_disposition="discharge",
        description="28yo healthy, reproducible MSK chest pain, no Wells red flags.",
        tags=["pe", "wells", "low_risk"],
    ),
    "sepsis": Scenario(
        id="sepsis",
        title="Sepsis screen (qSOFA)",
        bundle=_build_sepsis(),
        expected_rule="qSOFA",
        expected_risk="high",
        expected_disposition="admit",
        description="78yo from SNF, fever + AMS + hypotension + tachypnea — qSOFA 3.",
        tags=["sepsis", "qsofa", "high_risk"],
    ),
}


def list_scenarios() -> list[Scenario]:
    """Return scenarios in stable order."""
    return [SCENARIOS[k] for k in ("stemi", "pe_high", "pe_low", "sepsis")]


def load_scenario(scenario_id: str) -> Scenario:
    """Return a deep copy of a scenario so callers may mutate freely."""
    if scenario_id not in SCENARIOS:
        raise KeyError(f"Unknown scenario: {scenario_id}. Known: {sorted(SCENARIOS)}")
    s = SCENARIOS[scenario_id]
    return Scenario(
        id=s.id,
        title=s.title,
        bundle=copy.deepcopy(s.bundle),
        expected_rule=s.expected_rule,
        expected_risk=s.expected_risk,
        expected_disposition=s.expected_disposition,
        description=s.description,
        notes=s.notes,
        tags=list(s.tags),
    )
