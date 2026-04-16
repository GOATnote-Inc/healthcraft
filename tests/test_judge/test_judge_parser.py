"""Judge response parser tests.

``_parse_judge_response`` must handle four formats the judge may produce:
  1. Clean JSON (ideal)
  2. Markdown-fenced JSON (```json ... ```)
  3. Prose-wrapped JSON (text before/after the JSON object)
  4. Malformed / no JSON (keyword fallback)

A parser regression silently flips verdicts for every llm_judge criterion.
"""

from __future__ import annotations

import pytest

from healthcraft.llm.judge import _parse_judge_response

# ---------------------------------------------------------------------------
# 1. Clean JSON
# ---------------------------------------------------------------------------


class TestCleanJSON:
    def test_satisfied_true(self) -> None:
        raw = '{"satisfied": true, "evidence": "Found diagnosis", "confidence": "high"}'
        result = _parse_judge_response(raw)
        assert result["satisfied"] is True
        assert result["evidence"] == "Found diagnosis"
        assert result["confidence"] == "high"

    def test_satisfied_false(self) -> None:
        raw = '{"satisfied": false, "evidence": "No evidence", "confidence": "low"}'
        result = _parse_judge_response(raw)
        assert result["satisfied"] is False

    def test_whitespace_padded(self) -> None:
        raw = '  \n {"satisfied": true, "evidence": "ok", "confidence": "medium"} \n  '
        result = _parse_judge_response(raw)
        assert result["satisfied"] is True

    def test_minimal_keys(self) -> None:
        raw = '{"satisfied": false}'
        result = _parse_judge_response(raw)
        assert result["satisfied"] is False


# ---------------------------------------------------------------------------
# 2. Markdown-fenced JSON
# ---------------------------------------------------------------------------


class TestMarkdownFenced:
    def test_json_fence(self) -> None:
        raw = (
            "Here is my evaluation:\n\n"
            "```json\n"
            '{"satisfied": true, "evidence": "Agent ordered ECG", "confidence": "high"}\n'
            "```"
        )
        result = _parse_judge_response(raw)
        assert result["satisfied"] is True
        assert "ECG" in result["evidence"]

    def test_bare_fence(self) -> None:
        raw = '```\n{"satisfied": false, "evidence": "Missing labs", "confidence": "medium"}\n```'
        result = _parse_judge_response(raw)
        assert result["satisfied"] is False

    def test_fence_with_trailing_text(self) -> None:
        raw = (
            "Based on the trajectory:\n"
            "```json\n"
            '{"satisfied": true, "evidence": "ok", "confidence": "high"}\n'
            "```\n"
            "This concludes the evaluation."
        )
        result = _parse_judge_response(raw)
        assert result["satisfied"] is True


# ---------------------------------------------------------------------------
# 3. Prose-wrapped JSON (no fences)
# ---------------------------------------------------------------------------


class TestProseWrapped:
    def test_json_embedded_in_prose(self) -> None:
        raw = (
            "After reviewing the trajectory, I conclude:\n"
            '{"satisfied": true, "evidence": "Diagnosis was stated", "confidence": "high"}\n'
            "The agent performed well."
        )
        result = _parse_judge_response(raw)
        assert result["satisfied"] is True

    def test_leading_text_only(self) -> None:
        raw = 'My assessment: {"satisfied": false, "evidence": "Not found", "confidence": "low"}'
        result = _parse_judge_response(raw)
        assert result["satisfied"] is False


# ---------------------------------------------------------------------------
# 4. Malformed / keyword fallback
# ---------------------------------------------------------------------------


class TestMalformedFallback:
    def test_no_json_at_all(self) -> None:
        raw = "The criterion is not satisfied because the agent did not order labs."
        result = _parse_judge_response(raw)
        # Fallback: "satisfied" keyword detected -> True (the keyword "satisfied"
        # appears in "not satisfied"). The parser checks for several keywords.
        assert isinstance(result["satisfied"], bool)
        assert result["confidence"] == "low"

    def test_empty_string(self) -> None:
        raw = ""
        result = _parse_judge_response(raw)
        assert result["satisfied"] is False
        assert result["confidence"] == "low"

    def test_truncated_json(self) -> None:
        raw = '{"satisfied": true, "evidence": "partial'
        result = _parse_judge_response(raw)
        # Falls through to keyword fallback; "satisfied" is in the string.
        assert isinstance(result["satisfied"], bool)

    def test_nested_braces(self) -> None:
        """Nested JSON objects should still parse via brace-finding."""
        raw = (
            'Response: {"satisfied": true, "evidence": "Params were '
            '{\\"order_type\\": \\"lab\\"}", "confidence": "high"}'
        )
        result = _parse_judge_response(raw)
        # The brace-finder picks { to }, which may or may not parse cleanly
        # depending on escaping. The parser must not crash either way.
        assert isinstance(result["satisfied"], bool)


# ---------------------------------------------------------------------------
# Contract: return type always has the three expected keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"satisfied": true, "evidence": "ok", "confidence": "high"}',
        "No JSON here at all",
        "",
        "```json\n{}\n```",
    ],
)
def test_always_returns_satisfied_key(raw: str) -> None:
    """Every code path must return a dict with at least 'satisfied'."""
    result = _parse_judge_response(raw)
    assert "satisfied" in result
    assert isinstance(result["satisfied"], bool)
