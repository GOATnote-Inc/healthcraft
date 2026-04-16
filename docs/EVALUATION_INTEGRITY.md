# Evaluation Integrity

## Approach

HEALTHCRAFT maintains a public, versioned audit trail of all evaluation
infrastructure changes. Every bug discovery produces a new evaluation version
with re-run trajectories -- never retroactive corrections to existing results.

All results in `results/` are immutable. Prior versions are preserved as
reference data regardless of known issues.

This document records the full history of evaluation versions, infrastructure
bugs, corrections, and known limitations.

## Version History

| Version | Date | Tasks | Trials | Models | Status | Key Change |
|---------|------|-------|--------|--------|--------|------------|
| v0 | 2026-03-10 | 20 | varied | 2 | Exploratory | Initial wiring |
| v1 | 2026-03-10 | 20 | varied | 2 | Exploratory | Schema fixes |
| v2 | 2026-03-10 | 20 | 5 | 2 | Complete | First complete eval |
| v3 | 2026-03-10 | 20 | 5 | 2 | Complete | Task entity injection |
| v4 | 2026-03-10 | 20 | 5 | 2 | Complete | Ordering + judge fixes |
| v5 | 2026-03-10 | 1 | 3 | 1 | Complete | CC-003 name fix |
| v6 | 2026-03-11 | 195 | 1 | 2 | INVALIDATED | Post-hoc audit found 2 critical bugs |
| v7 | 2026-03-13 | 195 | 3 | 2 | Superseded | 5 infrastructure bugs discovered post-publication |
| v8 | 2026-03-15 | 195 | 3 | 2 | Superseded | 6 bugs fixed. 0 criteria flips on offline rescore validation. |
| v9 | 2026-03-22 | 195 | 3 | 3 | Current | Added Gemini 3.1 Pro Preview. Judge reliability study (kappa=0.553). Gemini thought_signature fix. |

## V7 to V8: What Changed and Why

V7 was published as authoritative on 2026-03-13. Within 2 days, the rescore
validation pipeline identified 5 infrastructure bugs. Combined with 1
additional tool-side bug, V8 corrects 6 issues total.

### Bug Inventory

| Bug | Type | Impact Direction | Criteria Affected |
|-----|------|-----------------|-------------------|
| Parameter qualifiers silently dropped | Evaluator | Inflated (both, mostly Claude) | 602 criteria flips S->U |
| AND/OR compound clauses not parsed | Evaluator | Deflated (minor) | 9 criteria flips U->S |
| Underscore/hyphen protocol name mismatch | Evaluator | Deflated (both) | Protocol-dependent criteria |
| processTransfer `destination_facility` rejected | Tool | Deflated (GPT) | Transfer task criteria |
| processTransfer unknown facility blocking error | Tool | Deflated (GPT) | Transfer task criteria |
| Injected entity IDs missing from agent prompt | Agent | Deflated (GPT) | Entity-dependent criteria |

### Evaluator-side bugs (inflated scores)

The parameter qualifier bug was the largest single source of error. V7's
evaluator treated `"audit_log contains call to createClinicalOrder for lab"`
and `"audit_log contains call to createClinicalOrder"` identically -- the
`"for lab"` qualifier was silently dropped. This gave credit for any
`createClinicalOrder` call regardless of what was ordered.

Re-scoring V7 trajectories with the V8 evaluator produced 611 criteria flips:
602 satisfied-to-unsatisfied (from qualifier enforcement) and 9
unsatisfied-to-satisfied (from compound OR parsing).

### Tool-side bugs (deflated GPT scores)

Three tool-side bugs disproportionately affected GPT because GPT follows
schema parameter names literally while Claude adapts to error messages.
The `processTransfer` bugs meant GPT's correctly-formatted transfer requests
were rejected. The missing entity ID injection meant GPT could not discover
which patient or encounter a task was about.

### Quantified Impact

| Metric | V7 Claude | V8 Claude | Delta | V7 GPT | V8 GPT | Delta |
|--------|-----------|-----------|-------|--------|--------|-------|
| Avg Reward | 0.730 | 0.634 | -0.096 | 0.264 | 0.546 | +0.282 |
| Pass@1 | 26.8% | 24.8% | -2.0pp | 4.6% | 12.6% | +8.0pp |
| Safety Failures | 17.9% | 27.5% | +9.6pp | 60.9% | 34.0% | -26.9pp |

Net effect: Claude decreased (false passes removed). GPT nearly tripled in
pass rate (tool bugs fixed). Safety failure rates converged from opposite
directions.

## Cumulative Infrastructure Impact

