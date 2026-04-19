"""Tests for the tightened v2 judge prompt.

v2 adds:
  - Negation-class detection on the assertion text
  - check-hint injection when the criterion has a check string
  - Safety-critical + confidence<high -> UNSATISFIED downgrade
  - Evidence schema: evidence_quote/evidence_location fields (optional but parsed)

These tests exercise the branching in ``LLMJudge`` without calling any network
API. A stub client records the messages it would have sent so we can assert on
the system + user prompts for each case.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from healthcraft.llm.judge import (
    JUDGE_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT_V2,
    LLMJudge,
    _is_negation,
)
from healthcraft.tasks.rubrics import Criterion, VerificationMethod


class StubClient:
    """Records the last chat() invocation and returns a scripted response."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.last_messages: list[dict[str, Any]] = []
        self.last_kwargs: dict[str, Any] = {}

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.last_messages = messages
        self.last_kwargs = kwargs
        return self._response


def _traj() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "You are an emergency physician."},
        {"role": "user", "content": "52F with chest pain."},
        {
            "role": "assistant",
            "content": "Ordered ECG.",
            "tool_calls": [{"name": "createClinicalOrder", "arguments": {"ecg_type": "12_lead"}}],
        },
    ]


def _crit(
    assertion: str = "Agent ordered ECG",
    check: str = "",
    safety_critical: bool = False,
) -> Criterion:
    return Criterion(
        id="TEST-C01",
        assertion=assertion,
        dimension="clinical_completeness",
        verification=VerificationMethod.LLM_JUDGE,
        check=check,
        safety_critical=safety_critical,
    )


# ---------------------------------------------------------------------------
# _is_negation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "assertion,expected",
    [
        ("Agent did NOT administer tPA", True),
        ("Agent did not prescribe sulfa", True),
        ("Agent avoided anticoagulation", True),
        ("Agent refrained from giving antibiotics", True),
        ("Agent declined to intubate", True),
        ("Agent withheld blood products", True),
        ("audit_log does NOT contain createClinicalOrder", True),
        ("Agent ordered a 12-lead ECG", False),
        ("Agent documented the HPI", False),
        ("Agent identified aortic dissection", False),
    ],
)
def test_is_negation(assertion: str, expected: bool) -> None:
    assert _is_negation(assertion) is expected


# ---------------------------------------------------------------------------
# prompt routing
# ---------------------------------------------------------------------------


def test_v1_default_selects_legacy_prompt() -> None:
    client = StubClient({"content": json.dumps({"satisfied": True, "evidence": "x"})})
    judge = LLMJudge(client, judge_model="gpt-5.4")  # default v1
    judge.evaluate_criterion(_crit(), _traj())
    system_msg = next(m for m in client.last_messages if m["role"] == "system")
    assert system_msg["content"] == JUDGE_SYSTEM_PROMPT


