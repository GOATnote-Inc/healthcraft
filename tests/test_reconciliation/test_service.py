"""Behavioral contract for the private-host reconciliation tool session.

These tests use no sockets/models and obtain success from the independent
source/persistence oracle after the actual reference controller and handlers.
"""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.mcp.server import HealthcraftServer
from healthcraft.reconciliation.execution import execute_reference
from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "test-private-session-secret"
AUTH = f"Bearer {TOKEN}"
TOOLS = {
    "searchPatients",
    "searchEncounters",
    "getPatientHistory",
    "getEncounterDetails",
    "updateEncounter",
}
TARGET = {"patient_id": "PAT-AAAAAAAA", "encounter_id": "ENC-AAAAAAAA"}


def session_class():
    from healthcraft.reconciliation.service import ReconciliationSession

    return ReconciliationSession


def request(name, params):
    return json.dumps({"name": name, "params": params}, allow_nan=False).encode()


class SessionRecorder:
    """Controller adapter contains only the exposed authenticated call route."""

    def __init__(self, session):
        self.session = session

    def call(self, name, params):
        status, response = self.session.handle("POST", "/call", request(name, params), AUTH)
        assert status == 200
        return response


def finish(session, status="completed", error=None):
    return session.finalize(status, error=error)


@pytest.fixture(autouse=True)
def idempotency(monkeypatch):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")


def test_public_tool_discovery_is_exact_five_native_schemas_and_detached():
    session = session_class()(token=TOKEN)
    status, response = session.handle("GET", "/tools", authorization=AUTH)
    expected = [
        tool
        for tool in json.loads((ROOT / "configs/mcp-tools.json").read_text())["tools"]
        if tool["name"] in TOOLS
    ]
    assert status == 200
    assert set(response) == {"tools"}
    assert {tool["name"] for tool in response["tools"]} == TOOLS
    assert sorted(response["tools"], key=lambda tool: tool["name"]) == sorted(
        expected, key=lambda tool: tool["name"]
    )
    response["tools"][0]["name"] = "client mutation"
    status, fresh = session.handle("GET", "/tools", authorization=AUTH)
    assert status == 200
    assert {tool["name"] for tool in fresh["tools"]} == TOOLS
    evidence = finish(session)
    assert evidence["calls"] == evidence["audit"] == []


def test_authenticated_health_does_not_expose_world_or_dispatch():
    session = session_class()(token=TOKEN)
    status, response = session.handle("GET", "/health", authorization=AUTH)
    assert (status, response) == (200, {"status": "ok"})
    evidence = finish(session)
    assert evidence["calls"] == evidence["audit"] == []
    assert evidence["before"] == evidence["after"]


def test_reference_through_private_session_passes_independent_oracle_once_with_retry():
    scenario = load_scenario()
    session = session_class()(scenario=scenario, token=TOKEN)
    execute_reference(SessionRecorder(session), target=deepcopy(scenario["target"]))
    evidence = finish(session)
    assert evidence["schema_version"] == "healthcraft-reconciliation-execution/v1"
    assert evidence["completion"]["status"] == "completed"
    result = verify_reconciliation(scenario, load_expectations(), evidence)
    assert result["mechanical_passed"] is True
    assert all(result["checks"].values())
    assert len(evidence["after"]["entities"]["clinical_note"]) == 1
    writes = [call for call in evidence["calls"] if call["name"] == "updateEncounter"]
    assert len(writes) == 2
    assert writes[1]["response"]["deduplicated"] is True
    assert len(evidence["calls"]) == len(evidence["audit"]) == 10
    assert len(evidence["transport_events"]) == 10
    assert TOKEN not in json.dumps(evidence)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/health", b""),
        ("GET", "/tools", b""),
        ("POST", "/call", request("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})),
    ],
)
@pytest.mark.parametrize("authorization", ["", "Bearer wrong-session", "Basic not-bearer"])
def test_every_route_requires_bearer_authentication_without_dispatch(
    method, path, body, authorization
):
    session = session_class()(token=TOKEN)
    status, response = session.handle(method, path, body, authorization)
    assert status == 401
    assert response.get("status") == "error"
    assert "data" not in response and "tools" not in response
    evidence = finish(session)
    assert evidence["calls"] == evidence["audit"] == []
    assert evidence["before"] == evidence["after"]
    assert evidence["completion"]["status"] == "failed"
    assert evidence["completion"].get("error")
    assert len(evidence["transport_events"]) == 1
    assert TOKEN not in json.dumps(evidence)
    if authorization:
        assert authorization not in json.dumps(evidence)


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/evidence"),
        ("GET", "/snapshot"),
        ("GET", "/world"),
        ("GET", "/finalize"),
        ("POST", "/finalize"),
        ("POST", "/tools"),
        ("GET", "/call"),
        ("PUT", "/call"),
        ("GET", "/unknown"),
    ],
)
def test_nonpublic_routes_never_return_coordinator_data(method, path):
    session = session_class()(token=TOKEN)
    status, response = session.handle(method, path, authorization=AUTH)
    assert status == 404
    assert response.get("status") == "error"
    assert "entities" not in json.dumps(response)
    assert "source_id" not in json.dumps(response)
    evidence = finish(session)
    assert evidence["calls"] == evidence["audit"] == []
    assert evidence["completion"]["status"] == "failed"


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b"[]",
        b"null",
        b"{}",
        b'{"name":"getPatientHistory","params":{},"extra":true}',
        b'{"name":null,"params":{}}',
        b'{"name":1,"params":{}}',
        b'{"name":"getPatientHistory","params":[]}',
        b'{"name":"getPatientHistory","params":null}',
        b'{"name":"getPatientHistory","params":{},"name":"updateEncounter"}',
        b'{"name":"getPatientHistory","params":{"patient_id":"one","patient_id":"two"}}',
        b'{"name":"getPatientHistory","params":{"value":NaN}}',
        b'{"name":"getPatientHistory","params":{"value":Infinity}}',
        b'{"name":"getPatientHistory","params":{"value":-Infinity}}',
        b'{"name":"getPatientHistory","params":{"value":1e400}}',
        b"\xff\xfe",
    ],
)
def test_invalid_transport_body_fails_before_dispatch_and_retains_raw_bytes(body):
    session = session_class()(token=TOKEN)
    status, response = session.handle("POST", "/call", body, AUTH)
    assert status == 400
    assert response.get("status") == "error"
    evidence = finish(session)
    assert evidence["calls"] == evidence["audit"] == []
    assert evidence["before"] == evidence["after"]
    assert evidence["completion"]["status"] == "failed"
    assert evidence["completion"].get("error")
    (event,) = evidence["transport_events"]
    assert event["method"] == "POST" and event["path"] == "/call"
    assert event["status"] == 400
    assert base64.b64decode(event["raw_body_b64"], validate=True) == body
    assert event["body_length"] == len(body)
    assert event["body_truncated"] is False
    assert TOKEN not in json.dumps(evidence)


