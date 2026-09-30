"""A varied case runs once with exact binding and faithful partial evidence."""

import json
from copy import deepcopy

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.reconciliation.execution import scenario_digest
from tests.test_reconciliation.test_fixture_v2 import scenario


def case(**counts):
    source = scenario(**counts)
    expectations = {"private_test_marker": "Never pass an answer document to the controller"}
    return {
        "schema_version": "healthcraft-reconciliation-case/v2",
        "case_id": "REC2-001",
        "scenario_family_id": "same-name-original-family",
        "exposure": "development",
        "label_status": "engineering_authored_independent_review_pending",
        "casebook_sha256": "b" * 64,
        "scenario_sha256": scenario_digest(source),
        "expectations_sha256": scenario_digest(expectations),
        "scenario": source,
        "expectations": expectations,
        "designated_control": "reference",
    }


def api():
    from healthcraft.reconciliation import execution_v2

    return execution_v2


@pytest.mark.parametrize("counts", [(1, 1, 1), (2, 3, 5), (3, 5, 11), (8, 16, 128)])
def test_reference_reads_every_source_persists_one_note_retries_and_reads_back(counts, tmp_path):
    source = case(patient_count=counts[0], encounter_count=counts[1], source_count=counts[2])
    original = deepcopy(source)
    evidence = api().run_case(source, journal_path=tmp_path / "execution.jsonl")
    assert evidence["schema_version"] == "healthcraft-reconciliation-execution/v2"
    assert evidence["completion"] == {"status": "completed"}
    assert evidence["execution_kind"] == "in_process_mcp_handlers"
    binding_keys = {
        "case_id",
        "casebook_sha256",
        "scenario_sha256",
        "expectations_sha256",
        "scenario_family_id",
    }
    assert evidence["case_binding"] == {k: source[k] for k in binding_keys}
    assert evidence["scenario_sha256"] == source["scenario_sha256"]
    assert not evidence["before"]["entities"]["clinical_note"]
    notes = list(evidence["after"]["entities"]["clinical_note"].values())
    assert len(notes) == 1
    note = json.loads(notes[0]["content"])
    assert len(note["observations"]) + len(note["scope_exclusions"]) == counts[2]
    assert all(
        row["encounter_id"] == source["scenario"]["target"]["encounter_id"]
        for row in note["observations"]
    )
    calls = evidence["calls"]
    assert len(calls) == len(evidence["audit"]) == 2 + counts[0] + counts[1] + 3
    assert calls[-1]["name"] == "getEncounterDetails"
    assert calls[-1]["response"]["data"]["clinical_notes"][-1][1] == notes[0]["content"]
    writes = [c for c in calls if c["name"] == "updateEncounter"]
    assert len(writes) == 2 and writes[-1]["response"]["deduplicated"] is True
    events = [json.loads(line) for line in (tmp_path / "execution.jsonl").read_text().splitlines()]
    assert len(events) == len(calls) * 2
    assert [e["event"] for e in events] == [
        item for _ in calls for item in ("requested", "returned")
    ]
    assert source == original
    assert evidence == api().run_case(source)


def test_controller_receives_only_target_and_returned_public_sources():
    source = case()
    seen = []

    def public_controller(recorder, **kwargs):
        assert kwargs == {"target": source["scenario"]["target"]}
        kwargs["target"]["patient_id"] = "PAT-FFFFFFFF"
        seen.append(kwargs)
        recorder.call(
            "getPatientHistory", {"patient_id": source["scenario"]["target"]["patient_id"]}
        )

    evidence = api().run_case(source, controller=public_controller)
    assert seen and evidence["completion"]["status"] == "completed"
    assert source["scenario"]["target"]["patient_id"] == "PAT-00000001"
    assert "private_test_marker" not in json.dumps(evidence)


def test_literal_changed_source_is_used_without_an_expected_answer():
    source = case()
    source["scenario"]["encounters"][0]["patient_data"]["active_orders"][0]["item"] = (
        "New literal token"
    )
    source["scenario_sha256"] = scenario_digest(source["scenario"])
    evidence = api().run_case(source)
    note = json.loads(
        next(iter(evidence["after"]["entities"]["clinical_note"].values()))["content"]
    )
    assert note["observations"][0]["source"]["item"] == "New literal token"


@pytest.mark.parametrize(
    "exception", [ValueError("controller failed"), KeyboardInterrupt("interrupted")]
)
def test_interruption_after_actual_write_preserves_partial_calls_audit_and_store(exception):
    def controller(recorder, *, target):
        recorder.call(
            "updateEncounter",
            {"encounter_id": target["encounter_id"], "notes": "Actual partial note"},
        )
        raise exception

    evidence = api().run_case(case(), controller=controller)
    assert evidence["completion"] == {
        "status": "interrupted" if isinstance(exception, KeyboardInterrupt) else "failed",
        "error": {"type": type(exception).__name__, "message": str(exception)},
    }
    assert len(evidence["after"]["entities"]["clinical_note"]) == 1
    assert len(evidence["calls"]) == len(evidence["audit"]) == 1
    assert evidence["calls"][0]["response"]["status"] == "ok"


