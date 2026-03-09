# HEALTHCRAFT Architecture

## Overview

HEALTHCRAFT is an emergency medicine RL training environment that adapts the
[Corecraft](https://arxiv.org/abs/2602.16179) architecture (Mehta et al., Surge AI)
to emergency medicine. It provides a stateful, deterministic environment where
AI agents interact with a fictional Level I Trauma Center (Mercy Point ED)
through Model Context Protocol (MCP) tools.

```
Agent (any MCP client)
  |
  v
MCP Server (24 tools via FastMCP)
  |
  +--- World State (PostgreSQL + FHIR R4)
  |        |
  |        +--- Entity Generator (OpenEM-powered, 14 types)
  |        +--- Temporal Spine (time-indexed state)
  |        +--- Audit Log (append-only)
  |
  +--- Task Engine
           |
           +--- Task Loader (YAML definitions)
           +--- Rubric Evaluator (6-dimension scoring)
           +--- Difficulty Progression (5 levels)
```

## World State

The world state is a PostgreSQL database whose schema maps to FHIR R4 resources.
It represents the current state of Mercy Point ED at a specific moment in time.

**Key properties:**

- **FHIR R4 compliance.** Patients, encounters, conditions, and other clinical
  entities are valid FHIR R4 resources. The database schema uses FHIR-compatible
  columns (resource_type, resource_id, version_id, last_updated, resource JSONB).
- **Deterministic seeding.** Given a seed (default=42), the entity generators
  produce identical world states. All randomness flows through `random.Random(seed)`.
- **Stateful mutations.** MCP tool calls mutate the world state. Changes persist
  within a session and affect subsequent tool calls.
- **Referential integrity.** Entity references are validated at generation time
  and enforced by foreign keys. No dangling references.

### Storage Layer

```
PostgreSQL 16
  |
  +--- patients (FHIR Patient resources)
  +--- encounters (FHIR Encounter resources, ESI levels, timelines)
  +--- clinical_tasks (active orders, pending results, consults)
  +--- time_constraints (door-to-ECG, door-to-balloon, sepsis bundles)
  +--- audit_log (append-only, every tool call recorded)
  +--- ... (additional tables per entity type)
```

### World Seed Configs

World seed configurations live in `configs/world/` and define:

- Facility parameters (bed count, departments, staffing)
- Patient census and acuity distribution
- Active protocols and standing orders
- Resource availability and constraints
- Time of day and shift configuration

## MCP Server

The MCP server exposes 24 tools via [FastMCP](https://github.com/jlowin/fastmcp),
a Python framework for building Model Context Protocol servers. The server runs
as a uvicorn ASGI application inside Docker.

**Tool categories:**

| Category | Tools | Description |
|----------|-------|-------------|
| Search | 6 | Find entities by criteria |
| Read | 7 | Get entity details |
| Write | 5 | Create or update entities |
| Execute | 4 | Run clinical workflows |
| Query | 2 | Check availability and coverage |

**Design principles:**

- Every tool validates inputs against JSON schemas before execution.
- Every tool call is recorded in the audit log with timestamp, parameters,
  result summary, and session ID.
- Tools interact with the world state through a state manager abstraction,
  never directly with the database.
- Tool responses use consistent envelope format: `{status, data, warnings}`.

See [`TOOL_MAPPING.md`](TOOL_MAPPING.md) for the complete tool reference.

## Task Engine

The task engine loads YAML task definitions, presents them to agents, and
evaluates agent performance using a 6-dimension rubric.

### Task Lifecycle

```
1. Load task YAML from configs/tasks/{category}/
2. Seed world state with task's initial_state
3. Present task description to agent
4. Agent interacts via MCP tools (recorded in audit log)
5. Evaluator scores against rubric (6 dimensions)
6. Results written to results/ (append-only)
```

### YAML Task Format

```yaml
id: "TASK-001"
category: clinical_reasoning
level: 3
title: "Atypical STEMI Presentation"
description: "Patient presents with epigastric pain and diaphoresis..."
initial_state:
  seed: 42
  patients: ["PAT-042"]
  encounters: ["ENC-107"]
expected_tools:
  - getEncounterDetails
  - getPatientHistory
  - runDecisionRule
  - applyProtocol
  - createClinicalOrder
rubric:
  clinical_completeness: {weight: 0.20, anchors: {...}}
  clinical_correctness: {weight: 0.25, anchors: {...}}
  protocol_adherence: {weight: 0.15, anchors: {...}}
  documentation_quality: {weight: 0.10, anchors: {...}}
  safety: {weight: 0.20, anchors: {...}}
  temporal_sequencing: {weight: 0.10, anchors: {...}}
```

### 6-Dimension Rubric

| Dimension | Weight | Hard Gate |
|-----------|--------|-----------|
| Clinical Completeness | 0.20 | No |
| Clinical Correctness | 0.25 | No |
| Protocol Adherence | 0.15 | No |
| Documentation Quality | 0.10 | No |
| Safety | 0.20 | **Yes** |
| Temporal Sequencing | 0.10 | No |

**Safety hard gate:** If the Safety dimension score is 0 (lethal error), the
total score is forced to 0 regardless of performance on other dimensions. This
creates a non-convex reward landscape that mirrors the real stakes of emergency
medicine.

See [`RUBRIC_DESIGN.md`](RUBRIC_DESIGN.md) for score anchors and examples.

### 6 Task Categories, 5 Difficulty Levels

| Category | Difficulty Range | Description |
|----------|-----------------|-------------|
| Information Retrieval | Triage-Workup | Entity lookup and filtering |
| Clinical Communication | Workup-Treatment | Transfer summaries, discharge instructions |
| Clinical Reasoning | Treatment-Resuscitation | Differential diagnosis, decision rules |
| Multi-Step Clinical Workflows | Resuscitation | Sepsis bundle, STEMI alert, trauma |
| Temporal Reasoning | Treatment-Resuscitation | Time-critical sequencing |
| Safety-Critical Judgment | Resuscitation-Mass Casualty | EMTALA, capacity, override |

See [`TASK_DESIGN.md`](TASK_DESIGN.md) for the full task taxonomy and examples.

## Entity Generator

The entity generator creates world state entities using OpenEM condition data
and deterministic seeding. It produces 14 entity types that map to Corecraft's
original entity types adapted for emergency medicine.

**OpenEM integration** is optional. The entity generator can produce entities
without OpenEM installed, but OpenEM provides:

- 370 emergency medicine conditions with structured metadata
- 152 confusion pairs (conditions with identical presentations but different treatments)
- 45 clinical decision rules with parameters and thresholds
- FHIR R4 bundle templates

```python
# Optional import pattern
try:
    from openem.conditions import load_condition_map
    HAS_OPENEM = True
except ImportError:
    HAS_OPENEM = False
```

See [`ENTITY_MAPPING.md`](ENTITY_MAPPING.md) for the complete entity reference.

## Docker Bundle Architecture

HEALTHCRAFT runs as a Docker Compose bundle with two services:

```
docker/
  docker-compose.yaml
  world-state/
    Dockerfile         # PostgreSQL 16 + init.sql
    init.sql           # Schema definition
  mcp-server/
    Dockerfile         # Python 3.12 + FastMCP + uvicorn
```

### Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| world-state | PostgreSQL 16 | 5432 | FHIR R4 data store |
| mcp-server | Python 3.12-slim | 8000 | MCP tool server |

### Startup Sequence

1. `world-state` starts, runs `init.sql` to create schema
2. `world-state` passes healthcheck (pg_isready)
3. `mcp-server` starts, connects to `world-state`
4. `mcp-server` seeds world state from config (if `HEALTHCRAFT_SEED_CONFIG` is set)
5. `mcp-server` serves MCP tools on port 8000

## Temporal Spine

Every entity in the world state has a temporal dimension. The temporal spine
is the set of timestamps that define when entities were created, modified, or
expire.

**Key concepts:**

- **World clock.** The world state represents a specific moment. Advancing the
  clock triggers time-dependent state changes (lab results arriving, consult
  timeouts, shift changes).
- **Time constraints.** Clinical time constraints (door-to-ECG < 10 min,
  door-to-balloon < 90 min, sepsis bundle < 3 hr) create urgency and force
  sequencing decisions.
- **Temporal reasoning tasks.** Tasks in the "Temporal Reasoning" category
  require agents to reason about timing, ordering, and overlapping protocols.

```
Timeline for encounter ENC-107:
  T+0:00  Patient arrival (triage)
  T+0:05  ESI-2 assignment
  T+0:08  ECG ordered (door-to-ECG constraint: 10 min)
  T+0:10  ECG performed  <-- constraint met
  T+0:12  STEMI identified
  T+0:14  Cath lab activation (door-to-balloon constraint: 90 min)
  ...
```

## Audit Logging

Every MCP tool call is recorded in the `audit_log` table:

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Unique log entry ID |
| session_id | UUID | Agent session identifier |
| timestamp | TIMESTAMPTZ | When the call occurred |
| tool_name | VARCHAR(100) | MCP tool name |
| parameters | JSONB | Input parameters |
| result_summary | JSONB | Abbreviated result |
| duration_ms | INTEGER | Execution time |
| error | TEXT | Error message if failed |

The audit log is append-only and immutable. It serves as the ground truth for
task evaluation: the rubric evaluator reconstructs the agent's behavior from
the audit log rather than relying on self-reported actions.

## Directory Structure

```
healthcraft/
  src/healthcraft/
    world/          # State manager, FHIR store, deterministic seeding
    entities/       # One module per entity type (14 types)
    mcp/            # FastMCP server, 24 tools, validation, audit
    tasks/          # Task loader, evaluator, rubric scoring
    openem/         # OpenEM bridge, condition mapper, FHIR adapter
  configs/
    tasks/          # Task YAML definitions (6 category subdirs)
    world/          # World state seed configs
    schemas/        # JSON schemas for all YAML formats
    rubrics/        # Rubric configurations
  docker/           # Docker Compose, Dockerfiles
  tests/            # Mirrors src/ structure
  results/          # Evaluation results (append-only, immutable)
  docs/             # Documentation
  scripts/          # Utility scripts
```
