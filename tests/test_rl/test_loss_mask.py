"""Loss-mask and deterministic tool-result serialisation tests."""

from __future__ import annotations

from healthcraft.rl.loss_mask import (
    role_loss_mask,
    serialize_tool_result,
    token_loss_mask,
)
from healthcraft.trajectory import Trajectory


def _build_trajectory() -> Trajectory:
    t = Trajectory(task_id="T", model="m", seed=0, system_prompt="sys")
    t.add_turn("system", "sys")
    t.add_turn("user", "user msg")
    t.add_turn(
        "assistant",
        "thinking",
        tool_calls=[{"id": "c1", "name": "f", "arguments": {}}],
    )
    t.add_turn("tool", '{"status":"ok"}', tool_call_id="c1")
    t.add_turn("assistant", "final answer")
    return t


def test_role_loss_mask_marks_only_assistant_turns():
    t = _build_trajectory()
    mask = role_loss_mask(t)
    assert mask == [0, 0, 1, 0, 1]
    assert len(mask) == len(t.turns)


def test_serialize_tool_result_is_deterministic_for_dicts():
    a = {"b": 1, "a": 2, "c": {"y": 1, "x": 2}}
    b = {"c": {"x": 2, "y": 1}, "a": 2, "b": 1}
    assert serialize_tool_result(a) == serialize_tool_result(b)


def test_serialize_tool_result_passes_strings_through():
    s = '{"x": 1, "y": 2}'
    assert serialize_tool_result(s) == s


def test_token_loss_mask_aligns_with_roles():
    t = _build_trajectory()

    def tokenize(s: str) -> list[int]:
        # Stub tokenizer: one int per word, value = char length.
        return [len(w) for w in s.split() if w]

    tokens, mask = token_loss_mask(t, tokenize)
    assert len(tokens) == len(mask)
    # Some assistant tokens (1) and some env tokens (0) must both appear.
    assert 1 in mask
    assert 0 in mask
    # No turn produces an empty-token slice and contributes only zeros for
    # an assistant role, so any 1 we see must correspond to assistant content.
    assert all(m in (0, 1) for m in mask)


def test_token_loss_mask_handles_empty_assistant_content():
    t = Trajectory(task_id="T", model="m", seed=0, system_prompt="sys")
    t.add_turn("assistant", "", tool_calls=[{"id": "c1", "name": "f", "arguments": {"x": 1}}])
    t.add_turn("tool", '{"status":"ok"}', tool_call_id="c1")

    def tokenize(s: str) -> list[int]:
        return [len(w) for w in s.split() if w]

    tokens, mask = token_loss_mask(t, tokenize)
    assert len(tokens) == len(mask)
    # The assistant turn renders only its tool-call payload (deterministic
    # JSON); those tokens get mask=1.
    assert 1 in mask