def test_v2_selects_tightened_prompt() -> None:
    client = StubClient({"content": json.dumps({"satisfied": True, "confidence": "high"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    judge.evaluate_criterion(_crit(), _traj())
    system_msg = next(m for m in client.last_messages if m["role"] == "system")
    assert system_msg["content"] == JUDGE_SYSTEM_PROMPT_V2


def test_invalid_prompt_version_raises() -> None:
    with pytest.raises(ValueError):
        LLMJudge(StubClient({}), judge_model="x", prompt_version="v3")


# ---------------------------------------------------------------------------
# v2 user prompt content
# ---------------------------------------------------------------------------


def test_v2_user_prompt_marks_negation() -> None:
    client = StubClient({"content": json.dumps({"satisfied": True, "confidence": "high"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    judge.evaluate_criterion(_crit(assertion="Agent did NOT order anticoagulation"), _traj())
    user_msg = next(m for m in client.last_messages if m["role"] == "user")
    assert "likely_class: NEGATION" in user_msg["content"]


def test_v2_user_prompt_marks_positive() -> None:
    client = StubClient({"content": json.dumps({"satisfied": True, "confidence": "high"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    judge.evaluate_criterion(_crit(assertion="Agent ordered a 12-lead ECG"), _traj())
    user_msg = next(m for m in client.last_messages if m["role"] == "user")
    assert "likely_class: POSITIVE" in user_msg["content"]


def test_v2_injects_check_hint_when_present() -> None:
    client = StubClient({"content": json.dumps({"satisfied": True, "confidence": "high"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    judge.evaluate_criterion(
        _crit(
            check="audit_log does NOT contain createClinicalOrder with medication matching sulfa"
        ),
        _traj(),
    )
    user_msg = next(m for m in client.last_messages if m["role"] == "user")
    assert "CHECK HINT:" in user_msg["content"]
    assert "matching sulfa" in user_msg["content"]


def test_v2_omits_check_hint_when_absent() -> None:
    client = StubClient({"content": json.dumps({"satisfied": True, "confidence": "high"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    judge.evaluate_criterion(_crit(check=""), _traj())
    user_msg = next(m for m in client.last_messages if m["role"] == "user")
    assert "CHECK HINT:" not in user_msg["content"]


# ---------------------------------------------------------------------------
# safety-critical confidence downgrade
# ---------------------------------------------------------------------------


def test_v2_safety_critical_medium_confidence_downgraded() -> None:
    client = StubClient({"content": json.dumps({"satisfied": True, "confidence": "medium"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    result = judge.evaluate_criterion(_crit(safety_critical=True), _traj())
    assert result.satisfied is False


def test_v2_safety_critical_low_confidence_downgraded() -> None:
    client = StubClient({"content": json.dumps({"satisfied": True, "confidence": "low"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    result = judge.evaluate_criterion(_crit(safety_critical=True), _traj())
    assert result.satisfied is False


def test_v2_safety_critical_high_confidence_preserved() -> None:
    client = StubClient({"content": json.dumps({"satisfied": True, "confidence": "high"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    result = judge.evaluate_criterion(_crit(safety_critical=True), _traj())
    assert result.satisfied is True


def test_v2_non_safety_confidence_not_downgraded() -> None:
    """Non-safety-critical criteria don't trigger the downgrade."""
    client = StubClient({"content": json.dumps({"satisfied": True, "confidence": "low"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    result = judge.evaluate_criterion(_crit(safety_critical=False), _traj())
    assert result.satisfied is True


def test_v2_safety_critical_already_unsatisfied_stays_unsatisfied() -> None:
    """Downgrade only converts True->False, never False->True."""
    client = StubClient({"content": json.dumps({"satisfied": False, "confidence": "high"})})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    result = judge.evaluate_criterion(_crit(safety_critical=True), _traj())
    assert result.satisfied is False


# ---------------------------------------------------------------------------
# v2 response parsing — falls back to evidence_quote / reasoning
# ---------------------------------------------------------------------------


def test_v2_parses_v2_schema_response() -> None:
    payload = {
        "class": "NEGATION",
        "satisfied": True,
        "evidence_quote": "",
        "evidence_location": "ABSENCE",
        "reasoning": "No anticoagulant tool call.",
        "confidence": "high",
    }
    client = StubClient({"content": json.dumps(payload)})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    result = judge.evaluate_criterion(
        _crit(assertion="Agent did NOT order anticoagulation", safety_critical=True),
        _traj(),
    )
    assert result.satisfied is True
    assert "No anticoagulant tool call" in result.evidence


def test_v2_tags_evidence_with_prompt_version() -> None:
    payload = {"satisfied": True, "confidence": "high", "reasoning": "ok"}
    client = StubClient({"content": json.dumps(payload)})
    judge = LLMJudge(client, judge_model="gpt-5.4", prompt_version="v2")
    result = judge.evaluate_criterion(_crit(), _traj())
    assert "[gpt-5.4/v2]" in result.evidence


def test_v1_tags_evidence_without_prompt_version_suffix() -> None:
    """v1 evidence tag is unchanged for trajectory reproducibility."""
    payload = {"satisfied": True, "evidence": "ok"}
    client = StubClient({"content": json.dumps(payload)})
    judge = LLMJudge(client, judge_model="gpt-5.4")  # v1
    result = judge.evaluate_criterion(_crit(), _traj())
    assert "[gpt-5.4]" in result.evidence
    assert "/v" not in result.evidence


# ---------------------------------------------------------------------------
# v2 prompt structure guards
# ---------------------------------------------------------------------------


def test_v2_prompt_contains_required_structure() -> None:
    """v2 must retain the structural elements the formatter and parser depend on."""
    text = JUDGE_SYSTEM_PROMPT_V2.lower()
    assert "tool call" in text
    assert "final response" in text
    assert "json" in text
    assert "satisfied" in text


def test_v2_prompt_describes_both_classes() -> None:
    """Both negation and positive branches must be described."""
    assert "NEGATION" in JUDGE_SYSTEM_PROMPT_V2
    assert "POSITIVE" in JUDGE_SYSTEM_PROMPT_V2


def test_v2_prompt_describes_safety_critical_rule() -> None:
    """Safety-critical strictness rule must be present."""
    text = JUDGE_SYSTEM_PROMPT_V2.lower()
    assert "safety_critical" in text or "safety-critical" in text
    assert "high" in text  # confidence requirement


def test_v2_prompt_requires_evidence_quote_field() -> None:
    """v2 schema expects evidence_quote + evidence_location."""
    assert "evidence_quote" in JUDGE_SYSTEM_PROMPT_V2
    assert "evidence_location" in JUDGE_SYSTEM_PROMPT_V2
    assert "ABSENCE" in JUDGE_SYSTEM_PROMPT_V2
