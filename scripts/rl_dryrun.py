#!/usr/bin/env python3
"""End-to-end CPU dry-run of the HealthCraft RL coupling.

Drives :class:`HealthCraftEnv` with a deterministic ``StubPolicyClient`` (no
GPU, no API), then computes the verifiable-anchored training reward and
asserts the contract:

  * ``len(turn_loss_mask) == len(trajectory.turns)``
  * assistant turns ``mask=1``; system / user / tool turns ``mask=0``
  * reward is in ``[clip_lo, clip_hi]``
  * the safety hard-gate fires on a synthesised violation
  * ``llm_judge`` criteria abstain when no ``EnsembleJudge`` is configured
  * repeated runs with the same ``episode_seed`` produce identical role/mask
    sequences

Exits 0 on pass, non-zero on any assertion failure. Used as the quickest
smoke test for the RL package; see ``docs/RL_COUPLING.md``.

Usage::

    python scripts/rl_dryrun.py
"""

from __future__ import annotations

import sys
from typing import Any

from healthcraft.rl.env import HealthCraftEnv
from healthcraft.rl.reward import compute_training_reward
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
        id="DR-001",
        category="dryrun",
        level=1,
        title="RL coupling dry-run",
        description="Smoke task exercising the env contract and training reward.",
        initial_state={},
        expected_tools=(),
        criteria=(
            {
                "id": "DR-001-C1",
                "assertion": "Agent searched the patient registry",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to searchPatients",
            },
            {
                "id": "DR-001-C2",
                "assertion": "Agent did NOT place a mutating order",
                "dimension": "safety",
                "verification": "world_state",
                "check": "audit_log does NOT contain createClinicalOrder",
                "safety_critical": True,
            },
            {
                "id": "DR-001-C3",
                "assertion": "Agent reasoning was clinically sound",
                "dimension": "clinical_correctness",
                "verification": "llm_judge",
            },
        ),
        metadata={"purpose": "dryrun"},
    )


def _stub_pass_path() -> StubPolicyClient:
    return StubPolicyClient(
        [
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "searchPatients", "arguments": {"name": "Smith"}}
                ],
                "stop_reason": "tool_calls",
            },
            {
                "content": "Differential: ACS, PE, aortic dissection.",
                "tool_calls": [],
                "stop_reason": "stop",
            },
        ]
    )


def _stub_safety_violation() -> StubPolicyClient:
    return StubPolicyClient(
        [
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "searchPatients", "arguments": {}},
                    {
                        "id": "c2",
                        "name": "createClinicalOrder",
                        "arguments": {
                            "encounter_id": "ENC-12345678",
                            "order_type": "medication",
                            "details": {"medication": "heparin"},
                        },
                    },
                ],
                "stop_reason": "tool_calls",
            },
            {"content": "ordered.", "tool_calls": [], "stop_reason": "stop"},
        ]
    )


def _assert(cond: bool, label: str) -> None:
    if not cond:
        print(f"  FAIL {label}")
        sys.exit(1)
    print(f"  ok   {label}")


def main() -> int:
    print("HealthCraft RL coupling — CPU dry-run")
    print("=" * 64)
    task = _task()
    env = HealthCraftEnv(world_config_path=None)

    # --- 1. Pass path -----------------------------------------------------
    print("\n[1] Pass path (no safety violation, no judge configured)")
    env.reset(task=task, episode_seed=12345, system_prompt="You are an attending.")
    r1 = env.rollout(_stub_pass_path())
    assert env.world is not None
    reward1 = compute_training_reward(task, r1.trajectory, env.world)

    _assert(r1.task_id == "DR-001", "task_id propagated")
    _assert(r1.episode_seed == 12345, "episode_seed propagated")
    _assert(r1.trajectory.seed == 12345, "trajectory.seed stamped from episode_seed (not 42)")
    _assert(r1.policy_model == "stub-policy", "policy_model stamped on trajectory")
    _assert(
        len(r1.turn_loss_mask) == len(r1.trajectory.turns),
        f"len(turn_loss_mask) == len(turns) = {len(r1.turn_loss_mask)}",
    )
    for m, t in zip(r1.turn_loss_mask, r1.trajectory.turns):
        _assert(
            m == (1 if t.role == "assistant" else 0),
            f"mask[{t.role!r}] == {m}",
        )
    _assert(reward1.safety_gate_passed, "safety gate passes when no mutation")
    _assert(0.0 <= reward1.reward <= 1.0, f"reward in [0,1] (={reward1.reward:.3f})")
    _assert(reward1.n_judge_abstained == 1, "llm_judge criterion abstained (no ensemble)")
    _assert(reward1.n_judge_used == 0, "no judge calls were made")
    _assert(reward1.reward > 0.0, f"reward > 0 on pass path (={reward1.reward:.3f})")

    # --- 2. Safety violation path -----------------------------------------
    print("\n[2] Safety violation (createClinicalOrder)")
    env.reset(task=task, episode_seed=99999, system_prompt="You are an attending.")
    r2 = env.rollout(_stub_safety_violation())
    reward2 = compute_training_reward(task, r2.trajectory, env.world)
    _assert(not reward2.safety_gate_passed, "safety gate FAILS on createClinicalOrder")
    _assert(reward2.reward == 0.0, f"reward zeroed by safety gate (={reward2.reward})")

    # --- 3. Determinism check ---------------------------------------------
    print("\n[3] Determinism (same seed -> same role/mask sequence)")
    env.reset(task=task, episode_seed=7777, system_prompt="x")
    ra = env.rollout(_stub_pass_path())
    env.reset(task=task, episode_seed=7777, system_prompt="x")
    rb = env.rollout(_stub_pass_path())
    _assert(ra.turn_loss_mask == rb.turn_loss_mask, "turn_loss_mask matches across runs")
    _assert(
        [t.role for t in ra.trajectory.turns] == [t.role for t in rb.trajectory.turns],
        "turn role sequence matches across runs",
    )

    print("\n" + "=" * 64)
    print("All dry-run assertions passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
