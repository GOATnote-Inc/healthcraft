"""Verifiable-anchored training reward — one design from the whitepaper's
training-reward-ablations future-work list.

This module computes the *training* reward read by the RL loop (DAPO/GRPO).
It is **decoupled** from ``tasks.rubrics.compute_reward`` (Eq. 1), which is
the evaluation reward. The whitepaper notes Eq. 1 is not drop-in
training-safe (restraint criteria pass at 0.929 prevalence on the NEG smoke
pilot — a gameability an evaluation harness tolerates but a training loop
amplifies); this module implements **one** design responding to that
finding (verifiable anchoring + restraint folding into the safety gate +
judge abstention on supermajority-fail). Alternative responses exist and
have not been compared.

**Empirical training-safety validation — the soft-gate/hard-gate ablation,
restraint-criterion reweighting study, and reward-hacking probes that the
whitepaper names as future work — has NOT been performed.** A model trained
against this reward is a research artifact; held-out prospective
physician-blind validation is required before any deployment conversation.

**Formula** ::

    R = G_safety * clip( w_v * R_verifiable
                       + w_j * R_judge
                       + w_p * R_process,
                         clip_lo, clip_hi )

- ``G_safety ∈ {0, 1}`` — multiplicative hard gate. 1 iff every safety AND
  every restraint criterion is satisfied. Gate criteria are *verifiable
  only* (no judge in the gate); enforced by
  :func:`classify_criteria` when ``require_verifiable_safety=True``.
- ``R_verifiable`` — mean satisfaction over non-safety, non-restraint
  ``world_state``/``pattern`` criteria. The shaped, ungameable spine.
- ``R_judge`` — mean satisfaction over judge-needed criteria, with
  :attr:`EnsembleResult.ambiguous` triggering abstention (criterion dropped
  from the denominator). If every judge criterion abstains, the judge term
  is omitted and ``w_j`` is folded into ``w_v``.
- ``R_process`` — small, capped process bonus from ``process_signals``.
  Empty until PR-B (WS-5) lands the signals (idempotency-key use,
  retry-with-backoff, escalation, retry-budget overflow).

**Design properties (each addresses one item on the whitepaper's
training-safety future-work list; none has been empirically validated):**

1. The hard safety gate is verifiable-only — deterministic, free of
   LLM-judge noise. It is NOT literally ungameable: the whitepaper's
   restraint-prevalence finding is itself a case where a deterministic
   world-state criterion still behaves poorly as a training-time signal.
2. Restraint criteria carry NO shaped gradient — they enter only via the
   gate. This responds to the whitepaper's 0.929 finding, but the design
   has not been compared against alternatives (prevalence-discount,
   affirmative-criterion substitution).
3. The LLM judge is the residual, not the spine — and it abstains rather
   than guessing when judges disagree (consumes ``EnsembleJudge`` directly).
4. ``compute_reward`` and ``evaluate_task`` (Eq. 1) are not called — they
   remain byte-identical for evaluation. ``tests/test_evaluator_integrity/``
   continues to pass.
"""

from __future__ import annotations

from typing import Any

from healthcraft.llm.ensemble_judge import EnsembleJudge
from healthcraft.rl.config import RewardConfig
from healthcraft.rl.criteria_classifier import classify_criteria
from healthcraft.rl.types import TrainingRewardResult
from healthcraft.tasks.evaluator import (
    _parse_criteria,
    _verify_pattern,
    _verify_world_state,
)
from healthcraft.tasks.loader import Task
from healthcraft.tasks.rubrics import (
    Criterion,
    CriterionResult,
    VerificationMethod,
)
from healthcraft.trajectory import Trajectory
from healthcraft.world.state import WorldState


def _trajectory_to_agent_output(trajectory: Trajectory) -> dict[str, Any]:
    """Build the agent_output structure expected by the verifier helpers.

    Mirrors :func:`healthcraft.tasks.evaluator._build_agent_output` but
    operates on a live ``Trajectory`` instead of a serialised dict.
    """
    tool_calls: list[str] = []
    assistant_text: list[str] = []
    for turn in trajectory.turns:
        if turn.role == "assistant":
            for tc in turn.tool_calls:
                name = tc.get("name", "")
                if name:
                    tool_calls.append(name)
            if turn.content:
                assistant_text.append(turn.content)
    joined = " ".join(assistant_text)
    return {
        "tool_calls": tool_calls,
        "reasoning": joined,
        "output": joined,
    }


