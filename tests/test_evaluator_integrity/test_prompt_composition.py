"""Snapshot test for the composed system prompt.

The orchestrator builds the agent's system prompt by concatenating four
files (base.txt + mercy_point.txt + policies.txt + tool_reference.txt) joined
by `\\n\\n`. A silent edit to any of those files changes agent behavior in
ways that won't show up in unit tests; the V8 snapshot in
`tests/fixtures/prompt_snapshots/base_composed.txt` is the diff line in CI.

When this test fails it means a system-prompts/*.txt edit has happened.
That is intentional in some cases — when it is, regenerate the snapshot
with `_regenerate_snapshot()` below and update the whitepaper appendix
that quotes the prompt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from healthcraft.llm.orchestrator import _load_system_prompt
from healthcraft.tasks.loader import Task

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "prompt_snapshots" / "base_composed.txt"
SYSTEM_PROMPT_DIR = REPO_ROOT / "system-prompts"


def _placeholder_task() -> Task:
    """A minimal Task suitable for prompt composition.

    We don't care about the task contents — composition only branches on
    `system_prompt_override`, which must be None to exercise the default
    concatenation path.
    """
    return Task(
        id="SNAPSHOT-X",
        category="clinical_reasoning",
        level=1,
        title="snapshot",
        description="snapshot",
        initial_state={},
        expected_tools=(),
        criteria=(),
        metadata={},
    )


# ---------------------------------------------------------------------------
# Composition snapshot
# ---------------------------------------------------------------------------


def test_composed_prompt_matches_snapshot() -> None:
    """The composed default prompt is byte-identical to the V8 snapshot.

    To regenerate after an intentional edit, run:

        from healthcraft.llm.orchestrator import _load_system_prompt
        from healthcraft.tasks.loader import Task
        # build a placeholder Task as in this module
        Path('tests/fixtures/prompt_snapshots/base_composed.txt') \\
            .write_text(_load_system_prompt(t))

    AND update the whitepaper appendix so the published prompt matches.
    """
    composed = _load_system_prompt(_placeholder_task())
    expected = SNAPSHOT.read_text(encoding="utf-8")

    if composed != expected:
        # Show a compact diff hint instead of the full 10KB blob.
        from difflib import unified_diff

        diff = "\n".join(
            unified_diff(
                expected.splitlines(),
                composed.splitlines(),
                fromfile="snapshot",
                tofile="composed",
                lineterm="",
                n=2,
            )
        )
        # Truncate diff to keep the test report readable.
        max_chars = 4000
        if len(diff) > max_chars:
            diff = diff[:max_chars] + "\n... [truncated]"
        pytest.fail(
            "Composed system prompt differs from the V8 snapshot. "
            "Either revert the system-prompts/*.txt edit or regenerate "
            "the snapshot AND update the whitepaper appendix.\n\n" + diff
        )


# ---------------------------------------------------------------------------
# Composition mechanics
# ---------------------------------------------------------------------------


_EXPECTED_COMPONENTS = ("base.txt", "mercy_point.txt", "policies.txt", "tool_reference.txt")


def test_all_expected_component_files_exist() -> None:
    """The four prompt component files must exist on disk."""
    missing = [f for f in _EXPECTED_COMPONENTS if not (SYSTEM_PROMPT_DIR / f).exists()]
    assert not missing, f"Missing system-prompts files: {missing}"


def test_composed_prompt_contains_all_components_in_order() -> None:
    """Each component file's first line appears in the composed prompt, in order.

    Catches reordering bugs (e.g. policies before base) without becoming
    fragile to internal edits within a component.
    """
    composed = _load_system_prompt(_placeholder_task())
    last_idx = -1
    for fname in _EXPECTED_COMPONENTS:
        first_line = (SYSTEM_PROMPT_DIR / fname).read_text(encoding="utf-8").splitlines()[0]
        idx = composed.find(first_line)
        assert idx >= 0, f"Component {fname!r} not found in composed prompt"
        assert idx > last_idx, f"Component {fname!r} appears out of order in composed prompt"
        last_idx = idx


def test_composed_prompt_uses_double_newline_separator() -> None:
    """Components are joined by '\\n\\n', not just '\\n'.

    A spacing change here could change tokenization for the agent.
    """
    composed = _load_system_prompt(_placeholder_task())
    # Find the boundary between base.txt and mercy_point.txt
    base_first = (SYSTEM_PROMPT_DIR / "base.txt").read_text(encoding="utf-8").splitlines()[0]
    mp_first = (SYSTEM_PROMPT_DIR / "mercy_point.txt").read_text(encoding="utf-8").splitlines()[0]
    base_idx = composed.find(base_first)
    mp_idx = composed.find(mp_first)
    assert 0 <= base_idx < mp_idx
    # The end of base.txt content + '\n\n' + start of mp.txt content
    base_text = (SYSTEM_PROMPT_DIR / "base.txt").read_text(encoding="utf-8")
    boundary = composed[base_idx + len(base_text) : mp_idx]
    assert boundary == "\n\n", (
        f"Component separator must be '\\n\\n', got {boundary!r}. Tokenization "
        f"is sensitive to this; even one extra newline shifts tokens."
    )


# ---------------------------------------------------------------------------
# Override path
# ---------------------------------------------------------------------------


def test_override_path_returns_override_string() -> None:
    """When system_prompt_override names a path that does NOT exist, the
    override string itself is returned verbatim (no concatenation)."""
    t = Task(
        id="OVR",
        category="clinical_reasoning",
        level=1,
        title="ovr",
        description="ovr",
        initial_state={},
        expected_tools=(),
        criteria=(),
        metadata={},
        system_prompt_override="literal-prompt-string",
    )
    assert _load_system_prompt(t) == "literal-prompt-string"


def test_override_path_loads_file_when_present(tmp_path: Path, monkeypatch) -> None:
    """When system_prompt_override names an existing file in system-prompts/,
    its contents are returned (not concatenated with components)."""
    # Patch the orchestrator's _SYSTEM_PROMPT_DIR to point to a tmp dir
    import healthcraft.llm.orchestrator as orch

    custom_file = tmp_path / "custom.txt"
    custom_file.write_text("CUSTOM PROMPT BODY", encoding="utf-8")
    monkeypatch.setattr(orch, "_SYSTEM_PROMPT_DIR", tmp_path)

    t = Task(
        id="OVR-FILE",
        category="clinical_reasoning",
        level=1,
        title="ovr",
        description="ovr",
        initial_state={},
        expected_tools=(),
        criteria=(),
        metadata={},
        system_prompt_override="custom.txt",
    )
    out = orch._load_system_prompt(t)
    assert out == "CUSTOM PROMPT BODY"


# ---------------------------------------------------------------------------
# Snapshot freshness sanity (length is in expected ballpark)
# ---------------------------------------------------------------------------


def test_snapshot_is_nonempty_and_reasonable_size() -> None:
    """A 10-byte or 1-MB snapshot is almost certainly wrong."""
    text = SNAPSHOT.read_text(encoding="utf-8")
    assert 1000 < len(text) < 100_000, (
        f"Snapshot size {len(text)} is outside reasonable range for the composed prompt"
    )
