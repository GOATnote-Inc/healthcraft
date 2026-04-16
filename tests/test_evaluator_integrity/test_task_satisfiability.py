"""Task satisfiability — every world_state criterion has a reachable handler.

A world_state criterion reads ``audit_log contains call to <tool> [with
qualifier]`` (or the ``does not contain`` negation). For the criterion to
ever be satisfiable, there must be a real MCP tool that, given valid input,
writes an audit entry that satisfies the check. If a criterion references a
tool that does not exist, that criterion will *always* fail — silently
penalizing every model that sees the task.

This test walks all 195 tasks and, for every ``world_state`` criterion:

  1. Normalizes the check string the same way ``_verify_world_state`` does
     (expand bare-tool alternatives, then AND/OR split).
  2. Extracts each clause's tool via ``_extract_tool_and_params``.
  3. Asserts the lowercased tool name maps to a real entry in
     ``TOOL_NAME_MAP``.
  4. For qualifiers that correspond to schema enums (``order_type``,
     ``status``), asserts the qualifier value is accepted by the handler.

Why this matters: the V7 -> V8 transition surfaced six infrastructure bugs
where checks referenced tools that had been renamed, split, or removed.
This test is the shortest feedback loop — a rename now fails in seconds,
not after a pilot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from healthcraft.mcp.server import TOOL_NAME_MAP
from healthcraft.mcp.tools import mutate_tools, workflow_tools
from healthcraft.tasks.evaluator import (
    _expand_tool_alternatives,
    _extract_tool_and_params,
    _parse_criteria,
    _split_compound,
)
from healthcraft.tasks.loader import load_tasks
from healthcraft.tasks.rubrics import VerificationMethod

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = REPO_ROOT / "configs" / "tasks"

# Canonical lowercased tool name set. The evaluator lowercases both sides
# of the comparison in `_verify_single_clause`, so we match that convention.
_VALID_TOOLS_LOWER = frozenset(name.lower() for name in TOOL_NAME_MAP)

# Qualifier name -> set of values the handler will accept. Keys match what
# ``_extract_tool_and_params`` emits when the qualifier is a known
# enum-bound parameter (see ``_QUALIFIER_PARAM_MAP``).
_QUALIFIER_ENUMS: dict[str, frozenset[str]] = {
    "order_type": frozenset(mutate_tools._VALID_ORDER_TYPES),
    "status": frozenset(mutate_tools._VALID_TASK_STATUSES),
    "transport_mode": frozenset(workflow_tools._VALID_TRANSPORT_MODES),
}


# ---------------------------------------------------------------------------
# Helpers — mirror the evaluator's parsing so test and runtime agree.
# ---------------------------------------------------------------------------


def _iter_check_clauses(check: str) -> list[str]:
    """Yield the clauses the evaluator would split a check into.

    Mirrors ``_verify_world_state``: first expand bare-tool alternatives,
    then split AND, then split OR. Returns a flat list of single-clause
    strings. We do AND then OR to match the evaluator precedence.
    """
    expanded = _expand_tool_alternatives(check)
    clauses = _split_compound(expanded, "AND")
    if len(clauses) == 1:
        clauses = _split_compound(expanded, "OR")
    return clauses


def _parse_clause(clause: str) -> tuple[str, dict[str, str]]:
    """Extract ``(tool_lower, params)`` from one clause.

    Returns ``("", {})`` if the clause contains no recognizable directive —
    the caller treats that as a separate error class.
    """
    lower = clause.lower()
    if "does not contain" in lower or "not contain" in lower:
        return _extract_tool_and_params(lower, "not contain")
    if "contains" in lower:
        return _extract_tool_and_params(lower, "contains")
    return "", {}


# ---------------------------------------------------------------------------
# Test 1: every world_state criterion names a real tool
# ---------------------------------------------------------------------------


def test_every_world_state_criterion_references_real_tool() -> None:
    """Every world_state check resolves its tool reference to a real MCP tool.

    A missing tool means the criterion is unsatisfiable by construction and
    silently penalizes every model that attempts the task.
    """
    orphans: list[str] = []
    unparseable: list[str] = []

    for task in load_tasks(TASK_DIR):
        for crit in _parse_criteria(task.criteria):
            if crit.verification != VerificationMethod.WORLD_STATE:
                continue
            for clause in _iter_check_clauses(crit.check):
                tool, _params = _parse_clause(clause)
                if not tool:
                    unparseable.append(
                        f"{task.id}/{crit.id}: no directive in clause {clause.strip()!r}"
                    )
                    continue
                if tool not in _VALID_TOOLS_LOWER:
                    orphans.append(
                        f"{task.id}/{crit.id}: unknown tool {tool!r} in clause {clause.strip()!r}"
                    )

    messages: list[str] = []
    if orphans:
        messages.append(f"{len(orphans)} world_state criterion clause(s) reference unknown tools:")
        messages.extend("  " + o for o in orphans)
    if unparseable:
        messages.append(
            f"{len(unparseable)} world_state criterion clause(s) have no recognizable directive:"
        )
        messages.extend("  " + u for u in unparseable)
    assert not messages, "\n".join(messages)


# ---------------------------------------------------------------------------
# Test 2: enum-bound qualifier values are accepted by the handler
# ---------------------------------------------------------------------------


def test_enum_qualifiers_are_accepted_by_handler() -> None:
    """Qualifiers like `for lab` or `for medication` must be handler-accepted.

    ``_QUALIFIER_PARAM_MAP`` emits structured keys (``order_type``,
    ``status``, ``transport_mode``) when it recognizes a qualifier. Each of
    those keys has a bounded enum; the qualifier value must be in the
    handler's enum or the audit match will never trigger.
    """
    bad: list[str] = []
    for task in load_tasks(TASK_DIR):
        for crit in _parse_criteria(task.criteria):
            if crit.verification != VerificationMethod.WORLD_STATE:
                continue
            for clause in _iter_check_clauses(crit.check):
                _tool, params = _parse_clause(clause)
                for key, accepted in _QUALIFIER_ENUMS.items():
                    if key in params and params[key] not in accepted:
                        bad.append(
                            f"{task.id}/{crit.id}: qualifier {key}={params[key]!r} "
                            f"not in handler enum {sorted(accepted)} "
                            f"(clause: {clause.strip()!r})"
                        )
    assert not bad, (
        f"{len(bad)} enum-qualifier mismatch(es) between task checks and "
        f"handler enums:\n  " + "\n  ".join(bad)
    )


# ---------------------------------------------------------------------------
# Test 3: self-test — parser heuristics still recognize canonical forms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clause,expected_tool,expected_param_key",
    [
        ("audit_log contains call to getPatientHistory", "getpatienthistory", None),
        (
            "audit_log contains call to createClinicalOrder for lab",
            "createclinicalorder",
            "order_type",
        ),
        (
            "audit_log does NOT contain createClinicalOrder with medication matching warfarin",
            "createclinicalorder",
            "_match",
        ),
        (
            "audit_log contains call to updateTaskStatus",
            "updatetaskstatus",
            None,
        ),
    ],
)
def test_parser_round_trip(clause: str, expected_tool: str, expected_param_key: str | None) -> None:
    """Guards `_parse_clause` against a heuristic regression that would
    orphan otherwise-valid criteria."""
    tool, params = _parse_clause(clause)
    assert tool == expected_tool, f"{clause!r} -> tool={tool!r}"
    if expected_param_key is not None:
        assert expected_param_key in params, f"expected param {expected_param_key!r} in {params}"


# ---------------------------------------------------------------------------
# Test 4: aggregate coverage report (informational, always passes)
# ---------------------------------------------------------------------------


def test_world_state_tool_distribution_reported(capsys: pytest.CaptureFixture) -> None:
    """Prints how often each tool is referenced by world_state criteria.

    Not a correctness assertion — a diagnostic. If one tool suddenly shows
    up zero times after a rename, it will be visible in the pytest -s
    output next to the other satisfiability tests.
    """
    counts: dict[str, int] = {t: 0 for t in _VALID_TOOLS_LOWER}
    for task in load_tasks(TASK_DIR):
        for crit in _parse_criteria(task.criteria):
            if crit.verification != VerificationMethod.WORLD_STATE:
                continue
            for clause in _iter_check_clauses(crit.check):
                tool, _ = _parse_clause(clause)
                if tool in counts:
                    counts[tool] += 1

    # Print — useful when run with `pytest -s`. Asserts only that we found
    # at least SOME world_state references (otherwise a schema rewrite has
    # silently nuked the check parser).
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    for tool, n in ordered:
        if n > 0:
            print(f"{tool:30s} {n:4d}")
    total = sum(counts.values())
    assert total > 0, (
        "No world_state criteria resolved to any known tool — the parser or schema has drifted."
    )
