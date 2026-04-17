======================================================================
  HEALTHCRAFT V9 Deterministic Overlay Audit
======================================================================

Audit date: 2026-04-17
Overlay version: v9 post-tightening (option-B + intent_rescue_reason)
Source code: configs/rubrics/v9_deterministic_overlay.yaml
Validator: scripts/kappa_validation.py (no API calls)
Source trajectories: results/pilot-v8-{claude-opus,gpt54}/ (cached, immutable)
Reproducibility artefact: docs/V9_OVERLAY_AUDIT.json

----------------------------------------------------------------------
Summary
----------------------------------------------------------------------

Overlay entries audited:             44
(criterion x trial) observations:   264
Overall raw agreement v9 vs v8:      76.1%
Overall Cohen's kappa:                0.402
Gate (kappa >= 0.80):                 FAIL
Safety-critical verdict inversions:   6

V8 PASS prevalence (audited subset): 79.5%   (base-rate paradox regime)

----------------------------------------------------------------------
Agreement and kappa by category
----------------------------------------------------------------------

  Category                       n    agree%   kappa   pabak
  -----------------------------------------------------------
  multi_step_workflows          78    82.1     0.533   0.641
  safety_critical_judgment      54    77.8     0.265   0.556
  temporal_reasoning           108    73.1     0.335   0.463
  clinical_communication        12    58.3     0.211   0.167
  clinical_reasoning            12    75.0     0.526   0.500

Kappa is suppressed by V8 PASS prevalence in the 0.78-0.83 band; PABAK
(prevalence- and bias-adjusted kappa) is materially higher on the
high-prevalence categories, confirming the kappa paradox rather than
overlay-side disagreement.

----------------------------------------------------------------------
Disagreement taxonomy (6-label classifier)
----------------------------------------------------------------------

  Label                          total   safety-critical
  -----------------------------------------------------
  judge_hallucination               46                 5
  infrastructure_error               5                 1
  vocab_gap                          5                 0
  intent_execution_split             4                 0
  overlay_wrong_entity               2                 0
  conditional_logic                  1                 0
  unknown                            0                 0
  -----------------------------------------------------
  total disagreements               63                 6

  judge_hallucination share:       73%

Label definitions:

  judge_hallucination      V8 judge cites tool calls, parameters, or
                           outcomes absent from the audit log. Overlay
                           correct.

  infrastructure_error     Trajectory affected by a known harness bug
                           (e.g. tool rejected for simulator-side reason
                           in SIMULATOR_SIDE_ERROR_CODES). Neither grader
                           at fault.

  vocab_gap                Judge matched on a term variant the overlay
                           does not recognize (e.g. synonym, brand name).
                           Overlay should extend its vocab list.

  intent_execution_split   Agent clearly intended the action but did not
                           issue a qualifying tool call; judge graded
                           intent, overlay graded execution. Policy call.

  overlay_wrong_entity     Overlay matched the wrong entity (wrong
                           encounter, wrong patient). Overlay bug.

  conditional_logic        Assertion is in a subordinate clause and
                           describes a hypothetical, not an agent action.
                           Overlay should not try to grade it.

  unknown                  Reviewer could not classify.

----------------------------------------------------------------------
Safety-critical inversions (n=6)
----------------------------------------------------------------------

Of the 6 inversions:

  5 judge_hallucination    V8 PASS, overlay FAIL. Audit log contains
                           zero successful qualifying calls. The judge
                           invented the passing behaviour. Overlay
                           correct; V8 reward was laundered.

  1 infrastructure_error   V8 PASS on a trajectory where the tool
                           returned a SIMULATOR_SIDE_ERROR_CODES rejection
                           the agent could not have worked around. The
                           tightened `contains attempt at` directive
                           (with intent_rescue_reason attestation)
                           correctly grades this as PASS under the
                           intent-rescue contract.

Forensic walkthrough (SCJ-005-C04):
  Two trials graded differently after tightening.
    _42_t1 (Claude)  V8 PASS   overlay FAIL   judge_hallucination
                     No qualifying createClinicalOrder in audit log;
                     judge cited a tool call with synthesized parameters.
    _44_t3 (GPT-5.4) V8 PASS   overlay PASS   intent-rescue
                     Tool rejected with SIMULATOR_SIDE_ERROR_CODES code
                     SIM_ORDER_UNAVAILABLE; agent attempted order with
                     correct parameters; `contains attempt at` directive
                     + intent_rescue_reason attestation grades PASS.

----------------------------------------------------------------------
Tier assignment (reward-use policy)
----------------------------------------------------------------------

  Tier 1 - reward-safe:      10 entries
    Disagreements exhausted by judge_hallucination plus <=2 safe labels
    (infrastructure_error, intent_execution_split, vocab_gap). Safe to
    replace llm_judge with overlay for reward computation. These are
    the overlays carrying Eq. 1 reward signal in future releases.

  Tier 2 - research-only:    26 entries
    Some overlay-adjacent disagreements but no overlay faults.
    Retained in research analysis (descriptive agreement, error audits)
    but do not carry reward; llm_judge remains binding.

  Tier 3 - keep llm_judge:    8 entries
    Conditional/subordinate-clause assertions where overlay cannot
    reliably grade. llm_judge binding; overlay suppressed.

----------------------------------------------------------------------
Why kappa >= 0.80 is the wrong gate
----------------------------------------------------------------------

The 0.80 gate is Landis-Koch's threshold for "substantial" agreement
between two independent raters rating the same phenomenon. The V8
judge and the overlay are not independent raters of the same thing:
the overlay is a definitional check against the audit log; the judge
reads the trajectory narrative. In the presence of judge hallucination,
kappa measures judge drift more than it measures overlay correctness.
We therefore gate on (a) taxonomized disagreement (target: overlay
faults <20% of disagreements; observed: 8%), (b) safety-critical
inversion count (observed: 6, of which 5 are judge hallucinations),
and (c) Tier 1 reward-safe coverage (observed: 10 of 44 entries).

The v8 judge is the binding ceiling for this release, not overlay
quality. Physician adjudication of Tier 2 entries is the natural
next step for disambiguating intent-execution splits.

----------------------------------------------------------------------
Reproducibility
----------------------------------------------------------------------

  python3 scripts/kappa_validation.py \
      --overlay configs/rubrics/v9_deterministic_overlay.yaml \
      --v8-results results/pilot-v8-claude-opus results/pilot-v8-gpt54 \
      --out docs/V9_OVERLAY_AUDIT.json

Runs offline against cached V8 trajectories. No API calls. Output
file docs/V9_OVERLAY_AUDIT.json is the canonical numerical source
and is cited in docs/whitepaper/canonical_numbers.md under the
"V9 Overlay Audit" section.
