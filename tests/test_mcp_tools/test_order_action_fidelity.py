"""Orders and their linked clinical work preserve actual requested actions."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from healthcraft.entities.clinical_tasks import ClinicalTask
from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_execution import ExecutionRecorder
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "configs/tasks/temporal_reasoning/task_012_lab_recheck_schedule.yaml"
SCHEMA = next(
    tool["parameters"]
    for tool in json.loads((ROOT / "configs/mcp-tools.json").read_text())["tools"]
    if tool["name"] == "createClinicalOrder"
)


@pytest.fixture(autouse=True)
def enable_idempotency(monkeypatch):
    monkeypatch.delenv("HC_IDEMPOTENT_TOOLS", raising=False)


def scenario():
    task = load_task(TASK)
    world = WorldState(start_time=datetime(2026, 1, 15, 11, 30, tzinfo=timezone.utc))
    ids = inject_task_patient(world, task.id, task.patient, task.initial_state)
    return world, ids, ExecutionRecorder(create_server(world), world)


def order_params(ids, **extra):
    return {
        "encounter_id": ids["encounter_id"],
        "order_type": "lab",
        "details": {"test_name": "Potassium", "unit": "mEq/L"},
        "priority": "stat",
        "indication": "Repeat the authored potassium measurement",
        "idempotency_key": "temporal-order-1",
        **extra,
    }


def test_real_tr012_order_keeps_requested_action_clock_and_audit_links():
    world, ids, recorder = scenario()
    params = order_params(ids)
    jsonschema.validate(params, SCHEMA)
    patients_before = deepcopy(world.list_entities("patient"))
    encounters_before = deepcopy(world.list_entities("encounter"))
    response = recorder.call("createClinicalOrder", params)
    assert response["status"] == "ok"
    order = world.get_entity("order", response["data"]["id"])
    assert order["priority"] == "stat"
    assert order["indication"] == params["indication"]
    assert order["order_id"] == order["id"]
    clinical_task = world.get_entity("clinical_task", order["task_id"])
    assert isinstance(clinical_task, ClinicalTask)
    assert clinical_task.id == clinical_task.task_id == order["task_id"]
    assert clinical_task.encounter_id == order["encounter_id"] == ids["encounter_id"]
    assert json.loads(clinical_task.description) == {
        "order_type": "lab",
        "details": {"test_name": "Potassium", "unit": "mEq/L"},
    }
    assert clinical_task.task_type == "lab_draw"
    assert clinical_task.priority == "stat"
    assert clinical_task.notes == params["indication"]
    assert clinical_task.created_at == clinical_task.updated_at == world.timestamp
    assert clinical_task.due_time is clinical_task.completed_time is None
    assert clinical_task.assigned_to == ""
    assert clinical_task.ordered_by == order["ordered_by"] == "attending"
    assert order["ordered_at"] == world.timestamp.isoformat()
    assert recorder.calls[0]["response"]["data"] == order
    audit = world.audit_log[recorder.calls[0]["audit_index"]]
    assert audit.params == params and audit.result_summary == "ok"
    assert world.list_entities("patient") == patients_before
    assert world.list_entities("encounter") == encounters_before

    completed = recorder.call(
        "updateTaskStatus", {"task_id": order["task_id"], "status": "completed"}
    )
    assert completed["status"] == "ok"
    assert world.get_entity("clinical_task", order["task_id"]).completed_time == world.timestamp


@pytest.mark.parametrize(
    ("kind", "task_type", "details"),
    [
        ("lab", "lab_draw", {"test": "Potassium", "unit": "mEq/L"}),
        ("imaging", "imaging", {"study": "Authored study", "instructions": ["Literal"]}),
        (
            "medication",
            "medication_admin",
            {"medication": "Calcium gluconate", "dose": "2g", "route": "IV"},
        ),
        ("procedure", "procedure", {"name": "Authored procedure", "laterality": "left"}),
        ("consult", "consult", {"specialty": "Nephrology", "question": "Authored request"}),
        ("blood_product", "blood_admin", {"product": "Authored product", "units": 2}),
    ],
)
def test_all_order_kinds_retain_exact_details_without_synthetic_action(kind, task_type, details):
    world, ids, recorder = scenario()
    response = recorder.call(
        "createClinicalOrder", order_params(ids, order_type=kind, details=details)
    )
    assert response["status"] == "ok"
    task = world.get_entity("clinical_task", response["data"]["task_id"])
    assert task.task_type == task_type
    assert json.loads(task.description) == {"order_type": kind, "details": details}


@pytest.mark.parametrize("priority", ["routine", "urgent", "stat", "emergent"])
def test_advertised_priorities_are_preserved_without_reinterpreting_urgency(priority):
    world, ids, recorder = scenario()
    params = order_params(ids, priority=priority)
    jsonschema.validate(params, SCHEMA)
    response = recorder.call("createClinicalOrder", params)
    task = world.get_entity("clinical_task", response["data"]["task_id"])
    assert response["data"]["priority"] == task.priority == priority
    assert task.due_time is None


def test_unspecified_priority_and_time_remain_unknown_and_existing_consumer_reads_them():
    world, ids, recorder = scenario()
    params = order_params(ids)
    params.pop("priority")
    params.pop("indication")
    response = recorder.call("createClinicalOrder", params)
    task = world.get_entity("clinical_task", response["data"]["task_id"])
    assert "priority" not in response["data"] and "indication" not in response["data"]
    assert task.priority == task.notes == task.assigned_to == ""
    assert task.due_time is None
    # Existing consumer reads the work queue; this is not a clinical discharge evaluation.
    discharged = recorder.call(
        "processDischarge",
        {"encounter_id": ids["encounter_id"], "diagnosis": "Synthetic document fixture"},
    )
    assert discharged["status"] == "ok"
    assert discharged["data"]["pending_tasks_warning"][0]["priority"] == ""


def test_equivalent_worlds_and_idempotent_retries_keep_one_exact_task():
    outputs = []
    for _ in range(2):
        world, ids, recorder = scenario()
        response = recorder.call("createClinicalOrder", order_params(ids))
        task = world.get_entity("clinical_task", response["data"]["task_id"])
        replay = recorder.call(
            "createClinicalOrder", order_params(ids, priority="routine", indication="Changed retry")
        )
        assert replay["deduplicated"] is True
        assert replay["data"] == response["data"]
        assert world.list_entities("clinical_task") == {task.id: task}
        outputs.append((response, asdict(task)))
    assert outputs[0] == outputs[1]


def test_task_id_collision_rejects_without_partial_order_or_unrelated_task_mutation():
    first, ids, recorder = scenario()
    response = recorder.call("createClinicalOrder", order_params(ids))
    original = first.get_entity("clinical_task", response["data"]["task_id"])
    world, ids, recorder = scenario()
    existing = replace(original, encounter_id="ENC-UNRELATED", description="Unrelated work")
    world.put_entity("clinical_task", existing.id, existing)
    response = recorder.call("createClinicalOrder", order_params(ids))
    assert response["status"] == "error"
    assert world.list_entities("order") == {}
    assert world.list_entities("clinical_task") == {existing.id: existing}
    assert world.audit_log[-1].result_summary == "error"


@pytest.mark.parametrize(
    "extra",
    [
        {"priority": "undefined"},
        {"priority": ["stat"]},
        {"indication": []},
        {"details": {"bad": object()}},
    ],
)
def test_malformed_action_metadata_fails_before_world_mutation(extra):
    world, ids, _ = scenario()
    response = create_server(world).call_tool("createClinicalOrder", order_params(ids, **extra))
    assert response["status"] == "error"
    assert world.list_entities("order") == world.list_entities("clinical_task") == {}


def test_existing_order_for_another_encounter_is_not_treated_as_idempotent_retry():
    first, ids, recorder = scenario()
    response = recorder.call("createClinicalOrder", order_params(ids))
    world, ids, recorder = scenario()
    unrelated = {**response["data"], "encounter_id": "ENC-UNRELATED"}
    world.put_entity("order", unrelated["id"], unrelated)
    response = recorder.call("createClinicalOrder", order_params(ids))
    assert response["status"] == "error"
    assert world.list_entities("order") == {unrelated["id"]: unrelated}
    assert world.list_entities("clinical_task") == {}
