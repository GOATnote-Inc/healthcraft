# Changelog

## [v8] - 2026-03-13 (in progress)
### Fixed
- applyProtocol: underscore/hyphen names now match display names (e.g., "sepsis_bundle" matches "Sepsis Hour-1 Bundle")
- Evaluator: parameter qualifiers ("for lab", "with medication matching X") no longer silently dropped
- processTransfer: `destination_facility` accepted (schema name), `ground` transport mode mapped to `ground_als`
- processTransfer: unknown facilities produce warning instead of blocking error
- Evaluator: AND/OR compound check clauses parsed into independent sub-checks
- Orchestrator: injected patient/encounter IDs included in agent prompt

### Added
- Micro-eval integration test (`tests/test_integration_microeval.py`) — catches infra bugs in <2 min
- 3 new preflight checks: parameter qualifier coverage, enum exhaustiveness, protocol name matching
- `emtala_justification` parameter in processTransfer schema
- README: badges, v7 results, known limitations, roadmap
- CHANGELOG.md

## [v7] - 2026-03-13
### Fixed
- Evaluator: failed tool calls no longer count as successes
- Evaluator: exact tool name matching (was substring)
- registerPatient schema aligned with handler
- blood_product added to valid order types
- 3 criteria migrated from world_state to llm_judge (reasoning checks)

### Added
- Preflight validation (`make preflight`)
- Per-category analysis script (`scripts/analyze_v7.py`)
- V6-V7 delta analysis
- Pass^k metrics (3 trials per task)

## [v6] - 2026-03-11 (invalidated)
### Added
- 218 criteria verification fixes (world_state to llm_judge migration)
- Cross-vendor LLM judge integration
- Full 195-task evaluation

## [v4] - 2026-03-10
### Fixed
- Entity ordering prioritizes task entities
- Judge formatting (full final response visible)
- Age parser edge cases

## [v3] - 2026-03-10
### Added
- Task patient injection into world state (inject.py)

## [v2] - 2026-03-10
### Added
- First complete evaluation (20 tasks x 5 trials x 2 models)
