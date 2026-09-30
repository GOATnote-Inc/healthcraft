"""Treatment-plan schema, patient scope, and structured-record regressions."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def world():
    world = WorldState()
    world.put_entity("patient", "PAT-A", {"allergies": ["Aspirin"], "medications": ["Warfarin"]})
    world.put_entity("patient", "PAT-B", {"allergies": [], "medications": []})
    world.put_entity("encounter", "ENC-A", {"patient_id": "PAT-A", "meds_administered": []})
    world.put_entity(
        "encounter",
        "ENC-B",
        {"patient_id": "PAT-B", "meds_administered": [{"medication_name": "Heparin"}]},
    )
    return world


def _call(world, params):
    return create_server(world).call_tool("validateTreatmentPlan", params)


def _assert_error(world, params, code):
    result = _call(world, params)
    assert result["status"] == "error", result
    assert result["code"] == code, result
    assert world.audit_log[-1].result_summary == "error"
    assert world.audit_log[-1].error_code == code


def test_documented_patient_and_medication_object_is_executable(world):
    params = {"patient_id": "PAT-A", "medications": [{"name": "Aspirin", "dose": "81 mg"}]}
    config = json.loads((REPO_ROOT / "configs/mcp-tools.json").read_text())
    schemas = config["tools"] if isinstance(config, dict) else config
    schema = next(item for item in schemas if item["name"] == "validateTreatmentPlan")
    jsonschema.validate(params, schema["parameters"])

    result = _call(world, params)

    assert result["status"] == "ok", result
    assert result["data"]["valid"] is False
    assert any("Aspirin" in item for item in result["data"]["allergy_conflicts"])
    assert any("warfarin" in item for item in result["data"]["interactions"])
    assert world.audit_log[-1].result_summary == "ok"


def test_legacy_encounter_and_string_medications_remain_supported(world):
    result = _call(world, {"encounter_id": "ENC-A", "medications": ["Aspirin"]})

    assert result["status"] == "ok", result
    assert result["data"]["valid"] is False
    assert any("Aspirin" in item for item in result["data"]["allergy_conflicts"])
    assert any("warfarin" in item for item in result["data"]["warnings"])


@pytest.mark.parametrize(
    "medication", ["Aspirin", {"name": "Aspirin"}, {"medication_name": "Aspirin"}]
)
def test_structured_allergy_records_are_normalized_without_modifying_patient(world, medication):
    allergy = {"name": "Aspirin", "reaction": "Hives", "severity": "severe", "verified": True}
    patient = {"allergies": [allergy], "medications": []}
    world.put_entity("patient", "PAT-A", deepcopy(patient))

    result = _call(world, {"encounter_id": "ENC-A", "medications": [medication]})

    assert result["status"] == "ok", result
    assert result["data"]["valid"] is False
    assert len(result["data"]["allergy_conflicts"]) == 1
    assert world.get_entity("patient", "PAT-A") == patient


def test_actual_ir001_injected_allergy_record_is_supported():
    task = load_task(REPO_ROOT / "configs/tasks/information_retrieval/task_001_allergy_check.yaml")
    world = WorldState()
    ids = inject_task_patient(world, task.id, task.patient, task.initial_state)

    result = _call(
        world, {"patient_id": ids["patient_id"], "medications": [{"name": "Penicillin"}]}
    )

    assert result["status"] == "ok", result
    assert result["data"]["valid"] is False
    assert any("Penicillin" in item for item in result["data"]["allergy_conflicts"])


def test_explicit_patient_must_own_explicit_encounter(world):
    _assert_error(
        world,
        {"patient_id": "PAT-B", "encounter_id": "ENC-A", "medications": ["Aspirin"]},
        "patient_encounter_mismatch",
    )


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({}, "missing_param"),
        ({"patient_id": "PAT-MISSING"}, "patient_not_found"),
        ({"encounter_id": "ENC-MISSING"}, "encounter_not_found"),
        ({"patient_id": "PAT-MISSING", "encounter_id": "ENC-A"}, "patient_not_found"),
        ({"patient_id": []}, "invalid_param"),
        ({"patient_id": "   "}, "invalid_param"),
        ({"encounter_id": []}, "invalid_param"),
        ({"patient_id": "PAT-A", "encounter_id": {}}, "invalid_param"),
    ],
)
def test_invalid_scope_returns_audited_error(world, params, code):
    _assert_error(world, params, code)


@pytest.mark.parametrize("patient_id", ["PAT-MISSING", ""])
def test_encounter_with_missing_patient_cannot_validate(world, patient_id):
    world.put_entity("encounter", "ENC-ORPHAN", {"patient_id": patient_id})
    _assert_error(
        world,
        {"encounter_id": "ENC-ORPHAN", "medications": ["Aspirin"]},
        "patient_not_found",
    )


def test_patient_only_does_not_use_unrelated_encounter_medications(world):
    result = _call(world, {"patient_id": "PAT-A", "medications": [{"name": "Alteplase"}]})

    assert result["status"] == "ok", result
    assert result["data"]["interactions"] == []


def test_matching_encounter_medications_are_checked(world):
    result = _call(
        world,
        {"patient_id": "PAT-B", "encounter_id": "ENC-B", "medications": [{"name": "Alteplase"}]},
    )

    assert result["status"] == "ok", result
    assert any("heparin" in item for item in result["data"]["interactions"])


def test_structured_current_medications_are_checked(world):
    world.put_entity("patient", "PAT-A", {"allergies": [], "medications": [{"name": "Warfarin"}]})
    result = _call(world, {"patient_id": "PAT-A", "medications": [{"name": "Aspirin"}]})

    assert result["status"] == "ok", result
    assert any("warfarin" in item for item in result["data"]["interactions"])


@pytest.mark.parametrize("medications", ["Aspirin", {}, [None], [{}], [{"name": 7}], [""]])
def test_uninterpretable_medication_inputs_do_not_validate(world, medications):
    _assert_error(
        world,
        {"encounter_id": "ENC-A", "medications": medications},
        "invalid_param",
    )


@pytest.mark.parametrize("procedures", ["CPR", [{}], [None], [""]])
def test_uninterpretable_procedure_inputs_do_not_validate(world, procedures):
    _assert_error(
        world,
        {"encounter_id": "ENC-A", "procedures": procedures},
        "invalid_param",
    )


@pytest.mark.parametrize(
    ("field", "records"),
    [("allergies", [{}]), ("allergies", [""]), ("medications", [{}])],
)
def test_uninterpretable_patient_records_do_not_silently_pass(world, field, records):
    patient = {"allergies": [], "medications": []}
    patient[field] = records
    world.put_entity("patient", "PAT-A", patient)
    _assert_error(
        world,
        {"encounter_id": "ENC-A", "medications": ["Aspirin"]},
        "invalid_patient_data",
    )


def test_patient_only_preserves_existing_directive_check(world):
    world.put_entity("patient", "PAT-A", {"advance_directives": "dnr_dni"})
    result = _call(world, {"patient_id": "PAT-A", "procedures": ["Intubation"]})

    assert result["status"] == "ok", result
    assert result["data"]["valid"] is False
    assert any("DNR_DNI" in item for item in result["data"]["contraindications"])


@pytest.mark.parametrize(
    ("protocol_id", "code"),
    [
        ("PROTO-KNOWN", "protocol_validation_unavailable"),
        ("PROTO-MISSING", "protocol_not_found"),
        ([], "invalid_param"),
        ("", "invalid_param"),
    ],
)
def test_requested_protocol_compliance_is_not_silently_certified(world, protocol_id, code):
    world.put_entity("protocol", "PROTO-KNOWN", {"name": "Example protocol"})
    _assert_error(
        world,
        {"encounter_id": "ENC-A", "medications": ["Aspirin"], "protocol_id": protocol_id},
        code,
    )


def test_malformed_encounter_medication_is_not_silently_ignored(world):
    world.put_entity("encounter", "ENC-A", {"patient_id": "PAT-A", "meds_administered": [{}]})
    _assert_error(
        world,
        {"encounter_id": "ENC-A", "medications": ["Alteplase"]},
        "invalid_encounter_data",
    )
