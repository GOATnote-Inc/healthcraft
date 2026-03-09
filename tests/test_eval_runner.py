"""Tests for the evaluation runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from healthcraft.eval_runner import evaluate_and_capture, load_system_prompt, run_evaluation
from healthcraft.tasks.loader import load_tasks


@pytest.fixture
def tasks_dir() -> Path:
    return Path(__file__).parents[1] / "configs" / "tasks"


@pytest.fixture
def sample_task(tasks_dir: Path):
    """Load the first available task."""
    tasks = load_tasks(tasks_dir)
    assert len(tasks) > 0, "No tasks found"
    return tasks[0]


class TestLoadSystemPrompt:
    def test_loads_base_prompt(self, sample_task) -> None:
        prompt = load_system_prompt(sample_task)
        assert len(prompt) > 0
        assert "Mercy Point" in prompt or "emergency" in prompt.lower()


class TestEvaluateAndCapture:
    def test_captures_trajectory(self, sample_task, tmp_path: Path) -> None:
        traj = evaluate_and_capture(
            task=sample_task,
            model="test-model",
            seed=42,
            trial=1,
            results_dir=tmp_path,
        )
        assert traj.task_id == sample_task.id
        assert traj.model == "test-model"
        assert traj.seed == 42
        assert traj.duration_seconds > 0
        assert len(traj.turns) >= 2  # system + user at minimum

    def test_trajectory_saved(self, sample_task, tmp_path: Path) -> None:
        evaluate_and_capture(
            task=sample_task,
            model="test-model",
            seed=42,
            trial=1,
            results_dir=tmp_path,
        )
        # Check trajectory file exists
        traj_dir = tmp_path / "trajectories" / sample_task.category
        assert traj_dir.exists()
        json_files = list(traj_dir.glob("*.json"))
        assert len(json_files) == 1


class TestRunEvaluation:
    def test_run_single_task(self, sample_task, tasks_dir: Path, tmp_path: Path) -> None:
        summary = run_evaluation(
            task_filter=sample_task.id,
            model="test",
            trials=1,
            seed=42,
            results_dir=tmp_path,
            tasks_dir=tasks_dir,
        )
        assert "error" not in summary
        assert summary["total_runs"] == 1
        assert summary["total_tasks"] == 1
        assert 0.0 <= summary["pass_rate"] <= 1.0
        assert 0.0 <= summary["avg_reward"] <= 1.0

    def test_run_multiple_trials(self, sample_task, tasks_dir: Path, tmp_path: Path) -> None:
        summary = run_evaluation(
            task_filter=sample_task.id,
            model="test",
            trials=3,
            seed=42,
            results_dir=tmp_path,
            tasks_dir=tasks_dir,
        )
        assert summary["total_runs"] == 3
        assert summary["trials"] == 3

    def test_experiment_log_created(self, sample_task, tasks_dir: Path, tmp_path: Path) -> None:
        run_evaluation(
            task_filter=sample_task.id,
            model="test",
            trials=2,
            seed=42,
            results_dir=tmp_path,
            tasks_dir=tasks_dir,
        )
        log_path = tmp_path / "experiments.jsonl"
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_summary_saved(self, sample_task, tasks_dir: Path, tmp_path: Path) -> None:
        run_evaluation(
            task_filter=sample_task.id,
            model="test",
            trials=1,
            seed=42,
            results_dir=tmp_path,
            tasks_dir=tasks_dir,
        )
        summary_path = tmp_path / "summary.json"
        assert summary_path.exists()

    def test_nonexistent_task(self, tasks_dir: Path, tmp_path: Path) -> None:
        summary = run_evaluation(
            task_filter="NONEXISTENT-999",
            model="test",
            trials=1,
            seed=42,
            results_dir=tmp_path,
            tasks_dir=tasks_dir,
        )
        assert "error" in summary
