"""Authored orders and mixed care context must not become administered doses."""

from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]


def inject(patient, task_id="CARE-SOURCE", setting=None):
    world = WorldState()
    ids = inject_task_patient(world, task_id, patient, setting)
    server = create_server(world)
    result = server.call_tool("getEncounterDetails", {"encounter_id": ids["encounter_id"]})
    assert result["status"] == "ok"
    return world, server, ids, result["data"]


@pytest.mark.parametrize("number", [2, 3, 6, 7])
def test_real_mixed_care_is_preserved_without_inventing_medication_events(number):
    task = load_task(
        next((ROOT / "configs/tasks/clinical_communication").glob(f"task_{number:03d}_*.yaml"))
    )
    original = deepcopy(task.patient)
    _, _, _, encounter = inject(task.patient, task.id, task.initial_state)
    assert encounter["meds_administered"] == ()
    rows = {row["source_collection"]: row for row in encounter["authored_care"]}
    for field in ("active_orders", "current_management"):
        if field in task.patient:
            assert rows[field]["source_data"] == task.patient[field]
            assert rows[field]["source_path"] == f"/patient/{field}"
    assert task.patient == original


def test_coexisting_care_fields_preserve_structure_and_negation_without_parser_guessing():
    patient = {
        "age": 50,
        "sex": "F",
        "active_orders": ["Hold warfarin", "NPO"],
        "current_management": [{"drug": "Example", "status": "not-done", "reason": "refused"}],
    }
    _, server, ids, encounter = inject(patient)
    assert encounter["meds_administered"] == ()
    rows = {row["source_collection"]: row for row in encounter["authored_care"]}
    assert rows["active_orders"]["source_data"] == patient["active_orders"]
    assert rows["current_management"]["source_data"] == patient["current_management"]
    patient["current_management"][0]["status"] = "changed caller"
    rows["active_orders"]["source_data"].append("changed returned result")
    reread = server.call_tool("getEncounterDetails", {"encounter_id": ids["encounter_id"]})["data"]
    again = {row["source_collection"]: row["source_data"] for row in reread["authored_care"]}
    assert again["active_orders"] == ["Hold warfarin", "NPO"]
    assert again["current_management"][0]["status"] == "not-done"


def test_discharge_does_not_report_plans_as_given_or_unknown_as_none():
    _, server, ids, _ = inject({"age": 50, "sex": "F", "active_orders": ["NPO", "Hold warfarin"]})
    response = server.call_tool(
        "processDischarge", {"encounter_id": ids["encounter_id"], "diagnosis": "Synthetic"}
    )
    assert response["status"] == "ok"
    text = response["data"]["discharge_summary"]
    assert "NPO  PO" not in text
    assert "Hold warfarin  PO" not in text
    assert "No medications administered during visit" not in text
    assert "administration" in text.lower() and "not established" in text.lower()
    assert "authored" in text.lower() and "active_orders" in text and "Hold warfarin" in text


def test_discharge_without_medication_evidence_does_not_assert_no_doses_given():
    _, server, ids, _ = inject({"age": 50, "sex": "F"})
    response = server.call_tool(
        "processDischarge", {"encounter_id": ids["encounter_id"], "diagnosis": "Synthetic"}
    )
    assert response["status"] == "ok"
    assert "No medications administered during visit" not in response["data"]["discharge_summary"]


@pytest.mark.parametrize(
    "relative",
    [
        "temporal_reasoning/task_024_serial_troponin_protocol.yaml",
        "clinical_communication/task_021_pharmacy_clarification.yaml",
    ],
)
def test_explicit_care_reports_keep_source_fields_without_becoming_audited_doses(relative):
    path = ROOT / "configs/tasks" / relative
    task = load_task(path)
    world, _, _, encounter = inject(task.patient, task.id, task.initial_state)
    source = {row["source_collection"]: row["source_data"] for row in encounter["authored_care"]}
    for field in ("treatments_given", "original_prescriptions"):
        if field in task.patient:
            assert source[field] == task.patient[field]
    assert encounter["meds_administered"] == ()
    assert all(entry.tool_name == "getEncounterDetails" for entry in world.audit_log)


def test_unresolved_encounter_context_cannot_silently_validate_drug_interactions():
    task = load_task(
        ROOT / "configs/tasks/temporal_reasoning/task_024_serial_troponin_protocol.yaml"
    )
    world, server, ids, _ = inject(task.patient, task.id, task.initial_state)
    result = server.call_tool(
        "validateTreatmentPlan",
        {
            "encounter_id": ids["encounter_id"],
            "medications": [{"name": "Alteplase"}],
        },
    )
    assert result["status"] == "error"
    assert result["code"] == "unresolved_medication_context"
    assert "valid" not in result.get("data", {})
    assert world.audit_log[-1].result_summary == "error"
    assert "/patient/treatments_given" in result["details"]["source_paths"]


