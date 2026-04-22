# PoC-Validator Extension — Pre-Ship Gate for Pass Decisions

Design proposal. No code changes attached. Scope: extend the existing
golden-trajectory replay gate from a 30-fixture CI check into a
pre-ship validator that must sign off on every pass decision involving
a `safety_critical: true` criterion.

Source of pattern: PRISM's PoC-validator gate. Source of lesson:
RadSlice post-mortem — L0 pattern grading produced 75% false-positive
rate on passes; even combined with state verification, a replay-based
pre-flight check catches judge drift and harness regression.

## What already exists (baseline — keep)

- `tests/test_evaluator_integrity/test_golden_trajectory_replay.py`:
  30 frozen trajectories, `replay_from_trajectory` re-derives
  `(reward, passed, safety_gate_passed)`, hash-compared to V8 writes.
  Locks down deterministic channels; judge verdicts are carried
  forward (not re-graded) so non-determinism of judges doesn't leak.
- `src/healthcraft/world/state.py:record_audit()`: every MCP tool
  call is an `AuditEntry`. Audit log is the deterministic substrate.
- `src/healthcraft/tasks/rubrics.py:compute_reward()`: hard safety
  gate — any `safety_critical` violated → `r = 0`.
- Rubric channels v8 → v9 → v10 → v11 with overlay composition.

## What is missing (the gate)

A **pass decision** for a safety-critical criterion today is emitted
by the judge and written straight into `criteria_results`, then
aggregated by `compute_reward`. There is no intervening step that
says: "before this PASS ships as reward-impacting, replay the trajectory
against a deterministic simulator and confirm the world-state
preconditions the judge believed were met are actually present in the
audit log."

That step is the gate.

## Gate contract

```
Input:  CriterionResult(id, satisfied=True, evidence, verification=llm_judge,
                         criterion.safety_critical=True)
        + trajectory (turns, tool_calls, world_state_audit_log)

Action: Replay audit log through a deterministic validator that knows
        the criterion's formal invariant (see SAFETY_INVARIANTS_PILOT.md).
        Validator emits: VERIFIED | CONTRADICTED | INSUFFICIENT_EVIDENCE.

Output:
  - VERIFIED:              pass reward = as-is. Log attestation.
  - CONTRADICTED:          downgrade to satisfied=False. Flip safety
                           gate. Log the contradiction for judge-prompt
                           feedback loop.
  - INSUFFICIENT_EVIDENCE: satisfied becomes UNCERTAIN (new state).
                           Does not contribute to reward in either
                           direction. Gate escalates to
                           human-in-loop queue (or ensemble re-judge
                           in v11 consensus mode).
```

## Where it plugs in

- `src/healthcraft/llm/judge.py:evaluate_criterion()` lines 294-387.
  Currently returns `CriterionResult` directly from the judge LLM.
  The gate wraps this return: if `criterion.safety_critical` AND
  `satisfied=True` AND `verification=llm_judge`, route through the
  validator before the result bubbles up.
- `src/healthcraft/tasks/evaluator.py:replay_from_trajectory()` is the
  reference implementation — its deterministic re-derivation code is
  exactly what the validator needs. Refactor the replay engine into
  a reusable library (not test-only) so the gate and the golden test
  share the same path.

## Configuration

```yaml
# configs/poc_validator.yaml
enabled: true
mode: enforce            # enforce | warn | shadow
applies_to:
  - safety_critical: true
  - verification: llm_judge
insufficient_evidence_policy: escalate_to_ensemble   # | downgrade_to_fail | human_review
audit_sink: results/poc_validator_log.jsonl
```

- `shadow`: run validator but do not override judge verdict. Use for
  the first 2 weeks to measure agreement rate before flipping to
  `enforce`. Same pattern as the v9/v10 overlay rollout.
- `warn`: log contradictions but do not change reward. Compromise
  mode for paper reproducibility while the validator stabilizes.
- `enforce`: gate is authoritative for safety-critical.

## Metrics the gate produces

- **Judge-validator agreement rate** per criterion (analog to v9
  overlay PPA/NPA). Target: >95% agreement for `enforce` mode.
- **Contradiction taxonomy**: judge-hallucination (validator says
  world-state doesn't support the claim) vs judge-strictness
  (validator sees required tool call, judge missed it).
- **Insufficient-evidence rate**: how often the trajectory genuinely
  lacks the audit entries needed to verify. High rate here means the
  criterion is badly scoped for deterministic verification — should
  probably be re-authored as world-state check, not llm_judge.

## Integration with v11 consensus

v11 uses an ensemble of 3 judges with 2-of-3 supermajority. The
PoC-validator complements this:
- Consensus catches **judge-to-judge disagreement**.
- PoC-validator catches **judge-to-reality disagreement** — every
  judge can miss the same thing.

Both layers can fire independently. Final safety-critical pass
requires both consensus AND validator VERIFIED.

## Rollout plan

1. **Phase 0 [DONE 2026-04-22]:** Validator package landed at
   `src/healthcraft/evaluator/`. 3 pilot invariants (MW-011 C01/C02/C05),
   15 unit tests, ruff clean, golden-trajectory replay unaffected.
2. **Phase 1 [DONE 2026-04-22]:** Shadow hook wired in
   `replay_from_trajectory`. Env-gated via
   `HEALTHCRAFT_POC_VALIDATOR_SHADOW=1`; JSONL sink at
   `results/poc_validator_log.jsonl`; 25 shadow tests;
   TaskResult byte-identical when shadow is off. Analysis script at
   `scripts/analyze_shadow_log.py` emits per-criterion agreement /
   PPA / NPA / insufficient-evidence rate.
3. **Phase 2 (next):** Replay the 30 frozen golden trajectories with
   `HEALTHCRAFT_POC_VALIDATOR_SHADOW=1`, run the analyzer, measure
   judge-validator agreement on MW-011 C01/C02/C05. Gate: >=95%. If
   below, identify top 3 disagreement classes and patch invariants.
4. **Phase 3:** Flip to `warn` mode (contradiction logged but reward
   unchanged). Ship a model card update.
5. **Phase 4:** Flip to `enforce` on safety-critical only. Wider
   categories later.

## What this costs

- Zero additional LLM spend in `enforce` mode — the gate is pure
  deterministic replay.
- In `shadow` mode, storage cost for the audit sink. Negligible.
- Human review queue cost if `insufficient_evidence_policy =
  human_review`. Budget: physician-time-bounded.

## What this is **not**

- Not a replacement for the judge. Judges still handle clinical
  reasoning criteria where deterministic verification is impossible.
- Not a replacement for ensemble consensus (v11). Both coexist.
- Not a new grading rubric channel. Rubric channels compose criteria;
  this composes the evaluation of a single criterion.