def test_server_construction_error_retains_before_after_and_original_error():
    def unavailable(world):
        raise RuntimeError("test server setup failed")

    evidence = api().run_case(case(), server_factory=unavailable)
    assert evidence["completion"] == {
        "status": "failed",
        "error": {"type": "RuntimeError", "message": "test server setup failed"},
    }
    assert evidence["before"] == evidence["after"]
    assert evidence["calls"] == evidence["audit"] == []


def test_real_failed_tool_response_remains_evidence_without_becoming_success():
    def controller(recorder, *, target):
        response = recorder.call("getEncounterDetails", {"encounter_id": "ENC-FFFFFFFF"})
        assert response["status"] == "error"
        raise ValueError("retrieval failed")

    evidence = api().run_case(case(), controller=controller)
    assert evidence["completion"]["status"] == "failed"
    assert evidence["calls"][0]["response"]["code"] == "not_found"
    assert evidence["audit"][0]["result_summary"] == "error"


def test_setup_or_dispatch_can_never_trigger_automatic_retry(tmp_path):
    made = []

    class Interrupted:
        def call_tool(self, name, params):
            made.append((name, params))
            assert json.loads((tmp_path / "journal").read_text())["event"] == "requested"
            raise RuntimeError("uncertain outcome")

    evidence = api().run_case(
        case(), server_factory=lambda world: Interrupted(), journal_path=tmp_path / "journal"
    )
    assert len(made) == 1 and len(evidence["calls"]) == 1
    assert evidence["completion"]["status"] == "failed"
    assert evidence["calls"][0]["error"]["outcome"] == "unknown"
    assert evidence["audit"] == []


def test_existing_journal_is_preserved_and_does_not_dispatch(tmp_path):
    path = tmp_path / "journal"
    path.write_text("existing evidence\n")
    evidence = api().run_case(case(), journal_path=path)
    assert path.read_text() == "existing evidence\n"
    assert evidence["completion"]["error"]["type"] == "FileExistsError"
    assert evidence["calls"] == []


@pytest.mark.parametrize(
    "change",
    [
        "wrong_schema",
        "missing_hash",
        "scenario_changed",
        "expectations_changed",
        "uppercase_book_hash",
        "wrong_case_id",
        "empty_family",
        "wrong_exposure",
        "wrong_label",
        "unknown_field",
        "nonfinite_expectation",
        "nonobject_expectation",
    ],
)
def test_invalid_case_binding_rejected_before_world_or_journal(change, tmp_path, monkeypatch):
    source = case()
    if change == "wrong_schema":
        source["schema_version"] = "healthcraft-reconciliation-case/v1"
    elif change == "missing_hash":
        del source["casebook_sha256"]
    elif change == "scenario_changed":
        source["scenario"]["clock"] = "2026-09-30T15:00:00Z"
    elif change == "expectations_changed":
        source["expectations"]["new_value"] = True
    elif change == "uppercase_book_hash":
        source["casebook_sha256"] = "B" * 64
    elif change == "wrong_case_id":
        source["case_id"] = "REC2-999"
    elif change == "empty_family":
        source["scenario_family_id"] = ""
    elif change == "wrong_exposure":
        source["exposure"] = "heldout"
    elif change == "wrong_label":
        source["label_status"] = "clinically_validated"
    elif change == "unknown_field":
        source["extra"] = 1
    elif change == "nonfinite_expectation":
        source["expectations"]["value"] = float("nan")
    elif change == "nonobject_expectation":
        source["expectations"] = []
        source["expectations_sha256"] = scenario_digest([])
    module = api()
    made = []
    monkeypatch.setattr(module, "build_world", lambda value: made.append(value))
    with pytest.raises(ValueError):
        module.run_case(source, journal_path=tmp_path / "journal")
    assert made == [] and not (tmp_path / "journal").exists()


def test_explicit_ack_without_storage_is_captured_as_actual_handler_behavior():
    class AckServer:
        def __init__(self, world):
            self.server = create_server(world)
            self.world = world

        def call_tool(self, name, params):
            if name == "updateEncounter":
                self.world.record_audit(name, params, "ok")
                return {"status": "ok", "data": {"encounter_id": params["encounter_id"]}}
            return self.server.call_tool(name, params)

    evidence = api().run_case(case(), server_factory=AckServer)
    assert evidence["completion"]["status"] == "completed"
    assert not evidence["after"]["entities"]["clinical_note"]
    assert evidence["calls"][-1]["response"]["data"]["clinical_notes"] == []
    # Completion is controller termination, never an oracle or storage verdict.
    assert "mechanical_passed" not in evidence


def test_all_case_binding_and_evidence_copies_are_detached():
    source = case()
    evidence = api().run_case(source)
    before = deepcopy(evidence)
    source["case_id"] = "REC2-999"
    source["scenario"]["target"]["patient_id"] = "PAT-FFFFFFFF"
    assert evidence == before
    evidence["after"]["entities"]["patient"]["PAT-00000001"]["first_name"] = "Changed"
    assert evidence["before"]["entities"]["patient"]["PAT-00000001"]["first_name"] == "Casebook"
