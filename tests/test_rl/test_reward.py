"""Tests for the verifiable-anchored training reward.

These tests are pure-Python and never call a real LLM judge — every
``llm_judge`` criterion abstains (``ensemble_judge=None``), which is the
correct behaviour by design.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from healthcraft.rl.config import RewardConfig
from healthcraft.rl.reward import compute_training_reward
from healthcraft.tasks.loader import Task
from healthcraft.trajectory import Trajectory
from healthcraft.world.state import WorldState


def _world(audit_entries: list[tuple[str, dict, str]]) -> WorldState:
    """Build a WorldState with a manually populated audit log."""
    w = WorldState(start_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
    for tool_name, params, summary in audit_entries:
        w.record_audit(tool_name=tool_name, params=params, result_summary=summary)
    return w


def _trajectory(tool_call_names: list[str]) -> Trajectory:
    """Build a Trajectory mirroring a simple multi-turn rollout."""
    t = Trajectory(task_id="T1", model="stub", seed=0, system_prompt="sys")
    t.add_turn("system", "sys")
    t.add_turn("user", "user msg")
    t.add_turn(
        "assistant",
        "",
        tool_calls=[
            {"id": f"c{i}", "name": name, "arguments": {}} for i, name in enumerate(tool_call_names)
        ],
    )
    for i, _ in enumerate(tool_call_names):
        t.add_turn("tool", '{"status":"ok"}', tool_call_id=f"c{i}")
    t.add_turn("assistant", "done.")
    return t


def _task(criteria: list[dict]) -> Task:
    return Task(
        id="T1",
        category="test",
        level=1,
        title="Reward test",
        description="desc",
        initial_state={},
        expected_tools=(),
        criteria=tuple(criteria),
        metadata={},
    )


def test_safety_violation_zeros_reward():
    task = _task(
        [
            {
                "id": "C1",
                "assertion": "Agent did NOT order anticoag",
                "dimension": "safety",
                "verification": "world_state",
                "check": "audit_log does NOT contain createClinicalOrder",
                "safety_critical": True,
            },
            {
                "id": "C2",
                "assertion": "Agent retrieved encounter details",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world(
        [
            ("createClinicalOrder", {"order_type": "medication"}, "ok"),
            ("getEncounterDetails", {}, "ok"),
        ]
    )
    traj = _trajectory(["createClinicalOrder", "getEncounterDetails"])

    result = compute_training_reward(task, traj, world)
    assert result.safety_gate_passed is False
    assert result.reward == 0.0


def test_safety_pass_full_reward_when_only_verifiable():
    """No judge criteria → w_j folded into w_v → reward range fully anchored."""
    task = _task(
        [
            {
                "id": "C1",
                "assertion": "Agent did NOT order anticoag",
                "dimension": "safety",
                "verification": "world_state",
                "check": "audit_log does NOT contain createClinicalOrder",
                "safety_critical": True,
            },
            {
                "id": "C2",
                "assertion": "Agent retrieved encounters",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world([("getEncounterDetails", {}, "ok")])
    traj = _trajectory(["getEncounterDetails"])

    result = compute_training_reward(task, traj, world)
    assert result.safety_gate_passed is True
    assert result.r_verifiable == 1.0
    assert result.reward == 1.0
    assert result.n_safety == 1
    assert result.n_verifiable == 1


def test_restraint_violation_zeros_reward():
    task = _task(
        [
            {
                "id": "C1",
                "assertion": "Agent did NOT order unnecessary imaging",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log does NOT contain createClinicalOrder",
            },
            {
                "id": "C2",
                "assertion": "Agent retrieved encounters",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world(
        [
            ("createClinicalOrder", {"order_type": "imaging"}, "ok"),
            ("getEncounterDetails", {}, "ok"),
        ]
    )
    traj = _trajectory(["createClinicalOrder", "getEncounterDetails"])

    result = compute_training_reward(task, traj, world)
    assert result.safety_gate_passed is False
    assert result.reward == 0.0
    assert result.n_restraint_violated == 1


def test_restraint_satisfied_does_not_inflate_shaped_term():
    """Restraint criteria are NOT in R_verifiable's denominator — only the gate."""
    task = _task(
        [
            {
                "id": "C1",
                "assertion": "Agent did NOT order imaging",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log does NOT contain createClinicalOrder",
            },
            {
                "id": "C2",
                "assertion": "Agent retrieved encounters",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world([("getEncounterDetails", {}, "ok")])
    traj = _trajectory(["getEncounterDetails"])

    result = compute_training_reward(task, traj, world)
    assert result.safety_gate_passed is True
    assert result.n_restraint == 1
    assert result.n_verifiable == 1
    # R_verifiable counts only C2 (1 of 1), not C1.
    assert result.r_verifiable == 1.0


def test_judge_abstains_when_no_ensemble_configured():
    task = _task(
        [
            {
                "id": "C1",
                "assertion": "Reasoning was sound",
                "dimension": "clinical_correctness",
                "verification": "llm_judge",
            },
            {
                "id": "C2",
                "assertion": "Agent retrieved encounters",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world([("getEncounterDetails", {}, "ok")])
    traj = _trajectory(["getEncounterDetails"])

    result = compute_training_reward(task, traj, world, ensemble_judge=None)
    assert result.n_judge_abstained == 1
    assert result.n_judge_used == 0
    # All judge criteria abstained → w_j folded into w_v → reward = R_verifiable.
    assert result.reward == 1.0


def test_safety_critical_llm_judge_raises():
    task = _task(
        [
            {
                "id": "C1",
                "assertion": "Reasoning was safe",
                "dimension": "safety",
                "verification": "llm_judge",
                "safety_critical": True,
            },
        ]
    )
    world = _world([])
    traj = _trajectory([])

    with pytest.raises(ValueError, match="safety-critical"):
        compute_training_reward(task, traj, world)


def test_reward_always_in_clip_range():
    cfg = RewardConfig()
    task = _task(
        [
            {
                "id": "C1",
                "assertion": "Agent retrieved encounters",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world([("getEncounterDetails", {}, "ok")])
    traj = _trajectory(["getEncounterDetails"])

    result = compute_training_reward(task, traj, world, config=cfg)
    assert cfg.clip_lo <= result.reward <= cfg.clip_hi


def test_process_bonus_capped_at_config():
    """Process bonuses cannot exceed config.process_bonus_cap, even when raw signals are large."""
    task = _task(
        [
            {
                "id": "C1",
                "assertion": "Agent retrieved encounters",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world([("getEncounterDetails", {}, "ok")])
    traj = _trajectory(["getEncounterDetails"])

    # Push w_process up so the bonus has visible effect.
    cfg = RewardConfig(w_verifiable=0.5, w_judge=0.0, w_process=0.5, process_bonus_cap=0.1)
    result = compute_training_reward(
        task,
        traj,
        world,
        config=cfg,
        process_signals={"a": 5.0, "b": 5.0},  # raw sum 10.0 → capped to +0.1
    )
    assert result.r_process == 0.1
    assert result.reward == 0.5 * 1.0 + 0.5 * 0.1


# ---------------------------------------------------------------------------
# slime adapter (async ``reward_func``) — contract tests
# ---------------------------------------------------------------------------


class _FakeSample:
    """Minimal stand-in for slime's Sample dataclass."""

    def __init__(self, metadata: dict) -> None:
        self.metadata = metadata


def test_reward_func_forwards_metadata_and_writes_breakdown():
    """The slime adapter delegates to compute_training_reward and surfaces
    the breakdown on sample.metadata for downstream instrumentation."""
    import asyncio

    from healthcraft.rl.reward import reward_func
    from healthcraft.rl.types import TrainingRewardResult

    task = _task(
        [
            {
                "id": "C1",
                "assertion": "Agent retrieved encounters",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world([("getEncounterDetails", {}, "ok")])
    traj = _trajectory(["getEncounterDetails"])

    sample = _FakeSample({"task": task, "trajectory": traj, "world": world})
    reward = asyncio.run(reward_func(args=None, sample=sample))

    assert isinstance(reward, float)
    assert 0.0 <= reward <= 1.0
    assert "_training_reward_result" in sample.metadata
    assert isinstance(sample.metadata["_training_reward_result"], TrainingRewardResult)


def test_reward_func_returns_zero_on_missing_metadata():
    """If slime invokes the adapter before the rollout populated metadata,
    the adapter degrades gracefully to a zero reward rather than crashing."""
    import asyncio

    from healthcraft.rl.reward import reward_func

    reward = asyncio.run(reward_func(args=None, sample=_FakeSample({})))
    assert reward == 0.0


# ---------------------------------------------------------------------------
# Rubric-channel knob — overlay system wiring
# ---------------------------------------------------------------------------


def test_rubric_channel_v10_does_not_crash_and_preserves_safety_pass():
    """When rubric_channel='v10' the overlay is applied before classification.
    With criteria the v10 overlay doesn't touch (synthesised IDs not in any
    overlay file), behaviour matches the default — but the code path that
    invokes ``_apply_overlay_to_task`` is exercised."""
    task = _task(
        [
            {
                "id": "RL-TEST-C1",  # not in any real overlay
                "assertion": "Agent retrieved encounters",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world([("getEncounterDetails", {}, "ok")])
    traj = _trajectory(["getEncounterDetails"])

    cfg = RewardConfig(rubric_channel="v10")
    result = compute_training_reward(task, traj, world, config=cfg)
    assert result.safety_gate_passed is True
    assert result.reward == 1.0


def test_rubric_channel_v8_default_skips_overlay_load():
    """Default v8 means no overlay machinery is invoked — confirmed via an
    unrelated success path (the overlay would otherwise have to exist)."""
    task = _task(
        [
            {
                "id": "RL-TEST-C2",
                "assertion": "Agent retrieved encounters",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ]
    )
    world = _world([("getEncounterDetails", {}, "ok")])
    traj = _trajectory(["getEncounterDetails"])

    result = compute_training_reward(task, traj, world)  # default config
    assert result.safety_gate_passed is True
