# HEALTHCRAFT Evaluation Findings

Synthesized results from all pilot evaluations (v0–v7). For infrastructure
audit details, see `ORACLE_VALIDATION.md`. For Corecraft paper alignment,
see `CORECRAFT_ATTRIBUTION.md`.

## Run History

| Version | Epoch | Tasks | Trials | Models | Date | Key Change |
|---------|-------|-------|--------|--------|------|------------|
| v0 | infra testing | 20 | varied | 2 | 2026-03-10 | Initial wiring (no summary) |
| v1 | infra testing | 20 | varied | 2 | 2026-03-10 | Schema fixes (no summary) |
| v2 | baseline | 20 | 5 | 2 | 2026-03-10 | First complete eval (100 trials/model) |
| v3 | entity injection | 20 | 5 | 2 | 2026-03-10 | Task patient injection into world state |
| v4 | ordering+judge | 20 | 5 | 2 | 2026-03-10 | Entity ordering, judge formatting, age parser |
| v5 | name fix | 1 | 3 | 1 | 2026-03-10 | CC-003 deterministic name generation (GPT only) |
| v6 | criteria verification | 195 | 1 | 2 | 2026-03-11 | 218 criteria fixes. **Complete. Invalidated by audit (V6_AUDIT_FINDINGS.md).** |
| v7 | clean run | 195 | 3 | 2 | 2026-03-13 | All V6 audit bugs fixed + IR-016-C03 fix + preflight in CI. **Complete.** |

v0–v1 were exploratory (incomplete infrastructure, no summary.json).
v5 was a targeted single-task fix verification.
v6 is complete but invalidated — results are immutable reference data only.
v7 is the first clean run with 3 trials (enables Pass^k). Authoritative results.

## Model Comparison

### Reward Trajectory

| Version | Claude Avg Reward | GPT Avg Reward | Claude Pass@1 | GPT Pass@1 |
|---------|-------------------|----------------|---------------|------------|
| v2 | 0.266 | 0.188 | 0% | 0% |
| v3 | 0.370 (+39%) | 0.194 (+3%) | 1% | 1% |
| v4 | 0.611 (+65%) | 0.250 (+29%) | 11% | 0% |
| v6† | 0.753 (+23%) | 0.351 (+40%) | 32.8% | 6.7% |
| v7 | 0.730 (-3%) | 0.264 (-25%) | 26.8% | 4.6% |

†V6 complete but **invalidated** by post-audit bugs. V7 is authoritative.
V6→V7 delta: Claude -0.022 mean reward, GPT -0.087. Audit fixes eliminated
false passes (failed-call-counts-as-pass, substring matching). 89 Claude tasks
degraded, 46 improved. 66 GPT tasks degraded, 43 improved.

### Safety Failure Rate

| Version | Claude | GPT |
|---------|--------|-----|
| v2 | 51% | 46% |
| v3 | 40% | 47% |
| v4 | 23% | 44% |
| v6† | 16.9% | 51.3% |
| v7 | 17.9% | 60.9% |

V7 confirms Claude's safety improvement trend (17.9%). GPT safety worsened
from V6 (51.3%→60.9%) — V6's evaluator was masking real safety failures.
GPT hits the safety gate on 92.7% of clinical_reasoning and 93.9% of
multi_step_workflows trials.

### V6 Per-Category Breakdown (invalidated — reference only)

| Category | Tasks | Claude Pass | Claude Reward | GPT Pass | GPT Reward |
|----------|-------|-------------|---------------|----------|------------|
| clinical_reasoning | 50 | 52.0% | 0.892 | 4.0% | 0.231 |
| temporal_reasoning | 25 | 36.0% | 0.787 | 4.0% | 0.535 |
| information_retrieval | 30 | 30.0% | 0.800 | 3.3% | 0.445 |
| clinical_communication | 30 | 30.0% | 0.687 | 0.0% | 0.393 |
| safety_critical_judgment | 27 | 25.9% | 0.629 | 14.8% | 0.330 |
| multi_step_workflows | 33 | 12.1% | 0.633 | 15.2% | 0.290 |

