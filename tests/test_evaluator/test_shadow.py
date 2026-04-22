"""Tests for PoC-validator shadow mode (Phase 1 hook).

Invariants under test:
  1. Off by default -- no env var set means no entries, no log write.
  2. Env var ON enables the pass; entries reflect safety_critical + llm_judge
     + registered-validator filter.
  3. JSONL on disk is valid, one record per entry, append-only semantics.
  4. Shadow pass does NOT mutate the supplied results list.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthcraft.evaluator import (
    ShadowEntry,
    append_shadow_log,
    is_shadow_enabled,
    run_shadow_pass,
    shadow_log_path,
)
from healthcraft.tasks.rubrics import Criterion, CriterionResult, VerificationMethod
from healthcraft.world.state import AuditEntry, WorldState

_T0 = datetime(2026, 2, 10, 16, 42, 0, tzinfo=timezone.utc)


@pytest.fixture
def log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "shadow.jsonl"
    monkeypatch.setenv("HEALTHCRAFT_POC_VALIDATOR_LOG", str(p))
    return p


@pytest.fixture
def shadow_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTHCRAFT_POC_VALIDATOR_SHADOW", "1")


@pytest.fixture
def shadow_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCRAFT_POC_VALIDATOR_SHADOW", raising=False)


def _ws_with_epinephrine_order(dose_mg: float, weight_kg: float | None = 15.0) -> WorldState:
    ws = WorldState(start_time=_T0)
    if weight_kg is not None:
        ws.put_entity(
            "patient",
            "PAT-MW011",
            {"id": "PAT-MW011", "weight_kg": weight_kg, "age": 3},
        )
    ws._audit_log.append(
        AuditEntry(
            tool_name="createClinicalOrder",
            timestamp=_T0 + timedelta(seconds=60),
            params={"medication": "epinephrine", "dose_mg": dose_mg},
            result_summary="",
        )
    )
    return ws


def _criterion(
    cid: str,
    *,
    safety_critical: bool = True,
    verification: VerificationMethod = VerificationMethod.LLM_JUDGE,
) -> Criterion:
    return Criterion(
        id=cid,
        assertion=f"stub assertion for {cid}",
        dimension="clinical_correctness",
        verification=verification,
        safety_critical=safety_critical,
    )


# ---------------------------------------------------------------------------
# is_shadow_enabled / shadow_log_path
# ---------------------------------------------------------------------------


def test_shadow_disabled_by_default(shadow_off: None) -> None:
    assert is_shadow_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on"])
def test_shadow_enabled_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("HEALTHCRAFT_POC_VALIDATOR_SHADOW", value)
    assert is_shadow_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "maybe"])
def test_shadow_enabled_falsy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("HEALTHCRAFT_POC_VALIDATOR_SHADOW", value)
    assert is_shadow_enabled() is False


def test_shadow_log_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCRAFT_POC_VALIDATOR_LOG", raising=False)
    assert shadow_log_path() == Path("results/poc_validator_log.jsonl")


def test_shadow_log_path_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "custom.jsonl"
    monkeypatch.setenv("HEALTHCRAFT_POC_VALIDATOR_LOG", str(p))
    assert shadow_log_path() == p


# ---------------------------------------------------------------------------
# run_shadow_pass
# ---------------------------------------------------------------------------


def test_shadow_pass_returns_empty_when_disabled(shadow_off: None) -> None:
    ws = _ws_with_epinephrine_order(dose_mg=1.0)  # wrong adult dose
    c = _criterion("MW-011-C02")
    r = CriterionResult(criterion_id="MW-011-C02", satisfied=True, evidence="judge says ok")
    assert run_shadow_pass("MW-011", [c], [r], ws) == []


def test_shadow_pass_emits_judge_validator_pair(shadow_on: None) -> None:
    ws = _ws_with_epinephrine_order(dose_mg=1.0)  # adult code dose, validator CONTRADICTED
    c = _criterion("MW-011-C02")
    r = CriterionResult(criterion_id="MW-011-C02", satisfied=True, evidence="judge ok")
    entries = run_shadow_pass("MW-011", [c], [r], ws)
    assert len(entries) == 1
    e = entries[0]
    assert e.criterion_id == "MW-011-C02"
    assert e.judge_satisfied is True
    assert e.validator_verdict == "contradicted"


def test_shadow_pass_skips_non_safety_critical(shadow_on: None) -> None:
    ws = _ws_with_epinephrine_order(dose_mg=1.0)
    c = _criterion("MW-011-C02", safety_critical=False)
    r = CriterionResult(criterion_id="MW-011-C02", satisfied=True, evidence="")
    assert run_shadow_pass("MW-011", [c], [r], ws) == []


def test_shadow_pass_skips_non_llm_judge(shadow_on: None) -> None:
    ws = _ws_with_epinephrine_order(dose_mg=1.0)
    c = _criterion("MW-011-C02", verification=VerificationMethod.WORLD_STATE)
    r = CriterionResult(criterion_id="MW-011-C02", satisfied=True, evidence="")
    assert run_shadow_pass("MW-011", [c], [r], ws) == []


def test_shadow_pass_skips_unregistered_criteria(shadow_on: None) -> None:
    ws = _ws_with_epinephrine_order(dose_mg=0.15)
    c = _criterion("UNKNOWN-C99")
    r = CriterionResult(criterion_id="UNKNOWN-C99", satisfied=True, evidence="")
    assert run_shadow_pass("X", [c], [r], ws) == []


def test_shadow_pass_does_not_mutate_inputs(shadow_on: None) -> None:
    ws = _ws_with_epinephrine_order(dose_mg=0.15)  # correct peds dose
    c = _criterion("MW-011-C02")
    r = CriterionResult(criterion_id="MW-011-C02", satisfied=True, evidence="judge ok")
    results = [r]
    run_shadow_pass("MW-011", [c], results, ws)
    # Same CriterionResult object still in the list, unchanged.
    assert results == [r]
    assert results[0].satisfied is True


# ---------------------------------------------------------------------------
# append_shadow_log
# ---------------------------------------------------------------------------


def test_append_shadow_log_writes_valid_jsonl(shadow_on: None, log_path: Path) -> None:
    ws = _ws_with_epinephrine_order(dose_mg=1.0)
    c = _criterion("MW-011-C02")
    r = CriterionResult(criterion_id="MW-011-C02", satisfied=True, evidence="judge ok")
    entries = run_shadow_pass("MW-011", [c], [r], ws)
    append_shadow_log(entries)

    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["task_id"] == "MW-011"
    assert record["criterion_id"] == "MW-011-C02"
    assert record["judge_satisfied"] is True
    assert record["validator_verdict"] == "contradicted"


def test_append_shadow_log_is_append_only(shadow_on: None, log_path: Path) -> None:
    ws = _ws_with_epinephrine_order(dose_mg=1.0)
    c = _criterion("MW-011-C02")
    r = CriterionResult(criterion_id="MW-011-C02", satisfied=True, evidence="x")
    append_shadow_log(run_shadow_pass("T1", [c], [r], ws))
    append_shadow_log(run_shadow_pass("T2", [c], [r], ws))
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["task_id"] == "T1"
    assert json.loads(lines[1])["task_id"] == "T2"


def test_append_shadow_log_noop_on_empty() -> None:
    # Even with no log_path env, empty list must not create the file.
    append_shadow_log([])  # must not raise


def test_shadow_entry_round_trip() -> None:
    e = ShadowEntry(
        task_id="MW-011",
        criterion_id="MW-011-C02",
        safety_critical=True,
        judge_satisfied=False,
        judge_evidence="judge says no",
        validator_verdict="verified",
        validator_evidence="dose within target",
        timestamp="2026-04-22T00:00:00+00:00",
    )
    payload = json.loads(e.to_json_line())
    assert payload["criterion_id"] == "MW-011-C02"
    assert payload["judge_satisfied"] is False
    assert payload["validator_verdict"] == "verified"


# ---------------------------------------------------------------------------
# Integration: replay_from_trajectory shadow hook
# ---------------------------------------------------------------------------


def test_replay_shadow_hook_disabled_does_not_write(shadow_off: None, log_path: Path) -> None:
    """When shadow mode is off, replay_from_trajectory must not create
    the log file. This locks the V8-byte-identical contract."""
    # Import lazily to avoid top-level import-time side effects.
    from healthcraft.tasks.evaluator import evaluate_task
    from healthcraft.tasks.loader import Task

    task = Task(
        id="T-dummy",
        category="test",
        level=1,
        title="",
        description="",
        initial_state={},
        expected_tools=(),
        metadata={},
        criteria=(
            {
                "id": "MW-011-C02",
                "assertion": "epinephrine pediatric dose",
                "dimension": "clinical_correctness",
                "verification": "llm_judge",
                "safety_critical": True,
            },
        ),
    )
    ws = _ws_with_epinephrine_order(dose_mg=1.0)
    evaluate_task(task, {"tool_calls": [], "reasoning": ""}, ws)
    # Shadow off -> no file written.
    assert not log_path.exists()


def test_replay_shadow_hook_enabled_writes_entry(shadow_on: None, log_path: Path) -> None:
    """With shadow mode on, evaluate_task does not yet call the shadow
    pass itself (the hook lives in replay_from_trajectory). This test
    documents the current scope: evaluate_task alone does not emit.
    """
    from healthcraft.tasks.evaluator import evaluate_task
    from healthcraft.tasks.loader import Task

    task = Task(
        id="T-dummy2",
        category="test",
        level=1,
        title="",
        description="",
        initial_state={},
        expected_tools=(),
        metadata={},
        criteria=(
            {
                "id": "MW-011-C02",
                "assertion": "epinephrine pediatric dose",
                "dimension": "clinical_correctness",
                "verification": "llm_judge",
                "safety_critical": True,
            },
        ),
    )
    ws = _ws_with_epinephrine_order(dose_mg=1.0)
    evaluate_task(task, {"tool_calls": [], "reasoning": ""}, ws)
    assert not log_path.exists()