def _verify_for_training(
    criterion: Criterion,
    tool_calls: tuple[str, ...],
    world: WorldState,
    agent_output: dict[str, Any],
    ensemble: EnsembleJudge | None,
    trajectory_turns: list[dict[str, Any]],
    trajectory_id: str,
) -> tuple[CriterionResult, bool]:
    """Verify one criterion for the training-reward path.

    Returns ``(result, abstained)``. ``world_state``/``pattern`` criteria
    reuse the evaluator helpers verbatim — Eq. 1 evaluation semantics are
    preserved for those. ``llm_judge`` criteria call ``EnsembleJudge`` and
    abstain on ambiguous verdicts; when no ensemble is configured, every
    judge criterion abstains (so a CPU dry-run never hits an API).
    """
    if criterion.verification == VerificationMethod.WORLD_STATE:
        return (
            _verify_world_state(criterion, tool_calls, world, rubric_channel="v8"),
            False,
        )
    if criterion.verification == VerificationMethod.PATTERN:
        return _verify_pattern(criterion, agent_output), False
    if criterion.verification == VerificationMethod.LLM_JUDGE:
        if ensemble is None:
            return (
                CriterionResult(
                    criterion_id=criterion.id,
                    satisfied=False,
                    evidence="abstained (no ensemble judge configured)",
                ),
                True,
            )
        er = ensemble.evaluate_criterion(criterion, trajectory_turns, trajectory_id)
        if er.ambiguous:
            return (
                CriterionResult(
                    criterion_id=criterion.id,
                    satisfied=False,
                    evidence=f"abstained (ensemble ambiguous): {er.evidence}",
                ),
                True,
            )
        return (
            CriterionResult(
                criterion_id=criterion.id,
                satisfied=er.satisfied,
                evidence=er.evidence,
            ),
            False,
        )
    return (
        CriterionResult(
            criterion_id=criterion.id,
            satisfied=False,
            evidence=f"unknown verification method: {criterion.verification}",
        ),
        False,
    )


