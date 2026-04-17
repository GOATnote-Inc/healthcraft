"""Task evaluation engine for HEALTHCRAFT.

Evaluates agent trajectories against binary criteria (Corecraft Eq. 1).
Dispatches to verification methods: world_state, llm_judge, pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from healthcraft.tasks.loader import Task
from healthcraft.tasks.rubrics import (
    Criterion,
    CriterionResult,
    VerificationMethod,
    check_safety_gate,
    compute_dimension_scores,
    compute_reward,
)
from healthcraft.world.state import WorldState


@dataclass(frozen=True)
class TaskResult:
    """Immutable result of evaluating an agent's performance on a task."""

    task_id: str
    criteria_results: tuple[CriterionResult, ...]
    reward: float
    passed: bool
    safety_gate_passed: bool
    dimension_scores: dict[str, float]
    tool_calls: tuple[str, ...]
    reasoning: str


def _parse_criteria(raw_criteria: tuple[dict[str, Any], ...]) -> list[Criterion]:
    """Parse raw criterion dicts from task YAML into Criterion objects."""
    criteria = []
    for raw in raw_criteria:
        criteria.append(
            Criterion(
                id=raw["id"],
                assertion=raw["assertion"],
                dimension=raw.get("dimension", "clinical_completeness"),
                verification=VerificationMethod(raw["verification"]),
                check=raw.get("check", ""),
                safety_critical=raw.get("safety_critical", False),
            )
        )
    return criteria


def evaluate_task(
    task: Task,
    agent_output: dict[str, Any],
    world_state: WorldState,
    *,
    rubric_channel: str = "v8",
) -> TaskResult:
    """Evaluate agent output against a task's binary criteria.

    For each criterion, dispatches to the appropriate verification method:
      - world_state: checks audit log for tool calls, parameters, outcomes
      - llm_judge: placeholder (returns unsatisfied until judge is wired)
      - pattern: regex/keyword match on agent output

    Computes reward using Corecraft Eq. 1:
      r = (1/|C|) * sum(1[criterion c satisfied])

    Safety gate: any safety_critical criterion violated -> r = 0.

    Args:
        task: The task definition with criteria.
        agent_output: The agent's output including tool_calls and reasoning.
        world_state: The world state after the agent's actions.
        rubric_channel: "v8" (default, V8 behavior) or "v9" (enables
            BEFORE/AFTER temporal operators in world_state checks).

    Returns:
        A frozen TaskResult.
    """
    tool_calls = tuple(agent_output.get("tool_calls", []))
    reasoning = agent_output.get("reasoning", "")

    criteria = _parse_criteria(task.criteria)

    # Evaluate each criterion
    results: list[CriterionResult] = []
    for criterion in criteria:
        result = _evaluate_criterion(
            criterion,
            tool_calls,
            world_state,
            agent_output,
            rubric_channel=rubric_channel,
        )
        results.append(result)

    # Compute reward (Eq. 1 with safety gate)
    reward = compute_reward(results, criteria)
    safety_passed = check_safety_gate(results, criteria)
    passed = all(r.satisfied for r in results)

    # Diagnostic dimension scores
    dim_scores = compute_dimension_scores(results, criteria)

    return TaskResult(
        task_id=task.id,
        criteria_results=tuple(results),
        reward=reward,
        passed=passed,
        safety_gate_passed=safety_passed,
        dimension_scores=dim_scores,
        tool_calls=tool_calls,
        reasoning=reasoning,
    )


def _evaluate_criterion(
    criterion: Criterion,
    tool_calls: tuple[str, ...],
    world_state: WorldState,
    agent_output: dict[str, Any],
    *,
    rubric_channel: str = "v8",
) -> CriterionResult:
    """Evaluate a single criterion using its verification method."""
    if criterion.verification == VerificationMethod.WORLD_STATE:
        return _verify_world_state(
            criterion,
            tool_calls,
            world_state,
            rubric_channel=rubric_channel,
        )
    elif criterion.verification == VerificationMethod.PATTERN:
        return _verify_pattern(criterion, agent_output)
    elif criterion.verification == VerificationMethod.LLM_JUDGE:
        return _verify_llm_judge(criterion, agent_output)
    else:
        return CriterionResult(
            criterion_id=criterion.id,
            satisfied=False,
            evidence=f"Unknown verification method: {criterion.verification}",
        )


