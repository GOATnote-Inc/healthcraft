"""Seeded fault injection for the MCP tool layer (PR-B / WS-5).

Wraps ``HealthcraftServer.call_tool`` to inject simulated latency, transient
failures, and retry-budget enforcement as a training curriculum. All
randomness flows through a seeded ``random.Random`` so rollouts are
reproducible given the same ``FaultProfile.seed``.

Latency is **simulated** — never wall-clock — by advancing the WorldState
clock. Transient failures return ``service_unavailable`` (already in
``SIMULATOR_SIDE_ERROR_CODES`` so ``contains attempt at`` criteria still
credit the intent of a well-formed call).

The injector hard-caps retries per ``(tool_name, idempotency_key)`` so the
policy cannot game the env by spinning forever — the retry budget is part
of the profile, and overflow returns a non-retryable
``retry_budget_exceeded`` code.

This module touches no global state and never sleeps wall-clock; it is safe
to use inside ``HealthCraftEnv.rollout``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable

from healthcraft.world.state import WorldState


@dataclass(frozen=True)
class FaultProfile:
    """Fault-injection knobs. Defaults are zero-fault (no behaviour change).

    A curriculum stage is a particular set of these values; subsequent
    stages ramp them up. The intended progression (per plan §WS-5) is::

        stage 0  (warmup)    : all zeros — clean env
        stage 1  (transient) : transient_failure_rate ≈ 0.05
        stage 2  (latency)   : + latency_mean_minutes ≈ 1.0
        stage 3  (auth/rate) : + (future) authorization / rate-limit codes

    PR-B ships stages 0–2; auth/rate-limit codes are a follow-up.
    """

    # Seed for this rollout's RNG. Distinct rollouts use distinct seeds so
    # the fault distribution is reproducible per rollout but varies across
    # the training pool. ``0`` is the default; production training samples
    # seeds from a pool the same way ``HealthCraftEnv.reset(episode_seed=)``
    # does.
    seed: int = 0
    # Mean simulated latency per tool call, in minutes (advances the
    # WorldState clock; never wall-clock sleep).
    latency_mean_minutes: float = 0.0
    # Symmetric jitter around the mean, in minutes. Final latency is
    # clamped at 0 so the clock never moves backwards.
    latency_jitter_minutes: float = 0.0
    # Probability of a transient ``service_unavailable`` on any given call.
    transient_failure_rate: float = 0.0
    # Upper bound on the ``retry_after`` value returned with transient
    # failures (simulated seconds). Sampled uniformly in
    # ``[1, max_retry_after_seconds]``.
    max_retry_after_seconds: int = 5
    # Hard cap on retries per ``(tool_name, idempotency_key)``. After this
    # many attempts the injector returns ``retry_budget_exceeded`` (a non-
    # retryable, agent-side error code — NOT in ``SIMULATOR_SIDE_ERROR_CODES``,
    # so the agent does not get "attempt at" credit for flailing).
    retry_budget: int = 5

    def __post_init__(self) -> None:
        if not 0.0 <= self.transient_failure_rate <= 1.0:
            raise ValueError(
                f"transient_failure_rate must be in [0.0, 1.0]; got {self.transient_failure_rate}"
            )
        if self.latency_mean_minutes < 0.0:
            raise ValueError(f"latency_mean_minutes must be >= 0; got {self.latency_mean_minutes}")
        if self.latency_jitter_minutes < 0.0:
            raise ValueError(
                f"latency_jitter_minutes must be >= 0; got {self.latency_jitter_minutes}"
            )
        if self.max_retry_after_seconds < 1:
            raise ValueError(
                f"max_retry_after_seconds must be >= 1; got {self.max_retry_after_seconds}"
            )
        if self.retry_budget < 1:
            raise ValueError(f"retry_budget must be >= 1; got {self.retry_budget}")


class FaultInjector:
    """Wraps a tool dispatcher with seeded latency + transient failures.

    Usage::

        injector = FaultInjector(profile, world)
        original = server.call_tool
        server.call_tool = injector.wrap(original)
        # ...drive the agent loop; tool calls now flow through the injector.

    NOT thread-safe — each rollout worker holds its own instance.
    """

    def __init__(self, profile: FaultProfile, world: WorldState) -> None:
        self._profile = profile
        self._world = world
        self._rng = random.Random(profile.seed)
        # (tool_name, idempotency_key) -> attempt count for retry-budget enforcement.
        # Untracked when no idempotency_key is provided (retry budget only
        # bites on logically-identical retries).
        self._attempt_count: dict[tuple[str, str], int] = {}

    def wrap(
        self,
        dispatch: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
        """Return a wrapped dispatcher that injects faults before delegating.

        The wrapped callable has the same signature as
        :meth:`HealthcraftServer.call_tool`.
        """

        def _wrapped(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
            # 1. Retry-budget bookkeeping (only when an idempotency_key is
            # supplied — otherwise we cannot identify "logical retries").
            key = ""
            if isinstance(params, dict):
                raw = params.get("idempotency_key", "")
                if isinstance(raw, str):
                    key = raw
            bucket = (tool_name, key) if key else None
            if bucket is not None:
                self._attempt_count[bucket] = self._attempt_count.get(bucket, 0) + 1
                if self._attempt_count[bucket] > self._profile.retry_budget:
                    return {
                        "status": "error",
                        "code": "retry_budget_exceeded",
                        "message": (
                            f"Retry budget {self._profile.retry_budget} exhausted "
                            f"for {tool_name} / {key}; escalate or abandon."
                        ),
                    }

            # 2. Simulated latency. Advance the world clock by ``round(lat)``
            # minutes (the clock has minute resolution). Negative jitter is
            # clamped at zero.
            if self._profile.latency_mean_minutes > 0.0:
                lat = self._profile.latency_mean_minutes
                if self._profile.latency_jitter_minutes > 0.0:
                    lat += self._rng.uniform(
                        -self._profile.latency_jitter_minutes,
                        self._profile.latency_jitter_minutes,
                    )
                if lat > 0.0:
                    self._world.advance_time(int(round(lat)))

            # 3. Transient failure?
            if (
                self._profile.transient_failure_rate > 0.0
                and self._rng.random() < self._profile.transient_failure_rate
            ):
                retry_after = self._rng.randint(1, max(1, self._profile.max_retry_after_seconds))
                return {
                    "status": "error",
                    "code": "service_unavailable",
                    "message": "Transient backend failure; retry with backoff.",
                    "retry_after": retry_after,
                }

            # 4. Delegate to the real dispatch.
            return dispatch(tool_name, params)

        return _wrapped

    @property
    def profile(self) -> FaultProfile:
        return self._profile

    @property
    def attempt_count(self) -> dict[tuple[str, str], int]:
        """Snapshot of per-``(tool, key)`` attempt counter."""
        return dict(self._attempt_count)
