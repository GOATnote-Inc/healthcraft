"""Reference evidence must come from actual tools and survive serialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_execution import ExecutionRecorder, run_ir002_reference
from healthcraft.world.state import WorldState


def test_recorder_executes_and_snapshots_real_requests_responses_and_audit():
    world = WorldState()
    world.put_entity("encounter", "ENC-AAAAAAAA", {"id": "ENC-AAAAAAAA", "notes": ["original"]})
    recorder = ExecutionRecorder(create_server(world), world)
    params = {"encounter_id": "ENC-AAAAAAAA"}
    response = recorder.call("getEncounterDetails", params)
    response["data"]["notes"].append("caller mutation")
    params["encounter_id"] = "ENC-BBBBBBBB"
    captured = recorder.calls
    assert captured[0]["params"] == {"encounter_id": "ENC-AAAAAAAA"}
    assert captured[0]["response"]["data"]["notes"] == ["original"]
    assert captured[0]["audit_index"] == 0
    assert world.audit_log[0].tool_name == "getEncounterDetails"
    captured[0]["response"]["data"]["notes"].clear()
    assert recorder.calls[0]["response"]["data"]["notes"] == ["original"]


def test_failed_real_tool_calls_are_evidence_not_success():
    world = WorldState()
    recorder = ExecutionRecorder(create_server(world), world)
    result = recorder.call("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})
    assert result["status"] == "error"
    assert recorder.calls[0]["response"]["status"] == "error"
    assert recorder.calls[0]["audit_index"] == 0


def test_recorder_rejects_unrecorded_dispatch():
    world = WorldState()
    dispatched = []

    class UnauditedServer:
        def call_tool(self, name, params):
            dispatched.append((name, params))
            return {"status": "error", "code": "unrecorded_test_failure"}

    recorder = ExecutionRecorder(UnauditedServer(), world)
    with pytest.raises(ValueError, match="audit"):
        recorder.call("testUnauditedTool", {"source": "synthetic"})
    assert dispatched == [("testUnauditedTool", {"source": "synthetic"})]
    assert world.audit_log == []
    assert recorder.calls == []


def test_real_unknown_tool_attempt_is_recorded_as_failed_evidence():
    world = WorldState()
    server = create_server(world)
    recorder = ExecutionRecorder(server, world)
    params = {"source": {"values": [None, "synthetic"]}}
    response = recorder.call("nonexistentTool", params)
    assert response == {
        "status": "error",
        "code": "unknown_tool",
        "message": "Unknown tool: nonexistentTool",
    }
    assert len(recorder.calls) == len(world.audit_log) == server.audit_logger.entry_count == 1
    call = recorder.calls[0]
    assert call["name"] == "nonexistentTool"
    assert call["params"] == params
    assert call["response"] == response
    assert call["audit_index"] == 0
    audit = world.audit_log[0]
    assert audit.tool_name == call["name"]
    assert audit.params == call["params"]
    assert audit.result_summary == "error"
    assert audit.error_code == "unknown_tool"
    assert world.entity_counts == {}


def test_reference_executes_all_four_visits_and_persists_summary_reproducibly():
    first = run_ir002_reference(world=WorldState())
    second = run_ir002_reference(world=WorldState())
    assert first["verification"]["mechanical_passed"] is True
    assert [row["id"] for row in first["verification"]["criteria"]] == [
        "IR-002-C01",
        "IR-002-C02",
        "IR-002-C03",
        "IR-002-C07",
    ]
    assert first["execution_kind"] == "in_process_mcp_handlers"
    assert first["calls"] == second["calls"]
    assert first["trace_sha256"] == second["trace_sha256"]
    assert len(first["calls"]) == 8
    assert len({call["id"] for call in first["calls"]}) == 8
    assert "reward" not in first
    assert "passed" not in first
    assert first["limitations"]
    assert first["source_hashes"]
    assert (
        first["task_sha256"]
        == first["source_hashes"][
            "configs/tasks/information_retrieval/task_002_encounter_lookup.yaml"
        ]
    )
    assert json.loads(json.dumps(first, allow_nan=False)) == first


def test_cli_preserves_existing_artifact(tmp_path):
    from scripts.certify_history_task import main

    output = tmp_path / "existing.json"
    output.write_text("immutable evidence\n")
    assert main(["--output", str(output)]) == 2
    assert output.read_text() == "immutable evidence\n"


def test_cli_report_has_recomputable_trace_hash(tmp_path):
    from scripts.certify_history_task import main

    output = tmp_path / "certificate.json"
    assert main(["--output", str(output)]) == 0
    report = json.loads(output.read_text())
    import hashlib

    canonical = json.dumps(report["calls"], sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert hashlib.sha256(canonical.encode()).hexdigest() == report["trace_sha256"]
    for relative, expected in report["source_hashes"].items():
        path = Path(__file__).resolve().parents[2] / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
