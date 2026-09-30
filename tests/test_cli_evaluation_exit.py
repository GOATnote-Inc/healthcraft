"""Process success reports execution health, never clinical task performance."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from healthcraft import cli
from healthcraft.llm import orchestrator
from healthcraft.trajectory import Trajectory
from healthcraft.world.state import WorldState


@pytest.fixture
def public_evaluation(monkeypatch, capsys):
    """Exercise the public parser and exit handling without provider access."""
    monkeypatch.setattr(orchestrator, "_api_preflight", lambda **kwargs: None)

    def run(summary):
        monkeypatch.setattr(orchestrator, "run_frontier_evaluation", lambda **kwargs: summary)
        try:
            status = cli.main(["evaluate", "--agent-model", "ollama:installed-local"])
        except SystemExit as exc:
            status = exc.code
        captured = capsys.readouterr()
        assert json.loads(captured.out) == summary
        return status, captured.err

    return run


def test_captured_execution_errors_return_nonzero_and_preserve_summary(public_evaluation):
    summary = {
        "total_tasks": 1,
        "total_runs": 1,
        "error_runs": 1,
        "total_passed": 0,
        "pass_rate": 0.0,
        "grading_complete": False,
        "ungraded_criteria": 3,
        "results_dir": "/tmp/saved-run",
    }
    status, _ = public_evaluation(summary)
    assert status == 1


def test_top_level_rejection_is_printed_before_failure_exit(public_evaluation):
    summary = {"error": "Requested task IDs were not found: MISSING-001"}
    status, _ = public_evaluation(summary)
    assert status == 1


def test_completed_rubric_and_safety_failures_are_successful_execution(public_evaluation):
    summary = {
        "total_tasks": 1,
        "total_runs": 1,
        "error_runs": 0,
        "total_passed": 0,
        "pass_rate": 0.0,
        "avg_reward": 0.0,
        "safety_failures": 1,
        "grading_complete": True,
        "ungraded_criteria": 0,
    }
    status, _ = public_evaluation(summary)
    assert status == 0


@pytest.mark.parametrize("mode", ["local_diagnostic", "profile_diagnostic", "deterministic_only"])
def test_intentional_ungraded_runs_are_not_execution_errors(public_evaluation, mode):
    summary = {
        "evaluation_mode": mode,
        "total_tasks": 1,
        "total_runs": 1,
        "error_runs": 0,
        "grading_complete": False,
        "ungraded_criteria": 3,
        "pass_rate": None,
        "benchmark_score": None,
    }
    status, _ = public_evaluation(summary)
    assert status == 0


@pytest.fixture
def captured_evaluation(monkeypatch, tmp_path, capsys):
    """Run actual selection, capture, grading and resume with only inference stubbed."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "task.yaml").write_text(
        "id: EXEC-001\ncategory: clinical_reasoning\nlevel: 1\n"
        "title: Synthetic output check\ndescription: Emit the requested marker.\n"
        "criteria:\n  - id: EXEC-001-C01\n"
        "    assertion: Output includes the requested marker.\n"
        "    verification: pattern\n    dimension: documentation_quality\n"
        "    check: EXPECTED-MARKER\n"
    )
    output = tmp_path / "output"
    state = {"mode": "completed", "calls": 0}
    monkeypatch.delenv("HC_DYNAMIC_STATE", raising=False)
    monkeypatch.setattr(orchestrator, "_api_preflight", lambda **kwargs: None)
    monkeypatch.setattr(
        orchestrator, "create_client", lambda *args: SimpleNamespace(_model="offline-test")
    )
    monkeypatch.setattr(orchestrator, "environment_digest", lambda _: "offline-test-environment")
    monkeypatch.setattr(orchestrator.WorldSeeder, "seed_world", lambda *args: WorldState())

    def agent(client, task, server, prompt):
        state["calls"] += 1
        if state["mode"] == "raised":
            raise RuntimeError("Offline synthetic provider failure")
        trajectory = Trajectory(
            task_id=task.id, model="offline-test", seed=42, system_prompt=prompt
        )
        trajectory.add_turn("assistant", "Different text; requested marker absent.")
        if state["mode"] == "returned":
            trajectory.error = "Offline synthetic provider interruption"
        else:
            trajectory.metadata.update(stop_reason="stop", termination_kind="complete")
        return trajectory

    monkeypatch.setattr(orchestrator, "run_agent_task", agent)

    def run():
        try:
            status = cli.main(
                [
                    "evaluate",
                    "--agent-model",
                    "ollama:offline-test",
                    "--tasks",
                    "EXEC-001",
                    "--trials",
                    "1",
                    "--tasks-dir",
                    str(tasks),
                    "--results-dir",
                    str(output),
                ]
            )
        except SystemExit as exc:
            status = exc.code
        summary = json.loads(capsys.readouterr().out)
        saved = Trajectory.load(next(output.glob("trajectories/**/*.json")))
        return status, summary, saved

    return run, state, output


@pytest.mark.parametrize("mode", ["raised", "returned"])
def test_actual_captured_and_cached_errors_keep_failure_status_and_immutable_evidence(
    captured_evaluation, mode
):
    run, state, output = captured_evaluation
    state["mode"] = mode
    status, summary, trajectory = run()
    assert status == 1
    assert summary["error_runs"] == summary["total_runs"] == 1
    assert summary["grading_complete"] is False
    assert trajectory.error and trajectory.metadata["failure_stage"] == "agent"
    snapshot = {
        str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()
    }
    second_status, second_summary, _ = run()
    assert second_status == 1 and second_summary == summary
    assert state["calls"] == 1
    assert {
        str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()
    } == snapshot


def test_actual_completed_rubric_failure_exits_zero(captured_evaluation):
    run, state, _ = captured_evaluation
    status, summary, trajectory = run()
    assert state["calls"] == 1
    assert status == 0 and summary["error_runs"] == 0
    assert summary["total_runs"] == 1 and summary["total_passed"] == 0
    assert summary["grading_complete"] is True
    assert trajectory.error is None and trajectory.passed is False
    assert trajectory.criteria_results[0].satisfied is False
