"""Review evidence must be captured at execution, never reconstructed later."""

from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from healthcraft.llm.review_context import (
    context_digest,
    freeze_review_context,
    seal_review_context,
    validate_review_context,
)
from healthcraft.tasks.loader import Task
from healthcraft.trajectory import Trajectory


def sample():
    task = Task(
        id="TEST-REVIEW",
        category="information_retrieval",
        level=1,
        title="Synthetic",
        description="Read the record",
        initial_state={"nested": [1]},
        expected_tools=(),
        criteria=(
            {
                "id": "C1",
                "assertion": "Read the record",
                "verification": "llm_judge",
                "dimension": "clinical_completeness",
            },
        ),
        metadata={},
    )
    draft = freeze_review_context(
        task,
        list(task.criteria),
        rubric_channel="v10",
        scenario_context={"encounter_id": "E1"},
        checkpoint_identity="checkpoint",
        grading_mode="benchmark",
    )
    traj = Trajectory(
        task_id=task.id,
        model="test",
        seed=42,
        system_prompt="System",
        rubric_channel="v10",
        metadata={
            "checkpoint_identity": "checkpoint",
            "scenario_context": {"encounter_id": "E1"},
            "agent_tool_definitions": [{"name": "read", "parameters": {}}],
        },
    )
    traj.add_turn("system", "System")
    traj.add_turn("user", "Read the record\nEncounter E1")
    traj.add_turn("assistant", "Read it")
    traj.metadata["review_context"] = seal_review_context(draft, traj)
    return task, draft, traj


def test_context_freezes_private_sources_and_exact_presented_evidence():
    task, draft, traj = sample()
    task.initial_state["nested"].append(2)
    task.criteria[0]["assertion"] = "Changed later"
    payload = validate_review_context(traj.to_dict())
    assert payload["task"]["initial_state"] == {"nested": [1]}
    assert payload["effective_criteria"][0]["assertion"] == "Read the record"
    assert payload["presented_user"] == "Read the record\nEncounter E1"
    assert payload["tool_definitions"] == traj.metadata["agent_tool_definitions"]
    draft["task"]["description"] = "Changed later"
    payload["task"]["description"] = "Caller mutation"
    assert validate_review_context(traj.to_dict())["task"]["description"] == "Read the record"


@pytest.mark.parametrize(
    "mutation",
    ["payload", "system", "user", "answer", "tool", "task", "channel", "checkpoint", "scenario"],
)
def test_stale_or_modified_evidence_is_rejected(mutation):
    _, _, traj = sample()
    data = traj.to_dict()
    if mutation == "payload":
        data["metadata"]["review_context"]["payload"]["task"]["description"] = "changed"
    elif mutation == "system":
        data["system_prompt"] = "changed"
    elif mutation in ("user", "answer"):
        data["turns"][1 if mutation == "user" else 2]["content"] = "changed"
    elif mutation == "tool":
        data["metadata"]["agent_tool_definitions"][0]["name"] = "changed"
    elif mutation == "task":
        data["task_id"] = "changed"
    elif mutation == "channel":
        data["rubric_channel"] = "v8"
    elif mutation == "checkpoint":
        data["metadata"]["checkpoint_identity"] = "changed"
    else:
        data["metadata"]["scenario_context"]["encounter_id"] = "changed"
    with pytest.raises(ValueError):
        validate_review_context(data)


def test_incomplete_capture_and_old_artifacts_are_not_backfilled():
    _, draft, traj = sample()
    del traj.metadata["agent_tool_definitions"]
    traj.metadata["review_context"] = seal_review_context(draft, traj)
    assert traj.metadata["review_context"]["payload"]["capture_status"] == "incomplete"
    with pytest.raises(ValueError, match="incomplete"):
        validate_review_context(traj.to_dict())
    del traj.metadata["review_context"]
    with pytest.raises(ValueError):
        validate_review_context(traj.to_dict())


def test_capture_completeness_is_distinct_from_execution_success():
    _, draft, traj = sample()
    traj.error = "Interrupted provider"
    traj.metadata["review_context"] = seal_review_context(draft, traj)
    assert validate_review_context(traj.to_dict())["capture_status"] == "complete"


def test_normalization_supports_loaded_yaml_dates_without_lossy_object_fallback():
    task, _, _ = sample()
    task.initial_state.update(date=date(2026, 1, 2), time=datetime(2026, 1, 2, tzinfo=timezone.utc))
    draft = freeze_review_context(
        task,
        list(task.criteria),
        rubric_channel="v8",
        scenario_context={},
        checkpoint_identity="x",
        grading_mode="benchmark",
    )
    assert draft["task"]["initial_state"]["date"] == "2026-01-02"
    assert draft["task"]["initial_state"]["time"] == "2026-01-02T00:00:00+00:00"
    for invalid in (object(), float("nan"), float("inf"), {1: "not a JSON key"}):
        with pytest.raises((ValueError, TypeError)):
            context_digest(invalid)


def test_digest_is_canonical_and_missing_fields_fail_closed():
    assert context_digest({"a": "é", "b": [1]}) == context_digest({"b": [1], "a": "é"})
    _, _, traj = sample()
    for field in ("task", "effective_criteria", "tool_definitions", "turns_sha256"):
        data = deepcopy(traj.to_dict())
        envelope = data["metadata"]["review_context"]
        del envelope["payload"][field]
        envelope["sha256"] = context_digest(envelope["payload"])
        with pytest.raises(ValueError):
            validate_review_context(data)


