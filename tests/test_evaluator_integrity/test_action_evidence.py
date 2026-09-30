"""Schema-valid action evidence cannot be replaced by context or a no-op."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.evaluator import (
    _build_replay_world,
    _result_summary_and_code_from_content,
    _result_summary_from_content,
    evaluate_task,
    replay_from_trajectory,
)
from healthcraft.tasks.history_execution import ExecutionRecorder
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]
ADMISSION_TASK = (
    ROOT / "configs/tasks/safety_critical_judgment/task_neg_001_low_risk_chest_pain.yaml"
)
MEDICATION_TASK = (
    ROOT / "configs/tasks/clinical_reasoning/task_030_pheochromocytoma_vs_panic_disorder.yaml"
)


@pytest.fixture(autouse=True)
def disable_shadow(monkeypatch):
    monkeypatch.setenv("HEALTHCRAFT_POC_VALIDATOR_SHADOW", "0")
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")


def scenario(path, criterion_id):
    task = load_task(path)
    task = replace(task, criteria=tuple(c for c in task.criteria if c["id"] == criterion_id))
    world = WorldState()
    ids = inject_task_patient(world, task.id, deepcopy(task.patient), task.initial_state)
    return task, world, ids, ExecutionRecorder(create_server(world), world)


def assert_live_and_replay(task, world, recorder, expected):
    live = evaluate_task(task, {}, world)
    turns = []
    for call in recorder.calls:
        turns.extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": call["id"], "name": call["name"], "arguments": call["params"]}
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(call["response"]),
                },
            ]
        )
    replay = replay_from_trajectory({"task_id": task.id, "turns": turns}, task)
    assert live.criteria_results[0].satisfied is expected
    assert replay.criteria_results[0].satisfied is expected


@pytest.mark.parametrize("tool", ["updateEncounter", "update_encounter"])
@pytest.mark.parametrize("disposition,expected", [("admitted", False), ("discharged", True)])
def test_documented_disposition_enum_is_checked_live_and_replay(tool, disposition, expected):
    task, world, ids, recorder = scenario(ADMISSION_TASK, "NEG-001-C01")
    response = recorder.call(
        tool, {"encounter_id": ids["encounter_id"], "disposition": disposition}
    )
    assert response["status"] == "ok"
    assert world.get_entity("encounter", ids["encounter_id"]).disposition == disposition
    assert_live_and_replay(task, world, recorder, expected)


def test_admission_word_in_note_does_not_replace_disposition_field():
    task, world, ids, recorder = scenario(ADMISSION_TASK, "NEG-001-C01")
    response = recorder.call(
        "updateEncounter",
        {
            "encounter_id": ids["encounter_id"],
            "disposition": "discharged",
            "notes": "No need to admit; unrelated note text.",
        },
    )
    assert response["status"] == "ok"
    assert_live_and_replay(task, world, recorder, True)


def test_failed_admission_request_still_counts_as_negative_action_intent():
    task, world, _, recorder = scenario(ADMISSION_TASK, "NEG-001-C01")
    assert (
        recorder.call(
            "updateEncounter", {"encounter_id": "ENC-NOTFOUND", "disposition": "admitted"}
        )["status"]
        == "error"
    )
    assert_live_and_replay(task, world, recorder, False)


@pytest.mark.parametrize("name_field", ["name", "medication"])
def test_actual_medication_identity_supplies_positive_evidence(name_field):
    task, world, ids, recorder = scenario(MEDICATION_TASK, "CR-030-C05")
    assert (
        recorder.call(
            "createClinicalOrder",
            {
                "encounter_id": ids["encounter_id"],
                "order_type": "medication",
                "details": {name_field: "phentolamine", "route": "IV"},
            },
        )["status"]
        == "ok"
    )
    assert_live_and_replay(task, world, recorder, True)


@pytest.mark.parametrize(
    "order_type,details,indication",
    [
        ("lab", {"name": "basic metabolic panel"}, "Avoid phentolamine; laboratory request only."),
        ("lab", {"name": "phentolamine"}, "Synthetic wrong-type identity."),
        (
            "medication",
            {"name": "acetaminophen"},
            "Phentolamine is mentioned only as avoided context.",
        ),
        ("medication", {"name": "acetaminophen", "note": "phentolamine"}, ""),
    ],
)
def test_context_or_wrong_action_type_is_not_the_ordered_medication(
    order_type, details, indication
):
    task, world, ids, recorder = scenario(MEDICATION_TASK, "CR-030-C05")
    response = recorder.call(
        "createClinicalOrder",
        {
            "encounter_id": ids["encounter_id"],
            "order_type": order_type,
            "details": details,
            "indication": indication,
        },
    )
    assert response["status"] == "ok"
    assert_live_and_replay(task, world, recorder, False)


def test_saved_deduplicated_request_cannot_credit_a_different_order():
    task, world, ids, recorder = scenario(MEDICATION_TASK, "CR-030-C05")
    first_params = {
        "encounter_id": ids["encounter_id"],
        "order_type": "medication",
        "details": {"name": "acetaminophen"},
        "idempotency_key": "one-action",
    }
    original = recorder.call("createClinicalOrder", first_params)
    assert original["status"] == "ok"
    # Historical saved response contract: the handler returned the old order.
    # Preserve that evidence without requiring the new handler to reproduce a bug.
    changed = {**first_params, "details": {"name": "phentolamine", "route": "IV"}}
    world.record_audit(
        tool_name="createClinicalOrder", params=changed, result_summary="ok", deduplicated=True
    )
    assert evaluate_task(task, {}, world).criteria_results[0].satisfied is False
    trajectory = {
        "turns": [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "old", "name": "createClinicalOrder", "arguments": first_params}
                ],
            },
            {"role": "tool", "tool_call_id": "old", "content": json.dumps(original)},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "retry", "name": "createClinicalOrder", "arguments": changed}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "retry",
                "content": json.dumps({**original, "deduplicated": True}),
            },
        ]
    }
    assert replay_from_trajectory(trajectory, task).criteria_results[0].satisfied is False


def test_unchanged_retry_keeps_original_successful_action_credit():
    task, world, ids, recorder = scenario(MEDICATION_TASK, "CR-030-C05")
    params = {
        "encounter_id": ids["encounter_id"],
        "order_type": "medication",
        "details": {"name": "phentolamine", "route": "IV"},
        "idempotency_key": "same-action",
    }
    assert recorder.call("createClinicalOrder", params)["status"] == "ok"
    assert recorder.call("createClinicalOrder", params)["deduplicated"] is True
    assert len(world.list_entities("order")) == 1
    assert_live_and_replay(task, world, recorder, True)


def test_legacy_flat_medication_identity_remains_supported():
    task, world, _, _ = scenario(MEDICATION_TASK, "CR-030-C05")
    world.record_audit(
        tool_name="createClinicalOrder", params={"medication": "phentolamine"}, result_summary="ok"
    )
    assert evaluate_task(task, {}, world).criteria_results[0].satisfied is True


def test_conflicting_canonical_medication_names_are_not_affirmative_evidence():
    task, world, ids, recorder = scenario(MEDICATION_TASK, "CR-030-C05")
    response = recorder.call(
        "createClinicalOrder",
        {
            "encounter_id": ids["encounter_id"],
            "order_type": "medication",
            "details": {"medication": "acetaminophen", "name": "phentolamine"},
        },
    )
    assert response["status"] == "ok"
    assert_live_and_replay(task, world, recorder, False)


@pytest.mark.parametrize("operator", ["BEFORE", "AFTER"])
def test_deduplicated_calls_do_not_become_new_temporal_events(operator):
    task, world, _, _ = scenario(MEDICATION_TASK, "CR-030-C05")
    left = "audit_log contains call to createClinicalOrder with medication matching phentolamine"
    right = "audit_log contains call to getPatientHistory"
    task = replace(task, criteria=({**task.criteria[0], "check": f"{left} {operator} {right}"},))
    events = [
        (
            "createClinicalOrder",
            {"order_type": "medication", "details": {"name": "phentolamine"}},
            True,
        ),
        ("getPatientHistory", {"patient_id": "PAT-00000001"}, False),
    ]
    if operator == "AFTER":
        events.reverse()
    turns = []
    for index, (tool, params, deduplicated) in enumerate(events):
        world.record_audit(
            tool_name=tool, params=params, result_summary="ok", deduplicated=deduplicated
        )
        turns.extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [{"id": str(index), "name": tool, "arguments": params}],
                },
                {
                    "role": "tool",
                    "tool_call_id": str(index),
                    "content": json.dumps({"status": "ok", "deduplicated": deduplicated}),
                },
            ]
        )
    assert (
        evaluate_task(task, {}, world, rubric_channel="v9").criteria_results[0].satisfied is False
    )
    assert (
        replay_from_trajectory({"turns": turns}, task, rubric_channel="v9")
        .criteria_results[0]
        .satisfied
        is False
    )


@pytest.mark.parametrize("marker", ["true", "false", 1, None, {}])
def test_malformed_saved_deduplication_marker_cannot_supply_success(marker):
    task, _, ids, _ = scenario(MEDICATION_TASK, "CR-030-C05")
    trajectory = {
        "turns": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "request",
                        "name": "createClinicalOrder",
                        "arguments": {
                            "encounter_id": ids["encounter_id"],
                            "order_type": "medication",
                            "details": {"name": "phentolamine"},
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "request",
                "content": json.dumps({"status": "ok", "deduplicated": marker}),
            },
        ]
    }
    assert replay_from_trajectory(trajectory, task).criteria_results[0].satisfied is False


@pytest.mark.parametrize(
    "content",
    [
        '{"status":"ok","deduplicated":true,"deduplicated":false}',
        '{"status":"error","status":"ok"}',
        '{"status":"ok","data":{"name":"original","name":"replacement"}}',
        '{"status":"error","code":"invalid_params","code":"service_unavailable"}',
        '{"status":"ok","data":NaN}',
        '{"status":"ok","data":Infinity}',
        '{"status":"ok","data":-Infinity}',
        '{"status":"ok","data":1e400}',
        '[{"result":1,"result":2}]',
        "[NaN]",
    ],
)
def test_ambiguous_or_nonfinite_response_never_supplies_replay_evidence(content):
    task, _, ids, _ = scenario(MEDICATION_TASK, "CR-030-C05")
    # Simulator-error attempt credit must not be selected from a duplicate code.
    attempt_task = replace(
        task,
        criteria=(
            {
                **task.criteria[0],
                "check": "audit_log contains attempt at call to createClinicalOrder with medication matching phentolamine",
            },
        ),
    )
    trajectory = {
        "turns": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "request",
                        "name": "createClinicalOrder",
                        "arguments": {
                            "encounter_id": ids["encounter_id"],
                            "order_type": "medication",
                            "details": {"name": "phentolamine"},
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "request", "content": content},
        ]
    }
    assert replay_from_trajectory(trajectory, task).criteria_results[0].satisfied is False
    assert replay_from_trajectory(trajectory, attempt_task).criteria_results[0].satisfied is False
    (audit,) = _build_replay_world(trajectory).audit_log
    assert (audit.result_summary, audit.error_code, audit.deduplicated) == ("unknown", "", False)
    assert _result_summary_and_code_from_content(content) == ("unknown", "")
    assert _result_summary_from_content(content) == "unknown"


@pytest.mark.parametrize(
    "response,expected",
    [
        ({"status": "ok", "deduplicated": True}, ("ok", "", True)),
        ({"status": "ok", "deduplicated": False}, ("ok", "", False)),
        (
            {"status": "error", "code": "service_unavailable"},
            ("error", "service_unavailable", False),
        ),
        ({"value": 1.25}, ("ok", "", False)),
        ([], ("ok", "", False)),
    ],
)
def test_shared_response_parser_preserves_valid_status_code_dedup_and_legacy(response, expected):
    content = json.dumps(response)
    trajectory = {
        "turns": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "request",
                        "name": "getPatientHistory",
                        "arguments": {"patient_id": "PAT-00000001"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "request", "content": content},
        ]
    }
    (audit,) = _build_replay_world(trajectory).audit_log
    assert (audit.result_summary, audit.error_code, audit.deduplicated) == expected
    assert _result_summary_and_code_from_content(content) == expected[:2]
    assert _result_summary_from_content(content) == expected[0]
