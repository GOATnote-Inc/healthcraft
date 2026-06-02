# Red-team — HealthCraft paper (arXiv 2605.21496) + the 2026-05/06 work

Adversarial self-review, written to be consumed by the arXiv-v2 update (which lands
when the gpt-5.5 run finishes). Performed **offline** — no model API calls. Ground
rule for v2 (operator decision): **no re-grade** of the V8 trajectories; V8 numbers
will be relabeled, not re-derived. This document is where we attack our own work
*before* a reviewer does. Each item: the attack a hostile reviewer/clinician makes,
the evidence, and the honest mitigation.

## Part A — attacks on the paper

**A1 (highest exposure). "You found your safety grader certifies-unsafe-as-safe, and
you're still printing the old safety numbers."**
V8/V9 were graded on a path whose LLM judge **failed OPEN** on `safety_critical`
criteria (v1 keyword fallback parsed "NOT satisfied"/truncated JSON as `satisfied=True`;
one live contaminated verdict CC-024-C07). With no re-grade, v2 relabels Table 1
"pre-audit grader, superseded, not re-measured." A reviewer will not accept the old
numbers reprinted, even relabeled, as if directional.
*Mitigation:* lead with the disclosure (dedicated Results subsection, not a footnote);
do **not** put V8 numbers in the abstract; state the **direction** explicitly — a
fail-OPEN on a *negated* safety gate **deflates** measured safety-failure, so the true
V8/V9 safety-fail rates are **≥** reported (the bug made the models look *safer*, the
worst direction for a safety paper). Carry the gold-set as evidence the *corrected*
grader is clean, not as a re-measurement of V8.

