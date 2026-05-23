"""Anti-Goodhart instrumentation for the training loop (PR-D / WS-6).

Pure functions consumed by the slime training loop. Each one surfaces a
signal that — when it crosses a threshold — should halt training before
reward-hacking sets in. The whitepaper's Limitations section explicitly
names these as future-work probes; PR-D ships the probes themselves.

Signals:

- :func:`group_reward_variance` — DAPO dynamic-sampling: identify groups
  with zero reward variance (all-pass or all-fail) so the trainer can
  drop them. Without this, ~70% of groups can be degenerate in early
  training (Sign-Advantage paper, arXiv:2605.07689).

- :func:`prevalence_drift` — restraint-prevalence canary: if
  high-prevalence criteria drift further upward during training (the
  whitepaper's 0.929 NEG-smoke observation getting worse), the policy
  is gaming the structural-restraint criteria rather than learning
  generalised clinical judgement.

- :func:`judge_kappa_drift` — cross-judge agreement canary: if Cohen's
  kappa between two judges (e.g., GPT-5.4 and Claude Opus 4.7) drops
  during training, the policy has learned to exploit one judge's
  blind spots. Halt training and audit.

- :func:`kl_overoptimisation_signal` — reward-model overoptimisation
  canary (Gao et al. 2023): gold reward is hump-shaped vs
  KL(policy ‖ ref). When proxy reward keeps rising but a separate
  held-out eval score plateaus or falls, the peak is past.

These are pure functions over numpy-free Python — they consume training-
loop bookkeeping (lists of rewards, dicts of per-criterion stats) and
emit signed-float signals. The actual *halt* decision (threshold +
policy) lives in the slime launcher, not here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GroupVarianceStat:
    """One row of DAPO dynamic-sampling output."""

    variance: float
    mean: float
    is_degenerate: bool  # True iff variance == 0 (all-pass or all-fail)
    n: int


def group_reward_variance(group_rewards: list[float]) -> GroupVarianceStat:
    """Compute per-group reward variance for DAPO dynamic sampling.

    A group with ``variance == 0`` (all rollouts got the same reward —
    the all-pass or all-fail case) contributes **zero gradient** to
    GRPO/DAPO because the advantage is uniformly zero. The trainer
    should drop such groups; this signal identifies them.

    Args:
        group_rewards: The G reward scalars for one prompt (G=16 typical).

    Returns:
        A :class:`GroupVarianceStat` with variance, mean,
        ``is_degenerate`` (variance == 0), and group size ``n``.
    """
    n = len(group_rewards)
    if n == 0:
        return GroupVarianceStat(variance=0.0, mean=0.0, is_degenerate=True, n=0)
    mean = sum(group_rewards) / n
    var = sum((r - mean) ** 2 for r in group_rewards) / n
    return GroupVarianceStat(
        variance=var,
        mean=mean,
        is_degenerate=(var == 0.0),
        n=n,
    )


def degenerate_group_fraction(group_variances: list[GroupVarianceStat]) -> float:
    """Fraction of recent groups with zero reward variance.

    A value persistently > 0.5 is a red flag: half the rollouts are
    contributing no gradient. Either the task suite is too easy/hard for
    the current policy (need curriculum adjustment) or the reward is
    misshapen (need restraint reweighting). Either way, training is
    burning compute for no signal.
    """
    if not group_variances:
        return 0.0
    n_degen = sum(1 for g in group_variances if g.is_degenerate)
    return n_degen / len(group_variances)


def prevalence_drift(
    current: dict[str, float],
    baseline: dict[str, float],
) -> dict[str, float]:
    """Per-criterion pass-rate change vs a baseline.

    A positive drift on already-high-prevalence criteria (e.g., a
    restraint criterion baselined at 0.929 rising to 0.99) is the
    Goodhart signature: the policy is learning to satisfy criteria
    that didn't carry training signal in the first place, instead of
    improving on the criteria that do.

    Args:
        current: ``{criterion_id: current_pass_rate}`` (in [0,1]).
        baseline: ``{criterion_id: baseline_pass_rate}`` (in [0,1]).

    Returns:
        ``{criterion_id: drift}`` where drift = current − baseline.
        Criteria not in both dicts are silently omitted.
    """
    return {cid: current[cid] - baseline[cid] for cid in current if cid in baseline}


def restraint_inflation_signal(
    drifts: dict[str, float],
    baselines: dict[str, float],
    high_prevalence_threshold: float = 0.9,
) -> float:
    """Aggregate "are high-prevalence criteria getting more high-prevalence?"

    Returns the mean drift restricted to criteria whose baseline pass-rate
    exceeded ``high_prevalence_threshold``. Positive → restraint inflation
    (Goodhart in progress). Zero or negative → the policy is not gaming
    structural-restraint criteria.
    """
    high_prev = [cid for cid, b in baselines.items() if b >= high_prevalence_threshold]
    if not high_prev:
        return 0.0
    relevant = [drifts[c] for c in high_prev if c in drifts]
    return sum(relevant) / len(relevant) if relevant else 0.0


def cohens_kappa(votes_a: list[bool], votes_b: list[bool]) -> float:
    """Cohen's κ between two binary verdicts on the same items.

    Range: κ = 1 perfect agreement, κ = 0 chance-level agreement, κ < 0
    worse than chance. Per Landis & Koch: > 0.80 substantial, > 0.60
    moderate, > 0.40 fair.

    Raises:
        ValueError: If lists differ in length or are empty.
    """
    n = len(votes_a)
    if n == 0 or n != len(votes_b):
        raise ValueError(
            f"cohens_kappa requires equal-length non-empty lists; "
            f"got len(a)={n}, len(b)={len(votes_b)}"
        )
    agree = sum(1 for a, b in zip(votes_a, votes_b) if a == b)
    p_o = agree / n
    pa_true = sum(votes_a) / n
    pb_true = sum(votes_b) / n
    p_e = pa_true * pb_true + (1 - pa_true) * (1 - pb_true)
    if p_e == 1.0:
        # Both judges unanimous — κ undefined; report perfect agreement
        # iff they unanimously matched.
        return 1.0 if p_o == 1.0 else 0.0
    return (p_o - p_e) / (1.0 - p_e)


def judge_kappa_drift(
    paired_votes_now: list[tuple[bool, bool]],
    paired_votes_baseline: list[tuple[bool, bool]],
) -> dict[str, float]:
    """Compare cross-judge κ now vs at training start.

    A drop is the canonical reward-hacking canary: the policy has
    learned to exploit one judge's specific blind spots, so the
    judges agree less even on the SAME criteria. Halt training when
    drop exceeds threshold (e.g., −0.1 vs baseline).

    Args:
        paired_votes_now: ``[(judge_a_vote, judge_b_vote), ...]`` over
            the current eval probe.
        paired_votes_baseline: Same shape, at training start (or a
            fixed reference checkpoint).

    Returns:
        ``{"kappa_now": …, "kappa_baseline": …, "kappa_drift": now - baseline}``.
    """
    now_a, now_b = (list(x) for x in zip(*paired_votes_now)) if paired_votes_now else ([], [])
    base_a, base_b = (
        (list(x) for x in zip(*paired_votes_baseline)) if paired_votes_baseline else ([], [])
    )
    k_now = cohens_kappa(now_a, now_b) if paired_votes_now else 0.0
    k_baseline = cohens_kappa(base_a, base_b) if paired_votes_baseline else 0.0
    return {
        "kappa_now": k_now,
        "kappa_baseline": k_baseline,
        "kappa_drift": k_now - k_baseline,
    }


def kl_overoptimisation_signal(
    proxy_reward_curve: list[float],
    gold_reward_curve: list[float],
    window: int = 20,
) -> dict[str, float]:
    """Detect Gao-2023 reward-model overoptimisation: gold reward is
    hump-shaped vs proxy reward / KL. When proxy is still rising but
    gold is plateauing or falling, the peak is past — we are in the
    overoptimisation regime and should halt.

    The signal: slope of the last ``window`` points of each curve.
    Positive proxy slope + non-positive gold slope ⇒ overoptimisation.

    Args:
        proxy_reward_curve: Training-time reward (what GRPO optimises).
        gold_reward_curve: Held-out / human eval score (the ground truth
            we actually care about).
        window: Recent number of points to fit slope over.

    Returns:
        ``{"proxy_slope": …, "gold_slope": …, "overoptimising": bool}``.
    """

    def _slope(xs: list[float]) -> float:
        n = len(xs)
        if n < 2:
            return 0.0
        # Use only the last ``window`` points.
        ys = xs[-window:]
        m = len(ys)
        mean_x = (m - 1) / 2.0
        mean_y = sum(ys) / m
        num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(ys))
        denom = sum((i - mean_x) ** 2 for i in range(m))
        return num / denom if denom > 0 else 0.0

    proxy_slope = _slope(proxy_reward_curve)
    gold_slope = _slope(gold_reward_curve)
    return {
        "proxy_slope": proxy_slope,
        "gold_slope": gold_slope,
        "overoptimising": proxy_slope > 0 and gold_slope <= 0,
    }


# ---------------------------------------------------------------------------
# Aggregator (slime instrumentation hook reads this)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanaryReport:
    """Aggregate of all canary signals at one training step.

    The slime instrumentation hook collects component signals into this
    dataclass and writes one row per step to a JSONL file. The training
    runbook (docs/RL_RUNBOOK.md) names the threshold policy: any one of
    these going into the red is sufficient grounds to halt training.
    """

    step: int
    degenerate_group_fraction: float
    restraint_inflation: float
    kappa_drift: float
    overoptimising: bool
    notes: str = ""

    def any_red(
        self,
        *,
        max_degenerate_fraction: float = 0.5,
        max_restraint_inflation: float = 0.05,
        max_kappa_drop: float = 0.10,
    ) -> bool:
        """Return True iff any canary crosses its threshold.

        Default thresholds are conservative starting points; the runbook
        explains how to tune for a specific task suite.
        """
        if self.degenerate_group_fraction > max_degenerate_fraction:
            return True
        if self.restraint_inflation > max_restraint_inflation:
            return True
        if self.kappa_drift < -max_kappa_drop:
            return True
        if self.overoptimising:
            return True
        return False
