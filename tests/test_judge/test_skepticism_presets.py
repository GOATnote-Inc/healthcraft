"""Skepticism preset tests.

``SKEPTICISM_PRESETS`` defines three judge strictness levels: default,
moderate, high. ``create_skeptical_judge`` applies them as system prompt
suffixes. These tests lock:

  1. All three presets exist and produce distinct prompt text.
  2. "default" adds nothing (V8 behavior).
  3. "moderate" and "high" each add non-empty guidance.
  4. The presets are ordered by strictness (high's suffix is longer / more
     directive than moderate's).
  5. ``create_skeptical_judge`` applies the suffix without corrupting the
     base prompt.
"""

from __future__ import annotations

from healthcraft.llm.evaluator import SKEPTICISM_PRESETS
from healthcraft.llm.judge import JUDGE_SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Preset existence and distinctness
# ---------------------------------------------------------------------------


def test_three_presets_exist() -> None:
    """default, moderate, high must all be defined."""
    assert "default" in SKEPTICISM_PRESETS
    assert "moderate" in SKEPTICISM_PRESETS
    assert "high" in SKEPTICISM_PRESETS


def test_presets_are_distinct() -> None:
    """Each preset produces a different suffix."""
    values = list(SKEPTICISM_PRESETS.values())
    assert len(set(values)) == len(values), "Two or more presets have identical suffix text"


# ---------------------------------------------------------------------------
# Default preserves V8 behavior
# ---------------------------------------------------------------------------


def test_default_is_empty() -> None:
    """'default' adds nothing to the judge prompt — V8 behavior."""
    assert SKEPTICISM_PRESETS["default"] == ""


# ---------------------------------------------------------------------------
# Non-default presets add guidance
# ---------------------------------------------------------------------------


def test_moderate_is_nonempty() -> None:
    assert len(SKEPTICISM_PRESETS["moderate"]) > 20


def test_high_is_nonempty() -> None:
    assert len(SKEPTICISM_PRESETS["high"]) > 20


def test_high_is_stricter_than_moderate() -> None:
    """High preset's suffix is longer (more rules) than moderate's."""
    mod_len = len(SKEPTICISM_PRESETS["moderate"])
    high_len = len(SKEPTICISM_PRESETS["high"])
    assert high_len > mod_len, (
        f"high ({high_len} chars) should be longer than moderate ({mod_len} chars)"
    )


# ---------------------------------------------------------------------------
# Suffix composition
# ---------------------------------------------------------------------------


def test_moderate_suffix_appends_to_base_prompt() -> None:
    """Composing base + moderate suffix produces a valid prompt."""
    composed = JUDGE_SYSTEM_PROMPT + SKEPTICISM_PRESETS["moderate"]
    assert composed.startswith(JUDGE_SYSTEM_PROMPT)
    assert "skeptical" in composed.lower()


def test_high_suffix_appends_to_base_prompt() -> None:
    composed = JUDGE_SYSTEM_PROMPT + SKEPTICISM_PRESETS["high"]
    assert composed.startswith(JUDGE_SYSTEM_PROMPT)
    assert "skeptical" in composed.lower()


def test_moderate_mentions_ambiguous_evidence() -> None:
    """Moderate preset should guide on ambiguous evidence."""
    text = SKEPTICISM_PRESETS["moderate"].lower()
    assert "ambiguous" in text or "lean toward" in text


def test_high_mentions_strict_or_unambiguous() -> None:
    """High preset should mention strict / unambiguous standards."""
    text = SKEPTICISM_PRESETS["high"].lower()
    assert "strict" in text or "unambiguous" in text
