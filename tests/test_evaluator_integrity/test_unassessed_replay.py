"""Ungraded source projections must not acquire scores through older readers."""

import importlib.util
from pathlib import Path

import pytest

from healthcraft.tasks.evaluator import replay_from_trajectory
from healthcraft.tasks.loader import load_task

ROOT = Path(__file__).parents[2]


@pytest.fixture
def trajectory():
    return {
        "task_id": "CC-022",
        "model": "local-fixture",
        "category": "clinical_communication",
        "reward": 0.0,
        "passed": False,
        "safety_gate_passed": False,
        "turns": [],
        "criteria_results": [],
        "metadata": {"scenario_context": {"profile_version": "roster-observations/v1"}},
    }


@pytest.mark.parametrize("error", [None, "Synthetic environment failure"])
def test_benchmark_replay_rejects_unvalidated_observation_contract(trajectory, error):
    trajectory["error"] = error
    task = load_task(ROOT / "configs/tasks/clinical_communication/task_022_nurse_delegation.yaml")
    with pytest.raises(ValueError, match="[Uu]nassessed"):
        replay_from_trajectory(trajectory, task)


def test_v7_analysis_cannot_treat_profile_placeholders_as_model_failure(trajectory):
    spec = importlib.util.spec_from_file_location("analyze_v7", ROOT / "scripts/analyze_v7.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="[Uu]nassessed"):
        module.analyze_model([trajectory], "local-fixture")
