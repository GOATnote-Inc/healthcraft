"""HealthCraftEnv contract tests (no GPU, no live API)."""

from __future__ import annotations

from typing import Any

import pytest

from healthcraft.rl.env import HealthCraftEnv
from healthcraft.tasks.loader import Task


class StubPolicyClient:
    """Deterministic ModelClient stub emitting a programmed script."""

    def __init__(self, script: list[dict[str, Any]], model: str = "stub-policy") -> None:
        self._script = list(script)
        self._idx = 0
        self._model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        if self._idx >= len(self._script):
            return {"content": "", "tool_calls": [], "stop_reason": "stop"}
        r = self._script[self._idx]
        self._idx += 1
        return r


def _task() -> Task:
    return Task(
        id="ENV-001",
        category="test",
        level=1,
        title="Env test",
        description="Env test description.",
        initial_state={},
        expected_tools=(),
        criteria=(),
        metadata={},
    )


def _stub() -> StubPolicyClient:
    return StubPolicyClient(
        [
            {
                "content": "thinking...",
                "tool_calls": [{"id": "c1", "name": "searchPatients", "arguments": {}}],
                "stop_reason": "tool_calls",
            },
            {"content": "done.", "tool_calls": [], "stop_reason": "stop"},
        ]
    )


def test_reset_then_rollout_returns_result():
    env = HealthCraftEnv(world_config_path=None)
    env.reset(task=_task(), episode_seed=12345, system_prompt="sys")
    r = env.rollout(_stub())

    assert r.task_id == "ENV-001"
    assert r.episode_seed == 12345
    assert r.trajectory.seed == 12345  # stamped from episode_seed, not 42
    assert r.policy_model == "stub-policy"  # stamped from client._model
    assert r.error is None


def test_loss_mask_aligns_with_turn_roles():
    env = HealthCraftEnv(world_config_path=None)
    env.reset(task=_task(), episode_seed=7, system_prompt="sys")
    r = env.rollout(_stub())

    assert len(r.turn_loss_mask) == len(r.trajectory.turns)
    for m, t in zip(r.turn_loss_mask, r.trajectory.turns):
        assert m == (1 if t.role == "assistant" else 0)


def test_rollout_before_reset_raises():
    env = HealthCraftEnv()
    with pytest.raises(RuntimeError, match="reset"):
        env.rollout(StubPolicyClient([]))


def test_determinism_same_seed_same_role_sequence():
    env = HealthCraftEnv(world_config_path=None)
    env.reset(task=_task(), episode_seed=42, system_prompt="x")
    r1 = env.rollout(_stub())
    env.reset(task=_task(), episode_seed=42, system_prompt="x")
    r2 = env.rollout(_stub())

    assert r1.turn_loss_mask == r2.turn_loss_mask
    assert [t.role for t in r1.trajectory.turns] == [t.role for t in r2.trajectory.turns]


def test_empty_world_audit_log_records_tool_calls():
    """With ``world_config_path=None`` the world is empty but the audit log
    still records the agent's tool calls — so verifiable criteria fire."""
    env = HealthCraftEnv(world_config_path=None)
    env.reset(task=_task(), episode_seed=1, system_prompt="x")
    env.rollout(_stub())
    assert env.world is not None
    tool_names = {entry.tool_name for entry in env.world.audit_log}
    assert "searchPatients" in tool_names
