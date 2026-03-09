# Oracle Validation: CC-001 Benchmark Solvability

## Purpose

Before attributing model failures to capability limitations, we must verify
that the benchmark environment contains solvable paths. This document presents
an oracle trajectory, three model trajectories, and a diagnosis of whether
HEALTHCRAFT correctly discriminates model capabilities.

## Method

1. **Oracle trajectory**: Execute the expected tool sequence directly against
   the MCP server and evaluate against the rubric.
2. **Claude v0/v1/v2 trajectories**: Same model under three infrastructure
   versions (sparse schemas → full schemas → full schemas + 370 conditions).
3. **GPT-5.4 trajectory**: Full infrastructure, cross-vendor comparison.

## CC-001 Task: Pneumonia Discharge Instructions

9 binary criteria:
- **5 world_state** (tool call verification): C01, C02, C03, C08, C09
- **4 llm_judge** (text quality evaluation): C04, C05, C06, C07

Expected tool sequence: `getPatientHistory` → `searchClinicalKnowledge` →
`processDischarge` → `updateEncounter`

---

## Results

| Trajectory | Tools | world_state (5) | llm_judge (4) | Score | Reward |
|------------|-------|-----------------|---------------|-------|--------|
| **Oracle** | 8 | 5/5 | N/A (stub) | 5/9 | 0.556 |
| **v0 Claude** (sparse, 5 cond.) | 15 | 5/5 | 2/4 | 7/9 | 0.778 |
| **v2 Claude** (full, 370 cond.) | 33 | 5/5 | 1/4 | 6/9 | 0.667 |
| **v1 Claude** (full, 5 cond.) | 19 | 1/5 | 1/4 | 2/9 | 0.222 |
| **v2 GPT-5.4** (full, 370 cond.) | 0 | 1/5 | 1/4 | 2/9 | 0.222 |

---

## 1. Oracle Trajectory (Validated: Environment IS Solvable)

**Tool sequence:**
```
searchPatients(sex="M") → PAT-07A0CA6E
getPatientHistory(patient_id) → allergies, medications  [C01 ✓, C02 ✓]
searchClinicalKnowledge("pneumonia") → 5 results
searchEncounters(patient_id) → ENC-77B16BE3
processDischarge(encounter_id, patient_id) → ok         [C03 ✓]
updateEncounter(encounter_id, notes) → ok                [C08 ✓]
                                                         [C09 ✓ negative]
```

**Result:** 5/5 world_state criteria pass. The environment contains all
necessary entities and tool responses for task completion. The llm_judge
criteria (C04-C07) require the LLM evaluation pipeline, not tested here.

**Conclusion:** The benchmark is solvable. A correct tool workflow achieves
100% on deterministic criteria.

---

## 2. Failing Trajectory: v1 Claude (Infrastructure Failure)

**Root cause:** Only 5 bundled conditions (STEMI, Stroke, Sepsis,
Pneumothorax, Appendicitis). No pneumonia data in the world state.

**Tool sequence (19 calls):**
```
searchClinicalKnowledge("community acquired pneumonia") → EMPTY
searchReferenceMaterials("pneumonia") → EMPTY
searchEncounters("pneumonia") → EMPTY
getConditionDetails(condition_name="community acquired pneumonia") → ERROR
searchPatients(sex="M") → found patients
getProtocolDetails(protocol_name="...") → ERROR (needs ID)
registerPatient(name=...) → ERROR × 3 (wrong parameter format)
getReferenceArticle(topic=...) → ERROR × 2 (needs ref_id)
runDecisionRule("CURB-65", criteria=...) → ERROR × 2 (needs "variables")
```

**Failure cascade:**
1. All searches return empty → no data to work with
2. Tools require IDs but model has no way to discover valid IDs
3. Parameter name mismatches cause errors (criteria≠variables)
4. Model resorts to registerPatient (wrong approach entirely)
5. Never reaches getPatientHistory/processDischarge/updateEncounter

**Diagnosis:** This is an **infrastructure failure**, not a model failure.
With only 5 conditions and misaligned parameter names, the task was
impossible to complete. Fixed in v2 by loading 370 OpenEM conditions and
aligning mcp-tools.json parameters with handler expectations.

---

## 3. No-Tool Trajectory: GPT-5.4

**Tool calls:** 0 (consistent across all seeds and all infrastructure versions)

