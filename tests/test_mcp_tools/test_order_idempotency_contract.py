"""Idempotency retries must represent the same persisted clinical request."""

from copy import deepcopy

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.world.state import WorldState


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")
    world = WorldState()
    ids = inject_task_patient(world, "ORDER-IDEM", {"age": 40, "sex": "F", "allergies": []}, {})
    params = {
        "encounter_id": ids["encounter_id"],
        "order_type": "medication",
        "details": {"name": "acetaminophen", "dose": 1},
        "idempotency_key": "one-effect",
    }
    return world, create_server(world), params


@pytest.mark.parametrize(
    "changes",
    [
        {"details": {"name": "phentolamine", "dose": 1}},
        {"details": {"name": "acetaminophen", "dose": 1.0}},
        {"priority": "stat"},
        {"indication": "Changed request context"},
    ],
)
def test_same_key_different_request_fails_without_mutating_original(setup, changes):
    world, server, params = setup
    initial = server.call_tool("createClinicalOrder", params)
    orders_before = deepcopy(world.list_entities("order"))
    tasks_before = deepcopy(world.list_entities("clinical_task"))
    assert initial["status"] == "ok"
    rejected = server.call_tool("createClinicalOrder", {**params, **changes})
    assert rejected["status"] == "error"
    assert rejected["code"] == "idempotency_conflict"
    assert not rejected.get("deduplicated", False)
    assert world.list_entities("order") == orders_before
    assert world.list_entities("clinical_task") == tasks_before
    assert world.audit_log[-1].result_summary == "error"
    assert world.audit_log[-1].error_code == "idempotency_conflict"


def test_identical_retry_is_still_exactly_one_persisted_action(setup):
    world, server, params = setup
    initial = server.call_tool("createClinicalOrder", params)
    retry = server.call_tool("createClinicalOrder", deepcopy(params))
    assert initial["status"] == retry["status"] == "ok"
    assert retry["deduplicated"] is True
    assert retry["data"] == initial["data"]
    assert len(world.list_entities("order")) == len(world.list_entities("clinical_task")) == 1


def test_removing_explicit_priority_or_indication_is_not_the_same_request(setup):
    world, server, params = setup
    assert (
        server.call_tool(
            "createClinicalOrder", {**params, "priority": "urgent", "indication": "Supplied"}
        )["status"]
        == "ok"
    )
    assert server.call_tool("createClinicalOrder", params)["code"] == "idempotency_conflict"
    assert len(world.list_entities("order")) == 1