| Version | Claude Avg Reward | GPT Avg Reward |
|---------|-------------------|----------------|
| v2 (baseline) | 0.266 | 0.188 |
| v8 (current) | 0.634 | 0.546 |
| Cumulative delta | +138% | +190% |

Most early "model failures" were benchmark failures. The infrastructure
correction trajectory (v2 through v8) demonstrates that environment fidelity
is the primary determinant of evaluation validity, consistent with
Corecraft's observation that "the quality of the environment is the quality
of the evaluation" (Section 3).

## Known Evaluation Limitations

These are limitations of the current evaluation methodology that users
should consider when interpreting results.

**Non-deterministic grading.** 57.1% of criteria (1,280 of 2,255) use
`llm_judge` verification. Judge decisions are non-deterministic even at
temperature 0.0. The rescore validation (0 flips on V8) provides a lower
bound on evaluator stability but does not cover judge variance. A judge
reliability study (2026-03-22, n=100, 3 repeats each) measured Cohen's
kappa = 0.553 (moderate agreement) with 77% self-agreement rate. See
[Judge Reliability](JUDGE_RELIABILITY.md) for full results.

**Judge context overload.** On trajectories exceeding ~40 turns, the
cross-vendor judge misses content in the final agent response. This affects
Claude (median ~49 turns) more than GPT (median ~8 turns). Identified on
CC-001 C04/C05 where the judge failed to find a diagnosis clearly present
in the last assistant message. The reliability study found kappa = 0.306
for long trajectories (>40 turns) vs. 0.542 for medium (15-40 turns),
confirming that judge accuracy degrades with trajectory length.

**Limited trials.** 3 trials per task. Wilson confidence interval ceiling
at n=3 is 0.57. Pass^5 (for direct comparison with tau2-Bench) requires 5
trials. Confidence intervals on per-task metrics are wide.

**Two models (V8), three models (V9).** V8 evaluated 2 models. Corecraft
reports 3+ frontier models (Table 1). V9 adds Gemini 3.1 Pro Preview as
the third model, strengthening the parity comparison.

**No external validation.** All evaluations have been run by the same team.
No independent replication exists. The rescore validation pipeline provides
internal consistency checks but not external verification.

**No contamination analysis.** Model training data may include OpenEM
conditions, clinical guidelines, or similar emergency medicine scenarios.
No analysis has been done to quantify potential data leakage.

**Single-team criteria authorship.** All 2,255 criteria were authored by
one team without external clinical peer review. Criteria correctness depends
on the authors' clinical expertise.

**Limited oracle validation.** Systematic oracle validation (proving tasks
are solvable by demonstrating a reference solution) exists only for CC-001.
104 tasks (53%) are unsolved by both models across all trials. Some may be
unsolvable due to rubric or world state issues.

**Safety gate non-convexity.** The safety gate (any `safety_critical`
criterion violated -> reward=0) creates a non-convex reward landscape. A
trial scoring 0.900 on 10/11 criteria scores 0.000 if the 11th is
safety-critical. This is intentional (clinical safety is non-negotiable)
but makes reward comparison across models sensitive to safety failure
distribution.

**V8 may contain undiscovered issues.** Every major evaluation version has
contained infrastructure bugs. The rescore validation pipeline catches
evaluator-side bugs but cannot detect tool-side bugs, criteria authoring
errors, or world state issues without oracle validation.

## How to Help

- **Run the benchmark on your model.** See
  [Evaluate Your Model](EVALUATE_YOUR_MODEL.md) for setup and protocol.
- **Audit specific criteria for correctness.** Criteria are in
  `configs/tasks/` YAML files. Report suspected errors as issues.
- **Report infrastructure bugs.** If a criterion gives unexpected results,
  include the task ID, criterion ID, and trajectory excerpt.
- **Contribute oracle validations.** Demonstrate that a zero-reward task is
  solvable (or prove it is not) by providing a reference tool-call sequence.
- **Independent replication.** Run the same models and report whether your
  results match. Divergence indicates environment or configuration issues.

## Immutability Policy

All results in `results/` are append-only. Existing result files are never
modified, deleted, or overwritten. Bug discoveries produce new evaluation
versions with new result directories.

Prior versions are preserved as reference data:
- `results/pilot-v6-*` -- V6 (invalidated)
- `results/pilot-v7-*` -- V7 (superseded)
- `results/pilot-v8-*` -- V8 (current)
- `results/rescore-v7/` -- V7 rescore validation report
- `results/rescore-v8/` -- V8 rescore validation report (0 flips)
- `results/pilot-v9-gemini-pro/` -- V9 Gemini 3.1 Pro Preview (current)
