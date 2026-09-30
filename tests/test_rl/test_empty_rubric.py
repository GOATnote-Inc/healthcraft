"""Invalid RL rubrics must stop execution, not receive a training scalar."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from healthcraft.rl import env as env_module
from healthcraft.rl import reward as reward_module
from healthcraft.rl.config import RewardConfig
from healthcraft.rl.env import HealthCraftEnv
from healthcraft.rl.reward import compute_training_reward, reward_func
from healthcraft.tasks.loader import Task, load_task
from healthcraft.tasks.rubrics import compute_reward
from healthcraft.trajectory import Trajectory
from healthcraft.world.state import WorldState


def valid_task() -> Task:
    return Task(
        id="RL-EMPTY-GUARD",
        category="test",
        level=1,
        title="Synthetic retrieval",
        description="Retrieve patient records.",
        initial_state={},
        expected_tools=(),
        criteria=(
            {
                "id": "C1",
                "assertion": "Agent retrieved patient records",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to searchPatients",
            },
        ),
        metadata={},
    )


@pytest.fixture(params=["missing", "empty"])
def empty_task(request, tmp_path):
    path = tmp_path / "empty.yaml"
    text = (
        "id: RL-EMPTY\ncategory: test\nlevel: 1\n"
        "title: Invalid rubric fixture\ndescription: No assessment defined.\n"
    )
    if request.param == "empty":
        text += "criteria: []\n"
    path.write_text(text)
    task = load_task(path)
    assert task.criteria == ()  # Lenient loading remains supported.
    return task


def trajectory():
    return Trajectory("RL-EMPTY", "offline", 42, "Synthetic test")


@pytest.mark.parametrize("signals", [None, {"idempotency": 1.0}])
def test_training_reward_rejects_invalid_rubric_without_a_scalar(empty_task, signals):
    with pytest.raises(ValueError, match="nonempty criteria"):
        compute_training_reward(empty_task, trajectory(), WorldState(), process_signals=signals)


def test_invalid_rubric_rejected_before_overlay_or_classifier(empty_task, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid rubric reached grading work")

    monkeypatch.setattr(reward_module, "_apply_overlay_to_task", forbidden)
    monkeypatch.setattr(reward_module, "classify_criteria", forbidden)
    with pytest.raises(ValueError, match="nonempty criteria"):
        compute_training_reward(
            empty_task, trajectory(), WorldState(), config=RewardConfig(rubric_channel="v10")
        )


@pytest.mark.parametrize("criteria", [None, {}, "not a rubric"])
def test_nonsequence_rubric_is_a_configuration_error(criteria):
    with pytest.raises(ValueError, match="nonempty criteria"):
        compute_training_reward(
            replace(valid_task(), criteria=criteria), trajectory(), WorldState()
        )


def test_slime_adapter_rejects_empty_rubric_without_reward_breakdown(empty_task):
    metadata = {
        "task": empty_task,
        "trajectory": trajectory(),
        "world": WorldState(),
        "process_signals": {"idempotency": 1.0},
    }
    before = dict(metadata)
    with pytest.raises(ValueError, match="nonempty criteria"):
        asyncio.run(reward_func(None, SimpleNamespace(metadata=metadata)))
    assert metadata == before
    assert "_training_reward_result" not in metadata


def test_slime_rejects_present_invalid_task_before_missing_metadata_fallback(empty_task):
    metadata = {"task": empty_task}
    with pytest.raises(ValueError, match="nonempty criteria"):
        asyncio.run(reward_func(None, SimpleNamespace(metadata=metadata)))
    assert set(metadata) == {"task"}


@pytest.mark.parametrize("configured_world", [False, True])
def test_reset_rejects_before_world_creation_or_preparation(
    empty_task, configured_world, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid rubric reached world reset work")

    env = HealthCraftEnv(world_config_path=Path("unused.yaml") if configured_world else None)
    monkeypatch.setattr(env_module, "WorldState", forbidden)
    monkeypatch.setattr(env_module, "WorldSeeder", forbidden)
    monkeypatch.setattr(env_module, "prepare_task_environment", forbidden)
    monkeypatch.setattr(env_module, "create_server", forbidden)
    with pytest.raises(ValueError, match="nonempty criteria"):
        env.reset(empty_task, 123, "new prompt")
    assert env.task is env.world is env.server is env.episode_seed is None
    assert env._system_prompt == ""


def test_invalid_reset_invalidates_episode_but_preserves_old_world(empty_task, monkeypatch):
    env = HealthCraftEnv()
    env.reset(valid_task(), 42, "prior prompt")
    old_world = env.world
    old_world.record_audit("searchPatients", {}, "ok")
    old_audit = deepcopy(old_world.audit_log)
    old_time = old_world.timestamp

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid rubric reached a new world or model call")

    monkeypatch.setattr(env_module, "WorldState", forbidden)
    monkeypatch.setattr(env_module, "run_agent_task", forbidden)
    with pytest.raises(ValueError, match="nonempty criteria"):
        env.reset(empty_task, 999, "new prompt")
    assert env.task is env.world is env.server is env.episode_seed is None
    assert env._system_prompt == "prior prompt"
    assert old_world.audit_log == old_audit and old_world.timestamp == old_time
    with pytest.raises(RuntimeError, match="reset"):
        env.rollout(SimpleNamespace())


def test_rollout_rechecks_mutated_criteria_before_any_policy_or_tool_call(monkeypatch):
    mutable = list(valid_task().criteria)
    env = HealthCraftEnv()
    env.reset(replace(valid_task(), criteria=mutable), 42, "Synthetic")
    env.task.criteria.clear()
    before = deepcopy(env.world.audit_log)

    def forbidden(*args, **kwargs):
        pytest.fail("Mutated empty rubric reached the policy")

    monkeypatch.setattr(env_module, "run_agent_task", forbidden)
    with pytest.raises(ValueError, match="nonempty criteria"):
        env.rollout(SimpleNamespace())
    assert env.world.audit_log == before


def test_valid_training_reward_and_slime_scalar_unchanged():
    task = valid_task()
    world = WorldState()
    world.record_audit("searchPatients", {}, "ok")
    traj = trajectory()
    result = compute_training_reward(task, traj, world, process_signals={"bonus": 1.0})
    assert result.reward == 1.0 and result.safety_gate_passed is True
    sample = SimpleNamespace(metadata={"task": task, "trajectory": traj, "world": world})
    assert asyncio.run(reward_func(None, sample)) == 1.0
    assert sample.metadata["_training_reward_result"].reward == 1.0


def test_low_level_empty_reward_and_missing_slime_metadata_remain_unchanged():
    assert compute_reward([], []) == 0.0
    assert asyncio.run(reward_func(None, SimpleNamespace(metadata={}))) == 0.0
