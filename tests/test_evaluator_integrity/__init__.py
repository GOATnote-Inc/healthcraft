"""Evaluator-integrity test suite.

These tests guard the contracts that prevent silent infrastructure regressions.
Six modules cover:

  * test_schema_handler_contract.py  -- mcp-tools.json <-> TOOL_NAME_MAP <-> handler enums
  * test_missing_entity_links.py     -- mutating-tool entity-not-found error paths
  * test_audit_log_invariants.py     -- timestamp monotonicity, casing, append-only
  * test_prompt_composition.py       -- snapshot of the composed system prompt
  * test_golden_trajectory_replay.py -- V8 trajectories replay to bit-identical scores
  * test_task_satisfiability.py      -- every world_state criterion is producible

The V7 to V8 transition uncovered six infrastructure bugs that changed Pass
rates substantially (Claude -13% rel, GPT +107% rel). This suite is the
regression net for that class of bug.
"""
