"""Development controls exercise actual handlers without generating model labels."""

import importlib
import json
from copy import deepcopy

import pytest

from healthcraft.reconciliation.casebook import load_cases


def run(case, **kwargs):
    return importlib.import_module("healthcraft.reconciliation.case_controls").run_control(
        case, **kwargs
    )


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["case_id"])
def test_designated_control_uses_native_state_and_preserves_inputs(case, tmp_path):
    original = deepcopy(case)
    capture = run(case, journal_path=tmp_path / "journal.jsonl")
    assert case == original
    assert capture["schema_version"] == "healthcraft-reconciliation-control-capture/v2"
    assert capture["control"] == case["designated_control"]
    assert capture["model_calls"] == 0
    evidence = capture["evidence"]
    assert evidence["case_binding"]["case_id"] == case["case_id"]
    from healthcraft.reconciliation.oracle_v2 import verify_case

    report = verify_case(case, evidence)
    control = case["designated_control"]
    assert report["mechanical_passed"] is (control == "valid")
    assert report["benchmark_score"] is None
    if control == "incomplete_capture":
        assert report["status"] == "provenance_error"
        assert evidence["after"] is None
        assert "response" not in evidence["calls"][-1]
        assert verify_case(case, capture["original_evidence"])["mechanical_passed"] is True
        assert capture["capture_transformation"]["kind"] == "deliberate_capture_omission"
        assert capture["original_evidence"]["calls"][-1]["response"]["status"] == "ok"
        return
    assert report["checks"]["provenance"] is True
    notes = list(evidence["after"]["entities"]["clinical_note"].values())
    writes = [c for c in evidence["calls"] if c["name"] == "updateEncounter"]
    assert writes and all(c["response"]["status"] == "ok" for c in writes)
    assert len(notes) == (
        0 if control == "ack_without_storage" else 2 if control == "duplicate_notes" else 1
    )
    if control == "wrong_target":
        assert notes[0]["patient_id"] != case["scenario"]["target"]["patient_id"]
        assert notes[0]["encounter_id"] != case["scenario"]["target"]["encounter_id"]
        assert (
            evidence["calls"][-1]["response"]["data"]["clinical_notes"][-1][1]
            == notes[0]["content"]
        )
        assert report["checks"]["persisted_action"] is False
    elif control == "wrong_exclusion":
        note = json.loads(notes[0]["content"])
        assert note["scope_exclusions"][0]["reason"] == "other_patient"
        assert note["scope_exclusions"][0]["patient_id"] == note["patient_id"]
        assert report["checks"]["source_fidelity"] is False
    elif control == "incorrect_content_readback":
        note = json.loads(notes[0]["content"])
        assert note["observations"][0]["source"]["status"] == "administered"
        assert len(note["unresolved_conflicts"][0]["source_ids"]) == 1
        assert (
            evidence["calls"][-1]["response"]["data"]["clinical_notes"][-1][1]
            == notes[0]["content"]
        )
        assert report["checks"]["source_fidelity"] is False
    elif control == "interrupted_after_write":
        assert evidence["completion"]["status"] == "interrupted"
        assert len(writes) == 1
        assert evidence["calls"][-1]["name"] == "updateEncounter"
        assert report["checks"]["persisted_action"] is True
        assert report["checks"]["readback"] is False
        assert report["checks"]["execution_complete"] is False
    elif control in {"ack_without_storage", "duplicate_notes"}:
        assert report["checks"]["persisted_action"] is False
        assert report["checks"]["source_fidelity"] is True
    assert capture["original_evidence"] is None
    assert capture["capture_transformation"] is None
    # Every actual outcome has a native middleware audit link.
    assert all(call["audit_end"] == call["audit_start"] + 1 for call in evidence["calls"])
    events = [json.loads(line) for line in (tmp_path / "journal.jsonl").read_text().splitlines()]
    assert sum(e["event"] == "returned" for e in events) == len(evidence["calls"])


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["case_id"])
def test_reference_control_passes_every_authored_case(case):
    from healthcraft.reconciliation.oracle_v2 import verify_case

    capture = run(case, control="valid")
    report = verify_case(case, capture["evidence"])
    assert report["mechanical_passed"] is True
    assert report["coverage"]["expected_sources"] == len(case["expectations"]["sources"])
    assert report["coverage"]["target_observations"] == len(
        case["expectations"]["observation_source_ids"]
    )


def test_unknown_control_fails_before_creating_journal(tmp_path):
    path = tmp_path / "journal.jsonl"
    with pytest.raises(ValueError, match="Unknown"):
        run(load_cases()[0], control="invented", journal_path=path)
    assert not path.exists()


def test_failed_original_is_retained_when_capture_omission_cannot_be_applied(monkeypatch, tmp_path):
    module = importlib.import_module("healthcraft.reconciliation.case_controls")
    native_run = module.run_case
    from healthcraft.mcp.server import create_server

    observed = []

    def failed_readback_server(world):
        server = create_server(world)

        class FailingReadback:
            def call_tool(self, name, params):
                if name == "getEncounterDetails" and world.list_entities("clinical_note"):
                    raise RuntimeError("Deliberate readback transport failure after stored write")
                return server.call_tool(name, params)

        return FailingReadback()

    def capture_actual_failure(case, **kwargs):
        kwargs["server_factory"] = failed_readback_server
        evidence = native_run(case, **kwargs)
        observed.append(deepcopy(evidence))
        return evidence

    monkeypatch.setattr(module, "run_case", capture_actual_failure)
    capture = run(load_cases()[-1], journal_path=tmp_path / "journal.jsonl")
    assert capture["evidence"] == observed[0]
    assert capture["evidence"]["completion"]["error"]["type"] == "RuntimeError"
    assert len(capture["evidence"]["after"]["entities"]["clinical_note"]) == 1
    assert capture["evidence"]["calls"][-1]["error"]["type"] == "RuntimeError"
    assert capture["original_evidence"] is None
    assert capture["capture_transformation"] == {
        "kind": "not_applied",
        "reason": "original_capture_not_complete",
    }