def test_patient_only_plan_check_explicitly_excludes_encounter_context():
    _, server, ids, _ = inject({"age": 50, "sex": "F", "current_management": ["Heparin held"]})
    result = server.call_tool(
        "validateTreatmentPlan",
        {
            "patient_id": ids["patient_id"],
            "medications": [{"name": "Alteplase"}],
        },
    )
    assert result["status"] == "ok"
    assert result["data"]["encounter_medications_assessed"] is False
    assert result["data"]["assessment_scope"] == "provided_patient_history_only"


def test_discovery_advertises_encounter_scope_and_actual_source_context_fields():
    import json

    schemas = {
        tool["name"]: tool
        for tool in json.loads((ROOT / "configs/mcp-tools.json").read_text())["tools"]
    }
    validator = schemas["validateTreatmentPlan"]
    assert "encounter_id" in validator["parameters"]["properties"]
    assert "assessment_scope" in validator["returns"]["properties"]
    assert "encounter_medications_assessed" in validator["returns"]["properties"]
    details = schemas["getEncounterDetails"]["returns"]["properties"]
    assert "authored_care" in details and "meds_administered" in details
    assert "clinical_notes" in details and "imaging_projection_notices" in details
    assert "unavailable" in validator["description"].lower()


def test_unresolved_context_reports_known_allergy_evidence_without_coercing_unknown_check():
    _, server, ids, _ = inject(
        {
            "age": 50,
            "sex": "F",
            "allergies": ["Aspirin"],
            "current_management": ["unresolved source statement"],
        }
    )
    response = server.call_tool(
        "validateTreatmentPlan",
        {
            "patient_id": ids["patient_id"],
            "encounter_id": ids["encounter_id"],
            "medications": [{"name": "Aspirin"}],
        },
    )
    assert response["status"] == "error"
    assert response["details"]["unassessed"] == ["encounter_drug_interactions"]
    assert any("Aspirin" in value for value in response["details"]["known_allergy_conflicts"])


def test_other_patients_and_prior_visits_are_not_projected_as_index_patient_care():
    _, _, _, encounter = inject(
        {
            "age": 50,
            "sex": "F",
            "prior_encounters": [{"active_orders": ["Other visit medication"]}],
            "other_patient": {"current_management": ["Other patient's medication"]},
        }
    )
    assert encounter["authored_care"] == ()
    assert encounter["meds_administered"] == ()


def test_medication_context_does_not_prevent_a_separate_procedure_only_check():
    _, server, ids, _ = inject({"age": 50, "sex": "F", "current_management": ["unresolved"]})
    response = server.call_tool(
        "validateTreatmentPlan",
        {
            "patient_id": ids["patient_id"],
            "encounter_id": ids["encounter_id"],
            "procedures": ["Synthetic procedure"],
        },
    )
    assert response["status"] == "ok"
    assert response["data"]["encounter_medications_assessed"] is False


@pytest.mark.parametrize(
    "source",
    [
        {0: "First entry", "note": "Second entry"},
        {"nested": {0: "First entry", "note": "Second entry"}},
    ],
)
def test_discharge_rendering_preserves_mixed_source_keys_without_comparison_errors(source):
    _, server, ids, _ = inject({"age": 50, "sex": "F", "current_management": source})
    result = server.call_tool(
        "processDischarge", {"encounter_id": ids["encounter_id"], "diagnosis": "Synthetic"}
    )
    assert result["status"] == "ok"
    assert "First entry" in result["data"]["discharge_summary"]
    assert "Second entry" in result["data"]["discharge_summary"]


def test_unresolved_encounter_context_retains_independently_assessable_findings():
    _, server, ids, _ = inject(
        {
            "age": 50,
            "sex": "F",
            "medications": ["Warfarin"],
            "advance_directives": "dnr",
            "current_management": ["unresolved"],
        }
    )
    result = server.call_tool(
        "validateTreatmentPlan",
        {
            "encounter_id": ids["encounter_id"],
            "medications": [{"name": "Aspirin"}],
            "procedures": ["CPR"],
        },
    )
    assert result["status"] == "error" and result["code"] == "unresolved_medication_context"
    findings = result["details"]["known_findings"]
    assert any("warfarin" in value.lower() for value in findings["interactions"])
    assert any("DNR" in value for value in findings["contraindications"])
    assert result["details"]["unassessed"] == ["encounter_drug_interactions"]
