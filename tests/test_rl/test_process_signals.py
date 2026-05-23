"""Tests for healthcraft.rl.process_signals (PR-B / WS-5)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from healthcraft.rl.process_signals import process_signals_from_audit_log
from healthcraft.world.state import AuditEntry


def _audit(
    tool_name: str,
    params: dict[str, Any] | None = None,
    *,
    summary: str = "ok",
    idem_key: str = "",
    attempt: int = 1,
    deduplicated: bool = False,
    error_code: str = "",
) -> AuditEntry:
    return AuditEntry(
        tool_name=tool_name,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        params=params or {},
        result_summary=summary,
        error_code=error_code,
        idempotency_key=idem_key,
        attempt_number=attempt,
        deduplicated=deduplicated,
    )


def test_empty_audit_log_yields_no_signals():
    assert process_signals_from_audit_log([]) == {}


def test_single_mutation_emits_no_retry_signal():
    log = [_audit("createClinicalOrder", {"encounter_id": "E1"}, idem_key="k1")]
    signals = process_signals_from_audit_log(log)
    assert "idempotency_key_on_retry" not in signals
    assert "missing_idempotency_key_on_retry" not in signals


def test_retry_with_idempotency_key_emits_positive_signal():
    log = [
        _audit("createClinicalOrder", {"encounter_id": "E1"}, idem_key="k1"),
        _audit(
            "createClinicalOrder",
            {"encounter_id": "E1"},
            idem_key="k1",
            attempt=2,
            deduplicated=True,
        ),
    ]
    signals = process_signals_from_audit_log(log)
    assert signals.get("idempotency_key_on_retry", 0.0) > 0.0
    # The dedup'd entry also earns the replay bonus.
    assert signals.get("deduplicated_replay", 0.0) > 0.0


def test_retry_without_idempotency_key_emits_negative_signal():
    log = [
        _audit("createClinicalOrder", {"encounter_id": "E1"}),
        _audit("createClinicalOrder", {"encounter_id": "E1"}),  # logical retry, no key
    ]
    signals = process_signals_from_audit_log(log)
    assert signals.get("missing_idempotency_key_on_retry", 0.0) < 0.0
    assert "idempotency_key_on_retry" not in signals


def test_retry_budget_exceeded_emits_flat_penalty():
    log = [
        _audit(
            "createClinicalOrder",
            {"encounter_id": "E1"},
            idem_key="k1",
            summary="error",
            error_code="retry_budget_exceeded",
        )
    ]
    signals = process_signals_from_audit_log(log)
    assert signals.get("retry_budget_overflow", 0.0) < 0.0


def test_non_mutating_tools_ignored():
    log = [
        _audit("getEncounterDetails", {}),
        _audit("getEncounterDetails", {}),
    ]
    assert process_signals_from_audit_log(log) == {}


def test_distinct_params_not_treated_as_retry():
    log = [
        _audit("createClinicalOrder", {"encounter_id": "E1"}, idem_key="k1"),
        _audit("createClinicalOrder", {"encounter_id": "E2"}, idem_key="k2"),
    ]
    signals = process_signals_from_audit_log(log)
    assert "missing_idempotency_key_on_retry" not in signals
    assert "idempotency_key_on_retry" not in signals


def test_camelcase_and_snake_case_treated_as_same_tool():
    log = [
        _audit("createClinicalOrder", {"encounter_id": "E1"}, idem_key="k1"),
        _audit("create_clinical_order", {"encounter_id": "E1"}, idem_key="k1", attempt=2),
    ]
    signals = process_signals_from_audit_log(log)
    assert signals.get("idempotency_key_on_retry", 0.0) > 0.0


def test_multiple_retries_accumulate():
    log = [
        _audit("createClinicalOrder", {"encounter_id": "E1"}, idem_key="k1"),
        _audit("createClinicalOrder", {"encounter_id": "E1"}, idem_key="k1", attempt=2),
        _audit("createClinicalOrder", {"encounter_id": "E1"}, idem_key="k1", attempt=3),
    ]
    signals = process_signals_from_audit_log(log)
    # 2 retries × bonus (default 0.05) = 0.10.
    assert signals.get("idempotency_key_on_retry", 0.0) == 0.10