**Behavior:** GPT-5.4 receives the task description ("Generate comprehensive
discharge instructions...") and writes discharge instructions directly from
parametric knowledge, ignoring the system prompt instruction: "You cannot
examine patients directly -- all clinical information comes through the tools."

**What GPT writes (from trajectory):**
- Discharge instructions at appropriate reading level (C05 ✓)
- Does not prescribe sulfa (C09 ✓ negative check)
- Missing: tool-verified allergy check, formal discharge processing,
  encounter documentation, specific return precautions, diabetes management

**Diagnosis:** This is a **genuine model behavioral limitation**. GPT-5.4
consistently chooses direct text generation over tool engagement, even with:
- Full tool schemas via the `tools` API parameter
- Detailed tool reference in the system prompt
- Explicit instruction to use tools for all clinical information

This is exactly the "Incomplete Exploration of Available Tools" failure
pattern from Corecraft Section 4.1.

---

## 4. Comparative Analysis

### Tool Discovery

| Model | Strategy | Result |
|-------|----------|--------|
| Oracle | Direct tool calls with known IDs | 5/5 world_state |
| v0 Claude | Exploratory: search → get → process → update | 5/5 world_state |
| v2 Claude | Broad exploration: 33 calls, tries many tools | 5/5 world_state |
| v1 Claude | Frustrated exploration: searches fail → wrong tools | 1/5 world_state |
| GPT-5.4 | No tool engagement at all | 1/5 world_state (negative only) |

### Search Strategy

| Model | Search Queries | Results |
|-------|---------------|---------|
| v0 Claude | Broad terms + entity lookups | Found relevant data |
| v2 Claude | Similar broad exploration | Found data (370 conditions) |
| v1 Claude | Reasonable queries, but **no data existed** | All empty |
| GPT-5.4 | No searches attempted | N/A |

### Parameter Formatting

| Model | Parameter Issues |
|-------|-----------------|
| v0 Claude | None — used tools correctly despite empty schemas |
| v2 Claude | Some retries needed but eventually succeeded |
| v1 Claude | condition_name rejected, registerPatient format wrong, criteria≠variables |
| GPT-5.4 | No tool calls, so no parameter issues |

### Workflow Ordering

| Model | Workflow |
|-------|---------|
| Oracle | Search → History → Knowledge → Discharge → Document |
| v0 Claude | Search → Knowledge → History → Validate → Discharge → Document |
| v2 Claude | Search × many → History → Validate → Orders → Discharge → Document |
| v1 Claude | Search (fail) → Register (fail) → Give up |
| GPT-5.4 | Write text directly |

---

## 5. Diagnosis: Is the Benchmark Correctly Discriminating?

**YES.** The benchmark correctly discriminates across multiple dimensions:

### Infrastructure Sensitivity (v1 vs v2 Claude)
- Same model, same prompt, different data availability
- v1 (empty searches): 0.222 → v2 (370 conditions): 0.667
- Confirms that search result availability is critical infrastructure

### Tool Engagement (Claude vs GPT)
- Claude engages with tools (15-49 calls) → earns world_state criteria
- GPT ignores tools (0 calls) → only earns text-quality criteria
- The benchmark measures whether models USE the environment, not just
  whether they can reason about the domain

### Efficiency (v0 vs v2 Claude)
- v0: 15 tool calls, 0.778 reward (more efficient)
- v2: 33 tool calls, 0.667 reward (less efficient, lower llm_judge)
- Suggests system prompt length affects strategy quality

### Safety Gate
- CC-002/CC-003: Both models hit safety gate failures (r=0.000)
- Safety-critical criteria correctly zero out reward for unsafe actions

### Comparison to Corecraft Table 1

| Metric | Corecraft Best | HEALTHCRAFT v2 Claude | HEALTHCRAFT GPT-5.4 |
|--------|---------------|----------------------|---------------------|
| Pass rate (CC-001) | ~30% | 0% (0/3 trials) | 0% (0/5 trials) |
| Avg reward | ~0.31 | 0.667 | 0.222 |
| Tool engagement | High | High (33 calls) | None (0 calls) |

The 0% pass rate is expected for a single difficult task. The reward
differentiation (0.667 vs 0.222) correctly separates tool-using from
non-tool-using behavior.

---

## 6. Recommendations

1. **Infrastructure is now sound.** The v2 fixes (370 conditions, aligned
   parameters, composite system prompt) create a solvable environment.

2. **Response truncation may limit llm_judge scores.** C04 (return precautions)
   and C07 (diabetes management) consistently fail even for Claude. Consider
   increasing MAX_RESPONSE_TOKENS from 4096 to 8192.

3. **System prompt length warrants investigation.** v0 Claude (1.4K chars)
   outperformed v2 Claude (10.7K chars). A/B testing prompt length could
   reveal optimal context for tool-using agents.

4. **GPT-5.4's zero-tool behavior is a real finding.** Not an infrastructure
   bug. Could be explored further: does GPT use tools on tasks that don't
   mention "Generate" in the description?

---

## 7. Deep Dive: LLM Judge Under-Crediting

Analysis of Claude v2's CC-001 final response (4,196 chars) reveals that the
agent actually produced excellent clinical content that SHOULD satisfy more
criteria than the judge awarded:

**C04 (return precautions): Judge says FAIL, content says PASS**
- Agent listed 10 specific return precautions including: fever not responding
  to Tylenol, worsening SOB, chest pain, hemoptysis, inability to tolerate PO,
  confusion, no improvement after 48-72h, palpitations with A-fib context
- Judge evidence: "The visible trajectory does not show the agent explicitly
  including the required specific..."
- **Root cause:** 49-turn trajectory with tool calls. The detailed final
  response is buried. Judge appears to lose information in long context.

**C05 (reading level): Judge says FAIL, content says PASS**
- Agent explicitly states "6th-Grade Reading Level — Simple words, short
  sentences, no medical jargon without explanation"
- Same root cause: long trajectory context.

**C07 (diabetes management): Legitimate FAIL — task-world mismatch**
- Task describes patient with "Type 2 Diabetes (A1c 7.8%)"
- World state patient (William Johnson, PAT-07A0CA6E) has: stroke, A-fib,
  depression, hyperlipidemia, asthma — no diabetes
- Agent correctly adapted to the world state patient's actual conditions
- Criterion tests for diabetes content that the world state doesn't support
- **This is a benchmark design issue:** tasks reference patient attributes
  that may not exist in the seeded world state

### Recommendations

1. **Judge trajectory formatting:** Summarize tool calls, present final
   response prominently. Long trajectories degrade judge accuracy.
2. **Task-world alignment:** Either seed task-specific patient data or
   adjust criteria to test what the world state actually contains.
3. **MAX_RESPONSE_TOKENS:** Current 4096 is adequate (final response is
   4,196 chars ≈ 1,000 tokens), not a limiting factor.

---

## 8. Critical Bug: Task-World Mismatch (Fixed)

**Discovered during v2 pilot analysis.** This section documents a systematic
design issue and its resolution.

### The Problem

Every task YAML defines a `patient:` section with detailed clinical data
(age, sex, allergies, vitals, labs, imaging). But this data was **never
injected into the world state**. The task loader discarded it. Agents
searched for patients that didn't exist.

**Impact by task:**

| Task | Expected Tool Flow | What Happened | Root Cause |
|------|-------------------|---------------|------------|
| CC-001 | search → history → discharge | Partially worked — tools find seeded patients | Task patient ≠ seeded patient (different allergies, PMH) |
| CC-002 | history → encounter → consult | Claude made 28 tool calls, found nothing | 62M with AFib doesn't exist in world |
| CC-003 | history → encounter → handoff | GPT correctly refused to fabricate data | 71F with COPD not in world |
| CC-004 | encounter → history → communicate | GPT got 0.500 from text quality alone | Tool criteria impossible without patient |

### Second Bug: Allergy Erasure

`getPatientHistory` overwrote Patient dataclass allergies with a search for
separate allergy entities (which don't exist in the seeded world). Result:
even seeded patients returned **empty allergy lists**.

```python
# BEFORE (bug): overwrites even if entity search finds nothing
data["allergies"] = allergy_entities  # [] if no allergy entities exist

# AFTER (fix): only overwrite if entity search found results
if allergy_entities:
    data["allergies"] = allergy_entities
# else: preserve Patient's own allergy data from dataclass
```

### The Fix: Task Patient Injection

New module `src/healthcraft/tasks/inject.py` converts the task's `patient:`
section into proper entity instances and injects them into the world state:

1. Creates a Patient entity with demographics, allergies, medications, PMH
2. Creates an Encounter entity with vitals, labs, imaging, chief complaint
3. Entities are discoverable by existing MCP tools (searchEncounters,
   getPatientHistory, getEncounterDetails)
4. Called in orchestrator after world seeding, before agent execution

**Verified:** CC-002 task patient now discoverable:
- `searchEncounters("Palpitations")` → finds injected encounter
- `getPatientHistory` → returns amiodarone allergy correctly
- `getEncounterDetails` → returns HR=142, BP=128/84, 8 labs, 1 imaging study

### Revised Finding: GPT Tool Engagement Is Task-Specific

The v2 pilot (32 trials) revealed that **GPT's zero-tool behavior is NOT
universal**. It varies by task:

| Task | GPT Avg Tools | GPT Avg Reward | Pattern |
|------|--------------|----------------|---------|
| CC-001 | 0.0 | 0.222 | Zero-tool (writes from parametric knowledge) |
| CC-002 | 0.8 | 0.000 | Near-zero-tool + safety gate fail |
| CC-003 | 10.2 | 0.000 | Active tool use! But can't find patient → fails |
| CC-004 | 0.2 | 0.450 | Text-only, decent reward from llm_judge criteria |
| CC-005 | 2.2 | 0.300 | Light tool use |
| CC-006 | 0.0 | 0.375 | Zero-tool, moderate text quality reward |
| CC-007 | 10.5 | 0.136 | Active tool use, mixed results |

GPT engages with tools on CC-003 (10.2 avg) and CC-007 (10.5 avg) — tasks
that involve complex multi-system patients requiring data gathering. It
skips tools on CC-001, CC-004, CC-006 — tasks where the description alone
provides enough context for text generation.

This refines the Section 3 diagnosis: GPT's behavior is **"Selective Tool
Avoidance"** rather than **"Incomplete Exploration of Available Tools"**.
The model makes a (suboptimal) cost-benefit decision about when tools are
worth using.

---

*Generated 2026-03-10. Updated with task-world mismatch fix and GPT tool
engagement analysis. Oracle seed=42.*