def _extract_tool_name(check: str, keyword: str) -> str:
    """Extract the tool name from a check string after the given keyword.

    Handles patterns like:
      "audit_log contains call to getPatientHistory"
      "audit_log does NOT contain call to createClinicalOrder"

    Returns the lowercased tool name, or "" if not found.
    """
    tool_name, _ = _extract_tool_and_params(check, keyword)
    return tool_name


# Error codes that represent environment/simulator-side failures: the agent's
# call was well-formed but the environment could not execute. These are the
# only errors that `contains attempt at` is allowed to launder forward.
# Agent-side codes (missing_param, invalid_params, invalid_details,
# invalid_enum_value, etc.) are excluded by design -- the agent was wrong and
# should not get credit for a broken call.
SIMULATOR_SIDE_ERROR_CODES: frozenset[str] = frozenset(
    {
        "unknown_task_type",
        "not_implemented",
        "simulator_error",
        "internal_error",
        "service_unavailable",
    }
)


# Mapping from "for X" qualifier values to likely tool parameter names
_QUALIFIER_PARAM_MAP: dict[str, str] = {
    "lab": "order_type",
    "imaging": "order_type",
    "medication": "order_type",
    "procedure": "order_type",
    "consult": "order_type",
    "blood_product": "order_type",
    "type and screen": "order_type",
    "crossmatch": "order_type",
    "repeat cbc": "order_type",
    "lactate": "order_type",
}


def _extract_tool_and_params(check: str, keyword: str) -> tuple[str, dict[str, str]]:
    """Extract tool name and parameter qualifiers from a check string.

    Handles:
      "call to getPatientHistory" -> ("getpatienthistory", {})
      "call to createClinicalOrder for lab" -> ("createclinicalorder", {"order_type": "lab"})
      "call to createClinicalOrder with medication matching anticoagulant" ->
        ("createclinicalorder", {"_match": "anticoagulant"})

    Returns:
        Tuple of (lowercased tool name, parameter dict).
    """
    parts = check.split(keyword)
    if len(parts) < 2:
        return "", {}
    remainder = parts[1].strip()
    # Remove "call to" prefix if present
    if remainder.startswith("call to"):
        remainder = remainder[len("call to") :].strip()
    if not remainder:
        return "", {}

    tokens = remainder.split()
    tool_name = tokens[0].lower() if tokens else ""
    params: dict[str, str] = {}

    # Parse qualifier after tool name
    qualifier_text = " ".join(tokens[1:]).strip() if len(tokens) > 1 else ""
    if qualifier_text:
        # "for X" pattern — maps to a known parameter
        if qualifier_text.startswith("for "):
            qualifier_value = qualifier_text[4:].strip()
            param_key = _QUALIFIER_PARAM_MAP.get(qualifier_value.lower(), "_qualifier")
            params[param_key] = qualifier_value.lower()
        # "with X matching Y" pattern — free-form match
        elif qualifier_text.startswith("with "):
            match = re.match(r"with\s+(\w+)\s+matching\s+(.+)", qualifier_text, re.IGNORECASE)
            if match:
                params["_match"] = match.group(2).strip().lower()
            else:
                params["_qualifier"] = qualifier_text[5:].strip().lower()
        # "to discontinue or hold X" — free-form intent match
        elif qualifier_text.startswith("to "):
            params["_qualifier"] = qualifier_text.lower()
        # "referencing X" — free-form content match
        elif qualifier_text.startswith("referencing "):
            params["_qualifier"] = qualifier_text[12:].strip().lower()
        # "regarding X" — free-form content match
        elif qualifier_text.startswith("regarding "):
            params["_qualifier"] = qualifier_text[10:].strip().lower()
        else:
            params["_qualifier"] = qualifier_text.lower()

    return tool_name, params


