"""Source-linked explanations must distinguish real events from verified intent."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.mcp.tools.read_tools import get_encounter_details
from healthcraft.reconciliation.execution import run_reconciliation_trial
from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def note_document():
    expected = load_expectations()
    return {
        "schema_version": "healthcraft-reconciliation-note/v1",
        "patient_id": "PAT-AAAAAAAA",
        "encounter_id": "ENC-AAAAAAAA",
        "observations": deepcopy(expected["sources"][:6]),
        "unresolved_conflicts": deepcopy(expected["unresolved_conflicts"]),
        "scope_exclusions": deepcopy(expected["scope_exclusions"]),
    }


def case(*, mutate=None, raw=None, readback="target", ack=False, retry=False, alias=False):
    scenario, expected = load_scenario(), load_expectations()
    note = note_document()
    if mutate:
        mutate(note)
    content = raw if raw is not None else canonical(note)

    def controller(recorder, *, target):
        for encounter in ("ENC-AAAAAAAA", "ENC-BBBBBBBB", "ENC-CCCCCCCC"):
            recorder.call("getEncounterDetails", {"encounter_id": encounter})
        params = {
            "encounter_id": target["encounter_id"],
            "notes": content,
            "idempotency_key": "note",
        }
        name = "update_encounter" if alias else "updateEncounter"
        recorder.call(name, params)
        if retry:
            recorder.call(name, params)
        if readback in ("target", "wrong"):
            recorder.call(
                "getEncounterDetails",
                {
                    "encounter_id": target["encounter_id"]
                    if readback == "target"
                    else "ENC-BBBBBBBB"
                },
            )
        elif readback == "failed":
            recorder.call("getEncounterDetails", {"encounter_id": target["encounter_id"]})

    def server_factory(world):
        server = create_server(world)
        if ack:
            server._handlers["update_encounter"] = get_encounter_details
        if readback == "failed":
            original = server._handlers["get_encounter_details"]
            count = 0

            def later_failure(world, params):
                nonlocal count
                count += 1
                if count > 3:
                    return {
                        "status": "error",
                        "code": "unavailable",
                        "message": "Test readback unavailable",
                    }
                return original(world, params)

            server._handlers["get_encounter_details"] = later_failure
        return server

    evidence = run_reconciliation_trial(
        scenario=scenario, controller=controller, server_factory=server_factory
    )
    return scenario, expected, evidence


def explain(values):
    from healthcraft.reconciliation.diagnostics import explain_reconciliation

    return explain_reconciliation(*values)


def wrong_exclusions(note):
    note["scope_exclusions"][0]["source_id"] = "SRC-A01"
    note["scope_exclusions"][1]["source_id"] = "SRC-A06"


@pytest.fixture(autouse=True)
def idempotency(monkeypatch):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")


def test_same_false_oracle_has_distinct_actual_readback_diagnostics():
    absent, present = case(mutate=wrong_exclusions, readback="none"), case(mutate=wrong_exclusions)
    before_absent, before_present = verify_reconciliation(*absent), verify_reconciliation(*present)
    assert before_absent == before_present
    left, right = explain(absent), explain(present)
    assert left["status"] == right["status"] == "available"
    assert len(left["observed_execution"]["new_stored_notes"]) == 1
    assert len(right["observed_execution"]["new_stored_notes"]) == 1
    assert left["notes"][0]["readback"]["attempted_call_ids"] == []
    readback = right["notes"][0]["readback"]
    assert readback["successful_target_call_ids"] == ["call-0005"]
    assert readback["stored_text_seen_call_ids"] == ["call-0005"]
    assert readback["oracle_verified"] is False
    assert verify_reconciliation(*absent) == before_absent
    assert verify_reconciliation(*present) == before_present


def test_exact_missing_unexpected_exclusions_have_no_guessed_pairing():
    result = explain(case(mutate=wrong_exclusions))
    issues = result["notes"][0]["scope_exclusions"]["issues"]
    assert [(i["code"], i["source_id"]) for i in issues] == [
        ("exclusion_missing", "SRC-A07"),
        ("exclusion_missing", "SRC-B01"),
        ("exclusion_unexpected", "SRC-A01"),
        ("exclusion_unexpected", "SRC-A06"),
    ]
    assert all("replacement" not in item for item in issues)


def test_matching_id_descriptor_differences_preserve_null_type_and_missing_fields():
    def mutate(note):
        row = note["scope_exclusions"][0]
        row["patient_id"] = None
        row["encounter_id"] = True
        del row["reason"]
        row["extra/claim~"] = 1

    result = explain(case(mutate=mutate))
    issues = result["notes"][0]["scope_exclusions"]["issues"]
    by_field = {i["field"]: i for i in issues}
    assert by_field["patient_id"]["observed"] is None
    assert by_field["encounter_id"]["observed"] is True
    assert by_field["reason"]["code"] == "exclusion_field_missing"
    assert "observed" not in by_field["reason"]
    assert by_field["extra/claim~"]["code"] == "exclusion_field_unexpected"
    assert by_field["extra/claim~"]["evidence_refs"][0]["decoded_json_pointer"].endswith(
        "/extra~1claim~0"
    )


def test_duplicate_exclusion_ids_are_not_collapsed():
    def mutate(note):
        note["scope_exclusions"].append(deepcopy(note["scope_exclusions"][0]))

    issues = explain(case(mutate=mutate))["notes"][0]["scope_exclusions"]["issues"]
    duplicate = next(i for i in issues if i["code"] == "exclusion_duplicate")
    assert duplicate["source_id"] == "SRC-A07"
    assert len(duplicate["evidence_refs"]) == 2


@pytest.mark.parametrize("mode", ["none", "wrong", "failed"])
def test_prewrite_wrong_target_and_failed_reads_are_not_matching_readback(mode):
    report = explain(case(mutate=wrong_exclusions, readback=mode))
    rb = report["notes"][0]["readback"]
    assert rb["successful_target_call_ids"] == rb["stored_text_seen_call_ids"] == []
    assert rb["attempted_call_ids"] == (["call-0005"] if mode == "failed" else [])


def test_acknowledged_write_without_storage_stays_distinct():
    report = explain(case(ack=True))
    assert len(report["observed_execution"]["successful_write_calls"]) == 1
    assert report["observed_execution"]["new_stored_notes"] == []
    assert report["notes"][0]["matching_stored_note_ids"] == []
    assert report["notes"][0]["readback"]["successful_target_call_ids"] == ["call-0005"]
    assert report["notes"][0]["readback"]["stored_text_seen_call_ids"] == []


def test_idempotent_retry_is_observed_separately_and_aliases_match():
    report = explain(case(retry=True, alias=True))
    assert [w["call_id"] for w in report["observed_execution"]["successful_write_calls"]] == [
        "call-0004"
    ]
    assert [w["call_id"] for w in report["observed_execution"]["deduplicated_retries"]] == [
        "call-0005"
    ]
    assert len(report["notes"]) == len(report["observed_execution"]["new_stored_notes"]) == 1
    assert report["notes"][0]["readback"]["stored_text_seen_call_ids"] == ["call-0006"]


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        '{"scope_exclusions":[],"scope_exclusions":[]}',
        '{"scope_exclusions":NaN}',
        '{"scope_exclusions":1e999}',
        "[]",
        '{"scope_exclusions":null}',
        '{"scope_exclusions":[{}]}',
    ],
)
def test_malformed_notes_explain_failure_without_hiding_real_storage(raw):
    result = explain(case(raw=raw))
    assert result["status"] == "available"
    assert len(result["observed_execution"]["new_stored_notes"]) == 1
    assert result["notes"][0]["scope_exclusions"]["status"] == "malformed"
    assert result["notes"][0]["scope_exclusions"]["issues"]
    assert result["notes"][0]["readback"]["stored_text_seen_call_ids"] == ["call-0005"]


@pytest.mark.parametrize("where", ["scenario", "expectations", "audit"])
def test_invalid_provenance_unavailable_no_authoritative_content_diagnosis(where):
    values = case()
    if where == "scenario":
        values[0]["clock"] = "2000-01-01T00:00:00Z"
    elif where == "expectations":
        values[1]["sources"][0]["source"]["status"] = "administered"
    else:
        values[2]["audit"][0]["params"] = {}
    result = explain(values)
    assert result["status"] == "unavailable"
    assert result["notes"] == []
    assert result["observed_execution"] is None
    assert result["errors"]


@pytest.mark.parametrize("value", [None, {"bad": float("nan")}, {1: "invalid key"}, {"bad": (1,)}])
def test_malformed_inputs_fail_closed_to_json_safe_unavailable(value):
    from healthcraft.reconciliation.diagnostics import explain_reconciliation

    result = explain_reconciliation(value, load_expectations(), {})
    assert result["status"] == "unavailable"
    json.dumps(result, allow_nan=False)


def test_bindings_determinism_detachment_and_explicit_limited_coverage():
    values = case()
    before = deepcopy(values)
    result = explain(values)
    for name, data in zip(("scenario", "expectations", "evidence"), values):
        assert (
            result["bindings"][name + "_sha256"]
            == hashlib.sha256(canonical(data).encode()).hexdigest()
        )
    assert (
        result["bindings"]["oracle_sha256"]
        == hashlib.sha256(canonical(verify_reconciliation(*values)).encode()).hexdigest()
    )
    assert result["oracle_checks"] == verify_reconciliation(*values)["checks"]
    assert "scope_exclusions" in result["coverage"]["assessed"]
    assert {"observations", "unresolved_conflicts", "retrieval_coverage"} <= set(
        result["coverage"]["unassessed"]
    )
    assert not {"reward", "passed", "mechanical_passed", "benchmark_score"} & result.keys()
    assert values == before and explain(values) == result
    result["notes"][0]["scope_exclusions"]["issues"].append({"changed": True})
    assert values == before and explain(values)["notes"][0]["scope_exclusions"]["issues"] == []


def resolve(value, pointer):
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def test_every_reference_resolves_to_original_document_and_note_index():
    def mutate(note):
        note["scope_exclusions"].reverse()
        note["scope_exclusions"][0]["encounter_id"] = "ENC-DDDDDDDD"
        note["scope_exclusions"][0]["extra/claim~"] = None

    values = case(mutate=mutate)
    result = explain(values)
    documents = dict(zip(("scenario", "expectations", "evidence"), values))

    def walk(value):
        if isinstance(value, dict):
            if "document" in value and "pointer" in value:
                selected = resolve(documents[value["document"]], value["pointer"])
                if "decoded_json_pointer" in value:
                    resolve(json.loads(selected), value["decoded_json_pointer"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(result)
    mismatch = next(
        i
        for i in result["notes"][0]["scope_exclusions"]["issues"]
        if i.get("field") == "encounter_id"
    )
    assert (
        mismatch["evidence_refs"][0]["decoded_json_pointer"] == "/scope_exclusions/0/encounter_id"
    )
    assert mismatch["expectation_refs"][0]["pointer"] == "/scope_exclusions/1/encounter_id"


def test_later_real_write_does_not_retroactively_attribute_storage_to_ack_only_call():
    scenario, expected = load_scenario(), load_expectations()
    text = canonical(note_document())

    def server_factory(world):
        server = create_server(world)
        original = server._handlers["update_encounter"]
        calls = 0

        def first_ack_only(world, params):
            nonlocal calls
            calls += 1
            return get_encounter_details(world, params) if calls == 1 else original(world, params)

        server._handlers["update_encounter"] = first_ack_only
        return server

    def controller(recorder, *, target):
        for identifier in ("ENC-AAAAAAAA", "ENC-BBBBBBBB", "ENC-CCCCCCCC"):
            recorder.call("getEncounterDetails", {"encounter_id": identifier})
        recorder.call("updateEncounter", {"encounter_id": target["encounter_id"], "notes": text})
        recorder.call("getEncounterDetails", {"encounter_id": target["encounter_id"]})
        recorder.call("updateEncounter", {"encounter_id": target["encounter_id"], "notes": text})
        recorder.call("getEncounterDetails", {"encounter_id": target["encounter_id"]})

    evidence = run_reconciliation_trial(
        scenario=scenario, controller=controller, server_factory=server_factory
    )
    result = explain((scenario, expected, evidence))
    assert len(result["observed_execution"]["successful_write_calls"]) == 2
    assert len(result["observed_execution"]["new_stored_notes"]) == 1
    assert result["notes"][0]["matching_stored_note_ids"] == []
    assert result["notes"][0]["readback"]["stored_text_seen_call_ids"] == []
    assert len(result["notes"][1]["matching_stored_note_ids"]) == 1
    assert result["notes"][1]["readback"]["stored_text_seen_call_ids"] == ["call-0007"]


def test_duplicate_same_text_writes_report_final_matches_not_unique_creation():
    scenario, expected = load_scenario(), load_expectations()
    text = canonical(note_document())

    def controller(recorder, *, target):
        for identifier in ("ENC-AAAAAAAA", "ENC-BBBBBBBB", "ENC-CCCCCCCC"):
            recorder.call("getEncounterDetails", {"encounter_id": identifier})
        for _ in range(2):
            recorder.call(
                "updateEncounter", {"encounter_id": target["encounter_id"], "notes": text}
            )
        recorder.call("getEncounterDetails", {"encounter_id": target["encounter_id"]})

    evidence = run_reconciliation_trial(scenario=scenario, controller=controller)
    report = explain((scenario, expected, evidence))
    assert len(report["observed_execution"]["successful_write_calls"]) == 2
    assert len(report["observed_execution"]["new_stored_notes"]) == 2
    final_ids = sorted(evidence["after"]["entities"]["clinical_note"])
    assert all(note["matching_stored_note_ids"] == final_ids for note in report["notes"])
    assert any("not unique call attribution" in value for value in report["limitations"])
    assert report["oracle_checks"]["persisted_action"] is False
