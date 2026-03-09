# HEALTHCRAFT — Claude Code Project Instructions

## What This Is

Emergency Medicine RL Training Environment adapting the Corecraft architecture (Mehta et al., arXiv:2602.16179v5) to emergency medicine. Public repo, Apache 2.0.

## Architecture

- **World state:** Deterministic FHIR R4 data store seeded from OpenEM conditions
- **MCP server:** 24 tools exposing Mercy Point ED (fictional Level I Trauma Center)
- **Task engine:** YAML task definitions with 6-dimension rubric scoring
- **Entity generator:** OpenEM-powered procedural generation of 14 entity types

## Key Directories

| Path | Purpose |
|------|---------|
| `src/healthcraft/world/` | State manager, FHIR store, deterministic seeding |
| `src/healthcraft/entities/` | One module per entity type (14 types) |
| `src/healthcraft/mcp/` | FastMCP server, 24 tools, validation, audit |
| `src/healthcraft/tasks/` | Task loader, evaluator, rubric scoring |
| `src/healthcraft/openem/` | OpenEM bridge, condition mapper, FHIR adapter |
| `configs/tasks/` | Task YAML definitions (6 category subdirs) |
| `configs/world/` | World state seed configs |
| `configs/schemas/` | JSON schemas for all YAML formats |
| `docker/` | Docker Compose, Dockerfiles |
| `tests/` | Mirrors src/ structure |

## Conventions

- **Determinism:** `random.Random(seed)` everywhere. Default seed=42.
- **FHIR R4:** All patient/encounter/condition entities are valid FHIR R4.
- **OpenEM integration:** Optional dependency. World state is self-contained at runtime.
- **Immutable results:** `results/` is append-only. Never modify existing result files.
- **Synthetic data only:** No real patient data. All entities are fictional.
- **Safety gate:** Rubric dimension "Safety" is a hard gate (lethal error = zero total score).

## OpenEM Integration

```python
# Optional import pattern
try:
    from openem.conditions import load_condition_map
    HAS_OPENEM = True
except ImportError:
    HAS_OPENEM = False
```

Uses: `load_condition_map()`, condition metadata (confusion_pairs, decision_rules, time_to_harm), FHIR bundle generation.

## Testing

```bash
make test        # pytest tests/ -q
make lint        # ruff check + format check
make smoke       # Seed world, start MCP, run 5 tasks
make docker-up   # Docker compose
```

## Development Rules

1. Never commit real patient data or PHI
2. All entity generators must be deterministic from seed
3. Clinical tasks require rubrics for all 6 dimensions
4. MCP tools must validate inputs and log to audit trail
5. FHIR resources must pass schema validation
6. Stage files by name, never `git add -A`
