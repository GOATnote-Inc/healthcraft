# Paper Revision Notes (arXiv v2)

Notes for sharpening the HEALTHCRAFT whitepaper for v2 revision. The arXiv v1
submission is frozen -- all v1 numbers are untouchable. v2 additions are
clearly separated and marked `TBD-after-pilot` until backed by results.

## v1 Measured Claims (do not change)

These claims are backed by `results/pilot-v8-*/` trajectories. They are
locked by `scripts/verify_canonical_numbers.py` and `% CN:` tags in LaTeX.

| Metric | Claude Opus 4.6 | GPT-5.4 |
|--------|-----------------|---------|
| Pass@1 | 24.8% [21.5-28.4] | 12.6% [10.2-15.6] |
| Pass@3 | 37.9% | 24.6% |
| Pass^3 | 13.8% | 3.1% |
| Avg reward | 0.634 | 0.546 |
| Safety-fail rate | 27.5% | 34.0% |

Multi-step workflows collapse: Claude 1.0%, GPT 0.0%.

195 tasks x 3 trials = 585 runs. Cohen's kappa = 0.553 (judge reliability).

## Sharpened Limitations (new text for v2 Section 6)

These limitations were identified by the staff-research-engineer review
and must be explicitly stated in the paper:

### 1. LLM-judge dependence

63.5% of 2,241 criteria (1,420) use `llm_judge` verification. Overall
kappa = 0.553 (moderate). Long-trajectory kappa = 0.306. This is the
single largest source of evaluation variance.

**v2 text:** "The majority of criteria (63.5%) rely on LLM judge
evaluation with moderate inter-rater reliability (kappa = 0.553). This
limits reproducibility, particularly for long trajectories where judge
context overload (failure pattern 7) reduces reliability to kappa = 0.306."

### 2. Static patient state

`WorldState.advance_time()` advances the clock but does not evolve
patient physiology. All vitals, labs, and imaging results are static
from scenario start. This means the agent cannot observe the effects
of its treatment decisions.

**v2 text:** "Patient state is static: vitals and lab values do not
change in response to treatment. This eliminates closed-loop clinical
reasoning from the evaluation, limiting validity for scenarios where
treatment response is the key decision signal."

### 3. Duplicate-order and duplicate-append bugs

`createClinicalOrder` mints a fresh UUID per call -- duplicate orders
are silently created. `updatePatientRecord` appends to allergy/medication
lists without deduplication. Both identified but not fixed in V8 to
preserve result reproducibility.

**v2 text:** "Two known bugs in mutating tools (duplicate clinical
orders, duplicate allergy/medication appends) were identified after
V8 results were frozen. They are corrected behind opt-in flags in
v0.2 but not reflected in the reported V8 numbers."

### 4. No idempotency or retry semantics

Tool calls have no retry logic, no timeout handling, and no
idempotency guarantees. This is unrealistic for production clinical
systems where network failures and duplicate requests are common.

### 5. Benchmark coverage

130 of 370 OpenEM conditions (35%) are covered by the 195-task set.
The remaining 65% of conditions have no evaluation tasks.

### 6. Long-trajectory judge context overload

Failure pattern 7: in trajectories exceeding 40 turns (typical for
Claude), the cross-vendor judge misses content in the final response.
This disproportionately affects Claude evaluations.

## Tightened Novelty Claims

### What HEALTHCRAFT contributes (v2 should emphasize)

- **EM-specific adaptation** of the Corecraft architecture to emergency
  medicine, a domain with unique time pressure, safety gate dominance,
  and multi-system coordination requirements.
- **Dual-layer rubric** combining binary criteria (Eq. 1) with diagnostic
  dimension analysis -- 6 weighted dimensions for failure diagnosis.
- **Safety gate design** where any safety-critical criterion violation
  zeroes the reward. This non-convex reward landscape is harder to
  optimize than retail/enterprise domains.
- **24 MCP tools** mapping to real clinical workflows (4 waves:
  read/compute/mutate/workflow) with FHIR R4 entity graph.

### What is inherited (v2 should acknowledge)

- Corecraft's `r = (1/|C|) * Sigma sat(c, tau)` reward formulation (Eq. 1)
- Corecraft's Docker bundle architecture (Table 2)
- Corecraft's noise injection framework (Section 5.5)
- Pass^k methodology from tau^2-Bench and LostBench
- Cross-vendor judging pattern (not novel to this work)

## v2 Additions (TBD-after-pilot)

Each item below requires a completed pilot in `results/` before any
claim can be made in the paper. Until then, mark as `TBD-after-pilot`.

### v9 Deterministic Channel

- **What:** rubric_channel=v9 converts defensibly-deterministic llm_judge
  criteria to world_state checks.
- **Status:** Infrastructure complete. Overlay file starts empty; entries
  added after clinical review + kappa validation gate (>= 0.80/category).
- **Paper claim:** TBD-after-pilot. Report as "v9 Deterministic Pilot"
  table alongside V8, not as a replacement.

### Dynamic Patient State

- **What:** `--dynamic-state` flag enables vitals trajectories
  (sepsis/ACS/respiratory/stable) with reassessment triggers.
- **Status:** Infrastructure complete. No tasks have
  `clinical_trajectory` field yet.
- **Paper claim:** TBD-after-pilot. Report as "Dynamic-State Pilot
  (v2 Addendum)" table -- not comparable to V8.

### Idempotent Tools

- **What:** `HC_IDEMPOTENT_TOOLS=1` fixes duplicate-order and
  duplicate-append bugs.
- **Status:** Infrastructure complete. Tests pass.
- **Paper claim:** TBD-after-pilot. Report as "Idempotent-Tools Pilot"
  -- expected to change V8 numbers for tasks with duplicate orders.

### Expanded Task Set

- **What:** Additional tasks covering more OpenEM conditions.
- **Status:** Not started. See `docs/TASKSET_EXPANSION_PLAN.md`.
- **Paper claim:** TBD-after-pilot. "195-task set" remains the v1
  benchmark; new tasks reported as a separate set.

## What Has NOT Been Re-Measured

This section is critical for intellectual honesty. If no new pilot ran,
no improvement claim is made.

- V8 numbers with v9 overlay applied: NOT measured
- V8 numbers with dynamic state: NOT measured (no tasks have trajectories)
- V8 numbers with idempotent tools: NOT measured
- Gemini 3.1 Pro V8 completion: ~43% (250/585 runs; deferred)
- Any claim of reduced judge dependence: NOT measured (overlay is empty)
- Any claim of improved task coverage: NOT measured (no new tasks)

## Rule

If no new pilot ran, no improvement claim. Period. Every v2 number must
trace to a `results/` artifact via `scripts/verify_v2_claims.py`.
