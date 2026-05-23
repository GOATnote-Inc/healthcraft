"""Detect retry / idempotency patterns from the audit log → process bonuses.

PR-B / WS-5. The training reward's ``R_process`` term is a small, capped
bonus for behaviours we want the policy to internalise:

- Using idempotency keys when retrying mutations (safe-retry pattern).
- Letting the env dedup replays cleanly (key was correct, no double-apply).
- NOT retrying without a key (would risk duplicate clinical mutations).
- NOT flailing until the retry budget overflows.

This module scans the world's audit log (post-rollout) and emits a dict of
signed signals; :func:`healthcraft.rl.reward.compute_training_reward`
consumes it via the ``process_signals`` kwarg and clips the sum to
``config.process_bonus_cap``.

Detection is conservative: a retry is any mutating call whose
``(tool_name, params)`` signature (idempotency_key excluded) matches an
earlier audit entry. This works whether or not the agent used an
idempotency_key (which is the point — we want to penalise the no-key case).
"""

from __future__ import annotations

from typing import Any

from healthcraft.world.state import AuditEntry

_MUTATING_TOOL_NAMES = frozenset(
    name.lower()
    for name in (
        "createClinicalOrder",
        "create_clinical_order",
        "updateTaskStatus",
        "update_task_status",
        "updateEncounter",
        "update_encounter",
        "updatePatientRecord",
        "update_patient_record",
        "registerPatient",
        "register_patient",
        "applyProtocol",
        "apply_protocol",
        "processDischarge",
        "process_discharge",
        "processTransfer",
        "process_transfer",
    )
)


def _is_mutating(tool_name: str) -> bool:
    """True iff ``tool_name`` is one of the 8 mutating tools (camelCase or snake)."""
    return tool_name.lower() in _MUTATING_TOOL_NAMES


def _params_signature(params: dict[str, Any]) -> str:
    """Stable signature of params for retry detection.

    Excludes ``idempotency_key`` (otherwise distinct keys would look like
    distinct logical operations even when they're meant to be retries).
    Sorted by key so the signature is deterministic.
    """
    if not isinstance(params, dict):
        return str(params)
    items = sorted((k, str(v)) for k, v in params.items() if k != "idempotency_key")
    return str(items)


def process_signals_from_audit_log(
    audit_log: list[AuditEntry],
    *,
    idempotency_key_on_retry_bonus: float = 0.05,
    missing_idempotency_key_on_retry_penalty: float = -0.05,
    retry_budget_overflow_penalty: float = -0.10,
    deduplicated_replay_bonus: float = 0.02,
) -> dict[str, float]:
    """Scan the audit log for retry / idempotency patterns; return signed signals.

    A "retry" is any mutating call whose ``(tool_name, params_signature)``
    matches an earlier entry in the same audit log (idempotency_key
    deliberately excluded from the signature so we detect logical retries
    regardless of key usage).

    The returned dict is suitable for
    ``compute_training_reward(..., process_signals=…)``; ``compute_training_reward``
    sums and clips to ``RewardConfig.process_bonus_cap``.

    Args:
        audit_log: ``WorldState.audit_log`` snapshot at end of rollout.
        idempotency_key_on_retry_bonus: + per retried mutation carrying
            an idempotency_key. Rewards the safe-retry pattern.
        missing_idempotency_key_on_retry_penalty: − per retried mutation
            WITHOUT a key. Penalises duplicate-execution risk.
        retry_budget_overflow_penalty: − per ``retry_budget_exceeded``
            audit entry (from :class:`FaultInjector`). Penalises flailing.
        deduplicated_replay_bonus: + per successful deduplicated call
            (proof the policy used the key correctly and the env dedup'd).

    Returns:
        Dict of ``signal_name`` → signed float (may be empty).
    """
    signals: dict[str, float] = {}
    seen_signatures: dict[tuple[str, str], int] = {}

    for entry in audit_log:
        # 1. Retry-budget overflow (from FaultInjector) — flat penalty.
        if entry.error_code == "retry_budget_exceeded":
            signals["retry_budget_overflow"] = (
                signals.get("retry_budget_overflow", 0.0) + retry_budget_overflow_penalty
            )
            continue

        # 2. Skip non-mutating audit entries.
        if not _is_mutating(entry.tool_name):
            continue

        # 3. Retry detection via stable (tool, params) signature. Strip
        # underscores so camelCase and snake_case names ("createClinicalOrder"
        # vs "create_clinical_order") collapse to the same logical tool.
        sig = (
            entry.tool_name.lower().replace("_", ""),
            _params_signature(entry.params),
        )
        prior_count = seen_signatures.get(sig, 0)
        is_retry = prior_count > 0
        seen_signatures[sig] = prior_count + 1

        if is_retry:
            if entry.idempotency_key:
                signals["idempotency_key_on_retry"] = (
                    signals.get("idempotency_key_on_retry", 0.0) + idempotency_key_on_retry_bonus
                )
            else:
                signals["missing_idempotency_key_on_retry"] = (
                    signals.get("missing_idempotency_key_on_retry", 0.0)
                    + missing_idempotency_key_on_retry_penalty
                )

        # 4. Successful deduplicated replay — small bonus.
        if entry.deduplicated:
            signals["deduplicated_replay"] = (
                signals.get("deduplicated_replay", 0.0) + deduplicated_replay_bonus
            )

    return signals
