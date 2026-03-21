# Changelog

All notable changes to HEALTHCRAFT evaluation infrastructure are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

Evaluation results in `results/` are immutable. Bug discoveries produce new
evaluation versions, not retroactive corrections.

## [v8] - 2026-03-15

### Fixed
- Evaluator: parameter qualifiers ("for lab", "with medication matching X") were silently dropped, inflating scores on criteria requiring specific parameters (602 criteria flips S->U on V7 rescore)
- Evaluator: AND/OR compound check clauses were evaluated as single string match instead of parsed into independent sub-checks (9 criteria flips U->S on V7 rescore)
- Evaluator: underscore/hyphen normalization in protocol names (e.g., "sepsis_bundle" now matches "Sepsis Hour-1 Bundle")
- processTransfer: `destination_facility` accepted (matches schema name); `ground` transport mode mapped to `ground_als`
- processTransfer: unknown facilities produce warning instead of blocking error
- Orchestrator: injected patient/encounter IDs included in agent prompt (GPT could not discover task-relevant entities)

### Added
- Micro-eval integration test (`tests/test_integration_microeval.py`)
- 3 new preflight checks: parameter qualifier coverage, enum exhaustiveness, protocol name matching
- Offline rescore validation: V8 evaluator re-scored all 1,170 trajectories with 0 criteria flips

### Changed
- Claude: 0.730 -> 0.634 avg reward (-13.2%), 26.8% -> 24.8% Pass@1. Qualifier enforcement removed false passes.
- GPT: 0.264 -> 0.546 avg reward (+106.8%), 4.6% -> 12.6% Pass@1. Tool-side fixes enabled previously-impossible actions.
- Safety failures: Claude 17.9% -> 27.5%, GPT 60.9% -> 34.0%. Convergence from opposite directions.

### Note
V7 was presented as authoritative for 2 days before 5 infrastructure bugs
were discovered via the rescore validation pipeline. V7 results remain in
`results/pilot-v7-*` as immutable reference data. V8 re-ran all 1,170
trajectories with corrected infrastructure.

## [v7] - 2026-03-13

### Fixed
- Evaluator: failed tool calls no longer count as successes
- Evaluator: exact tool name matching (was substring)
- registerPatient schema aligned with handler (`first_name`/`last_name`)
- `blood_product` added to valid order types in createClinicalOrder
- 3 criteria migrated from `world_state` to `llm_judge` (reasoning checks)

### Added
- Preflight validation (`make preflight`)
- Per-category analysis script (`scripts/analyze_v7.py`)
- Pass^k metrics (3 trials per task)

### Note
First clean run with 3 trials. V6 audit bugs fixed. All 195 tasks, 2 models.

## [v6] - 2026-03-11 -- INVALIDATED

### Added
- 218 criteria verification fixes (`world_state` to `llm_judge` migration)
- Cross-vendor LLM judge integration
- Full 195-task evaluation (first at scale)

### Note
Post-hoc audit found 2 infrastructure bugs (failed-call-counts-as-pass,
substring tool matching) and 3 rubric bugs. Results are immutable reference
data. See `docs/V6_AUDIT_FINDINGS.md`.

## [v5] - 2026-03-10
Targeted single-task fix (CC-003 deterministic name generation, GPT only).

## [v4] - 2026-03-10
Entity ordering, judge formatting, age parser fixes. 20 tasks x 5 trials x 2 models.

## [v3] - 2026-03-10
Task patient injection into world state (inject.py). 20 tasks x 5 trials x 2 models.

## [v2] - 2026-03-10
First complete evaluation. 20 tasks x 5 trials x 2 models.

## [v1] - 2026-03-10
Schema fixes (exploratory, no summary).

## [v0] - 2026-03-10
Initial infrastructure wiring (exploratory, no summary).