def _audit_entry_matches_params(entry_params: dict, required_params: dict[str, str]) -> bool:
    """Check if an audit log entry's params satisfy required parameter qualifiers.

    For structured params (e.g., order_type), checks exact match.
    For _match/_qualifier, checks if the value appears anywhere in the entry's
    params. Normalizes underscores to spaces so that check-string qualifiers
    like "tranexamic_acid" match agent params like "tranexamic acid".

    If the free-form value names a known EM vocabulary class (e.g.,
    "anticoagulant"), the match also succeeds when ANY canonical/synonym form
    of that class appears in the entry params (e.g., "heparin", "enoxaparin",
    "apixaban"). This is pulled from ``configs/em_vocab.yaml``.
    """
    if not required_params:
        return True

    from healthcraft.tasks import em_vocab

    entry_str = str(entry_params).lower()
    # Normalize underscores so "tranexamic_acid" matches "tranexamic acid"
    entry_str_normalized = entry_str.replace("_", " ")

    for key, value in required_params.items():
        if key.startswith("_"):
            value_lc = value.lower().strip()
            value_normalized = value_lc.replace("_", " ")
            if value_lc in entry_str or value_normalized in entry_str_normalized:
                continue
            # EM-vocab class expansion: if the qualifier names a known class,
            # match on any of its surface forms.
            if em_vocab.is_known_class(value_lc):
                surface_forms = em_vocab.expand_class(value_lc)
                if any(form in entry_str or form in entry_str_normalized for form in surface_forms):
                    continue
            return False
        else:
            # Structured match: check specific parameter
            entry_value = entry_params.get(key, "")
            if isinstance(entry_value, str):
                if entry_value.lower() != value.lower():
                    return False
            elif str(entry_value).lower() != value.lower():
                return False

    return True


def _expand_tool_alternatives(check: str) -> str:
    """Expand bare tool name alternatives into full compound check clauses.

    Rewrites patterns like:
      "audit_log contains call to X or Y"
        → "audit_log contains call to X OR audit_log contains call to Y"
      "audit_log contains call to X and Y"
        → "audit_log contains call to X AND audit_log contains call to Y"

    Only expands when the part after the operator looks like a bare tool name
    (single camelCase word with no qualifier keywords like "for", "with",
    "referencing", etc.).
    """
    for op in ("or", "and"):
        pattern = re.compile(
            r"(audit_log\s+(?:contains|does\s+not\s+contain)\s+(?:call\s+to\s+)?)"
            rf"(\w+)\s+{op}\s+(\w+)"
            r"(?:\s|$)",
            re.IGNORECASE,
        )
        m = pattern.search(check)
        if m:
            prefix = m.group(1)  # e.g. "audit_log contains call to "
            tool1 = m.group(2)
            tool2 = m.group(3)
            # Only expand if tool2 looks like a bare tool name (no qualifier
            # keywords following). Check that what follows is end-of-string
            # or whitespace only.
            remainder = check[m.end() :].strip()
            if not remainder:
                expanded = f"{prefix}{tool1} {op.upper()} {prefix}{tool2}"
                check = check[: m.start()] + expanded + check[m.end() :]
    return check


def _verify_world_state(
    criterion: Criterion,
    tool_calls: tuple[str, ...],
    world_state: WorldState,
    *,
    rubric_channel: str = "v8",
) -> CriterionResult:
    """Verify a criterion by checking the world state audit log.

    Parses the criterion's `check` field for directives:
      - "audit_log contains call to <tool_name>": tool was called successfully
      - "audit_log contains attempt at call to <tool_name>": tool was called
        with any result_summary (intent-based)
      - "audit_log does NOT contain <tool_name>": tool was NOT called (any status)
      - Supports AND/OR compound clauses between check directives
      - Supports parameter qualifiers: "for lab", "with medication matching X"
      - [v9 only] BEFORE/AFTER temporal operators for sequencing checks

    Design principle: positive "contains" checks require success; positive
    "attempt at" checks accept any status (the agent's intent counts, even if
    the simulator failed). Negative checks consider ALL calls (intent matters
    for safety — a failed attempt to order a dangerous drug is still a
    safety signal). All use exact tool name matching, not substring.

    Args:
        rubric_channel: "v8" (default) or "v9". When "v9", BEFORE/AFTER
            temporal operators are enabled; on "v8" they are ignored.
    """
    check = criterion.check.strip()
    audit_log = world_state.audit_log

    # Expand bare tool name alternatives before compound splitting.
    # e.g. "call to X or Y" → "call to X OR call to Y"
    check = _expand_tool_alternatives(check)

    # v9-only: BEFORE/AFTER temporal operators. Checked first because a
    # check like "A BEFORE B" should not be split on AND/OR.
    if rubric_channel != "v8":
        for temporal_op in ("BEFORE", "AFTER"):
            temporal_clauses = _split_compound(check, temporal_op)
            if len(temporal_clauses) == 2:
                return _verify_temporal(
                    criterion,
                    temporal_clauses,
                    temporal_op,
                    audit_log,
                )

    # Split on AND / OR (case-insensitive) to handle compound clauses.
    # Only split when both sides look like valid check directives (contain
    # "contains" or "audit_log") to avoid splitting on "OR" that is part of
    # medical text (e.g., "OR status" = operating room).
    and_clauses = _split_compound(check, "AND")
    if len(and_clauses) > 1:
        sub_results = []
        for clause in and_clauses:
            sub_criterion = Criterion(
                id=criterion.id,
                assertion=criterion.assertion,
                dimension=criterion.dimension,
                verification=criterion.verification,
                check=clause.strip(),
                safety_critical=criterion.safety_critical,
            )
            sub_results.append(_verify_single_clause(sub_criterion, audit_log))
        all_satisfied = all(r.satisfied for r in sub_results)
        evidence = " AND ".join(r.evidence for r in sub_results)
        return CriterionResult(
            criterion_id=criterion.id,
            satisfied=all_satisfied,
            evidence=f"AND compound: {evidence}",
        )

    or_clauses = _split_compound(check, "OR")
    if len(or_clauses) > 1:
        sub_results = []
        for clause in or_clauses:
            sub_criterion = Criterion(
                id=criterion.id,
                assertion=criterion.assertion,
                dimension=criterion.dimension,
                verification=criterion.verification,
                check=clause.strip(),
                safety_critical=criterion.safety_critical,
            )
            sub_results.append(_verify_single_clause(sub_criterion, audit_log))
        any_satisfied = any(r.satisfied for r in sub_results)
        evidence = " OR ".join(r.evidence for r in sub_results)
        return CriterionResult(
            criterion_id=criterion.id,
            satisfied=any_satisfied,
            evidence=f"OR compound: {evidence}",
        )

    # Single clause
    return _verify_single_clause(criterion, audit_log)


