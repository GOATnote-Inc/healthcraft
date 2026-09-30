"""Independent mechanical checks of captured, source-linked roster retrieval."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_execution import ExecutionRecorder
from healthcraft.tasks.loader import load_task
from healthcraft.tasks.roster_profile import build_roster_profile
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]
TASKS = {
    "CC-022": "clinical_communication/task_022_nurse_delegation.yaml",
    "CC-027": "clinical_communication/task_027_ambulance_diversion.yaml",
    "CC-028": "clinical_communication/task_028_surge_capacity.yaml",
    "IR-018": "information_retrieval/task_018_supply_shortage.yaml",
    "IR-023": "information_retrieval/task_023_shortage_impact.yaml",
    "IR-025": "information_retrieval/task_025_multi_patient_triage.yaml",
}


def _scenario(task_id="CC-022"):
    task = load_task(ROOT / "configs/tasks" / TASKS[task_id])
    world = WorldState()
    context = build_roster_profile(world, task)
    recorder = ExecutionRecorder(create_server(world), world)
    return task, context, recorder, world


def _retrieve(scenario, *, members=None):
    _, context, recorder, _ = scenario
    for member in context["roster"] if members is None else members:
        recorder.call("getEncounterDetails", {"encounter_id": member["encounter_id"]})
    return recorder.calls


def _verify(scenario, calls=None):
    from healthcraft.tasks.roster_certificate import verify_roster_retrieval

    task, context, recorder, world = scenario
    return verify_roster_retrieval(task, context, recorder.calls if calls is None else calls, world)


@pytest.mark.parametrize("task_id,count", zip(TASKS, [4, 3, 7, 7, 7, 5], strict=True))
def test_actual_tool_retrieval_covers_every_source_member_without_clinical_claim(task_id, count):
    scenario = _scenario(task_id)
    calls = _retrieve(scenario)
    report = _verify(scenario)
    assert report["mechanical_passed"] is True
    assert all(report["checks"].values())
    assert report["coverage"]["expected_members"] == count
    assert report["coverage"]["retrieved_members"] == count
    assert report["coverage"]["source_concordant_members"] == count
    assert report["coverage"]["measured_clinical_criteria"] == 0
    assert report["coverage"]["measured_safety_criteria"] == 0
    assert report["coverage"]["unassessed_criteria"] == [c["id"] for c in scenario[0].criteria]
    assert report["benchmark_score"] is None
    assert "reward" not in report and "passed" not in report
    assert {c["id"] for c in calls} == {
        cid for member in report["members"] for cid in member["witness_call_ids"]
    }
    assert "clinical" in report["limitations"]


def test_retrieval_order_and_unrelated_prior_audit_do_not_change_certificate():
    scenario = _scenario()
    scenario[3].record_audit("otherTool", {}, "ok")
    _retrieve(scenario, members=list(reversed(scenario[1]["roster"])))
    assert _verify(scenario)["mechanical_passed"] is True


@pytest.mark.parametrize("kind", ["empty", "omitted", "duplicate"])
def test_missing_distinct_members_cannot_be_substituted_by_call_count(kind):
    scenario = _scenario()
    members = scenario[1]["roster"]
    selected = [] if kind == "empty" else members[:-1]
    if kind == "duplicate":
        selected += members[:1]
    _retrieve(scenario, members=selected)
    report = _verify(scenario)
    assert report["mechanical_passed"] is False
    assert report["checks"]["all_members_retrieved"] is False


def test_failed_actual_tool_call_does_not_supply_a_missing_member():
    scenario = _scenario()
    _retrieve(scenario, members=scenario[1]["roster"][:-1])
    scenario[2].call("getEncounterDetails", {"encounter_id": "ENC-MISSING"})
    report = _verify(scenario)
    assert report["mechanical_passed"] is False
    assert report["coverage"]["retrieved_members"] == 3


def test_failed_lookup_of_expected_member_is_not_positive_evidence():
    scenario = _scenario()
    missing_id = scenario[1]["roster"][-1]["encounter_id"]
    scenario[3]._entities["encounter"].pop(missing_id)
    calls = _retrieve(scenario)
    assert calls[-1]["response"]["status"] == "error"
    report = _verify(scenario)
    assert report["mechanical_passed"] is False
    assert report["coverage"]["retrieved_members"] == 3


def test_swapping_successful_response_payloads_does_not_match_request_ids():
    scenario = _scenario()
    calls = _retrieve(scenario)
    calls[0]["response"], calls[1]["response"] = calls[1]["response"], calls[0]["response"]
    report = _verify(scenario, calls)
    assert report["mechanical_passed"] is False
    assert report["coverage"]["source_concordant_members"] == 2


def test_captures_without_actual_world_audit_cannot_certify():
    scenario = _scenario()
    calls = _retrieve(scenario)
    unused_world = WorldState()
    task, context, _, _ = scenario
    from healthcraft.tasks.roster_certificate import verify_roster_retrieval

    with pytest.raises(ValueError, match="Audit"):
        verify_roster_retrieval(task, context, calls, unused_world)


@pytest.mark.parametrize(
    "field,value",
    [
        ("patient_id", "PAT-OTHER"),
        ("id", "ENC-OTHER"),
        ("source_path", "patients_requiring_action/1"),
        ("source_context", "Different source context"),
        ("profile_version", "other/v1"),
        ("task_id", "CC-027"),
        ("authored_observations", {}),
        ("arrival_time", "2026-01-15T03:00:00Z"),
    ],
)
def test_returned_identity_provenance_and_sparse_source_contract_are_required(field, value):
    scenario = _scenario()
    entity = scenario[3].get_entity("encounter", scenario[1]["roster"][0]["encounter_id"])
    entity[field] = value
    _retrieve(scenario)
    assert _verify(scenario)["mechanical_passed"] is False


@pytest.mark.parametrize("kind", ["changed", "omitted", "added", "swapped", "type"])
def test_source_values_are_checked_independently_by_member_and_type(kind):
    scenario = _scenario()
    first, second = [
        scenario[3].get_entity("encounter", r["encounter_id"]) for r in scenario[1]["roster"][:2]
    ]
    observations = first["authored_observations"]
    if kind == "changed":
        observations["summary"] = "Invented summary"
    elif kind == "omitted":
        observations.pop("summary")
    elif kind == "added":
        observations["needed_actions"] = "Unreviewed answer"
    elif kind == "swapped":
        first["authored_observations"], second["authored_observations"] = (
            second["authored_observations"],
            first["authored_observations"],
        )
    else:
        observations["bed"] = str(observations["bed"])
    _retrieve(scenario)
    report = _verify(scenario)
    assert report["mechanical_passed"] is False
    assert report["checks"]["source_facts_concordant"] is False


def test_correct_final_world_cannot_replace_truncated_captured_observations():
    scenario = _scenario()
    calls = _retrieve(scenario)
    calls[0]["response"]["data"]["authored_observations"].pop("summary")
    assert _verify(scenario, calls)["mechanical_passed"] is False


def test_correct_response_cannot_hide_changed_final_patient_record():
    scenario = _scenario()
    _retrieve(scenario)
    patient = scenario[3].get_entity("patient", scenario[1]["roster"][0]["patient_id"])
    patient["authored_observations"]["summary"] = "Changed after retrieval"
    report = _verify(scenario)
    assert report["mechanical_passed"] is False
    assert report["checks"]["final_world_source_concordant"] is False


@pytest.mark.parametrize(
    "kind",
    [
        "missing_response",
        "wrong_params",
        "wrong_status",
        "no_audit",
        "duplicate_id",
        "duplicate_audit",
        "unordered",
    ],
)
def test_missing_or_unbound_capture_is_a_harness_error(kind):
    scenario = _scenario()
    calls = _retrieve(scenario)
    if kind == "missing_response":
        calls[0].pop("response")
    elif kind == "wrong_params":
        calls[0]["params"]["encounter_id"] = calls[1]["params"]["encounter_id"]
    elif kind == "wrong_status":
        calls[0]["response"] = {"status": "error", "code": "fabricated"}
    elif kind == "no_audit":
        calls[0]["audit_index"] = len(scenario[3].audit_log) + 1
    elif kind == "duplicate_id":
        calls[1]["id"] = calls[0]["id"]
    elif kind == "duplicate_audit":
        calls[1]["audit_index"] = calls[0]["audit_index"]
    else:
        calls.reverse()
    with pytest.raises(ValueError):
        _verify(scenario, calls)


@pytest.mark.parametrize(
    "kind",
    [
        "source_hash",
        "contract_hash",
        "duplicate",
        "missing",
        "wrong_source_path",
        "label",
        "source_context",
    ],
)
def test_context_must_bind_the_complete_registered_source(kind):
    scenario = _scenario()
    context = scenario[1]
    _retrieve(scenario)
    if kind in ("source_hash", "contract_hash"):
        context[kind.replace("hash", "sha256")] = "0" * 64
    elif kind == "duplicate":
        context["roster"][-1] = deepcopy(context["roster"][0])
    elif kind == "missing":
        context["roster"].pop()
    elif kind == "wrong_source_path":
        context["roster"][0]["source_path"] = "patients_requiring_action/99"
    else:
        context["roster"][0][kind] = "Changed"
    with pytest.raises(ValueError):
        _verify(scenario)


def test_changed_authored_task_does_not_validate_under_old_context_hash():
    scenario = list(_scenario())
    _retrieve(scenario)
    changed = deepcopy(scenario[0].source_data)
    changed["patients_requiring_action"][0]["summary"] = "A different authored fact"
    scenario[0] = replace(scenario[0], source_data=changed)
    with pytest.raises(ValueError, match="source"):
        _verify(scenario)


def test_verification_is_read_only_and_return_value_is_json_serializable():
    import json

    scenario = _scenario("IR-025")
    calls = _retrieve(scenario)
    before_context, before_calls = deepcopy(scenario[1]), deepcopy(calls)
    before_patients = deepcopy(scenario[3].list_entities("patient"))
    before_encounters = deepcopy(scenario[3].list_entities("encounter"))
    before_audit = scenario[3].audit_log
    report = _verify(scenario, calls)
    json.dumps(report, allow_nan=False)
    assert scenario[1] == before_context and calls == before_calls
    assert scenario[3].list_entities("patient") == before_patients
    assert scenario[3].list_entities("encounter") == before_encounters
    assert scenario[3].audit_log == before_audit
