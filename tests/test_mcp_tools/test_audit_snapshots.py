"""Audit evidence captures invocation-time values rather than mutable aliases."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict

import pytest

from healthcraft.mcp.audit import AuditLogger
from healthcraft.mcp.server import create_server
from healthcraft.world.state import WorldState


def _params():
    return {
        "encounter_id": "ENC-AAAAAAAA",
        "order_type": "medication",
        "details": {"medication": "SyntheticDrug", "dose": "1 mg", "tags": [{"source": "agent"}]},
    }


def test_world_audit_snapshots_nested_caller_parameters():
    world = WorldState()
    params = _params()
    expected = deepcopy(params)
    world.record_audit(
        "createClinicalOrder", params, "ok", idempotency_key="attempt-A", attempt_number=2
    )

    params["details"]["medication"] = "RewrittenDrug"
    params["details"]["tags"][0]["source"] = "rewritten"
    params["details"]["tags"].append({"source": "later"})
    params["encounter_id"] = "ENC-BBBBBBBB"

    entry = world.audit_log[0]
    assert entry.params == expected
    assert entry.timestamp == world.timestamp
    assert entry.result_summary == "ok"
    assert entry.idempotency_key == "attempt-A"
    assert entry.attempt_number == 2


def test_mcp_audit_snapshots_nested_parameters_without_changing_sanitization():
    world = WorldState()
    logger = AuditLogger("synthetic-session")
    params = _params()
    params["notes"] = "x" * 501
    expected = deepcopy(params)
    expected["notes"] = "x" * 500 + "...[truncated]"
    result = {"status": "ok", "data": params["details"]}
    logger.log_tool_call("createClinicalOrder", params, result, world.timestamp)

    result["data"]["dose"] = "999 mg"
    params["details"]["tags"][0]["source"] = "rewritten"
    result["status"] = "error"

    entry = logger.get_audit_trail()[0]
    assert entry.params == expected
    assert entry.result_summary == "ok"
    assert entry.timestamp == world.timestamp.isoformat()
    assert entry.session_id == "synthetic-session"
    assert json.loads(logger.to_json())[0]["params"] == expected


def test_real_tool_returned_dictionary_cannot_rewrite_recorded_order_evidence():
    world = WorldState()
    world.put_entity("patient", "PAT-AAAAAAAA", {"allergies": []})
    world.put_entity("encounter", "ENC-AAAAAAAA", {"patient_id": "PAT-AAAAAAAA"})
    server = create_server(world)
    params = _params()
    expected = deepcopy(params)

    result = server.call_tool("createClinicalOrder", params)
    assert result["status"] == "ok", result
    result["data"]["details"]["medication"] = "RewrittenDrug"
    result["data"]["details"]["tags"][0]["source"] = "rewritten"
    result["status"] = "error"

    assert world.audit_log[0].params == expected
    assert server.audit_logger.get_audit_trail()[0].params == expected
    assert world.audit_log[0].result_summary == "ok"
    assert server.audit_logger.get_audit_trail()[0].result_summary == "ok"


@pytest.mark.parametrize("mutate_snapshot", [False, True])
def test_world_snapshot_isolates_nested_audit_evidence(mutate_snapshot):
    world = WorldState()
    world.record_audit("createClinicalOrder", _params(), "ok")
    expected = asdict(world.audit_log[0])
    snapshot = world.snapshot()
    mutated, untouched = (snapshot, world) if mutate_snapshot else (world, snapshot)

    mutated.audit_log[0].params["details"]["dose"] = "999 mg"
    mutated.audit_log[0].params["details"]["tags"].append({"source": "later"})

    assert asdict(untouched.audit_log[0]) == expected


@pytest.mark.parametrize("reader", ["world", "logger", "logger_session"])
def test_reading_audit_entries_cannot_mutate_the_stored_evidence(reader):
    world = WorldState()
    logger = AuditLogger("synthetic-session")
    params = _params()
    world.record_audit("createClinicalOrder", params, "ok")
    logger.log_tool_call("createClinicalOrder", params, {"status": "ok"}, world.timestamp)

    def read():
        if reader == "world":
            return world.audit_log
        if reader == "logger":
            return logger.get_audit_trail()
        return logger.get_audit_trail("synthetic-session")

    expected = asdict(read()[0])

    retrieved = read()
    retrieved[0].params["details"]["dose"] = "999 mg"
    retrieved[0].params["details"]["tags"].clear()
    retrieved.clear()

    assert [asdict(entry) for entry in read()] == [expected]


@pytest.mark.parametrize("recorder", ["world", "logger"])
def test_returned_created_entry_cannot_mutate_the_stored_evidence(recorder):
    world = WorldState()
    logger = AuditLogger()
    params = _params()
    if recorder == "world":
        entry = world.record_audit("createClinicalOrder", params, "ok")
    else:
        entry = logger.log_tool_call("createClinicalOrder", params, {"status": "ok"})

    def read():
        return world.audit_log if recorder == "world" else logger.get_audit_trail()

    expected = asdict(entry)

    entry.params["details"]["dose"] = "999 mg"
    entry.params["details"]["tags"].clear()

    assert asdict(read()[0]) == expected
