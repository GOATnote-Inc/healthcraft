"""Discharge documentation must preserve the advertised inputs and state."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.world.state import WorldState


@pytest.fixture
def case():
    world = WorldState()
    ids = inject_task_patient(world, "DISCHARGE-CONTRACT", {"age": 40, "sex": "F"}, {})
    return world, create_server(world), ids


def test_canonical_discharge_fields_persist_and_are_retrievable(case):
    world, server, ids = case
    medications = [{"name": "Example medication", "dose": "test dose", "duration": "3 days"}]
    follow_up = [{"service": "Synthetic clinic", "timeframe": "tomorrow", "phone": "555-0100"}]
    params = {
        "encounter_id": ids["encounter_id"],
        "diagnosis": "Synthetic diagnosis",
        "instructions": "UNIQUE instruction text",
        "medications": medications,
        "follow_up": follow_up,
        "return_precautions": ["UNIQUE return precaution"],
        "patient_language": "Portuguese",
    }
    original = deepcopy(params)
    schemas = json.loads((Path(__file__).parents[2] / "configs/mcp-tools.json").read_text())
    schema = next(tool for tool in schemas["tools"] if tool["name"] == "processDischarge")
    jsonschema.validate(params, schema["parameters"])

    response = server.call_tool("processDischarge", params)

    assert response["status"] == "ok", response
    data = response["data"]
    assert data["medications_prescribed"] == medications
    assert data["follow_up_arrangements"] == follow_up
    assert data["instructions_generated"] is True
    assert data["status"] == "discharged"
    note = world.get_entity("clinical_note", data["discharge_id"])
    assert note["patient_id"] == ids["patient_id"]
    assert note["encounter_id"] == ids["encounter_id"]
    assert note["medications_prescribed"] == medications
    assert note["follow_up_arrangements"] == follow_up
    assert note["return_precautions"] == params["return_precautions"]
    assert note["patient_language"] == "Portuguese"
    details = server.call_tool("getEncounterDetails", {"encounter_id": ids["encounter_id"]})
    retrieved = json.dumps(details["data"]["clinical_notes"])
    for value in (
        "UNIQUE instruction text",
        "UNIQUE return precaution",
        "Synthetic clinic",
        "tomorrow",
        "555-0100",
        "Example medication",
        "3 days",
        "Portuguese",
    ):
        assert value in retrieved
    assert params == original

    # Caller mutation must not rewrite saved clinical documentation.
    medications[0]["name"] = "changed after execution"
    follow_up[0]["service"] = "changed after execution"
    assert note["medications_prescribed"] == original["medications"]
    assert note["follow_up_arrangements"] == original["follow_up"]


def test_legacy_discharge_fields_remain_supported(case):
    world, server, ids = case
    result = server.call_tool(
        "processDischarge",
        {
            "encounter_id": ids["encounter_id"],
            "diagnosis": "Example",
            "discharge_instructions": "Legacy instructions",
            "follow_up_plan": "Legacy follow-up",
            "medications_prescribed": [{"name": "Legacy medication"}],
        },
    )
    assert result["status"] == "ok", result
    assert result["data"]["follow_up"] == "Legacy follow-up"
    assert result["data"]["medications_prescribed"] == [{"name": "Legacy medication"}]
    assert "Legacy instructions" in result["data"]["discharge_summary"]
    assert len(world.list_entities("clinical_note")) == 1


def test_missing_discharge_content_is_reported_as_missing(case):
    world, server, ids = case
    patient = world.get_entity("patient", ids["patient_id"])
    world.put_entity(
        "patient", patient.id, replace(patient, medications=("Example home medication",))
    )
    result = server.call_tool(
        "processDischarge", {"encounter_id": ids["encounter_id"], "diagnosis": "Example"}
    )
    assert result["status"] == "ok", result
    assert result["data"]["instructions_generated"] is False
    note = world.get_entity("clinical_note", result["data"]["discharge_id"])
    assert "No discharge instructions supplied" in note["content"]
    assert "No follow-up plan supplied" in note["content"]
    assert "[CONTINUE]" not in note["content"]
    assert "continuation not specified" in note["content"]


@pytest.mark.parametrize(
    "changes",
    [
        {"instructions": []},
        {"medications": "not a list"},
        {"medications": ["not an object"]},
        {"medications_prescribed": ["not an object"]},
        {"follow_up": "not an array"},
        {"follow_up": ["not an object"]},
        {"follow_up_plan": {}},
        {"return_precautions": "not an array"},
        {"return_precautions": [{}]},
        {"patient_language": []},
        {"diagnosis": {}},
        {"instructions": "one", "discharge_instructions": "two"},
        {"medications": [], "medications_prescribed": [{"name": "conflicting"}]},
        {"follow_up": [{"service": "one"}], "follow_up_plan": "conflicting"},
    ],
)
def test_invalid_or_conflicting_inputs_do_not_discharge_or_write_notes(case, changes):
    world, server, ids = case
    before = deepcopy(world.get_entity("encounter", ids["encounter_id"]))
    result = server.call_tool(
        "processDischarge",
        {"encounter_id": ids["encounter_id"], "diagnosis": "Example", **changes},
    )
    assert result["status"] == "error", result
    assert result["code"] in ("invalid_param", "conflicting_params")
    assert world.get_entity("encounter", ids["encounter_id"]) == before
    assert world.list_entities("clinical_note") == {}
    assert world.audit_log[-1].result_summary == "error"


def test_discharge_does_not_modify_another_encounter(case):
    world, server, ids = case
    other = inject_task_patient(world, "OTHER-PATIENT", {"age": 70, "sex": "M"}, {})
    before = deepcopy(world.get_entity("encounter", other["encounter_id"]))
    result = server.call_tool(
        "processDischarge", {"encounter_id": ids["encounter_id"], "diagnosis": "Example"}
    )
    assert result["status"] == "ok"
    assert world.get_entity("encounter", other["encounter_id"]) == before


def test_transfer_summary_preserves_unknown_triage(case):
    world, server, ids = case
    encounter = world.get_entity("encounter", ids["encounter_id"])
    world.put_entity(
        "encounter", encounter.id, replace(encounter, esi_level=None, triage_time=None)
    )
    result = server.call_tool(
        "processTransfer",
        {
            "encounter_id": ids["encounter_id"],
            "destination_facility": "University Medical Center",
            "reason": "Synthetic transfer test",
        },
    )
    assert result["status"] == "ok", result
    record = next(iter(world.list_entities("transfer").values()))
    assert "ESI Level: not recorded" in record.clinical_summary
