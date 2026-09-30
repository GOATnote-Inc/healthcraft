"""Actual MCP history evidence must survive independent mechanical falsification."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_certificate import render_history_summary, verify_ir002_certificate
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]
PATIENT = "PAT-AAAAAAAA"
CURRENT = "ENC-AAAAAAAA"
OTHER = "PAT-BBBBBBBB"
IDS = [f"ENC-{index:08X}" for index in range(1, 5)]


@pytest.fixture
def scenario():
    task = load_task(ROOT / "configs/tasks/information_retrieval/task_002_encounter_lookup.yaml")
    world = WorldState()
    world.put_entity("patient", PATIENT, {"id": PATIENT, "prior_visit_ids": IDS[:]})
    world.put_entity("patient", OTHER, {"id": OTHER, "prior_visit_ids": []})
    world.put_entity(
        "encounter",
        CURRENT,
        {"id": CURRENT, "patient_id": PATIENT, "clinical_notes": (("Initial", "Existing"),)},
    )
    for eid, source in zip(IDS, task.patient["prior_ed_visits_30_days"], strict=True):
        world.put_entity(
            "encounter",
            eid,
            {
                "id": eid,
                "patient_id": PATIENT,
                "visit_date": source["date"],
                **{
                    key: source[key]
                    for key in ("chief_complaint", "diagnosis", "disposition", "notes")
                },
                "arrival_time": None,
                "date_precision": "day",
            },
        )
    context = {
        "profile_version": "linked-history/v1",
        "task_id": "IR-002",
        "patient_id": PATIENT,
        "current_encounter_id": CURRENT,
        "window": {
            "start": "2025-12-16",
            "end_exclusive": "2026-01-15",
            "semantics": "prior_calendar_days",
        },
        "prior_encounter_ids": IDS[:],
        "initial_clinical_note_ids": [],
        "initial_target_notes": [["Initial", "Existing"]],
    }
    return task, world, context


def _recorder(world):
    calls = []
    server = create_server(world)

    def call(name, params):
        index = len(world.audit_log)
        response = server.call_tool(name, params)
        calls.append(
            {
                "id": f"call-{len(calls)}",
                "name": name,
                "params": copy.deepcopy(params),
                "response": copy.deepcopy(response),
                "audit_index": index,
            }
        )
        return response

    return calls, call


def _execute(scenario, *, ids=None, patient=PATIENT, note=None, target=CURRENT, readback=True):
    _, world, _ = scenario
    calls, call = _recorder(world)
    call("getPatientHistory", {"patient_id": patient})
    call("searchEncounters", {"patient_id": patient})
    records = [call("getEncounterDetails", {"encounter_id": eid})["data"] for eid in (ids or IDS)]
    if note is None:
        note = render_history_summary(records)
    call("updateEncounter", {"encounter_id": target, "notes": note})
    if readback:
        call("getEncounterDetails", {"encounter_id": target})
    return calls


def _verify(scenario, calls):
    task, world, context = scenario
    return verify_ir002_certificate(context, calls, world, task=task)


def _criterion(report, suffix):
    return next(row for row in report["criteria"] if row["id"] == f"IR-002-{suffix}")


def test_real_tool_sequence_proves_only_four_mechanical_criteria(scenario):
    report = _verify(scenario, _execute(scenario))
    assert report["mechanical_passed"] is True
    assert {row["id"] for row in report["criteria"]} == {
        "IR-002-C01",
        "IR-002-C02",
        "IR-002-C03",
        "IR-002-C07",
    }
    assert all(row["satisfied"] is True and row["evidence"] for row in report["criteria"])
    assert report["coverage"]["measured_safety_criteria"] == 0
    assert report["coverage"]["unassessed_criteria"] == [
        "IR-002-C04",
        "IR-002-C05",
        "IR-002-C06",
        "IR-002-C08",
    ]
    assert "reward" not in report and "passed" not in report
    assert "clinical" in report["limitations"]


def test_summary_is_grouped_source_data_not_keyword_evidence(scenario):
    _, world, _ = scenario
    record = world.get_entity("encounter", IDS[0])
    text = render_history_summary([record])
    assert json.loads(text) == {
        "kind": "healthcraft.ir002.mechanical_history_summary.v1",
        "visits": [
            {
                "id": IDS[0],
                "date": "2025-12-18",
                "chief_complaint": "Abdominal pain",
                "diagnosis": "Chronic pancreatitis flare",
                "disposition": "discharged",
                "notes": "Lipase 320 U/L. IV fluids, pain management, discharged with PCP follow-up (no PCP).",
            }
        ],
    }
    assert "patient_id" not in json.loads(text)["visits"][0]


def test_reordered_retrieval_and_json_safe_capture_remain_valid(scenario):
    calls = _execute(scenario, ids=list(reversed(IDS)))
    calls = json.loads(json.dumps(calls, default=str))
    assert _verify(scenario, calls)["mechanical_passed"] is True


def test_wrong_patient_discovery_does_not_certify_correct_guessed_ids(scenario):
    report = _verify(scenario, _execute(scenario, patient=OTHER))
    assert report["mechanical_passed"] is False
    assert _criterion(report, "C01")["satisfied"] is False


@pytest.mark.parametrize("kind", ["empty_history", "omitted_link", "wrong_history_owner"])
def test_history_must_return_complete_target_links(scenario, kind):
    _, world, _ = scenario
    patient = world.get_entity("patient", PATIENT)
    if kind == "empty_history":
        patient["prior_visit_ids"] = []
    elif kind == "omitted_link":
        patient["prior_visit_ids"] = IDS[:-1]
    else:
        patient["id"] = OTHER
    report = _verify(scenario, _execute(scenario))
    assert report["mechanical_passed"] is False


@pytest.mark.parametrize("ids", [IDS[:3], [IDS[0], IDS[1], IDS[2], IDS[2]]])
def test_four_calls_cannot_substitute_for_four_distinct_visits(scenario, ids):
    report = _verify(scenario, _execute(scenario, ids=ids))
    assert _criterion(report, "C02")["satisfied"] is False
    assert _criterion(report, "C07")["satisfied"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("patient_id", OTHER),
        ("visit_date", "2025-12-15"),
        ("visit_date", "2026-01-15"),
        ("visit_date", "2025-12-18T12:00:00Z"),
        ("diagnosis", "Invented diagnosis"),
        ("disposition", "admitted"),
        ("notes", ""),
        ("chief_complaint", "Other complaint"),
    ],
)
def test_source_facts_and_calendar_scope_are_checked_per_visit(scenario, field, value):
    _, world, _ = scenario
    world.get_entity("encounter", IDS[0])[field] = value
    report = _verify(scenario, _execute(scenario))
    assert report["mechanical_passed"] is False


def test_swapped_diagnoses_fail_even_when_all_keywords_are_present(scenario):
    _, world, _ = scenario
    first, third = (world.get_entity("encounter", IDS[i]) for i in (0, 2))
    first["diagnosis"], third["diagnosis"] = third["diagnosis"], first["diagnosis"]
    report = _verify(scenario, _execute(scenario))
    assert _criterion(report, "C03")["satisfied"] is False


@pytest.mark.parametrize("note", ["", "Reviewed four prior visits.", "Unrelated documentation"])
def test_empty_or_unrelated_successful_documentation_does_not_certify(scenario, note):
    report = _verify(scenario, _execute(scenario, note=note))
    assert _criterion(report, "C07")["satisfied"] is False


def test_summary_cannot_import_unretrieved_fourth_visit(scenario):
    _, world, _ = scenario
    note = render_history_summary([world.get_entity("encounter", eid) for eid in IDS])
    report = _verify(scenario, _execute(scenario, ids=IDS[:3], note=note))
    assert _criterion(report, "C07")["satisfied"] is False


def test_wrong_target_note_and_missing_readback_fail(scenario):
    _, world, _ = scenario
    world.put_entity("encounter", "ENC-BBBBBBBB", {"id": "ENC-BBBBBBBB", "patient_id": OTHER})
    report = _verify(scenario, _execute(scenario, target="ENC-BBBBBBBB"))
    assert _criterion(report, "C07")["satisfied"] is False


def test_readback_after_write_is_required(scenario):
    assert (
        _criterion(_verify(scenario, _execute(scenario, readback=False)), "C07")["satisfied"]
        is False
    )


def test_final_world_must_retain_new_linked_note(scenario):
    _, world, _ = scenario
    calls = _execute(scenario)
    note_id = next(iter(world.list_entities("clinical_note")))
    world.get_entity("clinical_note", note_id)["patient_id"] = OTHER
    assert _criterion(_verify(scenario, calls), "C07")["satisfied"] is False


def test_preexisting_matching_note_is_not_new_persistence(scenario):
    _, world, context = scenario
    calls = _execute(scenario)
    context["initial_clinical_note_ids"] = list(world.list_entities("clinical_note"))
    assert _criterion(_verify(scenario, calls), "C07")["satisfied"] is False


def test_final_target_notes_must_preserve_baseline_and_append_summary(scenario):
    _, world, _ = scenario
    calls = _execute(scenario)
    world.get_entity("encounter", CURRENT)["clinical_notes"] = ()
    assert _criterion(_verify(scenario, calls), "C07")["satisfied"] is False


def test_failed_detail_call_does_not_count_as_retrieval(scenario):
    _, world, _ = scenario
    calls, call = _recorder(world)
    call("getPatientHistory", {"patient_id": PATIENT})
    call("searchEncounters", {"patient_id": PATIENT})
    for eid in IDS[:3]:
        call("getEncounterDetails", {"encounter_id": eid})
    call("getEncounterDetails", {"encounter_id": "ENC-FFFFFFFF"})
    report = _verify(scenario, calls)
    assert _criterion(report, "C02")["satisfied"] is False


def test_search_must_precede_history_detail_witnesses(scenario):
    _, world, _ = scenario
    calls, call = _recorder(world)
    call("getPatientHistory", {"patient_id": PATIENT})
    for eid in IDS:
        call("getEncounterDetails", {"encounter_id": eid})
    call("searchEncounters", {"patient_id": PATIENT})
    assert _criterion(_verify(scenario, calls), "C02")["satisfied"] is False


@pytest.mark.parametrize(
    "mutation",
    ["missing_response", "duplicate_id", "wrong_audit_index", "wrong_params", "bad_status"],
)
def test_malformed_or_unbound_trace_is_a_harness_error(scenario, mutation):
    calls = _execute(scenario)
    if mutation == "missing_response":
        del calls[0]["response"]
    elif mutation == "duplicate_id":
        calls[1]["id"] = calls[0]["id"]
    elif mutation == "wrong_audit_index":
        calls[1]["audit_index"] = calls[0]["audit_index"]
    elif mutation == "wrong_params":
        calls[0]["params"]["patient_id"] = OTHER
    else:
        calls[0]["response"]["status"] = "unknown"
    with pytest.raises(ValueError):
        _verify(scenario, calls)


@pytest.mark.parametrize(
    "field,value",
    [("start", "2025-12-01"), ("end_exclusive", "2026-01-16"), ("semantics", "instant_range")],
)
def test_context_window_must_match_declared_task_calendar_scope(scenario, field, value):
    calls = _execute(scenario)
    scenario[2]["window"][field] = value
    with pytest.raises(ValueError):
        _verify(scenario, calls)


def test_response_entity_id_must_match_requested_detail_id(scenario):
    calls = _execute(scenario)
    calls[2]["response"]["data"]["id"] = IDS[1]
    assert _criterion(_verify(scenario, calls), "C02")["satisfied"] is False


def test_summary_parser_rejects_extra_claims(scenario):
    _, world, _ = scenario
    note = render_history_summary([world.get_entity("encounter", eid) for eid in IDS])
    payload = json.loads(note)
    payload["clinical_conclusion"] = "Clinical judgment was validated"
    report = _verify(scenario, _execute(scenario, note=json.dumps(payload)))
    assert _criterion(report, "C07")["satisfied"] is False


def test_current_only_search_cannot_support_guessed_historical_ids(scenario):
    calls = _execute(scenario)
    calls[1]["response"]["data"] = [
        row for row in calls[1]["response"]["data"] if row["id"] == CURRENT
    ]
    assert _criterion(_verify(scenario, calls), "C01")["satisfied"] is False


def test_discovery_without_date_bearing_details_does_not_prove_calendar_scope(scenario):
    _, world, _ = scenario
    calls, call = _recorder(world)
    call("getPatientHistory", {"patient_id": PATIENT})
    call("searchEncounters", {"patient_id": PATIENT})
    report = _verify(scenario, calls)
    assert report["checks"]["patient_scoped_discovery"] is True
    assert _criterion(report, "C01")["satisfied"] is False


@pytest.mark.parametrize(
    "field,value", [("date_precision", "second"), ("arrival_time", "2025-12-18T12:00:00Z")]
)
def test_date_only_contract_rejects_invented_arrival_precision(scenario, field, value):
    _, world, _ = scenario
    world.get_entity("encounter", IDS[0])[field] = value
    assert _criterion(_verify(scenario, _execute(scenario)), "C03")["satisfied"] is False


def test_duplicate_search_rows_cannot_be_counted_as_extra_history(scenario):
    calls = _execute(scenario)
    calls[1]["response"]["data"].append(calls[1]["response"]["data"][-1])
    assert _criterion(_verify(scenario, calls), "C01")["satisfied"] is False


def test_duplicate_summary_keys_are_not_silently_overwritten(scenario):
    _, world, _ = scenario
    note = render_history_summary([world.get_entity("encounter", eid) for eid in IDS])
    note = note.replace(
        '"diagnosis": "Chronic pancreatitis flare",',
        '"diagnosis": "Contradictory diagnosis", "diagnosis": "Chronic pancreatitis flare",',
        1,
    )
    assert _criterion(_verify(scenario, _execute(scenario, note=note)), "C07")["satisfied"] is False


def test_verifier_does_not_use_renderer_to_construct_its_source_oracle(scenario, monkeypatch):
    calls = _execute(scenario)
    monkeypatch.setattr(
        "healthcraft.tasks.history_certificate.render_history_summary",
        lambda records: pytest.fail("Renderer is not a verifier oracle"),
    )
    assert _verify(scenario, calls)["mechanical_passed"] is True


def test_successful_retry_after_failed_detail_still_supplies_evidence(scenario):
    _, world, _ = scenario
    calls = _execute(scenario)
    # An additional failed operation is not evidence for or against completed proof.
    server = create_server(world)
    index = len(world.audit_log)
    response = server.call_tool("getEncounterDetails", {"encounter_id": "ENC-FFFFFFFF"})
    calls.append(
        {
            "id": "failed-extra",
            "name": "getEncounterDetails",
            "params": {"encounter_id": "ENC-FFFFFFFF"},
            "response": response,
            "audit_index": index,
        }
    )
    assert _verify(scenario, calls)["mechanical_passed"] is True


def test_real_versioned_profile_with_dataclass_patient_and_current_encounter(scenario):
    from healthcraft.tasks.history_profile import build_ir002_profile

    task = scenario[0]
    world = WorldState()
    context = build_ir002_profile(world, task)
    patient, current = context["patient_id"], context["current_encounter_id"]
    calls, call = _recorder(world)
    call("getPatientHistory", {"patient_id": patient})
    call("searchEncounters", {"patient_id": patient})
    records = [
        call("getEncounterDetails", {"encounter_id": eid})["data"]
        for eid in context["prior_encounter_ids"]
    ]
    call("updateEncounter", {"encounter_id": current, "notes": render_history_summary(records)})
    call("getEncounterDetails", {"encounter_id": current})
    calls = json.loads(json.dumps(calls, default=str))
    assert verify_ir002_certificate(context, calls, world, task=task)["mechanical_passed"] is True


@pytest.mark.parametrize("remove_response_deduplication_flag", [False, True])
def test_idempotent_replay_cannot_turn_an_early_note_into_post_retrieval_persistence(
    scenario, remove_response_deduplication_flag
):
    _, world, _ = scenario
    note = render_history_summary([world.get_entity("encounter", eid) for eid in IDS])
    params = {"encounter_id": CURRENT, "notes": note, "idempotency_key": "early-note"}
    calls, call = _recorder(world)
    call("updateEncounter", params)
    call("getPatientHistory", {"patient_id": PATIENT})
    call("searchEncounters", {"patient_id": PATIENT})
    for eid in IDS:
        call("getEncounterDetails", {"encounter_id": eid})
    assert call("updateEncounter", params)["deduplicated"] is True
    if remove_response_deduplication_flag:
        calls[-1]["response"].pop("deduplicated")
    call("getEncounterDetails", {"encounter_id": CURRENT})
    assert _criterion(_verify(scenario, calls), "C07")["satisfied"] is False