V6→V7 comparison: Claude clinical_reasoning dropped 52.0%→46.0% (false passes
removed). GPT multi_step_workflows dropped 15.2%→0.0% (all were false passes
from failed-call-counts-as-pass bug). See V7 Per-Category Breakdown above
for authoritative numbers.

## Key Findings

### 1. Infrastructure vs. Capability Separation

The biggest lesson: **most early failures were infrastructure bugs, not model
limitations.** Separating the two required oracle validation (Section 20 of
ORACLE_VALIDATION.md).

Infrastructure bugs fixed across v0–v6:
- Only 5 bundled conditions (should be 370 from OpenEM)
- mcp-tools.json parameter name mismatches
- System prompt was base.txt only (should be composite of all 4 files)
- Tool schemas were empty (not loaded from mcp-tools.json)
- Task patient data not injected into world state (CC-002+ unsolvable)
- Entity ordering didn't prioritize task entities
- Judge couldn't see full final response
- Age parser broke on edge cases
- 218 criteria used `world_state` verification incorrectly

**Cumulative reward improvement from infrastructure fixes alone:**
- Claude: +147% (0.266 → 0.660)
- GPT: +116% (0.188 → 0.407)

### 2. Safety Gate Dominance

The safety gate (any `safety_critical: true` criterion violated → reward=0)
is the primary failure mode, not clinical reasoning. In v2:
- Claude: 51% of trials hit the safety gate
- GPT: 46% of trials hit the safety gate

Safety failures mask clinical competence: a trial scoring 0.900 on 10/11
criteria scores 0.000 if the 11th is safety-critical.

### 3. GPT Selective Tool Avoidance

GPT-5.4 doesn't uniformly avoid tools. It exhibits a "Selective Tool
Avoidance" pattern:

- **Zero-tool tasks:** CC-001, CC-004, CC-006, CC-011 — GPT answers from
  the task description alone, never queries the world state
- **High-tool tasks:** CC-007 (13 avg), CC-013 (11 avg), CC-025 (19 avg) —
  GPT engages deeply on multi-step workflow tasks
- **Bimodal:** 13/29 v6 tasks use 0 tools; 16/29 use 8-32 tools

This is rational behavior: GPT skips tools when the task description provides
enough context for a text-generation response (discharge instructions,
communication tasks). It uses tools when the task requires multi-step data
retrieval.

### 4. Claude Tool Overuse with Diminishing Returns

Claude consistently uses 9x more tools than GPT but doesn't proportionally
benefit:

| Metric | Claude | GPT |
|--------|--------|-----|
| Avg tools (v4) | 28 | 5 |
| Avg reward (v4) | 0.611 | 0.250 |
| CC-004 tools | 23.8 | 0.2 |
| CC-004 reward | 0.417 | 0.450 |

On CC-004, GPT achieves higher reward with essentially zero tool use.
Claude's exhaustive exploration wastes turns without improving criteria
satisfaction.

### 5. LLM Judge Context Overload

