"""Unknown tool attempts must appear in both audit trails without dispatch."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_execution import ExecutionRecorder
from healthcraft.world.state import WorldState


@pytest.mark.parametrize("name", ["doesNotExist", "does_not_exist", "getencounterDetails"])
def test_unknown_tool_has_one_error_audit_with_exact_request_and_clock(name, monkeypatch):
    clock = datetime(2031, 4, 5, 6, 7, tzinfo=timezone.utc)
    world = WorldState(start_time=clock)
    server = create_server(world)

    def forbidden_dispatch(*args):
        pytest.fail("An unknown tool must not dispatch a registered handler")

    for registered in server._handlers:
        monkeypatch.setitem(server._handlers, registered, forbidden_dispatch)
    params = {"nested": {"values": [1, None, "authored"]}, "idempotency_key": "unknown-attempt"}
    original = deepcopy(params)
    result = server.call_tool(name, params)
    assert result == {"status": "error", "code": "unknown_tool", "message": f"Unknown tool: {name}"}
    assert server.audit_logger.entry_count == len(world.audit_log) == 1
    entry = world.audit_log[0]
    assert entry.tool_name == name
    assert entry.params == original
    assert entry.timestamp == clock
    assert entry.result_summary == "error"
    assert entry.error_code == "unknown_tool"
    assert entry.idempotency_key == "unknown-attempt"
    assert entry.attempt_number == 1
    assert entry.deduplicated is False
    assert world.entity_counts == {}
    params["nested"]["values"].append("caller mutation")
    entry.params["nested"]["values"].append("retrieved audit mutation")
    result["code"] = "caller mutation"
    assert world.audit_log[0].params == original
    assert world.audit_log[0].error_code == "unknown_tool"
    private_entry = server.audit_logger.get_audit_trail()[0]
    assert private_entry.tool_name == name
    assert private_entry.params == original
    assert private_entry.timestamp == clock.isoformat()
    assert private_entry.result_summary == "error"


def test_missing_registered_handler_is_audited_under_exact_camel_name(monkeypatch):
    world = WorldState()
    server = create_server(world)
    monkeypatch.delitem(server._handlers, "get_encounter_details")
    response = server.call_tool("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})
    assert response["code"] == "unknown_tool"
    assert len(world.audit_log) == server.audit_logger.entry_count == 1
    assert world.audit_log[0].tool_name == "getEncounterDetails"
    assert world.audit_log[0].error_code == "unknown_tool"


def test_unknown_retries_increment_existing_key_attempt_metadata_without_deduplication():
    world = WorldState()
    server = create_server(world)
    params = {"idempotency_key": "shared-attempt-key"}
    assert server.call_tool("searchPatients", params)["status"] == "ok"
    assert server.call_tool("unknownOne", params)["code"] == "unknown_tool"
    world.advance_time(3)
    assert server.call_tool("unknownTwo", params)["code"] == "unknown_tool"
    assert server.call_tool("search_patients", params)["status"] == "ok"
    assert [entry.attempt_number for entry in world.audit_log] == [1, 2, 3, 4]
    assert [entry.tool_name for entry in world.audit_log] == [
        "searchPatients",
        "unknownOne",
        "unknownTwo",
        "search_patients",
    ]
    assert [entry.error_code for entry in world.audit_log] == [
        "",
        "unknown_tool",
        "unknown_tool",
        "",
    ]
    assert all(entry.deduplicated is False for entry in world.audit_log)
    assert world.audit_log[1].timestamp < world.audit_log[2].timestamp == world.timestamp
    assert server.audit_logger.entry_count == 4


def test_unknown_without_idempotency_key_has_normal_default_metadata():
    world = WorldState()
    response = create_server(world).call_tool("unknown", {})
    assert response["code"] == "unknown_tool"
    assert len(world.audit_log) == 1
    entry = world.audit_log[0]
    assert (entry.idempotency_key, entry.attempt_number, entry.deduplicated) == ("", 1, False)


@pytest.mark.parametrize("name", ["searchPatients", "search_patients"])
def test_known_camel_and_snake_alias_dispatch_remains_one_audit(name):
    world = WorldState()
    server = create_server(world)
    assert server.call_tool(name, {}) == {"status": "ok", "data": []}
    assert len(world.audit_log) == server.audit_logger.entry_count == 1
    assert world.audit_log[0].tool_name == name
    assert world.audit_log[0].result_summary == "ok"
    assert world.audit_log[0].error_code == ""


def test_actual_unknown_response_can_be_captured_by_exact_one_audit_recorder():
    world = WorldState()
    recorder = ExecutionRecorder(create_server(world), world)
    response = recorder.call("unknownExample", {"nested": {"values": []}})
    assert response["code"] == "unknown_tool"
    assert recorder.calls[0]["response"] == response
    assert recorder.calls[0]["audit_index"] == 0
    assert len(world.audit_log) == 1
