"""Regression coverage for authored social history reaching the read tools."""

from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

_TASK_PATH = (
    Path(__file__).parents[2] / "configs/tasks/temporal_reasoning/task_017_tetanus_prophylaxis.yaml"
)


def test_tr017_social_history_values_reach_patient_history():
    task = load_task(_TASK_PATH)
    source = deepcopy(task.patient)
    world = WorldState()
    ids = inject_task_patient(world, task.id, task.patient, task.initial_state)

    result = create_server(world).call_tool("getPatientHistory", {"patient_id": ids["patient_id"]})

    assert result["status"] == "ok"
    assert list(result["data"]["social_history"]) == [
        "occupation: Retired teacher, avid gardener",
        "tetanus_risk_factors: Gardening in soil, barefoot",
    ]
    assert task.patient == source


@pytest.mark.parametrize(
    "social_history",
    [[], ["Never smoked", "Occupation: retired teacher; volunteer gardener"]],
)
def test_list_social_history_and_other_authored_history_remain_unchanged(social_history):
    source = {
        "age": 61,
        "sex": "F",
        "social_history": social_history,
        "family_history": ["Father: stroke at 70"],
        "past_medical_history": ["Hypertension"],
        "medications": ["Lisinopril 10mg daily"],
        "allergies": [{"substance": "Penicillin", "reaction": "Rash"}],
    }
    original = deepcopy(source)
    world = WorldState()
    ids = inject_task_patient(world, "HISTORY-COMPAT", source)

    result = create_server(world).call_tool("getPatientHistory", {"patient_id": ids["patient_id"]})

    assert result["status"] == "ok"
    for key in ("social_history", "family_history", "medications", "allergies"):
        assert list(result["data"][key]) == source[key]
    assert list(result["data"]["pmh"]) == source["past_medical_history"]
    assert source == original