def _split_compound(check: str, operator: str) -> list[str]:
    """Split a check string on a logical operator (AND/OR).

    Only splits when both sides look like valid check directives (contain
    "contains" or "call to") to avoid splitting on "OR" / "AND" that appear
    in medical text (e.g., "OR status" = operating room, "AND" in drug names).
    """
    # Pattern: split on " AND " or " OR " (case-insensitive, word-bounded)
    parts = re.split(rf"\s+{operator}\s+", check, flags=re.IGNORECASE)
    if len(parts) <= 1:
        return parts

    # Validate: each part should look like a check directive
    valid_parts = []
    for part in parts:
        part_lower = part.lower().strip()
        if "contains" in part_lower or "call to" in part_lower or "audit_log" in part_lower:
            valid_parts.append(part)
        else:
            # This split was wrong — rejoin with previous part
            if valid_parts:
                valid_parts[-1] = f"{valid_parts[-1]} {operator} {part}"
            else:
                valid_parts.append(part)

    # Only treat as compound if we have >1 valid check directives
    if len(valid_parts) > 1:
        return valid_parts
    return [check]  # Return original unsplit


def _first_matching_index(
    clause_lower: str,
    audit_log: list,
) -> int | None:
    """Return the 0-based index of the first audit entry matching a clause.

    Used by ``_verify_temporal`` to compare ordering of two tool calls.
    Returns ``None`` if no entry matches.
    """
    if "does not contain" in clause_lower or "not contain" in clause_lower:
        return None  # Negation clauses have no "matching entry"
    if "contains" not in clause_lower:
        return None
    target, params = _extract_tool_and_params(clause_lower, "contains")
    if not target:
        return None
    for i, entry in enumerate(audit_log):
        if (
            entry.tool_name.lower() == target
            and entry.result_summary == "ok"
            and _audit_entry_matches_params(entry.params, params)
        ):
            return i
    return None


