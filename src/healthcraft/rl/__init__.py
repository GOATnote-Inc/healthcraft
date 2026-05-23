"""HealthCraft RL coupling — environment contract and training reward.

This package exposes the surface a Megatron+SGLang+GRPO loop (slime / verl)
needs to drive HealthCraft as a reinforcement-learning environment:

- :class:`HealthCraftEnv` — episodic rollout interface.
- :class:`RolloutResult` — trajectory + per-turn/per-token loss mask.
- :func:`compute_training_reward` — verifiable-anchored, safety-gated reward,
  DECOUPLED from the Eq. 1 evaluation reward (which remains byte-identical).
- :func:`classify_criteria` — partitions criteria into safety / restraint /
  verifiable / judged.
- slime adapters :func:`generate` and :func:`reward_func` are lazy-imported;
  ``slime`` itself is not a hard dependency.

The training reward is intentionally distinct from Eq. 1. Eq. 1 supports
evaluation; the HealthCraft whitepaper (Section ``sec:limits``) proves it
is not drop-in training-safe — restraint-pattern criteria pass at 0.929
prevalence on the NEG smoke pilot. See ``docs/RL_COUPLING.md``.

A trained policy is a research artifact. A strong HealthCraft training score
does NOT constitute evidence of clinical readiness — held-out prospective
validation is required before any deployment conversation.
"""

from healthcraft.rl.config import RewardConfig
from healthcraft.rl.criteria_classifier import CriteriaPartition, classify_criteria
from healthcraft.rl.env import HealthCraftEnv
from healthcraft.rl.loss_mask import (
    role_loss_mask,
    serialize_tool_result,
    token_loss_mask,
)
from healthcraft.rl.reward import compute_training_reward
from healthcraft.rl.types import RolloutResult, TrainingRewardResult

__all__ = [
    "CriteriaPartition",
    "HealthCraftEnv",
    "RewardConfig",
    "RolloutResult",
    "TrainingRewardResult",
    "classify_criteria",
    "compute_training_reward",
    "role_loss_mask",
    "serialize_tool_result",
    "token_loss_mask",
]
