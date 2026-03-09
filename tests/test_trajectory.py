"""Tests for trajectory capture and experiment logging."""

from __future__ import annotations

import json
from pathlib import Path

from healthcraft.trajectory import (
    CriterionEvalResult,
    ExperimentEntry,
    ExperimentLog,
    Trajectory,
    TrajectoryTurn,
)


class TestTrajectoryTurn:
    def test_basic_turn(self) -> None:
        turn = TrajectoryTurn(role="user", content="Hello")
        assert turn.role == "user"
        assert turn.content == "Hello"
        assert turn.timestamp  # auto-set

    def test_turn_with_tool_calls(self) -> None:
        turn = TrajectoryTurn(
            role="assistant",
            content="Checking...",
            tool_calls=[{"name": "searchPatients", "params": {"query": "Smith"}}],
        )
        assert len(turn.tool_calls) == 1


class TestTrajectory:
    def test_create_trajectory(self) -> None:
        traj = Trajectory(
            task_id="CR-001",
            model="claude-opus-4-6",
            seed=42,
            system_prompt="You are an emergency physician.",
        )
        assert traj.task_id == "CR-001"
        assert traj.reward == 0.0
        assert traj.passed is False
        assert traj.timestamp

    def test_add_turns(self) -> None:
        traj = Trajectory(task_id="T1", model="test", seed=1, system_prompt="test")
        traj.add_turn("system", "You are a doctor.")
        traj.add_turn("user", "Patient presents with chest pain.")
        traj.add_turn(
            "assistant",
            "Ordering ECG.",
            tool_calls=[{"name": "createClinicalOrder", "params": {}}],
        )
        assert len(traj.turns) == 3
        assert traj.total_tool_calls == 1

    def test_set_results(self) -> None:
        traj = Trajectory(task_id="T1", model="test", seed=1, system_prompt="test")
        traj.set_results(
            criteria_results=[
                CriterionEvalResult(id="C1", satisfied=True, evidence="found"),
                CriterionEvalResult(id="C2", satisfied=False, evidence="not found"),
            ],
            reward=0.5,
            passed=False,
            safety_gate_passed=True,
            dimension_scores={"safety": 1.0, "clinical_completeness": 0.5},
        )
        assert traj.reward == 0.5
        assert len(traj.criteria_results) == 2
        assert traj.dimension_scores["safety"] == 1.0

    def test_to_json(self) -> None:
        traj = Trajectory(task_id="T1", model="test", seed=1, system_prompt="test")
        traj.add_turn("user", "Hello")
        j = traj.to_json()
        data = json.loads(j)
        assert data["task_id"] == "T1"
        assert len(data["turns"]) == 1

    def test_save_and_load(self, tmp_path: Path) -> None:
        traj = Trajectory(task_id="T1", model="test", seed=42, system_prompt="prompt")
        traj.add_turn("user", "test content")
        traj.set_results(
            criteria_results=[CriterionEvalResult(id="C1", satisfied=True)],
            reward=1.0,
            passed=True,
            safety_gate_passed=True,
            dimension_scores={"safety": 1.0},
        )

        path = tmp_path / "traj.json"
        traj.save(path)
        assert path.exists()

        loaded = Trajectory.load(path)
        assert loaded.task_id == "T1"
        assert loaded.reward == 1.0
        assert loaded.passed is True
        assert len(loaded.turns) == 1
        assert len(loaded.criteria_results) == 1

    def test_save_creates_directories(self, tmp_path: Path) -> None:
        traj = Trajectory(task_id="T1", model="test", seed=1, system_prompt="test")
        path = tmp_path / "a" / "b" / "c" / "traj.json"
        traj.save(path)
        assert path.exists()


class TestExperimentLog:
    def test_append_and_load(self, tmp_path: Path) -> None:
        log_path = tmp_path / "experiments.jsonl"
        log = ExperimentLog(log_path)

        entry = ExperimentEntry(
            task_id="CR-001",
            model="test",
            seed=42,
            reward=0.75,
            passed=False,
            safety_gate_passed=True,
            total_tool_calls=5,
            duration_seconds=1.2,
            trajectory_path="trajectories/CR-001_test_42_t1.json",
        )
        log.append(entry)

        entries = log.load_all()
        assert len(entries) == 1
        assert entries[0].task_id == "CR-001"
        assert entries[0].reward == 0.75

    def test_multiple_appends(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "exp.jsonl")
        for i in range(5):
            entry = ExperimentEntry(
                task_id=f"T-{i:03d}",
                model="test",
                seed=42 + i,
                reward=i / 4.0,
                passed=i == 4,
                safety_gate_passed=True,
                total_tool_calls=i,
                duration_seconds=0.1 * i,
                trajectory_path=f"t_{i}.json",
            )
            log.append(entry)
        assert len(log.load_all()) == 5

    def test_from_trajectory(self) -> None:
        traj = Trajectory(task_id="CR-001", model="test", seed=42, system_prompt="")
        traj.reward = 0.8
        traj.passed = False
        traj.safety_gate_passed = True
        traj.total_tool_calls = 7
        traj.duration_seconds = 2.5

        entry = ExperimentEntry.from_trajectory(traj, "path/to/traj.json")
        assert entry.task_id == "CR-001"
        assert entry.reward == 0.8
        assert entry.total_tool_calls == 7

    def test_empty_log(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "empty.jsonl")
        assert log.load_all() == []