**A2. "Your load-bearing evidence is 55 self-adjudicated cases."**
`evals/grader_goldset/goldset.yaml` is "hand-labeled, EM-adjudicated" — but the
adjudication is **internal** (our EM-persona panel), not external blinded physicians,
n=55, and it measures grader **mechanics** (does the matcher/parser fire correctly),
**not** whether the criteria are clinically right. 0/0/0 has Wilson CIs as wide as
**[0–24%]** (world_state/v8) and **[0–39%]** (judge_parser).
*Mitigation:* claim only what it supports — "no detected false-PASS/FAIL in 55
EM-adjudicated cases; 95% upper bound on safety false-PASS ≈ 20%." Never call it
physician validation (that is issue #10, still owed). State the CI ceiling in-line.

**A3. "Your new frontier numbers rest on an unvalidated third judge."**
The frontier accounting swapped to **grok-4** for neutrality — but grok-4 as a clinical
judge has **zero** measured agreement (no Cohen's κ, no oracle-agreement check; gemini
was quota-blocked so it was the only working neutral option). opus-4.8's numbers inherit
grok-4's unmeasured reliability.
*Mitigation:* present grok-4 results as "neutral-judge, judge-reliability unmeasured";
do not imply grok-4 ≈ a validated judge. A judge-agreement study is future work alongside #10.

**A4. "'opus-4.8 ≈ V8 Claude-4.6' conflates three changes."**
The comparison crosses **judge** (grok-4 vs V8's GPT/Claude cross-vendor), **channel**
(v10 vs V8's baseline), and **corpus** (205 vs 195). "No generational shift" is not
supported — it is "indistinguishable under a *different measurement apparatus*."
*Mitigation:* frame opus-4.8 as a single-model durability datapoint under the new
apparatus, explicitly not a controlled comparison to V8. Keep the caveat in the caption.

**A5. "'seed=42' does not make your runs reproducible."**
No provider-side sampling seed is sent to any model API (`agent.py` — "seed" appears only
as `world_seed`). seed=42 governs the **environment** (entity generation, noise,
scheduling), not model sampling. With temperature=0 unavailable for both frontier models
and gpt-5.5 at temp=1, **gpt-5.5 trajectories are not reproducible run-to-run** (pilot
CC-001 reward swung 0.889→0.000). Pass^3 conflates capability with sampling luck.
*Mitigation:* say "environment-deterministic, model-stochastic"; scope seed=42 to the
environment; state that frontier-model reproducibility is statistical (Pass@k + CIs over
trials), not bit-exact.

## Part B — attacks on the work/fixes themselves

**B1 (the sharpest). The class gates that "fixed" member-not-class are themselves
incomplete allowlists — so the bug is narrowed, not eliminated.**
`expand_class("thrombolytic")` = {alteplase, tenecteplase, tpa, tnk + brands} —
**missing reteplase/Retavase, streptokinase, urokinase**. `expand_class("anticoagulant")`
is broad but **missing dalteparin/Fragmin, tinzaparin** (LMWHs), betrixaban, lepirudin.
A trajectory ordering an unlisted sibling slips a "did NOT order <class>" gate → the same
silent false-PASS we claimed to fix. We moved the boundary, not the failure mode.
*Mitigation:* state plainly that class gates are curated allowlists with known omissions;
correctness of the *membership* is unverified; the durable fix is an external drug
ontology (RxNorm/ATC class membership), tracked as future work. Do not claim the
member-not-class class of bug is "eliminated" — say "narrowed; completeness unverified."

**B2. The temporal revert handed six lethal gates back to the judge we just called
unreliable.**
The six MW temporal gates were reverted from (deterministic but order-blind) existence
checks to `llm_judge` — the same judge family shown to fail-open/hallucinate. The net
safety change is **unproven**: order-blind-deterministic → order-aware-but-noisy. It is
defensible (the v2 judge fails closed and *can* see turn order) but not validated.
*Mitigation:* present as "removed a deterministic false-PASS shape; the replacement is
judge-graded and inherits judge limitations" — not as a clean win.

**B3. Fail-closed grading lets an unvalidated judge perturb the headline both ways.**
Confirmed (`judge.py:361,367-369,388-393,464-469`): a parse failure / judge exception →
`satisfied=False`. For a **positive** criterion that is a false-FAIL (deflates Pass@1);
for a **negated safety gate** it makes the gate **fire** (inflates safety-fail). Since
grok-4's parse/error rate was never measured, opus-4.8's 23.7% / 28.9% carry an
unquantified judge-reliability term (Pass@1 biased low, safety-fail biased high if grok-4
ever returned malformed output).
*Mitigation:* note the conservative (fail-closed) direction and that the magnitude is
unmeasured; "0 error trajectories" counts agent-side crashes only, not judge hiccups.

**B4. The verdict-locks pin reproducibility, not correctness.**
A locked wrong verdict stays wrong; the lock prevents *drift*, not *error*. The
"0/0/0 + three locks" story establishes no-regression and no-detected-error, **not**
clinical correctness.
*Mitigation:* the paper already half-concedes this; say it outright — locks are an
anti-Goodhart / anti-drift control, complementary to (not a substitute for) the gold-set
and physician validation.

**B5. The consensus/v11 machinery is parked but its latent bugs are real.**
The v11 proposer can launder a hallucinated safety PASS into a permanent deterministic
check (≥0.95 oracle-agreement with no clinical/safety gate, defaulting to the contaminated
saved_judge oracle); `build_consensus` records an abstaining judge as a phantom-False vote
(deflates Fleiss κ). Both latent (v11 empty).
*Mitigation:* v2 must not cite "compute-consensus" / EnsembleJudge supermajority as a
reliability mechanism. Report at v10 only; if v11 is named, label PARKED/UNAUDITED.

**B6. One category carries the safety signal.**
opus-4.8: `multi_step_workflows` produced **79 of 178** safety failures (44%) at 1.9%
pass — and MW is exactly where the audit found the *most* grader defects (bare-order
collapse, the six temporal reverts, MW-016 phenytoin, MW-026 compound-AND). If the MW
rubric is mis-specified, the headline safety-fail rate is largely one category's artifact.
*Mitigation:* report safety-fail with the per-category decomposition; flag MW's
outsized, grader-sensitive contribution explicitly.

## What is genuinely defensible (so we don't over-correct into nihilism)
- The grader **fixes are real and directionally correct** (fail-OPEN → fail-CLOSED is
  strictly safer; the compound-AND and member-not-class corrections are evidenced).
- The **transparency posture** (documenting the audit at all, mirroring superseded-V7) is
  a strength most benchmarks lack.
- The **environment** determinism (seed=42 entities/noise) genuinely holds.
- The **gold-set is clean as far as it measures** (0 detected FP/FN), and the locks make
  the corrected behavior tamper-evident.

## Net guidance for v2
The single highest-integrity move: **front-load A1** (the fail-OPEN disclosure, with the
"made models look safer" direction), claim the gold-set only as mechanics-with-CIs (A2),
caveat every new-frontier number for judge (A3) + apparatus (A4) + reproducibility (A5),
and downgrade "member-not-class eliminated" to "narrowed, completeness unverified" (B1).
None of these need an API call or a re-grade; they are honesty edits the prose can carry.
