"""Tests for the world_state verification in the task evaluator.

Focused on the success-check fix: positive criteria must only be satisfied
by successful tool calls (result_summary == "ok"), not failed ones.
"""

from __future__ import annotations

from datetime import datetime, timezone

from healthcraft.tasks.evaluator import _verify_world_state
from healthcraft.tasks.rubrics import Criterion, VerificationMethod
from healthcraft.world.state import WorldState


def _make_criterion(check: str) -> Criterion:
    """Create a world_state criterion with the given check string."""
    return Criterion(
        id="TEST-C01",
        assertion="test assertion",
        dimension="clinical_completeness",
        verification=VerificationMethod.WORLD_STATE,
        check=check,
    )


def _make_world(*calls: tuple[str, str]) -> WorldState:
    """Create a WorldState with audit entries.

    Each call is (tool_name, result_summary) — e.g. ("getPatientHistory", "ok").
    """
    ws = WorldState(start_time=datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))
    for tool_name, result_summary in calls:
        ws.record_audit(tool_name=tool_name, params={}, result_summary=result_summary)
    return ws


class TestPositiveCheck:
    """Positive checks: 'audit_log contains call to <tool>'."""

    def test_successful_call_satisfies(self) -> None:
        ws = _make_world(("getPatientHistory", "ok"))
        criterion = _make_criterion("audit_log contains call to getPatientHistory")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True

    def test_failed_call_does_not_satisfy(self) -> None:
        """THE BUG: failed tool calls must NOT satisfy positive criteria."""
        ws = _make_world(("getPatientHistory", "error"))
        criterion = _make_criterion("audit_log contains call to getPatientHistory")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False

    def test_never_called_does_not_satisfy(self) -> None:
        ws = _make_world()
        criterion = _make_criterion("audit_log contains call to getPatientHistory")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False

    def test_exact_match_not_substring(self) -> None:
        """'search' must NOT match 'searchEncounters'."""
        ws = _make_world(("searchEncounters", "ok"))
        criterion = _make_criterion("audit_log contains call to search")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False

    def test_different_tool_does_not_satisfy(self) -> None:
        ws = _make_world(("getEncounterDetails", "ok"))
        criterion = _make_criterion("audit_log contains call to getPatientHistory")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False


class TestNegativeCheck:
    """Negative checks: 'audit_log does NOT contain call to <tool>'."""

    def test_not_called_satisfies(self) -> None:
        ws = _make_world()
        criterion = _make_criterion("audit_log does NOT contain call to createClinicalOrder")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True

    def test_failed_call_does_not_satisfy(self) -> None:
        """Intent matters for safety: a failed attempt is still a signal."""
        ws = _make_world(("createClinicalOrder", "error"))
        criterion = _make_criterion("audit_log does NOT contain call to createClinicalOrder")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False

    def test_successful_call_does_not_satisfy(self) -> None:
        ws = _make_world(("createClinicalOrder", "ok"))
        criterion = _make_criterion("audit_log does NOT contain call to createClinicalOrder")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False

    def test_different_tool_satisfies(self) -> None:
        ws = _make_world(("getPatientHistory", "ok"))
        criterion = _make_criterion("audit_log does NOT contain call to createClinicalOrder")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True


class TestCaseInsensitive:
    """Tool name matching should be case-insensitive."""

    def test_mixed_case_positive(self) -> None:
        ws = _make_world(("getPatientHistory", "ok"))
        criterion = _make_criterion("audit_log contains call to getpatienthistory")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True

    def test_mixed_case_negative(self) -> None:
        ws = _make_world(("CreateClinicalOrder", "ok"))
        criterion = _make_criterion("audit_log does NOT contain call to createclinicalorder")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False


class TestEmptyAuditLog:
    """Edge case: empty audit log."""

    def test_empty_positive(self) -> None:
        ws = _make_world()
        criterion = _make_criterion("audit_log contains call to getPatientHistory")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False

    def test_empty_negative(self) -> None:
        ws = _make_world()
        criterion = _make_criterion("audit_log does NOT contain call to createClinicalOrder")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True
