"""The native and RL interfaces must expose the authored task patient through tools."""

from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.environment import prepare_task_environment
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

ROOT = Path(__file__).parents[2]
PATIENT_TASK = ROOT / "configs/tasks/temporal_reasoning/task_017_tetanus_prophylaxis.yaml"
ROSTER_TASK = ROOT / "configs/tasks/clinical_communication/task_022_nurse_delegation.yaml"


def test_loader_retains_authored_sources_without_exposing_them_in_prompt():
    task = load_task(ROSTER_TASK)
    assert len(task.source_data["patients_requiring_action"]) == 4
    assert task.source_data["patients_requiring_action"][0]["bed"] == 3
    assert "MAP dropping to 58" not in task.description
    assert "patients_requiring_action" not in task.initial_state


def test_prepared_default_patient_is_retrievable_and_original_task_is_unchanged():
    task = load_task(PATIENT_TASK)
    before = deepcopy(task)
    world = WorldState()
    prepared, context = prepare_task_environment(world, task)
    server = create_server(world)
    patient = server.call_tool("getPatientHistory", {"patient_id": context["patient_id"]})
    encounter = server.call_tool("getEncounterDetails", {"encounter_id": context["encounter_id"]})
    assert patient["status"] == encounter["status"] == "ok"
    assert encounter["data"]["patient_id"] == patient["data"]["id"]
    assert "occupation: Retired teacher, avid gardener" in patient["data"]["social_history"]
    assert context["patient_id"] in prepared.description
    assert context["encounter_id"] in prepared.description
    assert task == before


def test_default_roster_task_does_not_silently_change_published_injection():
    task = load_task(ROSTER_TASK)
    world = WorldState()
    prepared, context = prepare_task_environment(world, task)
    assert prepared == task
    assert context == {}
    assert world.list_entities("patient") == {}
    assert world.list_entities("encounter") == {}


def test_unknown_profile_fails_before_world_mutation():
    world = WorldState()
    with pytest.raises(ValueError, match="profile"):
        prepare_task_environment(world, load_task(PATIENT_TASK), profile="invented/v1")
    assert world.list_entities("patient") == {}
    assert world.list_entities("encounter") == {}


def test_rl_reset_exposes_task_patient_without_manual_injection():
    from healthcraft.rl.env import HealthCraftEnv

    task = load_task(PATIENT_TASK)
    env = HealthCraftEnv()
    env.reset(task=task, episode_seed=42, system_prompt="Synthetic research task")
    patients = env.world.list_entities("patient")
    encounters = env.world.list_entities("encounter")
    assert len(patients) == len(encounters) == 1
    patient_id = next(iter(patients))
    result = create_server(env.world).call_tool("getPatientHistory", {"patient_id": patient_id})
    assert "occupation: Retired teacher, avid gardener" in result["data"]["social_history"]


def test_unvalidated_profile_rollout_cannot_be_used_as_training_reward():
    from types import SimpleNamespace

    from healthcraft.rl.env import HealthCraftEnv
    from healthcraft.rl.reward import RewardConfig, compute_training_reward
    from healthcraft.tasks.roster_profile import PROFILE_VERSION

    task = load_task(ROSTER_TASK)
    env = HealthCraftEnv()
    env.reset(task, 42, "Synthetic", scenario_profile=PROFILE_VERSION)
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: {
            "content": "Review pending",
            "tool_calls": [],
            "stop_reason": "stop",
        }
    )
    rollout = env.rollout(client)
    with pytest.raises(ValueError, match="profile"):
        compute_training_reward(
            task,
            rollout.trajectory,
            env.world,
            config=RewardConfig(require_verifiable_safety=False),
        )


def test_failed_rl_reset_cannot_reuse_the_previous_episode():
    from types import SimpleNamespace

    from healthcraft.rl.env import HealthCraftEnv

    env = HealthCraftEnv()
    task = load_task(PATIENT_TASK)
    env.reset(task, 42, "First episode")
    with pytest.raises(ValueError):
        env.reset(task, 43, "Invalid second episode", scenario_profile="unknown/v1")
    calls = []
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: (
            calls.append(args)
            or {"content": "Would reuse previous world", "tool_calls": [], "stop_reason": "stop"}
        )
    )
    with pytest.raises(RuntimeError, match="reset"):
        env.rollout(client)
    assert calls == []


def test_rl_profile_cannot_enable_unvalidated_physiology():
    from healthcraft.rl.env import HealthCraftEnv
    from healthcraft.tasks.roster_profile import PROFILE_VERSION

    env = HealthCraftEnv(dynamic_state_enabled=True)
    with pytest.raises(ValueError, match="dynamic"):
        env.reset(load_task(ROSTER_TASK), 42, "Synthetic", scenario_profile=PROFILE_VERSION)
    assert env.world is None
    assert env.server is None


def test_rl_trajectories_do_not_share_mutable_profile_context():
    from types import SimpleNamespace

    from healthcraft.rl.env import HealthCraftEnv
    from healthcraft.tasks.roster_profile import PROFILE_VERSION

    env = HealthCraftEnv()
    env.reset(load_task(ROSTER_TASK), 42, "Synthetic", scenario_profile=PROFILE_VERSION)
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: {
            "content": "Review pending",
            "tool_calls": [],
            "stop_reason": "stop",
        }
    )
    first = env.rollout(client)
    second = env.rollout(client)
    first.trajectory.metadata["scenario_context"]["roster"][0]["label"] = "Caller annotation"
    assert second.trajectory.metadata["scenario_context"]["roster"][0]["label"] == "Bed 3"
    third = env.rollout(client)
    assert third.trajectory.metadata["scenario_context"]["roster"][0]["label"] == "Bed 3"
