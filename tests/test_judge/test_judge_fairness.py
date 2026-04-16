"""Judge fairness tests — cross-vendor selection and self-judge prevention.

The evaluation protocol requires that the judge is always a different vendor
than the agent. ``select_judge_model`` implements this mapping. If it ever
returns a same-vendor judge, results are biased (self-judging inflates scores
for the agent's vendor).

These tests lock the cross-vendor invariant for every model family the
orchestrator may encounter.
"""

from __future__ import annotations

import pytest

from healthcraft.llm.judge import select_judge_model

# ---------------------------------------------------------------------------
# Cross-vendor: agent -> judge must be different vendor
# ---------------------------------------------------------------------------

_VENDOR_FAMILIES = {
    "anthropic": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
    "openai": ["gpt-5.4", "gpt-5.2", "gpt-4o"],
    "google": ["gemini-3.1-pro", "gemini-2.0-flash"],
    "xai": ["grok-4.1", "grok-4.0"],
}


def _vendor_of(model: str) -> str:
    """Return the vendor family of a model string."""
    m = model.lower()
    if "claude" in m or "opus" in m or "sonnet" in m or "haiku" in m:
        return "anthropic"
    if "gpt" in m:
        return "openai"
    if "gemini" in m:
        return "google"
    if "grok" in m:
        return "xai"
    return "unknown"


def _all_agent_models() -> list[str]:
    """Flatten all known agent model strings."""
    return [m for models in _VENDOR_FAMILIES.values() for m in models]


@pytest.mark.parametrize("agent_model", _all_agent_models())
def test_judge_is_different_vendor(agent_model: str) -> None:
    """Judge must be a different vendor than the agent."""
    judge = select_judge_model(agent_model)
    agent_vendor = _vendor_of(agent_model)
    judge_vendor = _vendor_of(judge)
    assert agent_vendor != judge_vendor, (
        f"Self-judging: agent={agent_model} (vendor={agent_vendor}) -> "
        f"judge={judge} (vendor={judge_vendor}). The evaluation protocol "
        f"requires cross-vendor judging to prevent bias."
    )


# ---------------------------------------------------------------------------
# Known mappings (regression guards)
# ---------------------------------------------------------------------------


def test_claude_agent_gets_gpt_judge() -> None:
    """Anthropic agent -> OpenAI judge (the V8 default)."""
    judge = select_judge_model("claude-opus-4-6")
    assert "gpt" in judge.lower()


def test_gpt_agent_gets_claude_judge() -> None:
    """OpenAI agent -> Anthropic judge (the V8 default)."""
    judge = select_judge_model("gpt-5.4")
    assert "claude" in judge.lower()


def test_gemini_agent_gets_non_google_judge() -> None:
    """Google agent -> non-Google judge."""
    judge = select_judge_model("gemini-3.1-pro")
    assert "gemini" not in judge.lower()


def test_unknown_model_gets_a_judge() -> None:
    """Unknown model string should still return a valid judge, not crash."""
    judge = select_judge_model("totally-unknown-model-v99")
    assert isinstance(judge, str)
    assert len(judge) > 0


# ---------------------------------------------------------------------------
# Determinism: same input -> same output
# ---------------------------------------------------------------------------


def test_select_judge_model_is_deterministic() -> None:
    """Calling select_judge_model twice with the same input -> same result."""
    for model in _all_agent_models():
        a = select_judge_model(model)
        b = select_judge_model(model)
        assert a == b, f"Nondeterministic: {model} -> {a} then {b}"