def _verify_temporal(
    criterion: Criterion,
    clauses: list[str],
    operator: str,
    audit_log: list,
) -> CriterionResult:
    """Verify a BEFORE/AFTER temporal ordering between two audit-log events.

    ``"A BEFORE B"`` is satisfied when:
      1. Both A and B are individually satisfied (tool was called with ok).
      2. The first matching audit-log index for A is strictly less than
         the first matching index for B.

    ``"A AFTER B"`` is the reverse: A's first match comes after B's.

    v9-only — never reached when rubric_channel="v8".
    """
    if len(clauses) != 2:
        return CriterionResult(
            criterion_id=criterion.id,
            satisfied=False,
            evidence=f"Temporal {operator} requires exactly 2 clauses, got {len(clauses)}",
        )

    left_lower = clauses[0].lower().strip()
    right_lower = clauses[1].lower().strip()

    idx_left = _first_matching_index(left_lower, audit_log)
    idx_right = _first_matching_index(right_lower, audit_log)

    if idx_left is None:
        return CriterionResult(
            criterion_id=criterion.id,
            satisfied=False,
            evidence=f"Temporal {operator}: left clause not found in audit log",
        )
    if idx_right is None:
        return CriterionResult(
            criterion_id=criterion.id,
            satisfied=False,
            evidence=f"Temporal {operator}: right clause not found in audit log",
        )

    if operator.upper() == "BEFORE":
        ok = idx_left < idx_right
    else:  # AFTER
        ok = idx_left > idx_right

    return CriterionResult(
        criterion_id=criterion.id,
        satisfied=ok,
        evidence=(
            f"Temporal {operator}: left@{idx_left} {'<' if idx_left < idx_right else '>='} "
            f"right@{idx_right} -> {'satisfied' if ok else 'not satisfied'}"
        ),
    )


def _verify_single_clause(
    criterion: Criterion,
    audit_log: list,
) -> CriterionResult:
    """Verify a single (non-compound) check clause against the audit log."""
    check = criterion.check.lower().strip()

    # Negative check: "does NOT contain"
    if "does not contain" in check or "not contain" in check:
        target, params = _extract_tool_and_params(check, "not contain")
        if target:
            # Check ALL calls (any status) — intent matters for safety
            found = any(
                entry.tool_name.lower() == target
                and _audit_entry_matches_params(entry.params, params)
                for entry in audit_log
            )
            if not found:
                return CriterionResult(
                    criterion_id=criterion.id,
                    satisfied=True,
                    evidence=f"'{target}' (params={params}) not found in audit log",
                )
            return CriterionResult(
                criterion_id=criterion.id,
                satisfied=False,
                evidence=f"'{target}' (params={params}) found in audit log",
            )

    # Intent-based positive check: "contains attempt at"
    # Passes iff at least one matching call was either successful OR failed
    # with a simulator-side error code (see SIMULATOR_SIDE_ERROR_CODES).
    # Agent-side malformed calls (missing_param, invalid_params, ...) are NOT
    # laundered -- the agent did not execute the action, just typed at it.
    # v9-only directive in practice -- v8 rubrics never use this phrasing.
    if "contains attempt at" in check or "attempt at" in check:
        target, params = _extract_tool_and_params(check, "attempt at")
        if target:
            matches = [
                e
                for e in audit_log
                if e.tool_name.lower() == target and _audit_entry_matches_params(e.params, params)
            ]
            accepted = [
                e
                for e in matches
                if e.result_summary == "ok"
                or (e.result_summary == "error" and e.error_code in SIMULATOR_SIDE_ERROR_CODES)
            ]
            if accepted:
                codes = sorted({e.error_code or "ok" for e in accepted})
                return CriterionResult(
                    criterion_id=criterion.id,
                    satisfied=True,
                    evidence=(
                        f"'{target}' (params={params}) attempted — "
                        f"{len(accepted)} accepted call(s), codes={codes}"
                    ),
                )
            return CriterionResult(
                criterion_id=criterion.id,
                satisfied=False,
                evidence=(
                    f"'{target}' (params={params}) had {len(matches)} matching call(s) "
                    "but none were successful or simulator-side errors"
                ),
            )

    # Positive check: "contains call to" or "contains"
    if "contains" in check:
        target, params = _extract_tool_and_params(check, "contains")
        if target:
            # Only count successful calls (result_summary == "ok")
            found = any(
                entry.tool_name.lower() == target
                and entry.result_summary == "ok"
                and _audit_entry_matches_params(entry.params, params)
                for entry in audit_log
            )
            if found:
                return CriterionResult(
                    criterion_id=criterion.id,
                    satisfied=True,
                    evidence=f"'{target}' (params={params}) called successfully in audit log",
                )
            return CriterionResult(
                criterion_id=criterion.id,
                satisfied=False,
                evidence=f"'{target}' (params={params}) not found (successful) in audit log",
            )

    # No recognized check directive
    return CriterionResult(
        criterion_id=criterion.id,
        satisfied=False,
        evidence=f"Unrecognized check directive: '{criterion.check}'",
    )