def compute_training_reward(
    task: Task,
    trajectory: Trajectory,
    world: WorldState,
    *,
    config: RewardConfig | None = None,
    ensemble_judge: EnsembleJudge | None = None,
    prevalence_stats: dict[str, float] | None = None,
    process_signals: dict[str, float] | None = None,
    trajectory_id: str | None = None,
) -> TrainingRewardResult:
    """Compute the training reward for one rollout. See module docstring.

    **Research artifact.** Empirical training-safety has not been validated.
    The output of this function is not evidence that a trained model is fit
    for clinical use; see ``docs/RL_COUPLING.md`` for the firewall.

    Args:
        task: The task definition.
        trajectory: The captured agent rollout.
        world: The world state at the end of the rollout (its audit log is
            the source of truth for ``world_state`` verification).
        config: Reward weights & thresholds. Defaults to :class:`RewardConfig`.
        ensemble_judge: Optional :class:`EnsembleJudge`. If None, every
            ``llm_judge`` criterion abstains and ``R_judge`` collapses.
        prevalence_stats: Optional per-criterion pass-prevalence map; high-
            prevalence criteria are reclassified as restraint.
        process_signals: Optional dict of process bonuses/penalties (PR-B
            populates this). Summed and clipped to
            ``[-cap, +cap]`` where ``cap = config.process_bonus_cap``.
        trajectory_id: Stable identifier for :class:`EnsembleJudge`'s
            disk cache. Defaults to ``"{task.id}:{seed}:{model}"``.

    Returns:
        A :class:`TrainingRewardResult` with the scalar ``reward`` and the
        decomposition the anti-Goodhart canaries read.
    """
    cfg = config or RewardConfig()
    criteria_objs = _parse_criteria(task.criteria)
    partition = classify_criteria(
        criteria_objs,
        prevalence_stats=prevalence_stats,
        restraint_prevalence_threshold=cfg.restraint_prevalence_threshold,
        require_verifiable_safety=cfg.require_verifiable_safety,
    )

    agent_output = _trajectory_to_agent_output(trajectory)
    tool_calls = tuple(agent_output["tool_calls"])
    traj_turns = [
        {"role": t.role, "content": t.content, "tool_calls": list(t.tool_calls)}
        for t in trajectory.turns
    ]
    traj_id = trajectory_id or f"{task.id}:{trajectory.seed}:{trajectory.model}"

    evidence: dict[str, str] = {}

    # --- Safety gate: safety + restraint criteria, all verifiable ---
    safety_pass = True
    n_restraint_violated = 0
    for c in partition.safety:
        result, _ = _verify_for_training(
            c, tool_calls, world, agent_output, ensemble_judge, traj_turns, traj_id
        )
        evidence[c.id] = result.evidence
        if not result.satisfied:
            safety_pass = False
    for c in partition.restraint:
        result, _ = _verify_for_training(
            c, tool_calls, world, agent_output, ensemble_judge, traj_turns, traj_id
        )
        evidence[c.id] = result.evidence
        if not result.satisfied:
            n_restraint_violated += 1
            safety_pass = False

    if not safety_pass:
        return TrainingRewardResult(
            reward=0.0,
            safety_gate_passed=False,
            r_verifiable=0.0,
            r_judge=0.0,
            r_process=0.0,
            n_safety=len(partition.safety),
            n_verifiable=len(partition.verifiable),
            n_restraint=len(partition.restraint),
            n_restraint_violated=n_restraint_violated,
            n_judge_used=0,
            n_judge_abstained=0,
            evidence=evidence,
        )

    # --- R_verifiable: shaped term over non-safety, non-restraint criteria ---
    if partition.verifiable:
        v_satisfied = 0
        for c in partition.verifiable:
            result, _ = _verify_for_training(
                c, tool_calls, world, agent_output, ensemble_judge, traj_turns, traj_id
            )
            evidence[c.id] = result.evidence
            if result.satisfied:
                v_satisfied += 1
        r_verifiable = v_satisfied / len(partition.verifiable)
    else:
        r_verifiable = 0.0

    # --- R_judge: with abstention ---
    j_satisfied = 0
    j_total = 0
    n_judge_abstained = 0
    for c in partition.judged:
        result, abstained = _verify_for_training(
            c, tool_calls, world, agent_output, ensemble_judge, traj_turns, traj_id
        )
        evidence[c.id] = result.evidence
        if abstained:
            n_judge_abstained += 1
            continue
        j_total += 1
        if result.satisfied:
            j_satisfied += 1
    r_judge = j_satisfied / j_total if j_total > 0 else 0.0

    # --- R_process: capped sum of process signals (PR-B populates) ---
    if process_signals:
        raw = sum(process_signals.values())
        r_process = max(-cfg.process_bonus_cap, min(cfg.process_bonus_cap, raw))
    else:
        r_process = 0.0

    # --- Weighted combination with empty-term renormalisation ---
    w_v, w_j, w_p = cfg.w_verifiable, cfg.w_judge, cfg.w_process

    judge_term_empty = (not partition.judged) or (j_total == 0)
    verifiable_term_empty = not partition.verifiable

    if judge_term_empty and not verifiable_term_empty:
        # Fold w_j into w_v so the shaped reward range stays anchored.
        w_v = w_v + w_j
        w_j = 0.0
    elif verifiable_term_empty and not judge_term_empty:
        w_j = w_j + w_v
        w_v = 0.0
    elif verifiable_term_empty and judge_term_empty:
        # Only process remains (rare). Absorb both into w_p.
        w_p = w_p + w_v + w_j
        w_v = 0.0
        w_j = 0.0

    shaped = w_v * r_verifiable + w_j * r_judge + w_p * r_process
    reward = max(cfg.clip_lo, min(cfg.clip_hi, shaped))

    return TrainingRewardResult(
        reward=reward,
        safety_gate_passed=True,
        r_verifiable=r_verifiable,
        r_judge=r_judge,
        r_process=r_process,
        n_safety=len(partition.safety),
        n_verifiable=len(partition.verifiable),
        n_restraint=len(partition.restraint),
        n_restraint_violated=0,
        n_judge_used=j_total,
        n_judge_abstained=n_judge_abstained,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# slime adapter (lazy — slime is not a hard dependency)
# ---------------------------------------------------------------------------


async def reward_func(args: Any, sample: Any, **kwargs: Any) -> float:
    """slime-compatible reward function — invoked as ``--custom-rm-path``.

    slime hands us its ``Sample`` after the rollout completes. We expect
    ``sample.metadata`` to carry references populated by the rollout
    adapter (``healthcraft.rl.rollout.generate``, landing in WS-6):
    ``task``, ``trajectory``, ``world``, optionally ``reward_config``,
    ``ensemble_judge``, ``prevalence_stats``, ``process_signals``.

    Returns the scalar reward; the breakdown is logged via
    ``sample.metadata`` for instrumentation.
    """
    md = getattr(sample, "metadata", None) or {}
    task = md.get("task")
    trajectory = md.get("trajectory")
    world = md.get("world")
    if task is None or trajectory is None or world is None:
        return 0.0
    result = compute_training_reward(
        task,
        trajectory,
        world,
        config=md.get("reward_config") or RewardConfig(),
        ensemble_judge=md.get("ensemble_judge"),
        prevalence_stats=md.get("prevalence_stats"),
        process_signals=md.get("process_signals"),
    )
    # Surface the breakdown so instrumentation can read it without recomputing.
    try:
        md["_training_reward_result"] = result
    except TypeError:  # pragma: no cover — metadata is a frozen mapping
        pass
    return result.reward
