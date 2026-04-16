"""Judge system prompt snapshot test.

The judge's behavior is a function of its system prompt. A silent edit to
``JUDGE_SYSTEM_PROMPT`` changes grading for all 1,420 llm_judge criteria.
This test locks the prompt at the snapshot in
``tests/fixtures/judge_prompts/default.txt``.

When this test fails it means someone edited the prompt. That may be
intentional -- when it is, regenerate the snapshot:

    from healthcraft.llm.judge import JUDGE_SYSTEM_PROMPT
    from pathlib import Path
    Path('tests/fixtures/judge_prompts/default.txt').write_text(JUDGE_SYSTEM_PROMPT)

AND re-run the judge reliability study (``scripts/judge_reliability.py``)
to measure whether the edit improved or regressed kappa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from healthcraft.llm.judge import JUDGE_SYSTEM_PROMPT

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "judge_prompts" / "default.txt"


def test_judge_prompt_matches_snapshot() -> None:
    """JUDGE_SYSTEM_PROMPT is byte-identical to the snapshot."""
    expected = SNAPSHOT.read_text(encoding="utf-8")
    if JUDGE_SYSTEM_PROMPT != expected:
        from difflib import unified_diff

        diff = "\n".join(
            unified_diff(
                expected.splitlines(),
                JUDGE_SYSTEM_PROMPT.splitlines(),
                fromfile="snapshot",
                tofile="current",
                lineterm="",
                n=2,
            )
        )
        max_chars = 3000
        if len(diff) > max_chars:
            diff = diff[:max_chars] + "\n... [truncated]"
        pytest.fail(
            "JUDGE_SYSTEM_PROMPT differs from snapshot. "
            "Either revert the edit or regenerate the snapshot AND "
            "re-run scripts/judge_reliability.py.\n\n" + diff
        )


def test_snapshot_exists_and_nonempty() -> None:
    """Guard against accidental deletion of the snapshot file."""
    assert SNAPSHOT.exists(), f"Snapshot missing: {SNAPSHOT}"
    text = SNAPSHOT.read_text(encoding="utf-8")
    assert len(text) > 100, f"Snapshot suspiciously small ({len(text)} chars)"


def test_prompt_contains_required_structure() -> None:
    """The prompt must contain key structural elements the formatter relies on.

    The trajectory formatter produces sections labeled TASK CONTEXT, TOOL CALL
    SUMMARY, AGENT'S FINAL RESPONSE, and AGENT'S EARLIER REASONING. The judge
    prompt must reference at least the final response section by name, or the
    judge will not know where to look for content-based criteria.
    """
    prompt_lower = JUDGE_SYSTEM_PROMPT.lower()
    assert "final response" in prompt_lower, (
        "Prompt must mention 'FINAL RESPONSE' — the formatter labels the "
        "most important section this way"
    )
    assert "tool call" in prompt_lower, (
        "Prompt must mention tool calls — tool-use criteria are checked there"
    )
    assert "json" in prompt_lower, "Prompt must request JSON output — the parser depends on it"


def test_prompt_requests_satisfied_key() -> None:
    """The parser expects 'satisfied' in the JSON response."""
    assert "satisfied" in JUDGE_SYSTEM_PROMPT.lower()