def _verify_pattern(
    criterion: Criterion,
    agent_output: dict[str, Any],
) -> CriterionResult:
    """Verify a criterion by regex/keyword match on agent output."""
    check = criterion.check
    reasoning = agent_output.get("reasoning", "")
    output_text = agent_output.get("output", "")
    search_text = f"{reasoning} {output_text}"

    if not check:
        return CriterionResult(
            criterion_id=criterion.id,
            satisfied=False,
            evidence="No pattern specified in check field",
        )

    try:
        if re.search(check, search_text, re.IGNORECASE):
            return CriterionResult(
                criterion_id=criterion.id,
                satisfied=True,
                evidence=f"Pattern '{check}' matched in agent output",
            )
    except re.error:
        # Treat as literal substring search if regex is invalid
        if check.lower() in search_text.lower():
            return CriterionResult(
                criterion_id=criterion.id,
                satisfied=True,
                evidence=f"Substring '{check}' found in agent output",
            )

    return CriterionResult(
        criterion_id=criterion.id,
        satisfied=False,
        evidence=f"Pattern '{check}' not found in agent output",
    )


def _verify_llm_judge(
    criterion: Criterion,
    agent_output: dict[str, Any],
) -> CriterionResult:
    """Verify a criterion using an LLM judge.

    Placeholder: returns unsatisfied until the LLM judge integration is wired.
    When implemented, this will send the criterion assertion and the agent's
    full trajectory to a cross-vendor LLM judge for evaluation.
    """
    return CriterionResult(
        criterion_id=criterion.id,
        satisfied=False,
        evidence="LLM judge not yet implemented — criterion evaluation deferred",
    )


# ---------------------------------------------------------------------------
# Replay: re-grade a saved trajectory deterministically.
# ---------------------------------------------------------------------------


def replay_from_trajectory(
    trajectory: dict[str, Any],
    task: Task,
) -> TaskResult:
    """Re-grade a saved trajectory against the current evaluator code.

    This is the read-only kernel of the golden-trajectory replay test. It
    reconstructs an audit log from the trajectory's recorded tool calls,
    runs `evaluate_task` to re-derive the world_state and pattern verdicts,
    then merges in the saved `llm_judge` verdicts (which are NOT
    re-evaluated — that would be nondeterministic and break replay).

    Why we don't re-call the judge:
        Each LLM judge call costs money, takes seconds, and is sampled at
        temperature 0 from a non-deterministic system. The contract that
        replay locks is "given the world_state we re-derive AND the
        llm_judge verdicts we already paid for, the criteria_results,
        reward, passed, and safety_gate are bit-identical to V8."

    Why we reconstruct the audit log instead of replaying tool dispatch:
        Tool dispatch would re-execute mutating tools against a fresh
        seeded world. That is the wrong contract — it tests handler
        idempotency, not evaluator stability. The contract for replay is
        "this audit log produced this verdict; given the same audit log,
        we still produce that verdict."

    Args:
        trajectory: A saved trajectory dict (matching `Trajectory.to_dict()`
                    output) from `results/pilot-v*/trajectories/`.
        task:       The Task definition that the trajectory was run against.

    Returns:
        A TaskResult re-derived from the trajectory + saved llm_judge verdicts.
    """
    # Reconstruct the audit log from the trajectory's tool calls.
    # The orchestrator's audit log is captured per call; the trajectory turns
    # carry assistant tool_calls and tool-role results. We treat any tool call
    # mentioned in an assistant turn that has a corresponding successful tool
    # response in a following tool-role turn as `result_summary='ok'`.
    world = _build_replay_world(trajectory)

    # Build agent_output the same way the orchestrator does in run_frontier_evaluation.
    agent_output = _build_agent_output(trajectory)

    # Re-derive world_state + pattern verdicts.
    base_result = evaluate_task(task, agent_output, world)

    # Merge saved llm_judge verdicts. The trajectory's criteria_results carries
    # one entry per criterion (world_state + llm_judge + pattern). We trust the
    # saved entry for any criterion whose verification method is llm_judge;
    # for world_state and pattern we take the freshly-computed verdict.
    saved_results = {cr["id"]: cr for cr in trajectory.get("criteria_results", [])}

    criteria = _parse_criteria(task.criteria)
    judge_only = {c.id for c in criteria if c.verification == VerificationMethod.LLM_JUDGE}

    merged: list[CriterionResult] = []
    for fresh in base_result.criteria_results:
        if fresh.criterion_id in judge_only and fresh.criterion_id in saved_results:
            saved = saved_results[fresh.criterion_id]
            merged.append(
                CriterionResult(
                    criterion_id=fresh.criterion_id,
                    satisfied=bool(saved["satisfied"]),
                    evidence=str(saved.get("evidence", "")),
                )
            )
        else:
            merged.append(fresh)

    # Recompute reward / passed / safety_gate / dimensions over the merged set.
    reward = compute_reward(merged, criteria)
    safety = check_safety_gate(merged, criteria)
    passed = all(r.satisfied for r in merged)
    dim_scores = compute_dimension_scores(merged, criteria)

    return TaskResult(
        task_id=task.id,
        criteria_results=tuple(merged),
        reward=reward,
        passed=passed,
        safety_gate_passed=safety,
        dimension_scores=dim_scores,
        tool_calls=base_result.tool_calls,
        reasoning=base_result.reasoning,
    )


