"""Actual retrieval preserves imaging reports without invented study results."""

from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]


def read(patient, task_id="IMAGING-FIDELITY"):
    world = WorldState()
    ids = inject_task_patient(world, task_id, patient, {"time": "2026-01-15T13:00:00Z"})
    result = create_server(world).call_tool(
        "getEncounterDetails", {"encounter_id": ids["encounter_id"]}
    )
    assert result["status"] == "ok"
    return world, result["data"]


def test_actual_tool_preserves_explicit_results_and_strings_without_defaults():
    source = {
        "cardiac_mri": {
            "modality": "MR",
            "body_part": "heart",
            "findings": " exact finding ",
            "result": " separate result ",
            "time": "2026-01-15T10:00:00.123456789+01:00",
        },
        "ct_head": "Not indicated — no head injury",
    }
    _, data = read({"age": 50, "sex": "F", "imaging": source})
    records = {row["source_label"]: row for row in data["imaging"]}
    assert set(records) == set(source)
    mr = records["cardiac_mri"]
    assert mr["modality"] == "MR" and mr["body_part"] == "heart"
    assert mr["findings"] == " exact finding " and mr["result"] == " separate result "
    assert mr["impression"] is None
    assert mr["timestamp"] == source["cardiac_mri"]["time"]
    assert mr["source_data"] == source["cardiac_mri"]
    ct = records["ct_head"]
    assert ct["report_text"] == source["ct_head"]
    assert ct["modality"] is ct["findings"] is ct["timestamp"] is ct["status"] is None


@pytest.mark.parametrize("task_id", ["MW-006", "MW-009", "SCJ-017"])
def test_actual_tools_do_not_expose_known_conditional_guidance(task_id):
    task = next(
        load_task(p)
        for p in sorted((ROOT / "configs/tasks").rglob("*.yaml"))
        if load_task(p).id == task_id
    )
    original = deepcopy(task.patient)
    _, data = read(task.patient, task.id)
    assert data["imaging_projection_notices"]
    public = str(data)
    for key, value in task.patient["imaging"].items():
        if key.endswith("_if_ordered"):
            assert key not in public and value not in public
        elif isinstance(value, dict):
            for field, content in value.items():
                if field.startswith("expected_"):
                    assert field not in public and content not in public
    assert task.patient == original


def test_unreviewed_guidance_fails_before_world_mutation():
    world = WorldState()
    before = deepcopy(world._entities)
    with pytest.raises(ValueError, match="Unreviewed conditional"):
        inject_task_patient(
            world,
            "NEW-TASK",
            {
                "age": 50,
                "sex": "F",
                "imaging_pending": {
                    "study": {"expected_finding": "A target that must not reach the actor"}
                },
            },
        )
    assert world._entities == before