def test_large_failed_request_is_retained_as_bounded_prefix_not_full_payload():
    body = b"bad JSON " + b"x" * 100_000
    session = session_class()(token=TOKEN)
    status, _ = session.handle("POST", "/call", body, AUTH)
    assert status == 400
    (event,) = finish(session)["transport_events"]
    prefix = base64.b64decode(event["raw_body_b64"], validate=True)
    assert 0 < len(prefix) <= 4096
    assert prefix == body[: len(prefix)]
    assert event["body_length"] == len(body)
    assert event["body_truncated"] is True


@pytest.mark.parametrize("name", ["createClinicalOrder", "processTransfer", "notRegistered"])
def test_unadvertised_or_unknown_tool_uses_real_error_audit_without_mutation(name):
    session = session_class()(token=TOKEN)
    params = {
        "encounter_id": "ENC-AAAAAAAA",
        "order_type": "lab",
        "details": {"name": "synthetic test"},
    }
    status, response = session.handle("POST", "/call", request(name, params), AUTH)
    assert status == 200
    assert response["status"] == "error" and response["code"] == "unknown_tool"
    evidence = finish(session)
    assert evidence["before"] == evidence["after"]
    (call,) = evidence["calls"]
    (audit,) = evidence["audit"]
    assert call["name"] == audit["tool_name"] == name
    assert call["params"] == audit["params"] == params
    assert call["response"] == response
    assert (call["audit_start"], call["audit_end"]) == (0, 1)
    assert audit["result_summary"] == "error" and audit["error_code"] == "unknown_tool"
    assert (
        verify_reconciliation(load_scenario(), load_expectations(), evidence)["mechanical_passed"]
        is False
    )


