"""Opt-in source projections cannot inherit unvalidated benchmark grades."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from healthcraft.llm import orchestrator as orch
from healthcraft.tasks.loader import load_task
from healthcraft.tasks.roster_profile import PROFILE_VERSION
from healthcraft.trajectory import Trajectory
from healthcraft.world.state import WorldState

ROOT = Path(__file__).parents[2]


@pytest.fixture
def harness(monkeypatch, tmp_path):
    task = load_task(ROOT / "configs/tasks/clinical_communication/task_022_nurse_delegation.yaml")
    state = {"calls": 0, "task": task}
    monkeypatch.setattr(orch, "load_tasks", lambda _, **kwargs: [state["task"]])
    monkeypatch.setattr(orch, "create_client", lambda *args: SimpleNamespace(_model="test"))
    monkeypatch.setattr(orch.WorldSeeder, "seed_world", lambda *args: WorldState())
    monkeypatch.setattr(orch, "environment_digest", lambda _: "test-environment")

    def never_grade(*args, **kwargs):
        pytest.fail("Unvalidated scenario profile reached the historical benchmark grader")

    monkeypatch.setattr(orch, "evaluate_task", never_grade)
    monkeypatch.setattr(orch, "_merge_judge_verdicts", never_grade)

    def run_agent(client, prepared, server, prompt):
        state["calls"] += 1
        assert len(server.world_state.list_entities("patient")) == 4
        assert "Bed 3" in prepared.description
        trajectory = Trajectory(task_id=task.id, model="test", seed=42, system_prompt=prompt)
        trajectory.add_turn("assistant", "Source review pending.")
        trajectory.metadata["stop_reason"] = "stop"
        return trajectory

    monkeypatch.setattr(orch, "run_agent_task", run_agent)

    def run(**changes):
        options = dict(
            agent_model="ollama:fixture",
            agent_key="",
            judge_model=None,
            judge_key=None,
            trials=1,
            results_dir=tmp_path,
            scenario_profile=PROFILE_VERSION,
        )
        options.update(changes)
        return orch.run_frontier_evaluation(**options)

    return state, run, tmp_path


def test_profile_execution_and_resume_remain_ungraded_and_not_clinical_failure(harness):
    state, run, root = harness
    first = run()
    assert first["evaluation_mode"] == "profile_diagnostic"
    assert first["benchmark_score"] is None
    assert not first["benchmark_comparable"] and not first["grading_complete"]
    assert first["ungraded_criteria"] == len(state["task"].criteria)
    assert first["safety_not_assessed_runs"] == 1
    for metric in (
        "pass_rate",
        "avg_reward",
        "total_passed",
        "safety_failures",
        "safety_failures_excl_errors",
    ):
        assert first[metric] is None
    trajectory = Trajectory.load(next(root.rglob("CC-022*.json")))
    assert trajectory.criteria_results == []
    assert trajectory.metadata["scenario_context"]["profile_version"] == PROFILE_VERSION
    assert trajectory.metadata["grading_complete"] is False
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert run() == first
    assert state["calls"] == 1
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("failure", ["returned", "raised", "environment"])
def test_failed_profile_trial_preserves_unassessed_status(harness, monkeypatch, failure):
    state, run, root = harness

    def interrupted(*args):
        if failure == "raised":
            raise RuntimeError("Synthetic transport unavailable")
        return Trajectory(
            task_id=state["task"].id,
            model="test",
            seed=42,
            system_prompt="",
            error="Synthetic transport interrupted",
        )

    monkeypatch.setattr(orch, "run_agent_task", interrupted)
    if failure == "environment":

        def failed_seed(*args):
            raise RuntimeError("Synthetic seeding failure")

        monkeypatch.setattr(orch.WorldSeeder, "seed_world", failed_seed)
    summary = run()
    assert summary["error_runs"] == summary["safety_not_assessed_runs"] == 1
    assert summary["safety_failures"] is None
    trajectory = Trajectory.load(next(root.rglob("CC-022*.json")))
    assert trajectory.error is not None
    assert trajectory.metadata["scenario_context"]["profile_version"] == PROFILE_VERSION
    assert trajectory.metadata["grading_complete"] is False
    assert trajectory.metadata["benchmark_comparable"] is False
    assert trajectory.metadata["benchmark_score"] is None
    assert trajectory.metadata["expected_criteria_count"] == len(state["task"].criteria)
    from healthcraft.rl.reward import compute_training_reward

    with pytest.raises(ValueError, match="profile"):
        compute_training_reward(state["task"], trajectory, WorldState())
    assert run() == summary


@pytest.mark.parametrize("change", ["source", "profile"])
def test_profile_or_authored_source_change_rejects_cached_evidence(harness, change):
    state, run, root = harness
    run()
    options = {}
    if change == "source":
        state["task"].source_data["patients_requiring_action"][0]["summary"] += " Changed."
    else:
        options["scenario_profile"] = None
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert "error" in run(**options)
    assert state["calls"] == 1
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "settings",
    [{"judge_model": "ollama:judge"}, {"dynamic_state": True}, {"scenario_profile": "unknown/v1"}],
)
def test_unvalidated_profile_rejects_incompatible_modes_before_model_execution(harness, settings):
    state, run, _ = harness
    assert "error" in run(**settings)
    assert state["calls"] == 0


def test_cli_profile_does_not_auto_select_or_probe_a_hosted_judge(monkeypatch, tmp_path):
    import sys

    calls = {}
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrator",
            "--agent-model",
            "gpt-fixture",
            "--agent-key",
            "unused",
            "--scenario-profile",
            PROFILE_VERSION,
            "--tasks",
            "CC-022",
            "--results-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.delenv("HC_DYNAMIC_STATE", raising=False)
    monkeypatch.setattr(orch, "_api_preflight", lambda **kwargs: calls.update(preflight=kwargs))
    monkeypatch.setattr(
        orch, "run_frontier_evaluation", lambda **kwargs: calls.update(run=kwargs) or {}
    )
    orch.main()
    assert calls["preflight"]["judge_model"] is None
    assert calls["preflight"]["judge_key"] == ""
    assert calls["run"]["scenario_profile"] == PROFILE_VERSION
