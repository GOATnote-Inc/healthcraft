"""Invalid model envelopes must not execute ambiguous actions or erase evidence."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from healthcraft.llm.agent import run_agent_task
from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import Task
from healthcraft.trajectory import trajectory_completion
from healthcraft.world.state import WorldState


def fixture():
    world = WorldState()
    ids = inject_task_patient(world, "PROTOCOL-TEST", {"age": 40, "sex": "F"})
    task = Task(
        id="PROTOCOL-TEST",
        category="information_retrieval",
        level=1,
        title="Synthetic execution protocol",
        description="Copy the requested synthetic software action exactly.",
        initial_state={},
        expected_tools=(),
        criteria=(),
        metadata={},
    )
    call = {
        "id": "call-1",
        "name": "createClinicalOrder",
        "arguments": {
            "encounter_id": ids["encounter_id"],
            "order_type": "lab",
            "details": {"test_name": "SYNTHETIC-PROTOCOL-CHECK"},
        },
    }
    return world, create_server(world), task, call


def client(*responses):
    items = iter(deepcopy(responses))
    return SimpleNamespace(chat=lambda *args, **kwargs: next(items))


def tool_response(*calls):
    return {
        "content": "Requested synthetic action",
        "tool_calls": list(calls),
        "stop_reason": "tool_calls",
    }


FINAL = {"content": "Complete", "tool_calls": [], "stop_reason": "stop"}


@pytest.mark.parametrize(
    "malformed", [None, [], {"content": "Malformed later response", "stop_reason": "stop"}]
)
def test_later_malformed_response_retains_real_prior_action_and_trace(malformed):
    world, server, task, call = fixture()
    trajectory = run_agent_task(client(tool_response(call), malformed), task, server, "system")
    assert trajectory.error is not None
    assert trajectory.metadata["termination_kind"] == "invalid_model_response"
    assert trajectory.metadata["agent_protocol_error"]["round"] == 2
    assert trajectory.metadata["agent_protocol_error"]["normalized_response"] == malformed
    assert len(world.list_entities("order")) == 1
    assert len(world.audit_log) == 1
    assert [turn.role for turn in trajectory.turns] == ["system", "user", "assistant", "tool"]
    assert trajectory.turns[-1].tool_call_id == "call-1"
    assert (
        trajectory_completion(trajectory.to_dict()["turns"], trajectory.metadata, trajectory.error)[
            0
        ]
        == "incomplete"
    )


@pytest.mark.parametrize(
    "kind", ["duplicate_id", "missing_id", "empty_id", "malformed_arguments", "missing_name"]
)
def test_invalid_batch_is_rejected_before_any_actual_order(kind):
    world, server, task, call = fixture()
    second = deepcopy(call)
    second["id"] = "call-2"
    if kind == "duplicate_id":
        second["id"] = call["id"]
    elif kind == "missing_id":
        second.pop("id")
    elif kind == "empty_id":
        second["id"] = ""
    elif kind == "malformed_arguments":
        second["arguments"] = []
    elif kind == "missing_name":
        second.pop("name")
    response = tool_response(call, second)
    trajectory = run_agent_task(client(response, FINAL), task, server, "system")
    assert trajectory.error is not None
    assert trajectory.metadata["termination_kind"] == "invalid_model_response"
    assert trajectory.metadata["agent_protocol_error"]["normalized_response"] == response
    assert not world.list_entities("order")
    assert not world.audit_log
    assert [turn.role for turn in trajectory.turns] == ["system", "user"]


def test_exception_after_a_real_tool_action_preserves_request_and_unknown_outcome():
    world, server, task, call = fixture()
    actual = server.call_tool

    def lose_response(name, params):
        actual(name, params)
        raise RuntimeError("Synthetic response transport interruption")

    server.call_tool = lose_response
    trajectory = run_agent_task(client(tool_response(call), FINAL), task, server, "system")
    assert trajectory.error is not None
    assert trajectory.metadata["termination_kind"] == "tool_execution_error"
    failure = trajectory.metadata["tool_execution_error"]
    assert failure["tool_call_id"] == call["id"]
    assert failure["outcome"] == "unknown"
    assert len(world.list_entities("order")) == 1
    assert len(world.audit_log) == 1
    assert [turn.role for turn in trajectory.turns] == ["system", "user", "assistant"]
    assert trajectory.turns[-1].tool_calls == [call]


def test_completed_roundtrips_may_reuse_provider_ids_without_becoming_ambiguous():
    world, server, task, call = fixture()
    trajectory = run_agent_task(
        client(tool_response(call), tool_response(call), FINAL), task, server, "system"
    )
    assert trajectory.error is None
    assert len(world.list_entities("order")) == 2
    assert len(world.audit_log) == 2
    assert (
        trajectory_completion(trajectory.to_dict()["turns"], trajectory.metadata, None)[0]
        == "complete"
    )


@pytest.mark.parametrize(
    "invalid", [float("nan"), float("inf"), {1: "value"}, ("tuple",), object()]
)
def test_non_json_arguments_fail_before_execution_and_remain_serializable(invalid):
    world, server, task, call = fixture()
    call["arguments"]["details"]["invalid"] = invalid
    trajectory = run_agent_task(client(tool_response(call)), task, server, "system")
    assert trajectory.error is not None
    assert trajectory.metadata["agent_protocol_error"]["capture_status"] == "unavailable"
    assert trajectory.metadata["agent_protocol_error"]["normalized_response"] is None
    assert not world.audit_log
    assert not world.list_entities("order")
    json.dumps(trajectory.to_dict(), allow_nan=False)


def test_cyclic_normalized_response_cannot_escape_runner():
    world, server, task, call = fixture()
    response = tool_response(call)
    response["cycle"] = response
    trajectory = run_agent_task(client(response), task, server, "system")
    assert trajectory.metadata["agent_protocol_error"]["capture_status"] == "unavailable"
    assert not world.audit_log
    json.dumps(trajectory.to_dict(), allow_nan=False)


@pytest.mark.parametrize("stage", ["dispatch", "serialize_response"])
def test_batch_interruption_retains_completed_sibling_and_skips_remaining_actions(stage):
    world, server, task, call = fixture()
    calls = [dict(deepcopy(call), id=f"call-{i}") for i in range(3)]
    actual = server.call_tool
    count = 0

    def interrupt_second(name, params):
        nonlocal count
        count += 1
        result = actual(name, params)
        if count == 2:
            if stage == "dispatch":
                raise RuntimeError("Synthetic post-action failure")
            result["unserializable"] = result
        return result

    server.call_tool = interrupt_second
    trajectory = run_agent_task(client(tool_response(*calls), FINAL), task, server, "system")
    assert count == 2
    assert len(world.list_entities("order")) == 2
    assert len(world.audit_log) == 2
    assert [turn.role for turn in trajectory.turns] == ["system", "user", "assistant", "tool"]
    assert trajectory.turns[-1].tool_call_id == "call-0"
    assert trajectory.metadata["tool_execution_error"]["tool_call_id"] == "call-1"
    assert trajectory.metadata["tool_execution_error"]["stage"] == stage
    assert trajectory.metadata["tool_execution_error"]["outcome"] == "unknown"
    json.dumps(trajectory.to_dict(), allow_nan=False)


def test_dispatch_and_client_mutation_cannot_rewrite_captured_request():
    _, server, task, call = fixture()
    expected = deepcopy(call)
    actual = server.call_tool

    def mutating_dispatch(name, params):
        result = actual(name, params)
        params["details"]["test_name"] = "SERVER-MUTATION"
        return result

    def chat(messages, tools):
        if len(messages) == 2:
            return tool_response(call)
        messages[2]["tool_calls"][0]["arguments"]["details"]["test_name"] = "CLIENT-MUTATION"
        call["arguments"]["details"]["test_name"] = "RETAINED-ALIAS-MUTATION"
        return FINAL

    server.call_tool = mutating_dispatch
    trajectory = run_agent_task(SimpleNamespace(chat=chat), task, server, "system")
    assert trajectory.error is None
    assert trajectory.turns[2].tool_calls == [expected]


@pytest.mark.parametrize("failure", ["malformed_model", "lost_tool_response"])
def test_real_orchestrator_saves_partial_execution_as_ungraded_and_resumes_immutably(
    monkeypatch, tmp_path, failure
):
    from healthcraft.llm import orchestrator as orch
    from healthcraft.llm.review_context import validate_review_context
    from healthcraft.trajectory import Trajectory

    world, server, task, call = fixture()
    task = replace(
        task,
        criteria=(
            {
                "id": "C1",
                "assertion": "Created synthetic order",
                "verification": "world_state",
                "dimension": "clinical_completeness",
                "check": "audit_log contains call to createClinicalOrder",
            },
        ),
    )
    actual = server.call_tool
    if failure == "lost_tool_response":

        def lose_response(name, params):
            actual(name, params)
            raise RuntimeError("Synthetic lost response after persistence")

        server.call_tool = lose_response
    model = client(tool_response(call), None)
    monkeypatch.setattr(orch, "create_client", lambda *a, **kw: model)
    monkeypatch.setattr(orch, "load_tasks", lambda _, **kwargs: [task])
    monkeypatch.setattr(orch, "_load_system_prompt", lambda _: "system")
    monkeypatch.setattr(orch, "environment_digest", lambda _: "synthetic-protocol-test")
    monkeypatch.setattr(orch.WorldSeeder, "seed_world", lambda *a: world)
    monkeypatch.setattr(orch, "create_server", lambda _: server)
    monkeypatch.setattr(orch, "_load_overlay", lambda _: {})

    def run():
        return orch.run_frontier_evaluation(
            agent_model="gpt-test",
            agent_key="unused",
            judge_model=None,
            judge_key=None,
            trials=1,
            rubric_channel="v8",
            results_dir=tmp_path,
        )

    result = run()
    path = next(tmp_path.rglob("PROTOCOL-TEST*.json"))
    saved = Trajectory.load(path)
    assert len(world.list_entities("order")) == 1
    assert saved.turns[2].tool_calls == [call]
    assert len(saved.turns) == (4 if failure == "malformed_model" else 3)
    assert saved.metadata["grading_complete"] is False
    assert saved.metadata["ungraded_criteria"] == 1
    assert saved.criteria_results == []
    assert saved.reward == 0 and saved.passed is False
    assert validate_review_context(saved.to_dict())["capture_status"] == "complete"
    assert result["error_runs"] == 1
    assert result["total_passed"] == 0
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert run() == result
    assert {p: p.read_bytes() for p in before} == before