def test_detached_response_and_input_scenario_cannot_mutate_session_state():
    scenario = load_scenario()
    session = session_class()(scenario=scenario, token=TOKEN)
    scenario["encounters"][0]["patient_data"]["active_orders"][0]["status"] = "administered"
    recorder = SessionRecorder(session)
    response = recorder.call("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})
    response["data"]["authored_care"][0]["source_data"][0]["status"] = "changed by caller"
    fresh = recorder.call("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})
    assert fresh["data"]["authored_care"][0]["source_data"][0]["status"] == "planned"
    evidence = finish(session)
    assert evidence["before"] == evidence["after"]
    assert (
        evidence["calls"][0]["response"]["data"]["authored_care"][0]["source_data"][0]["status"]
        == "planned"
    )


@pytest.mark.parametrize("status", ["completed", "interrupted", "failed"])
def test_finalize_closes_attempt_window_and_repeated_finalization_is_rejected(status, monkeypatch):
    session = session_class()(token=TOKEN)
    error = (
        {"type": "SyntheticInterruption", "message": "stopped"} if status != "completed" else None
    )
    evidence = finish(session, status, error)
    frozen = deepcopy(evidence)
    if error:
        error["message"] = "caller mutation"
    dispatched = []

    def forbidden_dispatch(*args):
        dispatched.append(True)
        pytest.fail("Finalized sessions must not dispatch another tool")

    monkeypatch.setattr(HealthcraftServer, "call_tool", forbidden_dispatch)
    response_status, response = session.handle(
        "POST",
        "/call",
        request("updateEncounter", {"encounter_id": "ENC-AAAAAAAA", "notes": "must not run"}),
        AUTH,
    )
    assert response_status == 409
    assert response.get("status") == "error"
    assert dispatched == []
    assert evidence == frozen
    with pytest.raises(ValueError):
        finish(session, status)
    session.close()
    assert evidence == frozen


@pytest.mark.parametrize("status", ["done", "", None, True])
def test_invalid_finalize_status_does_not_close_live_session(status):
    session = session_class()(token=TOKEN)
    with pytest.raises(ValueError):
        finish(session, status)
    assert session.handle("GET", "/health", authorization=AUTH)[0] == 200
    assert finish(session)["completion"]["status"] == "completed"


@pytest.mark.parametrize("existing", ["empty", "files"])
def test_existing_journal_directory_is_never_reused_or_overwritten(tmp_path, existing):
    directory = tmp_path / "journal"
    directory.mkdir()
    if existing == "files":
        (directory / "calls.jsonl").write_text("prior call evidence\n")
        (directory / "transport.jsonl").write_text("prior transport evidence\n")
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    with pytest.raises(FileExistsError):
        session_class()(token=TOKEN, journal_dir=directory)
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before


def test_journals_flush_request_before_real_dispatch_and_outcome_after(tmp_path, monkeypatch):
    directory = tmp_path / "new-journal"
    original = HealthcraftServer.call_tool
    observed = []

    def inspect(server, name, params):
        call_rows = [
            json.loads(line) for line in (directory / "calls.jsonl").read_text().splitlines()
        ]
        transport_rows = [
            json.loads(line) for line in (directory / "transport.jsonl").read_text().splitlines()
        ]
        assert call_rows and transport_rows
        assert call_rows[-1]["event"] == "requested"
        assert call_rows[-1]["call"]["name"] == name
        assert call_rows[-1]["call"]["params"] == params
        assert TOKEN not in json.dumps(transport_rows)
        observed.append(True)
        return original(server, name, params)

    monkeypatch.setattr(HealthcraftServer, "call_tool", inspect)
    session = session_class()(token=TOKEN, journal_dir=directory)
    body = request("getPatientHistory", {"patient_id": "PAT-AAAAAAAA"})
    assert session.handle("POST", "/call", body, AUTH)[0] == 200
    call_rows = [json.loads(line) for line in (directory / "calls.jsonl").read_text().splitlines()]
    assert [row["event"] for row in call_rows] == ["requested", "returned"]
    assert call_rows[-1]["call"]["response"]["status"] == "ok"
    transport_rows = [
        json.loads(line) for line in (directory / "transport.jsonl").read_text().splitlines()
    ]
    assert len(transport_rows) >= 2
    evidence = finish(session)
    assert observed == [True]
    assert len(evidence["calls"]) == len(evidence["audit"]) == 1
    assert TOKEN not in (directory / "transport.jsonl").read_text()
    assert TOKEN not in (directory / "calls.jsonl").read_text()
    session.close()


def test_failed_transport_is_journaled_without_a_fabricated_world_call(tmp_path):
    directory = tmp_path / "new-journal"
    session = session_class()(token=TOKEN, journal_dir=directory)
    status, _ = session.handle("POST", "/call", b"bad json", AUTH)
    assert status == 400
    assert (directory / "calls.jsonl").read_text() == ""
    assert (directory / "transport.jsonl").read_text()
    evidence = finish(session)
    assert evidence["calls"] == evidence["audit"] == []
    assert evidence["completion"]["status"] == "failed"
    session.close()


def test_failed_transport_after_valid_write_preserves_action_but_prevents_completion():
    scenario = load_scenario()
    session = session_class()(token=TOKEN)
    execute_reference(SessionRecorder(session), target=deepcopy(scenario["target"]))
    assert session.handle("POST", "/call", b"malformed trailing request", AUTH)[0] == 400
    evidence = finish(session)
    assert evidence["completion"]["status"] == "failed"
    assert len(evidence["calls"]) == len(evidence["audit"]) == 10
    assert len(evidence["transport_events"]) == 11
    result = verify_reconciliation(scenario, load_expectations(), evidence)
    assert result["checks"]["provenance"] is True
    assert result["checks"]["source_fidelity"] is True
    assert result["checks"]["persisted_action"] is True
    assert result["checks"]["readback"] is True
    assert result["checks"]["execution_complete"] is False
    assert result["mechanical_passed"] is False