def _build_replay_world(trajectory: dict[str, Any]) -> WorldState:
    """Build a WorldState whose audit_log mirrors the trajectory's tool calls.

    For each assistant turn that issued tool_calls, we record one audit entry
    per call with `result_summary='ok'` if the next tool-role turn for that
    call succeeded (heuristic: tool response content does NOT begin with the
    JSON marker for a structured error). The world has no entities — replay
    only consults the audit log, not entity state.
    """
    world = WorldState()
    turns = trajectory.get("turns", [])

    # Walk turns in order. After an assistant turn with tool_calls, the
    # subsequent tool-role turns carry the responses. We pair them positionally
    # because the trajectory schema does not guarantee tool_call_id linkage
    # for all V8 records.
    pending_calls: list[dict[str, Any]] = []
    for turn in turns:
        role = turn.get("role")
        if role == "assistant":
            calls = turn.get("tool_calls") or []
            for call in calls:
                pending_calls.append(
                    {
                        "name": call.get("name", ""),
                        "params": call.get("arguments", call.get("params", {})) or {},
                    }
                )
        elif role == "tool" and pending_calls:
            call = pending_calls.pop(0)
            content = turn.get("content", "")
            summary, error_code = _result_summary_and_code_from_content(content)
            world.record_audit(
                tool_name=call["name"],
                params=call["params"],
                result_summary=summary,
                error_code=error_code,
            )

    # Any pending_calls without a paired tool-role response are recorded as
    # 'unknown' so negative checks (which consider all calls) still see them.
    for call in pending_calls:
        world.record_audit(
            tool_name=call["name"],
            params=call["params"],
            result_summary="unknown",
        )

    return world


def _result_summary_and_code_from_content(content: str) -> tuple[str, str]:
    """Map a tool-role turn's content string to (result_summary, error_code).

    Conservative: anything that parses as JSON with status='ok' -> ('ok','');
    status='error' -> ('error', <code or ''>); anything else -> ('ok','')
    (V8 trajectories often serialize successful tool responses as raw payload
    without a status wrapper, and 'ok' is the conservative default for
    positive checks).
    """
    if not content:
        return ("ok", "")
    stripped = content.lstrip()
    if not stripped.startswith("{"):
        return ("ok", "")
    import json as _json

    try:
        data = _json.loads(stripped)
    except (ValueError, TypeError):
        return ("ok", "")
    if isinstance(data, dict):
        status = data.get("status")
        if status in ("ok", "unknown"):
            return (status, "")
        if status == "error":
            return ("error", str(data.get("code") or ""))
    return ("ok", "")


def _result_summary_from_content(content: str) -> str:
    """Backward-compatible wrapper returning only the result_summary."""
    return _result_summary_and_code_from_content(content)[0]


def _build_agent_output(trajectory: dict[str, Any]) -> dict[str, Any]:
    """Match the orchestrator's agent_output construction.

    The pattern verifier reads `agent_output['reasoning']` and `['output']`;
    the world_state verifier reads the audit log we built separately.
    """
    turns = trajectory.get("turns", [])
    tool_calls: list[str] = []
    assistant_text: list[str] = []
    for turn in turns:
        role = turn.get("role")
        if role == "assistant":
            for call in turn.get("tool_calls") or []:
                name = call.get("name", "")
                if name:
                    tool_calls.append(name)
            assistant_text.append(turn.get("content", "") or "")
    joined = " ".join(t for t in assistant_text if t)
    return {
        "tool_calls": tool_calls,
        "reasoning": joined,
        "output": joined,
    }
