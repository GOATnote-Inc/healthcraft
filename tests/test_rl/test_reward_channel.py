"""Training must apply the same temporal rubric channel as evaluation."""

from __future__ import annotations

import pytest

from healthcraft.rl.config import RewardConfig
from healthcraft.rl.reward import compute_training_reward
from healthcraft.tasks.loader import Task
from healthcraft.trajectory import Trajectory
from healthcraft.world.state import WorldState


@pytest.mark.parametrize("channel", ["v9", "v10", "v11"])
@pytest.mark.parametrize("safety_critical", [True, False])
@pytest.mark.parametrize("correct_order", [True, False])
def test_training_honors_temporal_channel(
    channel: str, safety_critical: bool, correct_order: bool
) -> None:
    task = Task(
        id="TRAIN-CHANNEL",
        category="temporal_reasoning",
        level=3,
        title="Synthetic sequencing task",
        description="Review history before discharge.",
        initial_state={},
        expected_tools=(),
        criteria=(
            {
                "id": "TRAIN-CHANNEL-C01",
                "assertion": "Agent reviewed history before discharge",
                "dimension": "temporal_sequencing",
                "verification": "world_state",
                "check": (
                    "audit_log contains call to getPatientHistory BEFORE "
                    "audit_log contains call to processDischarge"
                ),
                "safety_critical": safety_critical,
            },
            {
                "id": "TRAIN-CHANNEL-C02",
                "assertion": "Agent reviewed history",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getPatientHistory",
            },
        ),
        metadata={},
    )
    world = WorldState()
    names = ["getPatientHistory", "processDischarge"]
    if not correct_order:
        names.reverse()
    for name in names:
        world.record_audit(name, {}, "ok")
    trajectory = Trajectory(task_id=task.id, model="synthetic", seed=42, system_prompt="Test only")

    result = compute_training_reward(
        task, trajectory, world, config=RewardConfig(rubric_channel=channel)
    )

    expected_reward = 1.0 if correct_order else (0.0 if safety_critical else 0.5)
    assert result.reward == expected_reward
    assert result.safety_gate_passed is (correct_order or not safety_critical)
    assert "Temporal BEFORE" in result.evidence["TRAIN-CHANNEL-C01"]
