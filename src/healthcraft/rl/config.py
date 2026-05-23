"""Training-reward configuration.

Loaded from ``configs/rl/reward.yaml`` or instantiated with defaults. Frozen
so the running training process cannot mutate it mid-rollout.

This config governs ONLY
:func:`healthcraft.rl.reward.compute_training_reward`. The Eq. 1 evaluation
reward (``tasks/rubrics.py:compute_reward``) is untouched and unconfigured
by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RewardConfig:
    """Weights and thresholds for :func:`compute_training_reward`.

    Defaults are verifiable-dominant (``w_verifiable=0.8``, ``w_judge=0.2``)
    so the training signal leans on deterministic world-state checks (free
    of LLM-judge noise — though not literally ungameable; see the
    whitepaper's 0.929 restraint-prevalence finding). ``w_process`` is 0.0
    until PR-B (WS-5) lands the process signals (idempotency-key use,
    retry-with-backoff, escalation).
    """

    w_verifiable: float = 0.8
    w_judge: float = 0.2
    w_process: float = 0.0
    process_bonus_cap: float = 0.1
    # Criteria with measured pass-prevalence above this threshold are
    # classified as "restraint" — folded into the safety gate, excluded from
    # the shaped reward (see plan §WS-2). NEG smoke pilot observed 0.929.
    restraint_prevalence_threshold: float = 0.9
    # If True, any criterion marked ``safety_critical=True`` whose
    # verification is ``llm_judge`` raises an error at classification time.
    # No safety-critical decision may depend on a noisy judge.
    require_verifiable_safety: bool = True
    clip_lo: float = 0.0
    clip_hi: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "w_verifiable",
            "w_judge",
            "w_process",
            "process_bonus_cap",
            "restraint_prevalence_threshold",
            "clip_lo",
            "clip_hi",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0.0, 1.0]; got {value}")
        if self.clip_hi < self.clip_lo:
            raise ValueError(f"clip_hi ({self.clip_hi}) must be >= clip_lo ({self.clip_lo})")

    @classmethod
    def load(cls, path: Path | None = None) -> RewardConfig:
        """Load from a YAML file. Missing keys fall back to class defaults.

        If ``path`` is None, returns the all-defaults instance — useful for
        tests and the CPU dry-run.
        """
        if path is None:
            return cls()
        if not path.exists():
            raise FileNotFoundError(f"Reward config not found: {path}")
        try:
            import yaml
        except ImportError as exc:
            raise ImportError("PyYAML is required to load reward.yaml") from exc

        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)
