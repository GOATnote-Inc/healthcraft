"""HealthCraftEnv — the per-episode rollout surface for slime / verl.

This is the *environment side* of the Megatron + SGLang + GRPO coupling.
It owns:

- World seeding from an ``episode_seed`` (plan §WS-4) — the legacy
  hardcoded ``seed=42`` is overridden so training samples seeds from a
  pool and eval pins them.
- MCP server creation around the seeded world.
- The multi-turn rollout itself (reuses :func:`run_agent_task`).
- Per-turn loss-mask emission (assistant tokens → 1, env tokens → 0).

It does **not** own the reward — :func:`compute_training_reward` does.
Keeping rollout and reward distinct mirrors slime's
``--custom-generate-function-path`` / ``--custom-rm-path`` split and lets
the trainer interleave the two phases for throughput.

Closed-loop physiology and fault injection are plumbed via constructor
flags but their implementations land in PR-C (WS-3) and PR-B (WS-5).
PR-A leaves them off and ships the contract.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from healthcraft.llm.agent import ModelClient, run_agent_task
from healthcraft.mcp.faults import FaultInjector, FaultProfile
from healthcraft.mcp.server import HealthcraftServer, create_server
from healthcraft.rl.loss_mask import role_loss_mask
from healthcraft.rl.types import RolloutResult
from healthcraft.tasks.loader import Task
from healthcraft.world.seed import WorldSeeder
from healthcraft.world.state import WorldState

logger = logging.getLogger("healthcraft.rl.env")


class HealthCraftEnv:
    """One-episode rollout interface.

    Usage::

        env = HealthCraftEnv(world_config_path=Path("configs/world/mercy_point_v1.yaml"))
        env.reset(task=task, episode_seed=12345, system_prompt=prompt)
        result = env.rollout(policy_client)
        reward = compute_training_reward(task, result.trajectory, env.world)

    The instance is stateful for one episode at a time; call ``reset``
    before each new episode. Not thread-safe — each slime rollout worker
    holds its own instance.
    """

    def __init__(
        self,
        *,
        world_config_path: Path | None = None,
        dynamic_state_enabled: bool = False,
        fault_injection_enabled: bool = False,
        fault_profile: FaultProfile | None = None,
    ) -> None:
        """Args:
        world_config_path: World-seeding config (YAML/JSON). When
            ``None``, :meth:`reset` builds an *empty* WorldState — no
            entities, no encounters. The audit log still records tool
            calls, so verifiable criteria over the audit log fire
            normally. This is the form the CPU dry-run uses.
        dynamic_state_enabled: Forwarded to :class:`WorldState`. PR-C
            lands the closed-loop physiology that consumes it.
        fault_injection_enabled: Back-compat alias from PR-A. Now a
            no-op when ``fault_profile`` is given. When True without a
            profile, :meth:`reset` installs a zero-fault
            :class:`FaultProfile` and logs a deprecation note.
        fault_profile: PR-B / WS-5. Seeded latency + transient-failure
            injection (see :class:`mcp.faults.FaultProfile`). When given,
            :meth:`reset` wraps ``server.call_tool`` with a
            :class:`FaultInjector` for the episode lifetime.
        """
        self._world_config_path = world_config_path
        self._dynamic_state_enabled = dynamic_state_enabled
        self._fault_injection_enabled = fault_injection_enabled
        self._fault_profile = fault_profile
        self._task: Task | None = None
        self._world: WorldState | None = None
        self._server: HealthcraftServer | None = None
        self._fault_injector: FaultInjector | None = None
        self._system_prompt: str = ""
        self._episode_seed: int | None = None

    def reset(
        self,
        task: Task,
        episode_seed: int,
        system_prompt: str,
        *,
        start_time: datetime | None = None,
    ) -> None:
        """Initialise a fresh seeded world for a new episode."""
        self._task = task
        self._episode_seed = int(episode_seed)
        self._system_prompt = system_prompt

        if self._world_config_path is not None:
            seeder = WorldSeeder(seed=self._episode_seed)
            world = seeder.seed_world(self._world_config_path)
            # WorldSeeder.seed_world does not currently accept
            # ``dynamic_state_enabled``; thread it onto the returned
            # instance directly (regular instance attribute, not frozen).
            # PR-C (WS-3) will properly parameterise WorldSeeder.
            world._dynamic_state_enabled = self._dynamic_state_enabled  # noqa: SLF001
        else:
            world = WorldState(
                start_time=start_time or datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc),
                dynamic_state_enabled=self._dynamic_state_enabled,
            )

        self._world = world
        self._server = create_server(world)

        # PR-B / WS-5: wrap the dispatcher with FaultInjector when a profile
        # is provided. The wrapper installs at the instance level so existing
        # `server.call_tool` callers (including `run_agent_task`) flow through
        # it transparently. The profile's RNG is seeded; latency advances the
        # sim clock (no wall-clock sleep).
        profile = self._fault_profile
        if profile is None and self._fault_injection_enabled:
            logger.warning(
                "fault_injection_enabled=True is now an alias for a zero-"
                "fault FaultProfile() (no-op). Pass `fault_profile=` for "
                "real injection."
            )
            profile = FaultProfile()
        if profile is not None:
            injector = FaultInjector(profile, world)
            self._server.call_tool = injector.wrap(self._server.call_tool)  # type: ignore[method-assign]
            self._fault_injector = injector
        else:
            self._fault_injector = None

    def rollout(self, policy_client: ModelClient) -> RolloutResult:
        """Run one episode against ``policy_client``; return the result.

        The ``reward`` field of the returned :class:`RolloutResult` is 0.0
        — compute it via :func:`healthcraft.rl.reward.compute_training_reward`
        passing ``env.world``. This separation matches slime's
        rollout/reward function split.
        """
        if self._task is None or self._server is None or self._world is None:
            raise RuntimeError("HealthCraftEnv.reset(...) must be called before rollout()")
        if self._episode_seed is None:
            raise RuntimeError("episode_seed is unset; reset() did not record it")

        trajectory = run_agent_task(
            policy_client,
            self._task,
            self._server,
            self._system_prompt,
        )
        # Stamp the trajectory with our episode seed and policy model.
        # ``run_agent_task`` hard-codes ``seed=42`` and ``model="unknown"``;
        # both are corrected here.
        trajectory.seed = self._episode_seed
        trajectory.model = getattr(policy_client, "_model", "unknown")

        turn_mask = role_loss_mask(trajectory)

        return RolloutResult(
            task_id=self._task.id,
            episode_seed=self._episode_seed,
            policy_model=trajectory.model,
            trajectory=trajectory,
            turn_loss_mask=tuple(turn_mask),
            reward=0.0,
            error=trajectory.error,
            metadata={
                "n_turns": len(trajectory.turns),
                "total_tool_calls": trajectory.total_tool_calls,
                "duration_seconds": trajectory.duration_seconds,
            },
        )

    # ------------------------------------------------------------------
    # Read-only inspection (used by the training-reward path and tests)
    # ------------------------------------------------------------------

    @property
    def world(self) -> WorldState | None:
        """The world state from the most recent reset/rollout, or None."""
        return self._world

    @property
    def server(self) -> HealthcraftServer | None:
        """The MCP server bound to the current world, or None."""
        return self._server

    @property
    def task(self) -> Task | None:
        """The task being run (post-reset), or None."""
        return self._task

    @property
    def episode_seed(self) -> int | None:
        """The current episode seed, or None before the first reset."""
        return self._episode_seed

    @property
    def fault_injector(self) -> FaultInjector | None:
        """The active FaultInjector for the current episode, or None."""
        return self._fault_injector
