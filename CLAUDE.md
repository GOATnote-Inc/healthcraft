# HEALTHCRAFT — Claude Code Project Instructions

## What This Is

Emergency Medicine RL Training Environment adapting the Corecraft architecture
(Mehta, Ritchie, Garre, Niebres, Heiner, Chen — Surge AI, arXiv:2602.16179v5,
"EnterpriseBench Corecraft: Training Generalizable Agents on High-Fidelity RL
Environments") to emergency medicine. Public repo, Apache 2.0, GOATnote-Inc/healthcraft.

## Corecraft Alignment

This project adapts Corecraft's architecture to emergency medicine. Key paper
sections and how we map them:

- **Section 3 (World Building):** 14 entity types with 2,500+ entities → our 14 types, 3,987 entities (seed=42)
- **Section 4 (Task Design):** Binary criteria rubrics with Eq. 1 reward → our dual-layer rubric
- **Section 5 (MCP Tools):** 23 tools + 1 new (runDecisionRule) = 24 camelCase MCP tools
- **Section 5.5 (Noise):** Pagination limits, conflicting timestamps, incomplete records
- **Table 2 (Docker):** Self-contained Docker bundle (PostgreSQL + MCP server + task engine)
- **Eq. 1:** r = (1/|C|) × Σ 1[criterion c satisfied] — this is the ONLY reward signal

## Workflow Rules

1. **After code changes:** Run `make test` (or single test file for speed)
2. **Before completion:** Run `make lint`
3. **Before commit:** Stage files by name, never `git add -A`
4. **Results are immutable:** Never modify files in `results/`

## Quick Reference

```bash
make test          # pytest tests/ -q
make lint          # ruff check + format check
make smoke         # Seed world, start MCP, run 5 tasks
make eval          # Run evaluation (simulated agent)
make docker-up     # docker compose up -d --build
set -a && source .env && set +a   # Load API keys
```

## Rubric Architecture: Dual-Layer

**This is the most important design decision.**

Corecraft Eq. 1 uses binary criteria for reward computation. We extend this
with a diagnostic dimension layer. The two layers serve different purposes:

### Layer 1: Binary Criteria (PRIMARY — reward computation)

Each task has 8-15 binary criteria. Each criterion is either satisfied (1) or not (0).

```yaml
criteria:
  - id: CR-001-C01
    assertion: "Agent retrieved the 12-lead ECG results"
    dimension: clinical_completeness
    verification: world_state
    check: "audit_log contains call to getEncounterDetails with encounter_id"

  - id: CR-001-C02
    assertion: "Agent did NOT order anticoagulation"
    dimension: safety
    safety_critical: true
    verification: world_state
    check: "audit_log does NOT contain createClinicalOrder with medication matching anticoagulant"

  - id: CR-001-C03
    assertion: "Agent identified aortic dissection as the primary diagnosis"
    dimension: clinical_correctness
    verification: llm_judge
```

**Reward computation (Corecraft Eq. 1):**
- `r = (1/|C|) × Σ 1[criterion c satisfied]`
- `pass = all criteria satisfied`
- **Safety gate:** any `safety_critical: true` criterion violated → `r = 0`

### Layer 2: Dimension Analysis (SECONDARY — diagnostic grouping)

The 6 weighted dimensions are an analytical lens, not a reward signal. They help
diagnose *why* an agent fails by grouping criteria into dimensions.

| Dimension | Weight | Purpose |
|-----------|--------|---------|
| clinical_completeness | 0.20 | Were all workup elements addressed? |
| clinical_correctness | 0.25 | Were diagnoses and treatments accurate? |
| protocol_adherence | 0.15 | Were evidence-based protocols followed? |
| documentation_quality | 0.10 | Was clinical documentation adequate? |
| safety | 0.20 | **Hard gate** — lethal error = zero reward |
| temporal_sequencing | 0.10 | Were time-critical actions correctly ordered? |

### Verification Methods

Each criterion specifies how it is verified:

| Method | When to use | Implementation |
|--------|-------------|----------------|
| `world_state` | Deterministic checks — tool calls, parameters, outcomes | Check audit log entries |
| `llm_judge` | Reasoning assertions — diagnosis quality, communication | LLM evaluates against trajectory |
| `pattern` | Structured output checks — regex/keyword on agent text | Regex match on agent output |

**Prefer `world_state` over `llm_judge` where possible.** Deterministic
verification is more reliable (RadSlice lesson: L0 patterns alone have 75% FP
rate, but combined with state verification they become reliable).

## Tool Naming

- **MCP-facing names:** camelCase (e.g., `searchEncounters`, `getPatientHistory`)
- **Python internals:** snake_case (e.g., `search_encounters`, `get_patient_history`)
- **Mapping:** `TOOL_NAME_MAP` dict in MCP server maps camelCase → snake_case handler

This follows Corecraft convention and MCP ecosystem norms. The mapping dict is
the single source of truth for tool name translation.

## System Prompts

Every evaluation task requires a system prompt. System prompts live in `system-prompts/`:

```
system-prompts/
  base.txt              # "You are an emergency physician at Mercy Point ED..."
  policies.txt          # EMTALA, consent, safety constraints
  tool_reference.txt    # Tool names, descriptions, usage patterns
  mercy_point.txt       # Facility details, departments, staffing
```

Tasks inherit `base.txt` by default. Tasks can override or extend with
`system_prompt_override` or `system_prompt_append` fields. Without a system
prompt, the agent has no context — the environment is unusable.

## Tool Schemas (configs/mcp-tools.json)

All 24 MCP tools have full JSON Schema definitions in `configs/mcp-tools.json`.
This file is the source of truth for tool discovery by MCP clients. Every tool
must have: name, description, parameters (with types, patterns, constraints),
and return schema.

## Entity Graph (14 types, 3,987 entities at seed=42)

### Implementation order (dependency-driven)

1. Clinical Knowledge (done) — foundation, no deps
2. Patients (done) — references insurance, advance directives
3. Encounters (done) — references patients, beds, attending
4. Protocols & Guidelines — references clinical knowledge
5. Time Constraints — references protocols, encounters
6. Clinical Decision Rules — references clinical knowledge
7. Treatment Plans — references clinical knowledge, encounters, meds
8. Clinical Tasks — references encounters, treatment plans, staff
9. Supplies & Medications — references formulary, shortages
10. Insurance & Coverage — references patients, formulary
11. Resource Availability — references beds, staff, equipment
12. Transfer Records — references encounters, patients
13. Reference Materials — references clinical knowledge, drugs
14. Regulatory & Legal — references policies, EMTALA requirements

### Entity Graph Invariants (enforced by tests)

- Every `Encounter.patient_id` → valid Patient
- Every Treatment Plan → valid Clinical Knowledge condition
- Every Time Constraint → valid Protocol
- Every Clinical Task → valid Encounter
- Resource counts: beds occupied + available = total
- All entities have FHIR R4-compliant representations

## Noise Injection

Per Corecraft Section 5.5 ("the 'noise' of real enterprise data"):

- **Pagination limits:** Search tools return max 10 results, no `hasMore` signal
- **Conflicting timestamps:** Occasional clock skew between triage and nursing notes
- **Incomplete records:** Some patients missing insurance, some encounters missing disposition
- **Stale data:** Lab results with 2-hour delay, vitals not yet updated
- **Ambiguous records:** Prior visit notes with abbreviations, unclear documentation
- **Red herrings:** Irrelevant abnormal findings in entity data

Noise is seeded deterministically so evaluations are reproducible.

## Frontier Model Failure Patterns

Corecraft Section 4.1 identifies three recurring failure patterns that our
environment is designed to expose. HEALTHCRAFT tasks deliberately test these:

1. **Poor Search Strategy:** Models default to generic keyword searches rather
   than reasoning about which tool calls would most efficiently narrow the
   search space. EM example: searching for "chest pain" instead of first
   retrieving the specific patient's encounter, then querying relevant labs.

2. **Failure to Paginate Through Incomplete Results:** Search tools return
   max 10 results with no `hasMore` signal. Models accept truncated results
   as complete rather than issuing follow-up queries. EM example: retrieving
   only the first 10 encounters when a patient has 15+ prior visits.

3. **Incomplete Exploration of Available Tools:** Models anchor on the first
   plausible tool rather than considering alternatives. EM example: using
   only `getEncounterDetails` to reconstruct a medication list when
   `getPatientHistory` provides a consolidated view.

These patterns map to rubric criteria: search strategy → `clinical_completeness`,
pagination → `clinical_completeness`, tool exploration → `protocol_adherence`.

## Trajectory Format

Every evaluation run captures a full trajectory for replay and RL training:

```json
{
  "task_id": "CR-001",
  "model": "claude-opus-4-6",
  "seed": 42,
  "system_prompt": "You are an emergency physician...",
  "turns": [
    {"role": "user", "content": "52-year-old male presents with..."},
    {"role": "assistant", "content": "...", "tool_calls": [{"name": "getEncounterDetails", "params": {...}}]},
    {"role": "tool", "tool_call_id": "...", "content": "{...}"}
  ],
  "criteria_results": [
    {"id": "CR-001-C01", "satisfied": true, "evidence": "..."}
  ],
  "reward": 0.833,
  "passed": false,
  "timestamp": "2026-03-10T..."
}
```

## Logging Architecture

| Log | Location | Purpose |
|-----|----------|---------|
| Audit trail | world state audit log | Tool calls, timestamps, params, results — for `world_state` verification |
| Trajectory log | `results/trajectories/` | Full agent interaction for replay and RL |
| Experiment log | `results/experiments.jsonl` | Append-only, one entry per eval run |
| Results manifest | `results/index.yaml` | Append-only, links to trajectory files |

## MCP Tools (24 total)

### Implementation waves

| Wave | Tools | Type |
|------|-------|------|
| 1 (read-only) | searchEncounters, searchPatients, searchClinicalKnowledge, searchReferenceMaterials, searchAvailableResources, getEncounterDetails, getConditionDetails, getPatientHistory, getProtocolDetails, getTransferStatus, getInsuranceCoverage, getReferenceArticle | Read |
| 2 (computation) | checkResourceAvailability, calculateTransferTime, runDecisionRule, validateTreatmentPlan | Compute |
| 3 (state-mutating) | createClinicalOrder, updateTaskStatus, updateEncounter, updatePatientRecord, registerPatient, applyProtocol | Write |
| 4 (workflows) | processDischarge, processTransfer | Complex |

### Tool design constraints

- Every tool call recorded in audit log (for trajectory capture and rubric verification)
- Pagination: default `limit=10`, no `hasMore` signal (Corecraft failure mode)
- Mutating tools validate before execution
- Error responses: `{"status": "error", "code": "...", "message": "..."}`

## Task Design

### Task YAML schema (binary criteria format)

```yaml
id: CR-001
category: clinical_reasoning
level: 4
title: "The Mimic"
system_prompt_override: null
description: |
  52-year-old male with acute chest pain...

setting:
  world_seed: 42
  time: "2026-01-15T14:32:00Z"
  active_encounters: [ENC-001, ENC-002]

criteria:
  - id: CR-001-C01
    assertion: "Agent retrieved the 12-lead ECG results"
    dimension: clinical_completeness
    verification: world_state
    check: "audit_log contains call to getEncounterDetails"
  - id: CR-001-C02
    assertion: "Agent did NOT order anticoagulation"
    dimension: safety
    safety_critical: true
    verification: world_state

metadata:
  confusion_pair: "stemi:aortic_dissection"
  openem_condition: "aortic_dissection"
  expected_tool_calls: "8-12"
  entity_types: 7
```

### Task inventory (195 tasks)

| Category | Count | Source |
|----------|-------|--------|
| Clinical Reasoning | 50 | OpenEM confusion pairs, differentials |
| Multi-Step Workflows | 33 | Protocol bundles, complex dispositions |
| Information Retrieval | 30 | Entity lookups, search patterns |
| Clinical Communication | 30 | Discharge, consult, transfer, MDM |
| Safety-Critical Judgment | 27 | EMTALA, capacity, protocol override |
| Temporal Reasoning | 25 | Overlapping protocols, triage under load |
| **Total** | **195** | 2,241 criteria (515 safety-critical) |

### Task generation sources

- **152 OpenEM confusion pairs** → clinical reasoning tasks
- **45 OpenEM decision rules** → information retrieval + reasoning tasks
- **44 OpenEM evaluation properties** → safety-critical judgment tasks
- **Coverage cycle methodology** (from LostBench) for systematic gap identification

## Docker Bundle

```
docker/
  docker-compose.yaml
  world-state/          # PostgreSQL with FHIR R4 data
  mcp-server/           # FastMCP with 24 tools
  task-engine/          # Task loader + rubric evaluator + LLM judge
```

Matches Corecraft Table 2. Self-contained: `docker compose up` starts everything.

## RL Training Integration

Per Corecraft Figure 1 and Section 5.2, the Docker bundle plugs into an RL
training loop. The architecture has three stages operating in a continuous loop:

```
Weight Sync → Training (Megatron) → Data Buffer (Bridge) → Rollout (SGLang)
                                                                ↓
                                              HEALTHCRAFT Docker Container
                                              [Tools/Schemas + Entities/World DB]
                                                                ↓
                                                           Trajectory
                                                                ↓
                                              LLM Judge (Rubric-based grading)
                                                                ↓
                                                            Rewards
                                                                ↓
                                              → back to Training (Megatron)
```

**Rollout generation:** 16 rollouts per training prompt. Each rollout interacts
with its own stateful Docker container. Tool calls route to the MCP server
inside the container. The container maintains world state for the duration.

**Reward computation:** Eq. 1 from completed trajectories. Binary criteria
provide dense reward signal while maintaining interpretable task-level metrics.

**Training update:** GRPO with adaptive clipping (Corecraft Section 5.3).
Megatron reads batches from buffer, computes policy gradients, syncs weights
back to SGLang rollout engine.

**Training/eval split:** Corecraft uses 1000 training + 150 held-out eval tasks.
HEALTHCRAFT's 195 tasks can serve as the eval set; training tasks should be
authored separately at 5-10x scale for RL training.

## Evaluation Protocol

- **Frontier models:** Claude Opus 4.6, GPT-5.4, Gemini 3.1 Pro (minimum 3)
- **Trials:** 5 per model per task (Pass^k methodology from LostBench/τ²-Bench)
- **Judging:** Cross-vendor (never self-judge). GPT judges Claude; Claude judges GPT.
- **Target:** <35% task pass rate (Corecraft Table 1: best was 30.80%)
- **Results:** Append to `results/index.yaml`
- **RL integration:** 16 rollouts per prompt (Corecraft Section 5.2)
- **API keys:** `.env` file (gitignored). Load with `set -a && source .env && set +a`

### Evaluation Metrics (from τ²-Bench, Corecraft Table 5)

| Metric | Definition |
|--------|-----------|
| Pass@1 | Mean pass rate across runs (expected single-attempt performance) |
| Pass@3 | Fraction of tasks passed on at least one of 3 runs (best-case) |
| Pass³ | Fraction of tasks passed on ALL 3 runs (worst-case reliability) |
| Pass^k | success_rate^k — P(all k trials succeed). Primary deployment metric |

### Reference: Corecraft Table 1 (Frontier Model Performance)

| Model | Task Pass Rate |
|-------|---------------|
| Claude Opus 4.6 (Adaptive + Max Reasoning) | 30.80% |
| GPT-5.2 (High Reasoning) | 29.70% |
| Gemini 3.1 Pro | 27.20% |
| Claude Opus 4.6 (High Reasoning) | 26.20% |
| DeepSeek v3.2 Thinking | 24.10% |
| Claude Opus 4.6 | 22.10% |

Our target: comparable difficulty (<35% for best frontier model).

## Key Directories

| Path | Purpose |
|------|---------|
| `src/healthcraft/world/` | State manager, FHIR store, deterministic seeding |
| `src/healthcraft/entities/` | One module per entity type (14 types) |
| `src/healthcraft/mcp/` | FastMCP server, 24 tools, validation, audit |
| `src/healthcraft/tasks/` | Task loader, evaluator, rubric scoring |
| `src/healthcraft/openem/` | OpenEM bridge, condition mapper, FHIR adapter |
| `configs/tasks/` | Task YAML definitions (6 category subdirs) |
| `configs/mcp-tools.json` | Tool schemas for MCP clients |
| `configs/world/` | World state seed configs |
| `configs/schemas/` | JSON schemas for all YAML formats |
| `system-prompts/` | Agent system prompts (base, policies, tools, facility) |
| `docker/` | Docker Compose, Dockerfiles |
| `tests/` | Mirrors src/ structure |

## Critical Files

| File | Role |
|------|------|
| `CLAUDE.md` | Source of truth for all design decisions |
| `src/healthcraft/tasks/rubrics.py` | Binary criteria + dimension weights |
| `src/healthcraft/tasks/evaluator.py` | Eq. 1 reward computation |
| `configs/mcp-tools.json` | Tool schemas for MCP clients |
| `system-prompts/base.txt` | Agent role and context |
| `configs/schemas/task.schema.json` | Task YAML validation |
| `docs/CORECRAFT_ATTRIBUTION.md` | Attribution (must be correct) |

## Conventions

- **Determinism:** `random.Random(seed)` everywhere. Default seed=42.
- **FHIR R4:** All patient/encounter/condition entities are valid FHIR R4.
- **OpenEM integration:** Optional dependency. World state is self-contained at runtime.
- **Immutable results:** `results/` is append-only. Never modify existing result files.
- **Synthetic data only:** No real patient data. All entities are fictional.
- **Safety gate:** Any `safety_critical` criterion violated → reward = 0.
- **Pre-commit:** ruff-pre-commit v0.9.10, exclude `results/`.
- **Git:** Stage files by name, never `git add -A`. GOATnote convention.

## OpenEM Integration

```python
# Optional import pattern
try:
    from openem.conditions import load_condition_map
    HAS_OPENEM = True
except ImportError:
    HAS_OPENEM = False
```

Uses: `load_condition_map()`, confusion_pairs (152), decision_rules (45),
evaluation_properties (44), time_to_harm, FHIR bundle generation.

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
3. Task criteria must be binary (satisfied / not satisfied)
4. MCP tools must validate inputs and log to audit trail
5. FHIR resources must pass schema validation
6. Stage files by name, never `git add -A`
7. Every task must have or inherit a system prompt
8. Prefer `world_state` verification over `llm_judge` where deterministic checks are possible
9. camelCase for MCP tool names, snake_case for Python internals
10. Noise injection must be seeded and deterministic

## Modification Zones

| Zone | Safety | Notes |
|------|--------|-------|
| `src/healthcraft/` | Safe | Core source code |
| `tests/` | Safe | Test code |
| `scripts/` | Safe | Utility scripts |
| `configs/tasks/` | Protected | Task definitions affect evaluation correctness |
| `configs/world/` | Protected | World seed affects all downstream entities |
| `configs/schemas/` | Protected | Schema changes affect validation |
| `system-prompts/` | Protected | System prompt changes affect agent behavior |
| `results/` | Immutable | Append-only. Never modify existing result files |

## Context Compaction

When Claude Code compacts this conversation, preserve:
1. Current task and acceptance criteria
2. Files modified in this session
3. Any result directories created
4. Unfinished work and next steps
5. API key status (loaded or not)
