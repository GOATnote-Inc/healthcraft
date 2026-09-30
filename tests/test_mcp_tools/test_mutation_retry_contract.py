"""Retries must identify the same request before acknowledging a mutation."""

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import jsonschema
import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.clinical_tasks import ClinicalTask
from healthcraft.entities.encounters import Encounter
from healthcraft.entities.patients import Patient
from healthcraft.mcp.server import TOOL_NAME_MAP, create_server
from healthcraft.world.state import WorldState

SCHEMAS = {
    tool["name"]: tool["parameters"]
    for tool in json.loads(
        (Path(__file__).resolve().parents[2] / "configs/mcp-tools.json").read_text()
    )["tools"]
}
CASES = {
    "updateTaskStatus": (
        {"task_id": "TASK-AAAAAAAA", "status": "in_progress", "notes": "Original request"},
        {"status": "pending"},
        {"task_id": "TASK-BBBBBBBB"},
        "notes",
    ),
    "updateEncounter": (
        {"encounter_id": "ENC-AAAAAAAA", "notes": "Original request"},
        {"notes": "Changed request"},
        {"encounter_id": "ENC-BBBBBBBB"},
        "notes",
    ),
    "updatePatientRecord": (
        {"patient_id": "PAT-AAAAAAAA", "allergies": [{"name": "Synthetic A", "grade": 1}]},
        {"allergies": [{"name": "Synthetic B", "grade": 1}]},
        {"patient_id": "PAT-BBBBBBBB"},
        "allergies",
    ),
    "applyProtocol": (
        {"encounter_id": "ENC-AAAAAAAA", "protocol_name": "sepsis_bundle", "reason": "Supplied"},
        {"protocol_name": "stemi_alert"},
        {"encounter_id": "ENC-BBBBBBBB"},
        "reason",
    ),
}


def entity_snapshot(world):
    return deepcopy({kind.value: world.list_entities(kind.value) for kind in EntityType})


def field(entity, name):
    return entity[name] if isinstance(entity, dict) else getattr(entity, name)


@pytest.fixture(params=["dataclass", "dict"])
def world(request, monkeypatch):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")
    world = WorldState()
    for suffix in "AB":
        patient = Patient(
            id=f"PAT-{suffix * 8}",
            entity_type=EntityType.PATIENT,
            created_at=world.timestamp,
            updated_at=world.timestamp,
            first_name=suffix,
            last_name="Synthetic",
        )
        encounter = Encounter(
            id=f"ENC-{suffix * 8}",
            entity_type=EntityType.ENCOUNTER,
            created_at=world.timestamp,
            updated_at=world.timestamp,
            patient_id=patient.id,
            clinical_notes=(("Source", f"Baseline {suffix}"),),
        )
        task = ClinicalTask(
            id=f"TASK-{suffix * 8}",
            entity_type=EntityType.CLINICAL_TASK,
            created_at=world.timestamp,
            updated_at=world.timestamp,
            encounter_id=encounter.id,
            task_id=f"TASK-{suffix * 8}",
        )
        for kind, entity in (
            ("patient", patient),
            ("encounter", encounter),
            ("clinical_task", task),
        ):
            world.put_entity(kind, entity.id, asdict(entity) if request.param == "dict" else entity)
    for index, name in enumerate(("sepsis_bundle", "stemi_alert")):
        world.put_entity(
            "protocol",
            f"PROTO-{index}",
            {
                "name": name,
                "steps": [{"name": f"Synthetic step {index}", "description": "Recorded work"}],
            },
        )
    return world


@pytest.fixture(params=CASES)
def request_case(request):
    name = request.param
    params, payload_change, target_change, optional = deepcopy(CASES[name])
    params["idempotency_key"] = "shared-request-key"
    return name, params, payload_change, target_change, optional


