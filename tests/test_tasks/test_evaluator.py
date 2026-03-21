"""Tests for the world_state verification in the task evaluator.

Focused on the success-check fix: positive criteria must only be satisfied
by successful tool calls (result_summary == "ok"), not failed ones.
"""

from __future__ import annotations

from datetime import datetime, timezone

from healthcraft.tasks.evaluator import _expand_tool_alternatives, _verify_world_state
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


def _make_world_with_params(
    *calls: tuple[str, dict, str],
) -> WorldState:
    """Create a WorldState with audit entries that include params.

    Each call is (tool_name, params, result_summary).
    """
    ws = WorldState(start_time=datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))
    for tool_name, params, result_summary in calls:
        ws.record_audit(tool_name=tool_name, params=params, result_summary=result_summary)
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


class TestExpandToolAlternatives:
    """Tests for _expand_tool_alternatives helper."""

    def test_or_bare_tools(self) -> None:
        check = "audit_log contains call to searchEncounters or getPatientHistory"
        result = _expand_tool_alternatives(check)
        assert "audit_log contains call to searchEncounters" in result
        assert "audit_log contains call to getPatientHistory" in result
        assert " OR " in result

    def test_and_bare_tools(self) -> None:
        check = "audit_log contains call to searchEncounters and getEncounterDetails"
        result = _expand_tool_alternatives(check)
        assert "audit_log contains call to searchEncounters" in result
        assert "audit_log contains call to getEncounterDetails" in result
        assert " AND " in result

    def test_no_expansion_with_qualifier(self) -> None:
        """Don't expand when text follows after the second tool name."""
        check = "audit_log contains call to createClinicalOrder for lab"
        result = _expand_tool_alternatives(check)
        assert result == check

    def test_no_expansion_medical_or(self) -> None:
        """Don't expand 'OR' that is part of 'OR status' (operating room)."""
        check = "audit_log contains call to checkResourceAvailability for OR"
        result = _expand_tool_alternatives(check)
        # Should not expand — "OR" here is followed by end-of-string but
        # it's a qualifier value, not a tool name
        assert result == check

    def test_or_alternative_satisfies(self) -> None:
        """Either tool name should satisfy an OR alternative check."""
        ws = _make_world(("getPatientHistory", "ok"))
        criterion = _make_criterion(
            "audit_log contains call to searchEncounters or getPatientHistory"
        )
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True

    def test_or_alternative_first_satisfies(self) -> None:
        ws = _make_world(("searchEncounters", "ok"))
        criterion = _make_criterion(
            "audit_log contains call to searchEncounters or getPatientHistory"
        )
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True

    def test_or_alternative_neither_satisfies(self) -> None:
        ws = _make_world(("createClinicalOrder", "ok"))
        criterion = _make_criterion(
            "audit_log contains call to searchEncounters or getPatientHistory"
        )
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False

    def test_and_alternative_both_required(self) -> None:
        ws = _make_world(("searchEncounters", "ok"), ("getEncounterDetails", "ok"))
        criterion = _make_criterion(
            "audit_log contains call to searchEncounters and getEncounterDetails"
        )
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True

    def test_and_alternative_one_missing(self) -> None:
        ws = _make_world(("searchEncounters", "ok"))
        criterion = _make_criterion(
            "audit_log contains call to searchEncounters and getEncounterDetails"
        )
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False


class TestQualifierUnderscoreNormalization:
    """Underscore qualifiers must match space-separated agent params.

    Check strings use "for tranexamic_acid" but agents pass
    {"medication_name": "tranexamic acid"}. The evaluator must normalize
    underscores to spaces for matching.
    """

    def test_underscore_qualifier_matches_space_params(self) -> None:
        """Core bug: 'tranexamic_acid' must match 'tranexamic acid'."""
        ws = _make_world_with_params(
            (
                "createClinicalOrder",
                {"order_type": "medication", "medication_name": "tranexamic acid"},
                "ok",
            ),
        )
        criterion = _make_criterion("audit_log contains createClinicalOrder for tranexamic_acid")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True, f"Expected satisfied, got: {result.evidence}"

    def test_compound_underscore_qualifier(self) -> None:
        """'cta_head_neck' must match 'CTA head neck'."""
        ws = _make_world_with_params(
            (
                "createClinicalOrder",
                {"order_type": "imaging", "imaging_type": "CTA head neck"},
                "ok",
            ),
        )
        criterion = _make_criterion("audit_log contains createClinicalOrder for CTA_head_neck")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True, f"Expected satisfied, got: {result.evidence}"

    def test_exact_underscore_also_matches(self) -> None:
        """If params actually contain the underscore form, still match."""
        ws = _make_world_with_params(
            (
                "createClinicalOrder",
                {"medication": "tranexamic_acid"},
                "ok",
            ),
        )
        criterion = _make_criterion("audit_log contains createClinicalOrder for tranexamic_acid")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is True

    def test_no_match_when_wrong_medication(self) -> None:
        """Qualifier should still fail if the medication is wrong."""
        ws = _make_world_with_params(
            (
                "createClinicalOrder",
                {"order_type": "medication", "medication_name": "aspirin"},
                "ok",
            ),
        )
        criterion = _make_criterion("audit_log contains createClinicalOrder for tranexamic_acid")
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False

    def test_negative_check_underscore_normalization(self) -> None:
        """Negative checks must also normalize underscores."""
        ws = _make_world_with_params(
            (
                "createClinicalOrder",
                {"medication_name": "tranexamic acid"},
                "ok",
            ),
        )
        criterion = _make_criterion(
            "audit_log does NOT contain createClinicalOrder for tranexamic_acid"
        )
        result = _verify_world_state(criterion, (), ws)
        assert result.satisfied is False
