"""Execution evidence must survive failed actions and interrupted workflows."""

import hashlib
import json
from copy import deepcopy

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.world.state import WorldState


def recorder_class():
    from healthcraft.reconciliation.execution import ReconciliationRecorder

    return ReconciliationRecorder


def test_scenario_digest_uses_literal_utf8_canonical_json():
    from healthcraft.reconciliation.execution import scenario_digest

    scenario = {"text": "synthétique", "number": 1}
    expected = hashlib.sha256('{"number":1,"text":"synthétique"}'.encode()).hexdigest()
    assert scenario_digest(scenario) == expected


def test_record_actual_error_response_without_losing_unknown_tool_attempt():
    world = WorldState()
    recorder = recorder_class()(create_server(world), world)
    response = recorder.call("doesNotExist", {"nested": {"value": 3}})
    assert response["code"] == "unknown_tool"
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["name"] == "doesNotExist"
    assert call["response"] == response
    # A missing simulator audit entry is retained, not manufactured or hidden.
    assert call["audit_start"] == call["audit_end"] == 0


def test_attempt_is_journaled_before_dispatch_and_exception_retained(tmp_path):
    journal = tmp_path / "journal.jsonl"
    world = WorldState()

    class InterruptedServer:
        def call_tool(self, name, params):
            event = json.loads(journal.read_text())
            assert event["event"] == "requested"
            assert event["call"]["params"] == params
            raise RuntimeError("dispatch interrupted")

    recorder = recorder_class()(InterruptedServer(), world, journal_path=journal)
    with pytest.raises(RuntimeError, match="dispatch interrupted"):
        recorder.call("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["error"]["stage"] == "dispatch"
    assert recorder.calls[0]["error"]["outcome"] == "unknown"
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [event["event"] for event in events] == ["requested", "failed"]
    recorder.close()


def test_recorder_snapshots_requests_responses_and_property():
    world = WorldState()

    class MutableServer:
        def call_tool(self, name, params):
            params["nested"]["value"] = 8
            return {"status": "ok", "data": params}

    original = {"nested": {"value": 1}}
    recorder = recorder_class()(MutableServer(), world)
    response = recorder.call("example", original)
    original["nested"]["value"] = 2
    response["data"]["nested"]["value"] = 9
    calls = recorder.calls
    calls[0]["params"]["nested"]["value"] = 3
    assert recorder.calls[0]["params"]["nested"]["value"] == 1
    assert recorder.calls[0]["response"]["data"]["nested"]["value"] == 8


def test_nonfinite_response_does_not_erase_executed_attempt():
    world = WorldState()

    class BadServer:
        def call_tool(self, name, params):
            return {"status": "ok", "data": float("nan")}

    recorder = recorder_class()(BadServer(), world)
    with pytest.raises(ValueError):
        recorder.call("example", {})
    assert recorder.calls[0]["error"]["stage"] == "response_serialization"
    assert recorder.calls[0]["error"]["outcome"] == "unknown"
    assert "response" not in recorder.calls[0]


def test_existing_journal_is_never_overwritten(tmp_path):
    journal = tmp_path / "journal.jsonl"
    journal.write_text("prior evidence\n")
    world = WorldState()
    with pytest.raises(FileExistsError):
        recorder_class()(create_server(world), world, journal_path=journal)
    assert journal.read_text() == "prior evidence\n"


def test_reference_retrieves_and_persists_one_complete_note():
    from healthcraft.reconciliation.execution import run_reconciliation_trial
    from healthcraft.reconciliation.fixture import load_scenario

    evidence = run_reconciliation_trial()
    assert evidence["completion"] == {"status": "completed"}
    assert len(evidence["before"]["entities"]["clinical_note"]) == 0
    notes = list(evidence["after"]["entities"]["clinical_note"].values())
    assert len(notes) == 1
    note = json.loads(notes[0]["content"])
    assert note["patient_id"] == load_scenario()["target"]["patient_id"]
    assert {row["source_id"] for row in note["observations"]} == {
        "SRC-A01",
        "SRC-A02",
        "SRC-A03",
        "SRC-A04",
        "SRC-A05",
        "SRC-A06",
    }
    assert note["unresolved_conflicts"] == [
        {"source_ids": ["SRC-A04", "SRC-A05"], "event_id": "EVENT-A01", "field": "reported_status"}
    ]
    assert {row["source_id"] for row in note["scope_exclusions"]} == {"SRC-A07", "SRC-B01"}
    last = evidence["calls"][-1]
    assert last["name"] == "getEncounterDetails"
    assert last["response"]["data"]["clinical_notes"][-1][1] == notes[0]["content"]
    writes = [c for c in evidence["calls"] if c["name"] == "updateEncounter"]
    assert len(writes) == 2
    assert writes[1]["response"]["deduplicated"] is True


def test_reference_derives_source_values_from_received_tools_not_hidden_gold():
    from healthcraft.reconciliation.execution import run_reconciliation_trial
    from healthcraft.reconciliation.fixture import load_scenario

    scenario = load_scenario()
    scenario["encounters"][0]["patient_data"]["active_orders"][0]["item"] = "new_synthetic_token"
    evidence = run_reconciliation_trial(scenario=scenario)
    note = json.loads(
        next(iter(evidence["after"]["entities"]["clinical_note"].values()))["content"]
    )
    row = next(row for row in note["observations"] if row["source_id"] == "SRC-A01")
    assert row["source"]["item"] == "new_synthetic_token"


def test_interruption_after_note_write_retains_store_calls_and_audit():
    from healthcraft.reconciliation.execution import execute_reference, run_reconciliation_trial

    def interrupted(recorder, *, target):
        execute_reference(recorder, target=target)
        raise KeyboardInterrupt("stopped after write")

    evidence = run_reconciliation_trial(controller=interrupted)
    assert evidence["completion"]["status"] == "interrupted"
    assert len(evidence["after"]["entities"]["clinical_note"]) == 1
    assert len(evidence["calls"]) == len(evidence["audit"]) > 0


def test_failed_controller_is_not_recorded_as_completed():
    from healthcraft.reconciliation.execution import run_reconciliation_trial

    def broken(recorder, *, target):
        recorder.call("getEncounterDetails", {"encounter_id": "ENC-DEADBEEF"})
        raise ValueError("read failed")

    evidence = run_reconciliation_trial(controller=broken)
    assert evidence["completion"]["status"] == "failed"
    assert evidence["calls"][0]["response"]["status"] == "error"
    assert len(evidence["calls"]) == len(evidence["audit"]) == 1


def test_reference_refuses_saturated_search_instead_of_claiming_complete_retrieval():
    from healthcraft.reconciliation.execution import execute_reference

    class Saturated:
        def call(self, name, params):
            if name == "getPatientHistory":
                return {
                    "status": "ok",
                    "data": {"id": "PAT-AAAAAAAA", "first_name": "Rowan", "last_name": "Example"},
                }
            return {"status": "ok", "data": [{"id": f"PAT-{i:08}"} for i in range(10)]}

    with pytest.raises(ValueError, match="saturat"):
        execute_reference(
            Saturated(), target={"patient_id": "PAT-AAAAAAAA", "encounter_id": "ENC-AAAAAAAA"}
        )


def test_invalid_request_is_not_dispatched_but_attempt_remains_visible():
    world = WorldState()
    recorder = recorder_class()(create_server(world), world)
    with pytest.raises(ValueError):
        recorder.call("getEncounterDetails", {"encounter_id": float("nan")})
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["error"]["stage"] == "request_serialization"
    assert recorder.calls[0]["error"]["outcome"] == "not_dispatched"
    assert not world.audit_log


def test_reference_order_of_inputs_is_not_an_expected_answer_dependency():
    from healthcraft.reconciliation.execution import run_reconciliation_trial
    from healthcraft.reconciliation.fixture import load_scenario

    original = load_scenario()
    scenario = deepcopy(original)
    scenario["patients"].reverse()
    scenario["encounters"].reverse()
    evidence = run_reconciliation_trial(scenario=scenario)
    assert evidence["completion"]["status"] == "completed"
    note = json.loads(
        next(iter(evidence["after"]["entities"]["clinical_note"].values()))["content"]
    )
    assert note["patient_id"] == original["target"]["patient_id"]
    assert len(note["observations"]) == 6