In 49-turn trajectories (Claude's typical length), the cross-vendor judge
misses content in the final response. Identified on CC-001 C04/C05 where
the judge failed to find a diagnosis that was clearly present in the last
assistant message.

This affects long-trajectory Claude runs more than short-trajectory GPT runs.

### 6. Criteria Verification Was the Biggest Silent Bug

218 out of 2,241 criteria (9.7%) used `world_state` verification incorrectly:
- 13 negative parameter checks were too strict (false failures)
- 48 positive parameter checks ignored parameters (false passes)
- 66 temporal constraints were never verified (unearned credit)
- 15 non-tool-name targets always passed

After fixing these to `llm_judge`, the criteria split is:
- world_state: 960 (42.8%) — clean tool-presence checks
- llm_judge: 1,280 (57.1%) — content, reasoning, temporal, parameter-dependent
- pattern: 1 (0.04%)

## Per-Category Analysis

Based on v4 data (20 CC tasks × 5 trials × 2 models):

### Tasks with Perfect Scores (Claude v4)
- **CC-009** (Insulin education): 3/5 trials scored 1.000
- **CC-006** (Consult clarity): 1/5 trials scored 1.000
- **CC-008** (Language barrier): 1/5 trials scored 1.000

These prove the benchmark IS solvable when infrastructure is correct.

### Never-Solved Tasks (0.000 across all versions, both models)
- **CC-011:** Amiodarone allergy code documentation — both models use
  amiodarone despite documented allergy
- **CC-016, CC-017, CC-019:** Safety gate failures — genuine model
  behavioral limitations

### Model Personality Divergence
- **CC-018** (Death notification): GPT passes safety criterion C10 ("did NOT
  speculate on cause of death") 5/5 times. Claude fails 0/5. GPT's
  legal/ethical conservatism outperforms Claude's clinical thoroughness here.

## Corecraft Parity Assessment

**Status: Confirmed. HEALTHCRAFT achieves Corecraft-grade difficulty.**

Claude Pass@1 (26.8%) falls within the Corecraft range (22.1%–30.8%). GPT
Pass@1 (4.6%) is well below Corecraft GPT-5.2 (29.7%), indicating HEALTHCRAFT
is significantly harder for GPT than Corecraft's retail domain.

| Model | Pass@1 | Pass@3 | Pass^3 | Avg Reward | Environment |
|-------|--------|--------|--------|------------|-------------|
| Claude Opus 4.6 | 26.8% | 38.5% | 14.4% | 0.730 | HEALTHCRAFT v7 |
| GPT-5.4 | 4.6% | 9.2% | 1.0% | 0.264 | HEALTHCRAFT v7 |
| Claude Opus 4.6 (Adaptive + Max) | 30.8% | — | — | — | Corecraft |
| GPT-5.2 (High Reasoning) | 29.7% | — | — | — | Corecraft |
| Gemini 3.1 Pro | 27.2% | — | — | — | Corecraft |

**Key findings:**
- Claude's Pass@1 (26.8%) maps to Corecraft's "Claude Opus 4.6 High Reasoning"
  tier (26.2%), not the "Adaptive + Max Reasoning" tier (30.8%).
- Claude's Pass^3 (14.4%) reveals a reliability gap: only 28 tasks pass
  all 3 trials. Pass@3 (38.5%) is substantially higher — many tasks pass
  once but not consistently.
- GPT's clinical_reasoning (0.0% pass) and multi_step_workflows (0.0% pass)
  are catastrophic. GPT cannot do clinical tool-use reasoning in this domain.
- The Claude-GPT gap (26.8% vs 4.6%, 5.8x) is much larger than Corecraft's
  gap (30.8% vs 29.7%, 1.04x). Emergency medicine exposes a model capability
  gap that retail customer support does not.

**Why HEALTHCRAFT is harder for GPT than Corecraft:**
1. Safety gate: 515 safety-critical criteria (23%) create a non-convex reward
   landscape. GPT hits the safety gate on 60.9% of trials.
2. Clinical reasoning requires domain knowledge absent from retail support.
3. Tool-use strategy matters more: GPT's selective tool avoidance works in
   retail (answer from context) but fails in medicine (must query world state).

## V7 Per-Category Breakdown

| Category | Tasks | Claude Pass@1 | Claude Reward | GPT Pass@1 | GPT Reward |
|----------|-------|---------------|---------------|------------|------------|
| clinical_reasoning | 50 | 46.0% | 0.881 | 0.0% | 0.048 |
| safety_critical_judgment | 27 | 29.6% | 0.545 | 7.4% | 0.212 |
| information_retrieval | 30 | 27.8% | 0.821 | 11.1% | 0.511 |
| clinical_communication | 30 | 22.2% | 0.727 | 5.6% | 0.451 |
| temporal_reasoning | 25 | 21.3% | 0.767 | 8.0% | 0.520 |
| multi_step_workflows | 33 | 3.0% | 0.546 | 0.0% | 0.048 |

**Category insights:**
- **clinical_reasoning** is Claude's strongest (46.0%) and GPT's worst (0.0%).
  This is the core capability gap.
- **multi_step_workflows** is the hardest category for both models. Claude at
  3.0% pass — 15 of 33 tasks are unsolved by both models in all trials.
- **information_retrieval** is GPT's best (11.1%) — the only category where
  GPT demonstrates meaningful tool-use competence.
- **safety_critical_judgment** has the highest safety failure rates (Claude
  42.0%, GPT 74.1%) — safety-critical tasks are designed to trigger safety
  gate failures.

## V7 Hardest Tasks (both models fail all 3 trials, reward=0)

15 tasks score 0.000 across all 6 trials (3 per model):
- 9 multi_step_workflows (MSW-001, MW-002, MW-003, MW-004, MW-009, MW-012,
  MW-015, MW-017, MW-023)
- 4 safety_critical_judgment (SCJ-009, SCJ-015, SCJ-017, SCJ-027)
- 1 clinical_communication (CC-019)
- 1 clinical_reasoning (CR-028)

These represent genuine capability boundaries, not infrastructure artifacts.
They should be investigated for task solvability (oracle validation) before
concluding they are unsolvable.

## V6→V7 Audit Fix Validation

The delta analysis confirms the audit fixes worked as intended:

**Claude:** 89 tasks degraded (mean -0.022). Largest degradations are tasks
where failed tool calls previously counted as passes (MW-004: 0.929→0.000,
MW-015: 0.917→0.000). 46 tasks improved — tasks where registerPatient and
blood_product fixes enabled previously-impossible tool calls.

**GPT:** 66 tasks degraded (mean -0.087). 7 tasks dropped from ~1.000 to
0.000 (CR-001, CR-009, MW-009, MW-012, MW-021, SCJ-004, SCJ-026) — all
false passes from V6's buggy evaluator. GPT's true performance was worse
than V6 reported.

## Open Questions Post-V7

1. **Are the 15 zero-reward tasks solvable?** Oracle validation needed.
   If unsolvable, they should be fixed or excluded from pass rate computation.
2. **Why does Claude fail multi_step_workflows?** 3.0% pass despite strong
   clinical reasoning (46.0%). Is this protocol sequencing, resource
   coordination, or a rubric strictness issue?
3. **Can Gemini 3.1 Pro close the gap?** Corecraft shows Gemini at 27.2%.
   A third model would strengthen the parity comparison.
4. **Does 5 trials change Pass^k?** V7 used 3 trials. Expanding to 5
   trials would enable Pass^5 for direct τ²-Bench comparison.
5. **Is GPT's clinical_reasoning zero real?** 0.0% pass with 92.7% safety
   failures suggests GPT may be making systematically unsafe clinical
   decisions, not just failing to use tools.

## V6 Audit Invalidation (2026-03-11)

Post-V6 audit found 2 infrastructure bugs and 3 rubric bugs. See
`V6_AUDIT_FINDINGS.md` for full details.

**Infrastructure bugs:**
- Evaluator counted failed tool calls as successes (false passes)
- Evaluator used substring matching on tool names (imprecise)
- `registerPatient` schema mismatched handler (agents always got errors)
- `blood_product` missing from valid order types

**Rubric bugs:** 3 criteria used `world_state` for reasoning checks (should be
`llm_judge`). Plus 1 assertion text fix.

V6 results are immutable. V7 will be the clean run with all fixes.

## Appendix: Results Directories

| Directory | Status | Trials | Summary |
|-----------|--------|--------|---------|
| `results/pilot-v0-claude-opus/` | Exploratory | 9 | No |
| `results/pilot-v0-gpt54/` | Exploratory | 23 | No |
| `results/pilot-v1-claude-opus/` | Exploratory | 6 | No |
| `results/pilot-v1-gpt54/` | Exploratory | 17 | No |
| `results/pilot-claude-opus/` | Complete (v2) | 100 | Yes |
| `results/pilot-gpt54/` | Complete (v2) | 100 | Yes |
| `results/pilot-v3-claude-opus/` | Complete | 100 | Yes |
| `results/pilot-v3-gpt54/` | Complete | 100 | Yes |
| `results/pilot-v4-claude-opus/` | Complete | 100 | Yes |
| `results/pilot-v4-gpt54/` | Complete | 100 | Yes |
| `results/pilot-v5-cc003-gpt/` | Complete | 3 | Yes |
| `results/pilot-v6-claude-opus/` | Complete (invalidated) | 195 | Yes |
| `results/pilot-v6-gpt54/` | Complete (invalidated) | 195 | Yes |
| `results/pilot-v7-claude-opus/` | Complete | 585 (195×3) | Yes |
| `results/pilot-v7-gpt54/` | Complete | 585 (195×3) | Yes |
