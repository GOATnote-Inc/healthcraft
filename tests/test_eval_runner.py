"""The legacy runner is explicit, immutable, unassessed simulation evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from healthcraft import eval_runner
from healthcraft.tasks.loader import load_task
from healthcraft.trajectory import is_unassessed_experiment
from healthcraft.world.state import WorldState


@pytest.fixture
def tasks_dir() -> Path:
    return Path(__file__).parents[1] / "configs/tasks"


@pytest.fixture
def sample_task(tasks_dir):
    return load_task(tasks_dir / "clinical_reasoning/task_001_the_mimic.yaml")


@pytest.fixture
def simple_task(sample_task):
    return replace(sample_task, expected_tools=("firstTool", "secondTool"))


@pytest.fixture
def fake_server(monkeypatch):
    class Server:
        def __init__(self):
            self.calls = []
            self.responses = [{"status": "ok", "data": {"value": None}}] * 2
            self.world_state = WorldState()

        def call_tool(self, name, params):
            self.calls.append((name, dict(params)))
            response = self.responses[(len(self.calls) - 1) % len(self.responses)]
            if isinstance(response, Exception):
                raise response
            return response

    server = Server()
    monkeypatch.setattr(eval_runner.WorldSeeder, "seed_world", lambda *args: WorldState())
    monkeypatch.setattr(eval_runner, "create_server", lambda world: server)
    return server


def capture(task, output, **kwargs):
    return eval_runner.evaluate_and_capture(task, kwargs.get("model", "simulated"), 42, 1, output)


def test_loads_base_prompt(sample_task):
    assert "Mercy Point" in eval_runner.load_system_prompt(sample_task)


@pytest.mark.parametrize("model", ["test-model", "ollama:anything", "gpt-5.5", "", None])
def test_named_model_rejected_before_execution_or_output(simple_task, fake_server, tmp_path, model):
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="simulated.*orchestrator"):
        capture(simple_task, output, model=model)
    assert not output.exists()
    assert fake_server.calls == []


def test_capture_is_unassessed_and_records_actual_requests_responses(
    simple_task, fake_server, tmp_path, monkeypatch
):
    import healthcraft.tasks.evaluator as evaluator

    def forbidden(*args, **kwargs):
        raise AssertionError("Simulation must never invoke a grader")

    monkeypatch.setattr(evaluator, "evaluate_task", forbidden)
    fake_server.responses = [
        {"status": "ok", "data": {"unknown": None}},
        {"status": "error", "code": "missing_field", "message": "Missing encounter_id"},
    ]
    traj = capture(simple_task, tmp_path / "capture")
    assert traj.model == "simulated"
    assert traj.reward is traj.passed is traj.safety_gate_passed is None
    assert traj.criteria_results == [] and traj.dimension_scores == {}
    assert is_unassessed_experiment(traj.to_dict())
    assert traj.metadata["ungraded_criteria"] == len(simple_task.criteria)
    assert traj.metadata["model_calls"] == 0
    assert traj.metadata["evaluation_mode"] == "simulation_diagnostic"
    assert traj.metadata["tool_errors"][0]["tool"] == "secondTool"
    assert fake_server.calls == [("firstTool", {}), ("secondTool", {})]
    requests = [t for t in traj.turns if t.tool_calls]
    responses = [t for t in traj.turns if t.role == "tool"]
    assert len(requests) == len(responses) == traj.total_tool_calls == 2
    for index, (request, response) in enumerate(zip(requests, responses)):
        assert request.tool_calls == [
            {
                "id": f"simulation-call-{index + 1}",
                "name": fake_server.calls[index][0],
                "params": {},
            }
        ]
        assert response.tool_call_id == request.tool_calls[0]["id"]
        assert json.loads(response.content) == fake_server.responses[index]
    saved = json.loads(next((tmp_path / "capture").rglob("*.json")).read_text())
    assert saved["reward"] is saved["passed"] is saved["safety_gate_passed"] is None


def test_later_exception_keeps_completed_and_pending_attempt_evidence(
    simple_task, fake_server, tmp_path
):
    simple_task = replace(simple_task, expected_tools=("firstTool", "secondTool", "thirdTool"))
    fake_server.responses = [{"status": "ok", "data": 1}, RuntimeError("tool crashed")]
    traj = capture(simple_task, tmp_path / "partial")
    assert "tool crashed" in traj.error
    assert traj.total_tool_calls == 2
    assert [name for name, _ in fake_server.calls] == ["firstTool", "secondTool"]
    assert len([t for t in traj.turns if t.role == "tool"]) == 1
    assert traj.turns[-1].tool_calls[0]["name"] == "secondTool"
    assert traj.metadata["failure_stage"] == "tool_execution"
    assert traj.metadata["tool_outcome"] == "unknown"
    assert traj.reward is traj.passed is traj.safety_gate_passed is None


def test_nonfinite_tool_return_is_not_written_as_invalid_json(simple_task, fake_server, tmp_path):
    fake_server.responses = [{"status": "ok", "data": float("nan")}]
    traj = capture(simple_task, tmp_path / "invalid-response")
    assert traj.error and traj.total_tool_calls == 1
    assert not [t for t in traj.turns if t.role == "tool"]
    assert traj.metadata["tool_outcome"] == "unknown"
    text = next((tmp_path / "invalid-response").rglob("*.json")).read_text()
    assert ": NaN" not in text


def test_real_fixture_smoke_retains_real_handler_errors(sample_task, tmp_path):
    traj = capture(sample_task, tmp_path / "real-smoke")
    assert traj.total_tool_calls == len(sample_task.expected_tools)
    assert len([t for t in traj.turns if t.role == "tool"]) == len(sample_task.expected_tools)
    assert traj.metadata["tool_errors"]
    assert traj.criteria_results == []
    assert traj.reward is traj.passed is traj.safety_gate_passed is None
    assert is_unassessed_experiment(traj.to_dict())


def test_capture_collision_refuses_before_another_tool_call(simple_task, fake_server, tmp_path):
    output = tmp_path / "capture"
    capture(simple_task, output)
    path = next(output.rglob("*.json"))
    before = path.read_bytes()
    calls = list(fake_server.calls)
    with pytest.raises(FileExistsError):
        capture(simple_task, output)
    assert path.read_bytes() == before and fake_server.calls == calls


def run(output, tasks_dir, **kwargs):
    return eval_runner.run_evaluation(
        task_filter=kwargs.get("task_filter", "CR-001"),
        model=kwargs.get("model", "simulated"),
        trials=kwargs.get("trials", 1),
        seed=kwargs.get("seed", 42),
        results_dir=output,
        tasks_dir=tasks_dir,
    )


def test_all_trials_include_setup_failure_and_null_score_logs(
    sample_task, tasks_dir, fake_server, monkeypatch, tmp_path
):
    def seed_world(seeder, path):
        if seeder.seed == 43:
            raise RuntimeError("seed setup unavailable")
        return WorldState()

    monkeypatch.setattr(eval_runner.WorldSeeder, "seed_world", seed_world)
    output = tmp_path / "run"
    summary = run(output, tasks_dir, trials=3)
    assert summary["scheduled_runs"] == summary["total_runs"] == 3
    assert summary["execution_error_runs"] == 1
    assert summary["pass_rate"] is summary["avg_reward"] is summary["safety_failures"] is None
    assert summary["total_passed"] is None and is_unassessed_experiment(summary)
    rows = [json.loads(line) for line in (output / "experiments.jsonl").read_text().splitlines()]
    assert len(rows) == 3
    assert [r["seed"] for r in rows] == [42, 43, 44]
    assert [bool(r["error"]) for r in rows] == [False, True, False]
    for row in rows:
        assert row["model"] == "simulated" and is_unassessed_experiment(row)
        assert row["reward"] is row["passed"] is row["safety_gate_passed"] is None
        assert (output / row["trajectory_path"]).is_file()
    assert json.loads((output / "summary.json").read_text()) == summary


def test_invalid_prompt_keeps_failed_trial_and_remaining_cohort(
    sample_task, fake_server, monkeypatch, tmp_path
):
    override = tmp_path / "invalid-prompt.txt"
    override.write_bytes(b"\xff")
    tasks = [
        replace(sample_task, id="SIM-001", expected_tools=()),
        replace(
            sample_task,
            id="SIM-002",
            expected_tools=(),
            system_prompt_override=str(override),
        ),
        replace(sample_task, id="SIM-003", expected_tools=()),
    ]
    monkeypatch.setattr(eval_runner, "_select_tasks", lambda *args: tasks)
    output = tmp_path / "prompt-failure"
    summary = run(output, tmp_path, task_filter="all")
    assert summary["scheduled_runs"] == summary["total_runs"] == 3
    assert summary["execution_error_runs"] == 1
    assert summary["tool_error_runs"] == 0
    rows = [json.loads(line) for line in (output / "experiments.jsonl").read_text().splitlines()]
    assert [row["task_id"] for row in rows] == [task.id for task in tasks]
    assert [bool(row["error"]) for row in rows] == [False, True, False]
    for row in rows:
        assert row["reward"] is row["passed"] is row["safety_gate_passed"] is None
        assert is_unassessed_experiment(row)
        assert (output / row["trajectory_path"]).is_file()
    failed = json.loads((output / rows[1]["trajectory_path"]).read_text())
    assert failed["metadata"]["failure_stage"] == "prompt_setup"
    assert failed["metadata"]["simulation_completed"] is False
    assert failed["system_prompt"] == "" and failed["turns"] == []
    assert "UnicodeDecodeError" in failed["error"]
    assert fake_server.calls == []
    assert json.loads((output / "summary.json").read_text()) == summary


@pytest.mark.parametrize("trials", [0, -1, True, 1.5, "1"])
def test_invalid_trials_create_no_output(tasks_dir, tmp_path, trials):
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="trials"):
        run(output, tasks_dir, trials=trials)
    assert not output.exists()


@pytest.mark.parametrize("seed", [True, None, "42", 1.5])
def test_invalid_seed_create_no_output(tasks_dir, tmp_path, seed):
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="seed"):
        run(output, tasks_dir, seed=seed)
    assert not output.exists()


def test_run_named_model_rejected_before_output(tasks_dir, tmp_path):
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="simulated.*orchestrator"):
        run(output, tasks_dir, model="gpt-5.5")
    assert not output.exists()


@pytest.mark.parametrize("selection", ["MISSING-999", "", " CR-001 "])
def test_invalid_selection_creates_no_output(tasks_dir, tmp_path, selection):
    output = tmp_path / "invalid"
    with pytest.raises(ValueError):
        run(output, tasks_dir, task_filter=selection)
    assert not output.exists()


def test_malformed_selected_task_not_silently_skipped(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "broken.yaml").write_text("id: broken\n")
    output = tmp_path / "invalid"
    with pytest.raises(ValueError):
        run(output, tasks, task_filter="all")
    assert not output.exists()


def test_existing_run_directory_including_empty_is_refused(tasks_dir, fake_server, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        run(output, tasks_dir)
    assert list(output.iterdir()) == [] and fake_server.calls == []


def test_main_explicit_simulation_help_and_rejects_named_model(capsys):
    with pytest.raises(SystemExit) as error:
        eval_runner.main(["--model", "gpt-5.5"])
    assert error.value.code == 2
    assert "simulated" in capsys.readouterr().err


@pytest.mark.parametrize("seed,trial", [(True, 1), ("42", 1), (42, 0), (42, True)])
def test_capture_validates_seed_trial_before_creating_parent(
    simple_task, fake_server, tmp_path, seed, trial
):
    output = tmp_path / "not-created"
    with pytest.raises(ValueError):
        eval_runner.evaluate_and_capture(simple_task, "simulated", seed, trial, output)
    assert not output.exists() and fake_server.calls == []


def test_duplicate_selected_ids_are_not_silently_collapsed(tasks_dir, tmp_path):
    tasks = tmp_path / "duplicates"
    tasks.mkdir()
    content = (tasks_dir / "clinical_reasoning/task_001_the_mimic.yaml").read_bytes()
    (tasks / "one.yaml").write_bytes(content)
    (tasks / "two.yml").write_bytes(content)
    with pytest.raises(ValueError, match="Duplicate"):
        run(tmp_path / "not-created", tasks, task_filter="all")
    assert not (tmp_path / "not-created").exists()


def test_second_run_preserves_summary_trajectory_and_log(tasks_dir, fake_server, tmp_path):
    output = tmp_path / "run"
    run(output, tasks_dir)
    before = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    calls = list(fake_server.calls)
    with pytest.raises(FileExistsError):
        run(output, tasks_dir)
    assert before == {
        str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()
    }
    assert calls == fake_server.calls


def test_cli_default_chooses_fresh_simulation_directory(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(eval_runner, "_RESULTS_DIR", tmp_path / "existing-results")
    selected = []

    def run_stub(task_filter, model, trials, seed, results_dir, tasks_dir):
        selected.append(results_dir)
        return {"execution_error_runs": 0, "tool_error_runs": 0, "model": model}

    monkeypatch.setattr(eval_runner, "run_evaluation", run_stub)
    assert eval_runner.main([]) == eval_runner.main([]) == 0
    assert selected[0] != selected[1]
    assert all(path.parent == tmp_path / "existing-results/simulations" for path in selected)
    assert not (tmp_path / "existing-results").exists()
    assert '"model": "simulated"' in capsys.readouterr().out
