"""Public regrading paths reject empty authored rubrics before assessment."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from healthcraft.llm import evaluator
from healthcraft.tasks.loader import load_task
from healthcraft.trajectory import CriterionEvalResult, Trajectory

ROOT = Path(__file__).resolve().parents[2]


class ForbiddenJudge:
    _judge_model = "offline-no-judge-calls"

    def evaluate_criterion(self, *args, **kwargs):
        pytest.fail("Empty rubric must not reach a judge")


def write_task(directory, identifier, *, empty=None):
    directory.mkdir(parents=True, exist_ok=True)
    row = {
        "id": identifier,
        "category": "clinical_reasoning",
        "level": 1,
        "title": "Synthetic rubric boundary",
        "description": "Emit done.",
        "criteria": [
            {
                "id": identifier + "-C01",
                "assertion": "Said done",
                "verification": "pattern",
                "dimension": "documentation_quality",
                "check": "done",
            }
        ],
    }
    if empty == "missing":
        row.pop("criteria")
    elif empty == "empty":
        row["criteria"] = []
    path = directory / (identifier + ".yaml")
    path.write_text(yaml.safe_dump(row))
    return load_task(path)


def write_trajectory(directory, task, *, error=None):
    trajectory = Trajectory(task.id, "offline-fixture", 42, "Synthetic prompt", error=error)
    trajectory.add_turn("assistant", "done")
    if task.criteria:
        trajectory.criteria_results = [
            CriterionEvalResult(task.criteria[0]["id"], True, "Saved deterministic verdict")
        ]
        trajectory.reward = 1.0
        trajectory.passed = True
    path = directory / (task.id + "_offline_42_t1.json")
    trajectory.save(path)
    return trajectory, path


def snapshot(directory):
    return {
        str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()
    }


@pytest.fixture
def simple_eval(tmp_path, monkeypatch):
    name = "_empty_rubric_simple_eval"
    spec = importlib.util.spec_from_file_location(name, ROOT / "evals/healthcraft_simple_eval.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_PROJECT_ROOT", tmp_path)
    return module


@pytest.mark.parametrize("criteria", [(), [], None, {}])
def test_standalone_direct_rejects_unassessable_task(tmp_path, criteria):
    task = write_task(tmp_path / "tasks", "EMPTY-001")
    trajectory = Trajectory(task.id, "offline", 42, "")
    with pytest.raises(ValueError, match="requires nonempty criteria"):
        evaluator.evaluate_trajectory(
            trajectory, replace(task, criteria=criteria), ForbiddenJudge()
        )


@pytest.mark.parametrize("empty", ["empty", "missing"])
@pytest.mark.parametrize("error", [None, "synthetic interrupted execution"])
def test_standalone_file_rejects_before_grading_write(tmp_path, empty, error):
    tasks = tmp_path / "tasks"
    task = write_task(tasks, "EMPTY-001", empty=empty)
    _, path = write_trajectory(tmp_path / "originals", task, error=error)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match="requires nonempty criteria"):
        evaluator.evaluate_trajectory_file(
            path, ForbiddenJudge(), tasks_dir=tasks, output_dir=tmp_path / "new-grading"
        )
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("empty", ["empty", "missing"])
def test_standalone_cli_preflights_later_invalid_task_before_judge_or_writes(
    tmp_path, monkeypatch, capsys, empty
):
    tasks = tmp_path / "tasks"
    valid = write_task(tasks, "A-VALID")
    invalid = write_task(tasks, "Z-EMPTY", empty=empty)
    originals = tmp_path / "originals"
    write_trajectory(originals, valid)
    write_trajectory(originals, invalid)
    output = tmp_path / "existing-output"
    output.mkdir()
    (output / "evaluation_summary.json").write_text("preserve original summary")
    before = snapshot(tmp_path)
    calls = []
    monkeypatch.setattr(
        evaluator, "create_skeptical_judge", lambda *args: calls.append(args) or ForbiddenJudge()
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluator",
            "--trajectory-dir",
            str(originals),
            "--tasks-dir",
            str(tasks),
            "--output-dir",
            str(output),
            "--judge-key",
            "unused",
        ],
    )
    with pytest.raises(SystemExit) as caught:
        evaluator.main()
    assert caught.value.code == 2
    assert calls == [] and snapshot(tmp_path) == before
    captured = capsys.readouterr()
    assert "requires nonempty criteria" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("empty", ["empty", "missing"])
@pytest.mark.parametrize("limit", [None, 1])
def test_simple_eval_validates_authored_rubrics_before_any_replay(
    tmp_path, monkeypatch, simple_eval, empty, limit
):
    tasks = tmp_path / "configs/tasks"
    valid = write_task(tasks, "A-VALID")
    invalid = write_task(tasks, "Z-EMPTY", empty=empty)
    replay = tmp_path / "replay"
    write_trajectory(replay, valid)
    write_trajectory(replay, invalid)
    before = snapshot(tmp_path)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        pytest.fail("All selected authored rubrics must validate before any replay")

    monkeypatch.setattr("healthcraft.tasks.evaluator.replay_from_trajectory", forbidden)
    with pytest.raises(ValueError, match="requires nonempty criteria"):
        simple_eval._run_replay(
            [simple_eval._DatasetTask(t.id, t.category, ()) for t in (valid, invalid)],
            replay,
            rubric_channel="v8",
            trials=1,
            limit=limit,
        )
    assert calls == [] and snapshot(tmp_path) == before


@pytest.mark.parametrize("empty", ["empty", "missing"])
def test_simple_eval_cli_reports_configuration_error_without_success_summary(
    tmp_path, simple_eval, capsys, empty
):
    task = write_task(tmp_path / "configs/tasks", "EMPTY-001", empty=empty)
    replay = tmp_path / "replay"
    write_trajectory(replay, task)
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(json.dumps({"task_id": task.id}) + "\n")
    before = snapshot(tmp_path)
    status = simple_eval.main(
        [
            "--dataset",
            str(dataset),
            "--agent-model",
            "offline-fixture",
            "--replay-from",
            str(replay),
            "--rubric-channel",
            "v8",
        ]
    )
    assert status == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "requires nonempty criteria" in captured.err
    assert snapshot(tmp_path) == before


def test_valid_authored_task_ignores_unused_empty_dataset_rubric(tmp_path, simple_eval):
    task = write_task(tmp_path / "configs/tasks", "VALID-001")
    replay = tmp_path / "replay"
    write_trajectory(replay, task)
    before = snapshot(tmp_path)
    verdicts = simple_eval._run_replay(
        [simple_eval._DatasetTask(task.id, task.category, ())],
        replay,
        rubric_channel="v8",
        trials=1,
        limit=None,
    )
    assert len(verdicts) == 1 and verdicts[0].passed is True
    assert verdicts[0].reward == 1.0 and verdicts[0].safety_gate_passed is True
    assert snapshot(tmp_path) == before


def test_valid_standalone_regrade_preserves_saved_verdict_and_original(tmp_path):
    tasks = tmp_path / "tasks"
    task = write_task(tasks, "VALID-001")
    write_task(tasks, "UNSELECTED-EMPTY", empty="empty")
    _, path = write_trajectory(tmp_path / "originals", task)
    before = path.read_bytes()
    result = evaluator.evaluate_trajectory_file(
        path, ForbiddenJudge(), tasks_dir=tasks, output_dir=tmp_path / "new-grading"
    )
    assert result.passed is True and result.safety_gate_passed is True and result.reward == 1.0
    assert path.read_bytes() == before