def assert_readback(world, server, name, params):
    if name == "updateEncounter":
        actual = server.call_tool("getEncounterDetails", {"encounter_id": params["encounter_id"]})
        assert actual["data"]["clinical_notes"][-1][1] == params["notes"]
        notes = list(world.list_entities("clinical_note").values())
        assert len(notes) == 1
        assert notes[0]["content"] == params["notes"]
        assert notes[0]["encounter_id"] == params["encounter_id"]
        assert notes[0]["patient_id"] == "PAT-AAAAAAAA"
    elif name == "updatePatientRecord":
        actual = server.call_tool("getPatientHistory", {"patient_id": params["patient_id"]})
        assert actual["data"]["allergies"][-1] == params["allergies"][0]
    elif name == "updateTaskStatus":
        task = world.get_entity("clinical_task", params["task_id"])
        assert field(task, "status") == params["status"]
        assert field(task, "notes") == params["notes"]
    else:
        tasks = [
            t
            for t in world.list_entities("clinical_task").values()
            if field(t, "description").startswith("[")
        ]
        assert len(tasks) == 1
        assert field(tasks[0], "encounter_id") == params["encounter_id"]
        assert params["protocol_name"] in field(tasks[0], "description")


@pytest.mark.parametrize("change_kind", ["payload", "target", "missing_optional"])
def test_changed_request_conflicts_without_mutation(world, request_case, change_kind):
    name, params, payload_change, target_change, optional = request_case
    server = create_server(world)
    jsonschema.validate(params, SCHEMAS[name])
    assert server.call_tool(name, params)["status"] == "ok"
    snapshot = entity_snapshot(world)
    altered = deepcopy(params)
    if change_kind == "missing_optional":
        altered.pop(optional)
    else:
        altered.update(payload_change if change_kind == "payload" else target_change)
    jsonschema.validate(altered, SCHEMAS[name])
    saved_body = deepcopy(altered)
    result = server.call_tool(name, altered)
    assert result["status"] == "error", result
    assert result["code"] == "idempotency_conflict"
    assert not result.get("deduplicated", False)
    assert entity_snapshot(world) == snapshot
    assert altered == saved_body
    audit = world.audit_log[-1]
    assert audit.params == saved_body
    assert audit.tool_name == name
    assert audit.result_summary == "error"
    assert audit.error_code == "idempotency_conflict"
    assert not audit.deduplicated
    assert_readback(world, server, name, params)


@pytest.mark.parametrize("first_snake", [False, True])
def test_registered_alias_retry_is_exactly_one_effect(world, request_case, first_snake):
    name, params, _, _, _ = request_case
    server = create_server(world)
    first_name, second_name = (
        (TOOL_NAME_MAP[name], name) if first_snake else (name, TOOL_NAME_MAP[name])
    )
    initial_body = deepcopy(params)
    first = server.call_tool(first_name, params)
    assert first["status"] == "ok"
    snapshot = entity_snapshot(world)
    reordered = dict(reversed(list(params.items())))
    second = server.call_tool(second_name, reordered)
    assert second["status"] == "ok"
    assert second.get("deduplicated") is True
    assert entity_snapshot(world) == snapshot
    assert params == initial_body
    assert [a.tool_name for a in world.audit_log] == [first_name, second_name]
    assert [a.params for a in world.audit_log] == [initial_body, initial_body]
    assert world.audit_log[-1].deduplicated
    assert_readback(world, server, name, params)


@pytest.mark.parametrize("first_snake", [False, True])
def test_changed_alias_request_conflicts(world, request_case, first_snake):
    name, params, changes, _, _ = request_case
    server = create_server(world)
    first_name, second_name = (
        (TOOL_NAME_MAP[name], name) if first_snake else (name, TOOL_NAME_MAP[name])
    )
    assert server.call_tool(first_name, params)["status"] == "ok"
    snapshot = entity_snapshot(world)
    result = server.call_tool(second_name, {**params, **changes})
    assert result.get("code") == "idempotency_conflict", result
    assert entity_snapshot(world) == snapshot


def test_failed_attempt_does_not_reserve_key(world, request_case):
    name, params, _, targets, _ = request_case
    server = create_server(world)
    target_field = next(iter(targets))
    failed = server.call_tool(name, {**params, target_field: "MISSING"})
    assert failed["status"] == "error"
    result = server.call_tool(name, params)
    assert result["status"] == "ok"
    assert not result.get("deduplicated", False)
    assert_readback(world, server, name, params)