@pytest.mark.parametrize("criteria", [[], [{"id": "other"}], [{"id": "C1"}, {"id": "C1"}]])
def test_effective_rubric_cannot_drop_replace_or_duplicate_authored_opportunities(criteria):
    _, _, traj = sample()
    data = traj.to_dict()
    envelope = data["metadata"]["review_context"]
    envelope["payload"]["effective_criteria"] = criteria
    envelope["sha256"] = context_digest(envelope["payload"])
    with pytest.raises(ValueError):
        validate_review_context(data)


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("with_overlay", [False, True])
def test_real_agent_orchestrator_capture_uses_actual_interface_and_frozen_overlay(
    monkeypatch, tmp_path, interrupted, with_overlay
):
    from healthcraft.clinical_review import build_review_packet
    from healthcraft.llm import orchestrator as orch
    from healthcraft.world.state import WorldState

    task, _, _ = sample()
    seen = {}

    class Client:
        def chat(self, messages, tools):
            seen.update(messages=deepcopy(messages), tools=deepcopy(tools))
            # Even a caller retaining mutable aliases cannot alter the snapshot.
            tools[0]["description"] = "Caller mutation"
            task.criteria[0]["assertion"] = "Caller mutation"
            task.criteria[0]["check"] = "never-match"
            if interrupted:
                raise RuntimeError("Synthetic interruption")
            return {"content": "done", "tool_calls": [], "stop_reason": "stop"}

    monkeypatch.setattr(orch, "create_client", lambda *a, **kw: Client())
    monkeypatch.setattr(orch, "load_tasks", lambda _, **kwargs: [task])
    monkeypatch.setattr(orch, "_load_system_prompt", lambda _: "Actual system")
    monkeypatch.setattr(orch, "environment_digest", lambda _: "fixed-test-environment")
    monkeypatch.setattr(orch.WorldSeeder, "seed_world", lambda *a: WorldState())
    monkeypatch.setattr(
        orch,
        "_load_overlay",
        lambda _: {"C1": {"verification": "pattern", "check": "done"}} if with_overlay else {},
    )
    result = orch.run_frontier_evaluation(
        agent_model="gpt-test",
        agent_key="unused",
        judge_model="claude-test",
        judge_key=None,
        trials=1,
        rubric_channel="v10",
        results_dir=tmp_path,
    )
    path = next(tmp_path.rglob("TEST-REVIEW*.json"))
    traj = Trajectory.load(path)
    payload = validate_review_context(traj.to_dict())
    assert payload["presented_system"] == seen["messages"][0]["content"]
    assert payload["presented_user"] == seen["messages"][1]["content"]
    assert payload["tool_definitions"] == seen["tools"]
    assert payload["effective_criteria"][0]["verification"] == (
        "pattern" if with_overlay else "llm_judge"
    )
    if with_overlay:
        assert payload["effective_criteria"][0]["check"] == "done"
    assert payload["task"]["criteria"][0]["assertion"] == "Read the record"
    assert result["error_runs"] == int(interrupted)
    assert traj.reward == (1 if with_overlay and not interrupted else 0)
    manifest = build_review_packet(
        [path],
        tmp_path / "packet",
        protocol={
            "protocol_id": "unit-fixture",
            "version": "1",
            "purpose": "engineering_pilot",
            "sampling_plan": "One synthetic unit fixture",
            "eligibility_rule": "Fixture only",
        },
        reviewer_assignment={"reviewer_id": "unit-fixture", "role": "independent"},
    )
    assert manifest["sources"][0]["unassessed_experiment"] == (interrupted or not with_overlay)


@pytest.mark.parametrize("setup_failure", [False, True])
def test_profile_capture_never_enables_clinical_grading(monkeypatch, tmp_path, setup_failure):
    from pathlib import Path

    from healthcraft.llm import orchestrator as orch
    from healthcraft.tasks.loader import load_tasks
    from healthcraft.world.state import WorldState

    task = next(t for t in load_tasks(Path("configs/tasks")) if t.id == "CC-022")

    class Client:
        def chat(self, messages, tools):
            return {"content": "Synthetic completion", "tool_calls": [], "stop_reason": "stop"}

    monkeypatch.setattr(orch, "create_client", lambda *a, **kw: Client())
    monkeypatch.setattr(orch, "load_tasks", lambda _, **kwargs: [task])
    monkeypatch.setattr(orch, "_load_system_prompt", lambda _: "Synthetic profile test")
    monkeypatch.setattr(orch, "environment_digest", lambda _: "fixed-test-environment")
    monkeypatch.setattr(orch.WorldSeeder, "seed_world", lambda *a: WorldState())
    if setup_failure:

        def fail(*args):
            raise RuntimeError("Setup failure before a captured agent trace")

        monkeypatch.setattr(orch, "run_agent_task", fail)
    result = orch.run_frontier_evaluation(
        agent_model="gpt-test",
        agent_key="unused",
        judge_model=None,
        judge_key=None,
        trials=1,
        rubric_channel="v8",
        results_dir=tmp_path,
        scenario_profile="roster-observations/v1",
    )
    traj = Trajectory.load(next(tmp_path.rglob("CC-022*.json")))
    payload = traj.metadata["review_context"]["payload"]
    assert payload["grading_mode"] == "profile_diagnostic"
    assert traj.metadata["grading_complete"] is False
    assert traj.metadata["benchmark_score"] is None
    assert traj.criteria_results == []
    assert result["benchmark_score"] is None
    if setup_failure:
        assert payload["capture_status"] == "incomplete"
        with pytest.raises(ValueError, match="incomplete"):
            validate_review_context(traj.to_dict())
    else:
        assert validate_review_context(traj.to_dict())["capture_status"] == "complete"
