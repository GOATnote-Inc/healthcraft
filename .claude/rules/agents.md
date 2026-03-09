# Agent Governance Rules

## Agent Roster

| Agent | Model | Role |
|-------|-------|------|
| project-lead | opus | Architecture decisions, Corecraft mapping verification |
| entity-builder | sonnet | Entity generators, FHIR compliance, data validation |
| tool-implementer | sonnet | MCP tools, schemas, tool tests |
| task-author | opus | Clinical tasks, rubrics, example scenarios |
| openem-integrator | sonnet | OpenEM bridge, condition mapper, FHIR adapter |
| clinical-reviewer | opus | Clinical accuracy review |
| infra-engineer | sonnet | Docker, CI/CD, database, deployment |

## File Ownership

| Path | Owner | Others |
|------|-------|--------|
| src/healthcraft/world/ | project-lead | entity-builder: read |
| src/healthcraft/entities/ | entity-builder | clinical-reviewer: review |
| src/healthcraft/mcp/ | tool-implementer | infra-engineer: docker |
| src/healthcraft/tasks/ | task-author | clinical-reviewer: review |
| src/healthcraft/openem/ | openem-integrator | entity-builder: read |
| configs/tasks/ | task-author | [PROPOSED CHANGES] |
| configs/world/ | project-lead | [PROPOSED CHANGES] |
| docker/ | infra-engineer | tool-implementer: read |
| results/ | IMMUTABLE | append-only |

## Safety-Critical Zones

Paths requiring [PROPOSED CHANGES] review before modification:
- `configs/tasks/` — task definitions affect evaluation correctness
- `configs/world/` — world seed affects all downstream entities
- `configs/rubrics/` — rubric weights affect scoring

## Determinism Rule

- All entity generation: `random.Random(seed)`, default seed=42
- All model evaluation: temperature=0.0, seed=42
- Deterministic task generation and scoring

## Fail-Loud Protocol

- Stop on API error, report immediately
- Flag if FHIR resources fail schema validation
- Flag if entity references are dangling (referential integrity)
- Immutable results: never modify, create new files for re-evaluation
