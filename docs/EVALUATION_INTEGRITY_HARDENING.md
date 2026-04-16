# Evaluation Integrity Hardening (Phase 1)

## Purpose

Phase 1 of the v0.2 hardening plan locks the invariants exposed by the
V7-to-V8 transition, where 6 infrastructure bugs silently changed evaluation
results. The core thesis: **if a tool is renamed, a check parser changed, an
audit log convention altered, or a prompt file edited, CI must go red in
seconds -- not after a pilot.**

This document covers what was added, why, and what each test protects against.

## Test Suite: `tests/test_evaluator_integrity/`

73 tests across 6 modules. All deterministic, no LLM calls, no network.

### test_schema_handler_contract.py (37 tests)

Guards three invariants between `configs/mcp-tools.json` and the Python handler
layer:

| Invariant | What breaks if violated |
|-----------|------------------------|
| Bidirectional tool coverage (TOOL_NAME_MAP <-> schema) | Dead surface area: agents call tools with no handler, or handlers invisible to agents |
| Required-key alignment (schema.required == handler `_require()`) | Agents get hidden preconditions or 422s on documented inputs |
| Enum dispatch (schema enum values accepted by handler) | Documented inputs produce 500 instead of structured error |

**Method:** Bidirectional set difference on TOOL_NAME_MAP / schema tool names.
AST static parsing of `_require(params, "a", "b")` calls to extract
handler-required keys without runtime execution. Parametrized dispatch of all
24 tools with minimal valid inputs.

### test_missing_entity_links.py (8 tests)

Guards the error-path contract: mutating tools called with a nonexistent entity
must return a documented error code, not succeed silently or crash.

| Tool | Expected error code |
|------|-------------------|
| createClinicalOrder | `encounter_not_found` |
| applyProtocol | `encounter_not_found` |
| updateEncounter | `encounter_not_found` |
| updatePatientRecord | `patient_not_found` |
| updateTaskStatus | `task_not_found` |

Also validates that every task's `setting.active_encounters` resolves to a
real entity after seed + patient injection (per-task, ~100s total).

### test_audit_log_invariants.py (9 tests)

The audit log is the substrate `world_state` criteria are evaluated against.
Five invariants:

1. **Append-only:** recording an entry never reorders earlier entries.
2. **Monotonic time:** timestamps are non-decreasing in record order.
3. **Result-summary set:** documented values only (`ok`, `error`, `unknown`).
4. **Tool-name preserved:** `world.record_audit()` stores the tool_name
   verbatim; the evaluator lowercases at compare time. Changing this
   convention would break V8 trajectory replay.
5. **Snapshot independence:** `WorldState.snapshot()` returns a separate
   audit list; mutating the original does not retroactively appear in the
   snapshot.

### test_prompt_composition.py (7 tests)

The system prompt is composed from 4 files (`base.txt`, `mercy_point.txt`,
`policies.txt`, `tool_reference.txt`) joined by `\n\n`. A silent edit to
any component changes agent behavior in ways that won't show up in unit tests.

- **Byte-identical snapshot** at `tests/fixtures/prompt_snapshots/base_composed.txt`.
  When this test fails, either revert the edit or regenerate the snapshot AND
  update the whitepaper appendix.
- Component ordering and separator (`\n\n`) tests catch reordering or
  tokenization-shifting changes.
- Override-path tests validate both literal strings and file-based overrides.

### test_golden_trajectory_replay.py (5 tests)

The most important test in the suite. Reads the 30-trajectory manifest at
`tests/fixtures/golden_trajectories/index.json` and asserts that
`replay_from_trajectory()` re-derives byte-identical `(reward, passed,
safety_gate_passed, criteria_results_hash)` tuples.

**Contract:** Given the same audit log (reconstructed from saved tool_calls)
AND the same `llm_judge` verdicts (read from saved `criteria_results`), the
evaluator produces identical scores. This locks the deterministic channels
(`world_state` + `pattern`) without requiring nondeterministic LLM calls.

**If this test goes red:** It means a silent change to `_verify_world_state`
parsing, `compute_reward`, `check_safety_gate`, or `_split_compound` altered
the aggregation. Per the plan: document in `docs/PAPER_REVISION_NOTES.md`, do
NOT silently "fix" the score.

### test_task_satisfiability.py (7 tests)

Every `world_state` criterion's `(tool, qualifier)` must be producible by at
least one handler given valid input. Mirrors the evaluator's runtime parsing
(`_expand_tool_alternatives` + `_split_compound` + `_extract_tool_and_params`)
so the test agrees with the runtime on compound-clause splitting.

Also validates enum-bound qualifiers (`order_type`, `status`,
`transport_mode`) against handler-accepted values.

## Replay Helper: `evaluator.py:replay_from_trajectory()`

Read-only helper added to `src/healthcraft/tasks/evaluator.py`. Re-derives
`agent_output` and `audit_log` from a saved trajectory, then runs
`evaluate_task`. For `llm_judge` criteria, uses saved verdicts from
`trajectory.criteria_results` (does not re-call the judge).

Design decisions:
- Audit log is reconstructed by pairing assistant `tool_calls` with subsequent
  tool-role responses positionally (FIFO queue). V8 trajectories do not
  guarantee `tool_call_id` linkage.
- Pending calls without paired responses are recorded as
  `result_summary='unknown'` so negative checks still see them.
- `_result_summary_from_content()` maps tool response content to audit
  `result_summary`: JSON with explicit `status` field is used verbatim;
  anything else defaults to `'ok'` (conservative for positive checks).

## Extended Preflight: `scripts/preflight.py` Check 7

Adds a runtime-aligned satisfiability check that walks compound AND/OR splits
the same way the evaluator does, catching cases where the simpler regex in
Check 3 only inspects the first clause.

## Batch Oracle: `scripts/oracle_batch.py`

Generalized from `scripts/oracle_cc001.py`. For each task, seeds a world,
injects the task patient, dispatches every tool referenced by `world_state`
criteria with minimally valid params, and evaluates. Known limitation:
qualifier-bound tools (e.g., "order specific medication X") get best-effort
params that may not satisfy the criterion. The hand-crafted per-task oracles
remain useful for exercising the judge channel.

## Fixture Files

| File | Purpose |
|------|---------|
| `tests/fixtures/golden_trajectories/index.json` | 30-trajectory manifest (5 per category, stratified) |
| `tests/fixtures/prompt_snapshots/base_composed.txt` | Byte-identical snapshot of composed system prompt |

## V8 Impact

**None.** All changes are tests, fixtures, one read-only helper, and scripts.
No V8-era code path was modified. The existing 317 tests remain green.