@pytest.mark.parametrize("mode", ["distinct_key", "no_key", "flag_off"])
def test_unrelated_requests_preserve_existing_behavior(world, request_case, monkeypatch, mode):
    name, params, changes, _, _ = request_case
    server = create_server(world)
    if mode == "flag_off":
        monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "0")
    if mode == "no_key":
        params.pop("idempotency_key")
    assert server.call_tool(name, params)["status"] == "ok"
    altered = {**params, **changes}
    if mode == "distinct_key":
        altered["idempotency_key"] = "other-request-key"
    result = server.call_tool(name, altered)
    assert result["status"] == "ok"
    assert not result.get("deduplicated", False)
    assert world.audit_log[-1].params == altered


@pytest.mark.parametrize("value", [True, 1.0])
def test_json_scalar_types_are_not_interchangeable(world, value):
    server = create_server(world)
    params = deepcopy(CASES["updatePatientRecord"][0])
    params["idempotency_key"] = "typed-source"
    assert server.call_tool("updatePatientRecord", params)["status"] == "ok"
    snapshot = entity_snapshot(world)
    changed = deepcopy(params)
    changed["allergies"][0]["grade"] = value
    result = server.call_tool("updatePatientRecord", changed)
    assert result.get("code") == "idempotency_conflict", result
    assert entity_snapshot(world) == snapshot
    assert type(world.audit_log[-1].params["allergies"][0]["grade"]) is type(value)


def test_input_mutation_cannot_rewrite_committed_retry_body(world):
    server = create_server(world)
    params = deepcopy(CASES["updatePatientRecord"][0])
    params["idempotency_key"] = "immutable-body"
    original = deepcopy(params)
    result = server.call_tool("updatePatientRecord", params)
    params["allergies"][0]["name"] = "Changed after return"
    result["data"]["allergies"][0]["name"] = "Changed returned response"
    assert world.audit_log[-1].params == original
    assert server.call_tool("updatePatientRecord", original).get("deduplicated") is True
    assert server.call_tool("updatePatientRecord", params).get("code") == "idempotency_conflict"
    assert_readback(world, server, "updatePatientRecord", original)


def test_tool_namespace_remains_separate(world):
    server = create_server(world)
    for name, (base, _, _, _) in CASES.items():
        result = server.call_tool(name, {**deepcopy(base), "idempotency_key": "one-key-many-tools"})
        assert result["status"] == "ok"
        assert not result.get("deduplicated", False)


def test_legacy_audit_without_request_payload_cannot_prove_retry(world):
    server = create_server(world)
    world.record_audit("updateEncounter", {}, "ok", idempotency_key="missing-body")
    result = server.call_tool(
        "updateEncounter",
        {
            "encounter_id": "ENC-AAAAAAAA",
            "notes": "New text",
            "idempotency_key": "missing-body",
        },
    )
    assert result.get("code") == "idempotency_conflict", result
    assert not world.list_entities("clinical_note")


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), {1: "not a string key"}, (1, 2)])
def test_non_json_keyed_request_is_rejected_before_mutation(world, bad_value):
    server = create_server(world)
    before = entity_snapshot(world)
    result = server.call_tool(
        "updatePatientRecord",
        {
            "patient_id": "PAT-AAAAAAAA",
            "advance_directives": {"source": bad_value},
            "idempotency_key": "finite-json-request",
        },
    )
    assert result.get("code") == "invalid_params", result
    assert entity_snapshot(world) == before


@pytest.mark.parametrize("bad_key", [False, 0, None, [], {}])
def test_present_nonstring_falsy_key_cannot_bypass_validation(world, request_case, bad_key):
    name, params, _, _, _ = request_case
    server = create_server(world)
    params["idempotency_key"] = bad_key
    before = entity_snapshot(world)
    result = server.call_tool(name, params)
    assert result.get("code") == "invalid_params", result
    assert entity_snapshot(world) == before
    assert world.audit_log[-1].params == params
    assert world.audit_log[-1].error_code == "invalid_params"


def test_flag_off_keeps_legacy_nonstring_key_behavior(world, request_case, monkeypatch):
    name, params, _, _, _ = request_case
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "0")
    params["idempotency_key"] = None
    assert create_server(world).call_tool(name, params)["status"] == "ok"
