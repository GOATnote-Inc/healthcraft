"""Trajectory formatter tests.

``_format_trajectory_for_judge`` transforms raw trajectory turns into a
structured, section-labeled string the judge consumes. Two properties are
critical:

  1. The agent's final assistant message is preserved in full (no truncation).
     This is where discharge instructions, consult notes, and clinical content
     live. Truncating it causes the judge to miss content-based criteria.

  2. Long trajectories (>40 turns, typical for Claude) keep the final-turn
     text intact even as earlier reasoning is condensed. Judge context overload
     (failure pattern #7) is mitigated by section structure, not by cutting the
     final response.
"""

from __future__ import annotations

from healthcraft.llm.judge import _format_trajectory_for_judge


def _make_turn(role: str, content: str = "", tool_calls: list | None = None) -> dict:
    """Helper to create a turn dict."""
    turn: dict = {"role": role, "content": content}
    if tool_calls is not None:
        turn["tool_calls"] = tool_calls
    return turn


# ---------------------------------------------------------------------------
# Final response preservation
# ---------------------------------------------------------------------------


def test_final_response_preserved_in_full() -> None:
    """The last assistant message must appear without truncation."""
    final_text = "A" * 10000  # 10KB final response
    turns = [
        _make_turn("system", "You are an EM physician."),
        _make_turn("user", "Patient presents with chest pain."),
        _make_turn("assistant", "Let me gather more information."),
        _make_turn("assistant", final_text),
    ]
    formatted = _format_trajectory_for_judge(turns)
    assert final_text in formatted, (
        "Final assistant message was truncated. Content-based criteria "
        "will fail if the final response is cut."
    )


def test_final_response_is_last_assistant_message() -> None:
    """If the trajectory ends with a tool turn, the last assistant message
    before it is still the 'final response'."""
    turns = [
        _make_turn("user", "Treat this patient."),
        _make_turn("assistant", "First response."),
        _make_turn("assistant", "This is the actual final clinical output."),
        _make_turn("tool", '{"status": "ok"}'),
    ]
    formatted = _format_trajectory_for_judge(turns)
    assert "actual final clinical output" in formatted


# ---------------------------------------------------------------------------
# Section labels
# ---------------------------------------------------------------------------


def test_output_has_section_labels() -> None:
    """The formatted output must contain the four section headers."""
    turns = [
        _make_turn("system", "System prompt here."),
        _make_turn("user", "Task description."),
        _make_turn(
            "assistant",
            "Thinking...",
            tool_calls=[{"name": "getPatientHistory", "arguments": {}}],
        ),
        _make_turn("tool", '{"status": "ok", "data": {}}'),
        _make_turn("assistant", "Final answer."),
    ]
    formatted = _format_trajectory_for_judge(turns)
    assert "TASK CONTEXT" in formatted
    assert "TOOL CALL SUMMARY" in formatted
    assert "FINAL RESPONSE" in formatted


def test_earlier_reasoning_section_when_multiple_assistants() -> None:
    """When there are multiple assistant messages, earlier ones appear
    in the EARLIER REASONING section."""
    turns = [
        _make_turn("user", "Treat patient."),
        _make_turn("assistant", "Step 1: gather data."),
        _make_turn("assistant", "Step 2: order labs."),
        _make_turn("assistant", "Step 3: final plan."),
    ]
    formatted = _format_trajectory_for_judge(turns)
    assert "EARLIER REASONING" in formatted
    assert "Step 1" in formatted
    assert "Step 3" in formatted


# ---------------------------------------------------------------------------
# Tool call summary
# ---------------------------------------------------------------------------


def test_tool_calls_listed_in_summary() -> None:
    """Each tool call appears by name in the summary section."""
    turns = [
        _make_turn("user", "Go."),
        _make_turn(
            "assistant",
            "",
            tool_calls=[
                {"name": "searchPatients", "arguments": {"sex": "M"}},
                {"name": "getEncounterDetails", "arguments": {"encounter_id": "ENC-001"}},
            ],
        ),
        _make_turn("tool", '{"status": "ok"}'),
        _make_turn("tool", '{"status": "ok"}'),
        _make_turn("assistant", "Done."),
    ]
    formatted = _format_trajectory_for_judge(turns)
    assert "searchPatients" in formatted
    assert "getEncounterDetails" in formatted


def test_tool_call_arguments_truncated_at_150() -> None:
    """Very long tool arguments are truncated to keep the summary readable."""
    long_args = {"data": "x" * 300}
    turns = [
        _make_turn("user", "Go."),
        _make_turn(
            "assistant",
            "",
            tool_calls=[{"name": "createClinicalOrder", "arguments": long_args}],
        ),
        _make_turn("tool", "ok"),
        _make_turn("assistant", "Done."),
    ]
    formatted = _format_trajectory_for_judge(turns)
    # The args serialization should be capped; check for the truncation marker.
    assert "createClinicalOrder" in formatted
    # Full 300-char string should NOT appear
    assert ("x" * 300) not in formatted


# ---------------------------------------------------------------------------
# Long trajectory handling (>40 turns)
# ---------------------------------------------------------------------------


def test_long_trajectory_final_response_intact() -> None:
    """In a 50-turn trajectory, the final assistant message is not truncated."""
    turns = [_make_turn("user", "Initial presentation.")]
    # Simulate 24 tool-call cycles (assistant + tool = 48 turns) + final
    for i in range(24):
        turns.append(
            _make_turn(
                "assistant",
                f"Reasoning step {i}: " + "x" * 200,
                tool_calls=[{"name": f"tool_{i}", "arguments": {}}],
            )
        )
        turns.append(_make_turn("tool", f'{{"status": "ok", "step": {i}}}'))
    # Final long response
    final = "DISCHARGE INSTRUCTIONS: " + "detailed content " * 100
    turns.append(_make_turn("assistant", final))
    assert len(turns) > 40

    formatted = _format_trajectory_for_judge(turns)
    assert final in formatted, (
        "Final response was truncated in a long trajectory. "
        "This triggers failure pattern #7 (judge context overload)."
    )


def test_earlier_reasoning_condensed_in_long_trajectory() -> None:
    """Earlier assistant messages are excerpted (max 500 chars each)."""
    turns = [_make_turn("user", "Go.")]
    long_msg = "A" * 1000
    for _ in range(10):
        turns.append(_make_turn("assistant", long_msg))
    turns.append(_make_turn("assistant", "Final."))

    formatted = _format_trajectory_for_judge(turns)
    # The full 1000-char message should NOT appear for earlier steps
    # (they get truncated to 500 + "...")
    earlier_section_start = formatted.find("EARLIER REASONING")
    final_section_start = formatted.find("FINAL RESPONSE")
    if earlier_section_start >= 0 and final_section_start >= 0:
        earlier_section = formatted[earlier_section_start:final_section_start]
        assert ("A" * 1000) not in earlier_section


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_trajectory() -> None:
    """Empty turn list should not crash."""
    formatted = _format_trajectory_for_judge([])
    assert isinstance(formatted, str)


def test_no_assistant_messages() -> None:
    """Trajectory with only system + user turns (agent never responded)."""
    turns = [
        _make_turn("system", "You are an EM physician."),
        _make_turn("user", "Patient has chest pain."),
    ]
    formatted = _format_trajectory_for_judge(turns)
    assert "TASK CONTEXT" in formatted
    # Should not crash or include FINAL RESPONSE section
    assert isinstance(formatted, str)
