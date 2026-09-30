"""Evidence assistance describes captured facts without supplied answer labels."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.reconciliation.case_controls import run_control
from healthcraft.reconciliation.casebook import load_cases
from healthcraft.reconciliation.execution_v2 import run_case


def describe(documents):
    from healthcraft.reconciliation.incident_evidence import describe_incident

    return describe_incident(documents)


def documents(case_id="REC2-001", control=None):
    case = next(row for row in load_cases() if row["case_id"] == case_id)
    evidence = run_case(case) if control is None else run_control(case, control=control)["evidence"]
    return {
        "task": {"instruction": "Inspect the source reconciliation capture."},
        "scenario": case["scenario"],
        "evidence": evidence,
        "runtime": {
            "kind": "scripted_capture",
            "execution_error": evidence["completion"].get("error"),
        },
    }


def claims(report, code):
    return [row for row in report["claims"] if row["code"] == code]


def count(report, code, field):
    return claims(report, code)[0]["observed"][field]


def pointer(value, path):
    if not path:
        return value
    assert path.startswith("/")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if type(value) is list else value[part]
    return value


def resolve_refs(docs, report):
    for claim in report["claims"]:
        assert set(claim) == {"id", "category", "code", "summary", "observed", "refs"}
        assert claim["refs"], claim
        for ref in claim["refs"]:
            assert ref["document"] in docs
            value = pointer(docs[ref["document"]], ref["pointer"])
            if "decoded_json_pointer" in ref:
                value = pointer(json.loads(value), ref["decoded_json_pointer"])
    return True


@pytest.fixture(autouse=True)
def idempotency(monkeypatch):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")


def test_actual_reference_reports_ack_storage_readback_as_distinct_facts():
    docs = documents()
    report = describe(docs)
    assert report["schema_version"] == "healthcraft-incident-evidence/v1"
    assert count(report, "write_acknowledgements", "count") == 2  # one retry
    assert count(report, "write_acknowledgements", "deduplicated_count") == 1
    assert count(report, "new_note_count", "count") == 1
    assert count(report, "stored_text_readback_count", "count") == 1
    assert count(report, "recorded_completion", "status") == "completed"
    assert report["unassessed"]
    assert not {"passed", "score", "answers", "oracle", "checks"} & report.keys()
    assert resolve_refs(docs, report)


def test_real_ack_without_storage_does_not_infer_a_note():
    report = describe(documents("REC2-004", "ack_without_storage"))
    assert count(report, "write_acknowledgements", "count") > 0
    assert count(report, "new_note_count", "count") == 0
    assert count(report, "stored_text_readback_count", "count") == 0


def test_wrong_target_notes_and_readback_remain_visible():
    docs = documents("REC2-003", "wrong_target")
    report = describe(docs)
    assert count(report, "new_note_count", "count") == 1
    assert count(report, "stored_text_readback_count", "count") == 1
    note = claims(report, "new_stored_note")[0]["observed"]
    assert note["on_requested_target"] is False
    assert resolve_refs(docs, report)


def test_real_duplicate_writes_preserve_multiplicity():
    report = describe(documents("REC2-005", "duplicate_notes"))
    assert count(report, "new_note_count", "count") == 2
    assert count(report, "stored_text_readback_count", "count") == 2
    assert len(claims(report, "new_stored_note")) == 2


def test_one_returned_text_cannot_read_back_two_same_text_records():
    docs = documents("REC2-005", "duplicate_notes")
    final = docs["evidence"]["calls"][-1]
    final["response"]["data"]["clinical_notes"] = final["response"]["data"]["clinical_notes"][:1]
    assert count(describe(docs), "stored_text_readback_count", "count") == 1


def test_missing_final_snapshot_is_unknown_not_zero_or_counterfactual():
    docs = documents("REC2-008", "incomplete_capture")
    report = describe(docs)
    assert report["status"] == "partial"
    assert count(report, "new_note_count", "count") is None
    assert count(report, "stored_text_readback_count", "count") is None
    assert not claims(report, "new_stored_note")
    assert resolve_refs(docs, report)


def test_after_write_interruption_keeps_storage_but_no_readback():
    docs = documents("REC2-007", "interrupted_after_write")
    report = describe(docs)
    assert count(report, "recorded_completion", "status") == "interrupted"
    assert count(report, "new_note_count", "count") == 1
    assert count(report, "stored_text_readback_count", "count") == 0


@pytest.mark.parametrize("mode", ["prewrite", "wrong_owner", "failed", "missing_audit"])
def test_readback_requires_later_successful_linked_owned_response(mode):
    docs = documents()
    evidence = docs["evidence"]
    read = evidence["calls"][-1]
    if mode == "prewrite":
        evidence["calls"] = [read] + evidence["calls"][:-1]
    elif mode == "wrong_owner":
        read["response"]["data"]["patient_id"] = "PAT-NOTOWNER"
    elif mode == "failed":
        read["response"] = {"status": "error", "code": "unavailable", "message": "Unavailable"}
        evidence["audit"][-1]["result_summary"] = "error"
        evidence["audit"][-1]["error_code"] = "unavailable"
    else:
        evidence["audit"] = evidence["audit"][:-1]
    assert count(describe(docs), "stored_text_readback_count", "count") in (0, None)


def mutate_note(docs, change=None, raw=None):
    notes = docs["evidence"]["after"]["entities"]["clinical_note"]
    note = next(iter(notes.values()))
    parsed = json.loads(note["content"])
    if change:
        change(parsed)
    note["content"] = raw if raw is not None else json.dumps(parsed)


def test_wrong_path_is_distinct_from_unchanged_raw_source():
    docs = documents()
    mutate_note(docs, lambda n: n["observations"][0].update(source_path="/patient/active_orders"))
    report = describe(docs)
    assert len(claims(report, "observation_path_difference")) == 1
    assert claims(report, "observation_raw_source_unchanged")
    assert not claims(report, "observation_raw_source_difference")
    assert resolve_refs(docs, report)


def test_literal_unknowns_types_and_time_changes_are_reported_without_normalization():
    docs = documents()
    mutate_note(docs, lambda n: n["observations"][0]["source"].update(time=0, status=False))
    report = describe(docs)
    changed = claims(report, "observation_raw_source_difference")[0]["observed"]
    assert changed["authored"]["time"] is None
    assert changed["recorded"]["time"] == 0
    assert changed["recorded"]["status"] is False
    assert resolve_refs(docs, report)


@pytest.mark.parametrize(
    "text", ['{"observations":[],"observations":[]}', '{"x":NaN}', '{"x":1e999}', "not JSON"]
)
def test_malformed_string_notes_stay_unresolved_not_silently_repaired(text):
    docs = documents()
    mutate_note(docs, raw=text)
    report = describe(docs)
    assert claims(report, "note_json_unresolved")
    assert not claims(report, "target_source_not_listed")
    assert all(
        "decoded_json_pointer" not in ref
        for row in claims(report, "note_json_unresolved")
        for ref in row["refs"]
    )
    assert resolve_refs(docs, report)


def test_missing_note_fields_cite_existing_parent_not_nonexistent_pointer():
    docs = documents()
    mutate_note(docs, lambda n: n.pop("observations"))
    report = describe(docs)
    assert claims(report, "note_observations_unavailable")
    assert resolve_refs(docs, report)


def test_source_conflicts_keep_all_literal_reports_without_truth_adjudication():
    docs = documents("REC2-004")
    report = describe(docs)
    group = claims(report, "opposing_source_reports")[0]["observed"]
    assert group["source_ids"] == ["SRC-A02", "SRC-A03", "SRC-A04"]
    assert group["reported_statuses"] == ["administered", "not_administered", "not_administered"]
    assert not claims(report, "opposing_group_not_listed")
    assert resolve_refs(docs, report)


def test_source_conflicts_do_not_merge_different_patients_or_distinct_events():
    for case_id in ("REC2-003", "REC2-005"):
        report = describe(documents(case_id))
        assert not claims(report, "opposing_source_reports")


def test_unavailable_documents_and_internal_missing_capture_are_explicit():
    docs = documents()
    docs["evidence"] = None
    report = describe(docs)
    assert count(report, "new_note_count", "count") is None
    assert count(report, "write_acknowledgements", "count") is None
    assert resolve_refs(docs, report)
    for c in report["claims"]:
        assert all(ref["document"] != "evidence" for ref in c["refs"])


@pytest.mark.parametrize(
    "extra", ["expectations", "verification", "original_evidence", "designated_control"]
)
def test_private_or_unsupported_document_set_is_rejected(extra):
    docs = documents()
    docs[extra] = {}
    with pytest.raises(ValueError, match="documents"):
        describe(docs)


def test_strict_inputs_detachment_stability_and_no_oracle_dependency(monkeypatch):
    import healthcraft.reconciliation.oracle as oracle
    import healthcraft.reconciliation.oracle_v2 as oracle_v2

    def forbidden(*args, **kwargs):
        raise AssertionError("Assistance cannot call a grader")

    monkeypatch.setattr(oracle, "verify_reconciliation", forbidden)
    monkeypatch.setattr(oracle_v2, "verify_case", forbidden)
    docs = documents()
    before = deepcopy(docs)
    first, second = describe(docs), describe(docs)
    assert first == second
    first["claims"][0]["observed"]["changed"] = True
    assert docs == before
    docs["runtime"] = {"bad": float("nan")}
    with pytest.raises(ValueError, match="finite|JSON"):
        describe(docs)


def test_frozen_live_notes_preserve_paths_vs_values_and_malformed_note():
    root = (
        Path(__file__).resolve().parents[2]
        / "artifacts/reconciliation/20260930/local-casebook-pilot-v1/run"
    )
    if not root.is_dir():
        pytest.skip("Immutable local development capture is unavailable")
    parseable, malformed, stored, readback = 0, 0, 0, 0
    for folder in sorted(root.glob("REC2-*/*")):
        if not (folder / "execution.json").is_file():
            continue
        case = json.loads((folder / "case.json").read_text())
        docs = {
            "task": json.loads((folder / "public-context.json").read_text()),
            "scenario": case["scenario"],
            "evidence": json.loads((folder / "execution.json").read_text()),
            "runtime": None,
        }
        report = describe(docs)
        stored += count(report, "new_note_count", "count")
        readback += count(report, "stored_text_readback_count", "count")
        parseable += len(claims(report, "note_json_available"))
        malformed += len(claims(report, "note_json_unresolved"))
        assert not claims(report, "observation_raw_source_difference")
        assert resolve_refs(docs, report)
    assert (parseable, malformed, stored, readback) == (14, 1, 15, 2)


@pytest.mark.parametrize("audit", [None, [{"tool_name": []}]])
def test_missing_or_malformed_audit_cannot_claim_zero_write_acknowledgements(audit):
    docs = documents()
    docs["evidence"]["audit"] = audit
    report = describe(docs)
    assert count(report, "write_acknowledgements", "count") is None
    assert count(report, "new_note_count", "count") == 1
    assert count(report, "stored_text_readback_count", "count") is None
    assert resolve_refs(docs, report)


@pytest.mark.parametrize("field,value", [("patient_id", "PAT-OTHER"), ("encounter_id", None)])
def test_note_header_identity_is_compared_to_public_target_and_stored_identity(field, value):
    docs = documents()
    mutate_note(docs, lambda n: n.update({field: value}))
    report = describe(docs)
    assert claims(report, "note_target_difference")
    assert claims(report, "note_storage_identity_difference")
    assert resolve_refs(docs, report)


def test_all_unavailable_documents_emit_no_unresolvable_claims_or_counts():
    report = describe(dict.fromkeys(("task", "scenario", "evidence", "runtime")))
    assert report["status"] == "unavailable"
    assert report["claims"] == []


def test_failed_audit_code_cannot_back_a_successful_acknowledgement():
    docs = documents()
    first = next(c for c in docs["evidence"]["calls"] if c["name"] == "updateEncounter")
    docs["evidence"]["audit"][first["audit_start"]]["error_code"] = "permission_denied"
    report = describe(docs)
    assert count(report, "write_acknowledgements", "count") is None
    assert claims(report, "call_linkage_unresolved")
    assert count(report, "new_note_count", "count") == 1


@pytest.mark.parametrize(
    "key", ["expectations", "verification", "designated_control", "original_evidence"]
)
def test_structured_private_inputs_are_rejected_even_inside_a_public_slot(key):
    docs = documents()
    docs["runtime"] = {"nested": {key: {"hidden": "not public evidence"}}}
    with pytest.raises(ValueError, match="private"):
        describe(docs)


def test_original_error_text_that_names_a_control_is_preserved_as_source_text():
    docs = documents()
    docs["runtime"] = {"execution_error": {"message": "Development control: interrupted"}}
    report = describe(docs)
    assert (
        claims(report, "recorded_runtime_error")[0]["observed"]["recorded"]
        == docs["runtime"]["execution_error"]
    )
    assert resolve_refs(docs, report)


@pytest.mark.parametrize("missing", ["write_data", "write_notes", "read_patient", "read_encounter"])
def test_missing_readback_linkage_is_unknown_not_an_exhaustive_zero(missing):
    docs = documents()
    for call in docs["evidence"]["calls"]:
        if call["name"] == "updateEncounter":
            if missing == "write_data":
                del call["response"]["data"]
            elif missing == "write_notes":
                del call["response"]["data"]["clinical_notes"]
    if missing.startswith("read_"):
        field = "patient_id" if missing == "read_patient" else "id"
        del docs["evidence"]["calls"][-1]["response"]["data"][field]
    report = describe(docs)
    assert count(report, "new_note_count", "count") == 1
    assert count(report, "stored_text_readback_count", "count") is None
    assert count(report, "stored_text_readback_count", "observed_matching_count") == 0
    assert report["coverage"]["readback"] != "available"
    assert resolve_refs(docs, report)


def test_unresolved_linkage_preserves_an_independently_observed_readback_subset():
    docs = documents()
    case = next(row for row in load_cases() if row["case_id"] == "REC2-001")

    def controller(recorder, *, target):
        for key, content in (("first", "alpha"), ("second", "beta")):
            recorder.call(
                "updateEncounter",
                {"encounter_id": target["encounter_id"], "notes": content, "idempotency_key": key},
            )
        recorder.call("getEncounterDetails", {"encounter_id": target["encounter_id"]})

    docs["evidence"] = run_case(case, controller=controller)
    del docs["evidence"]["calls"][0]["response"]["data"]
    report = describe(docs)
    assert count(report, "stored_text_readback_count", "count") is None
    assert count(report, "stored_text_readback_count", "observed_matching_count") == 1
    assert resolve_refs(docs, report)


@pytest.mark.parametrize("unavailable", [("evidence",), ("scenario", "evidence", "runtime")])
def test_unavailable_claim_references_are_usable_by_the_public_importer(unavailable):
    from healthcraft.operator_incidents import validate_incident_references

    docs = documents()
    for name in unavailable:
        docs[name] = None
    report = describe(docs)
    for claim in report["claims"]:
        validate_incident_references(claim["refs"], docs)
