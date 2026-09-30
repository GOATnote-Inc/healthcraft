# Value evidence and release order

Status: **not demonstrated**. This is a protocol proposal, not a registered
study, a superiority result, or clinical validation. The release instruction
from 2026-09-30 is: establish superior end-user and healthcare value, then
complete formal red-team review, then publish to remote `main` and update
the manuscript for arXiv resubmission. Development remains local until those
conditions are satisfied. The existing draft PR is an engineering checkpoint.

## Intended user and claim boundary

The initial user is a clinical-AI team building, evaluating, or reviewing
emergency-medicine agents. Its useful outcome is an independently valid,
reproducible evaluation that reveals clinically important errors and supports
a correct decision about further development. A lower model pass rate, more
entities, more tests, or faster production of an incorrect report does not
establish that value.

Clinical relevance must be reviewed independently. Research-platform value
does not establish better patient outcomes or deployment readiness. The
existing [research-artifact boundary](RL_COUPLING.md) continues to apply.

## Comparative protocol to freeze before outcomes

1. Name the exact claim, intended users, workflows, alternatives, versions,
   inclusion/exclusion rules, and licenses. Run a feasibility pilot first;
   pilot cases cannot become held-out evaluation cases.
2. Select one primary endpoint before inspecting study outcomes. The proposed
   endpoint is operator active time to a valid report: an upper simultaneous
   confidence bound on the HealthCraft/comparator time ratio of at most 0.80,
   with a lower bound on valid-completion difference of at least -0.02.
   These are proposed research margins requiring reviewer ratification,
   not established clinical thresholds. Do not switch to another endpoint
   after seeing the results. Define the time estimand as the ratio of mean
   restricted operator active time across all assigned trials. Before the
   study, assign each workflow a time cap and charge that cap to any trial
   that times out or produces no valid report, including a fast invalid
   result. Keep actual elapsed and active times as separate diagnostics.
   Freeze workflow weights and the validity adjudication procedure; do not
   calculate the primary ratio only among successful trials.
3. Freeze common synthetic scenario families, required facts/actions, model
   revisions, hardware, budgets, and trial rosters. Use randomized operator
   crossover and account for operator and scenario-family clustering. Specify
   the sample-size justification, stopping rule, uncertainty calculation,
   multiple-comparator adjustment, exclusions, and missing-run policy.
4. Define a valid report independently of each framework: correct task and
   patient attribution, preserved source facts and state changes, explicit
   tool/provider/grader errors and unassessed criteria, and reproducible
   verdicts from captured evidence. Every scheduled trial remains accounted
   for; failures and missing runs cannot disappear from the denominator.
5. Freeze analysis code and obtain a registration receipt anchored independently
   of editable local timestamps before outcome acquisition. Record all changes;
   changes after outcome inspection require a new protocol and fresh hold-out.

## Comparator eligibility

| Alternative | Proposed comparison | Current status |
|---|---|---|
| [MedAgentBench](https://github.com/stanfordmlgroup/MedAgentBench) | EHR retrieval/action workflows through a reviewed common synthetic adapter. | Feasibility and permissions not established. Published patient-derived scores are not a baseline for new synthetic cases. |
| [HealthAgentBench](https://github.com/microsoft/HealthAgentBench) | Portable task execution and review of a valid result. | Feasibility not established; pin repository, adapter, dependencies, and task license before use. |
| [NeMo Gym](https://github.com/NVIDIA-NeMo/Gym) | Rollout, verifier, and evidence integration effort on the same workflow. | Feasibility not established; infrastructure comparison alone cannot establish clinical value. |
| Corecraft, Archangel Health, Baseten | Equivalent executable workflows and review procedures where accessible. | Numerical superiority is not demonstrated. Product descriptions and unrelated published scores cannot fill missing comparisons. |

Adapted comparisons must be labeled as adapted. An unavailable alternative
is `not_demonstrated`, never a failed competitor. A result against one named
baseline cannot support a claim about all available products. Primary-source
design context and licensing decisions are in the
[evaluation design roadmap](EVALUATION_DESIGN_ROADMAP.md).

## Independent clinical and scoring evidence

Two independent emergency physicians should review scenario plausibility,
clinically important error definitions, and blinded outputs; a third should
adjudicate disagreements. Record reviewer qualifications and conflicts,
pre-adjudication agreement, exclusions, uncertainty, and case provenance.
Model consensus and MedGemma judgments cannot substitute for this review.

The proposed calibration target is zero observed critical false passes with
a one-sided 95% upper bound no greater than 1%, alongside a lower confidence
bound of at least 95% for valid-case acceptance and a one-sided 95% upper
confidence bound of at most 5% for the unassessed proportion. Define that
proportion over every predeclared case-criterion judgment opportunity,
including missing and invalid judgments, and account for clustering by case.
These targets also require clinical/statistical review before
registration. Under an independent binomial zero-event model, the upper bound
is `1 - 0.05**(1/n)`; meeting the 1% target needs at least 299 independent
critical negative cases. Correlated paraphrases or repeated trials of one
case cannot be counted as independent cases. Clustering can require more
evidence. This is a proposed research calibration target, not a clinical
deployment safety guarantee.

Every deterministic criterion included in the claim needs a reachable
reference execution plus independently expected controls. Unsafe action,
omission, incorrect answer, tool/provider/grader error, abstention, and
missing execution must remain separate outcomes.

## Ordered release evidence

| Stage | Required evidence before advancing |
|---|---|
| Local development | Versioned tasks, reliable tools, source-linked evidence, and useful review workflows. Unit/regression tests establish engineering behavior only. |
| Value demonstrated | Frozen candidate/protocol, eligible comparators, registered and complete held-out outcomes, independent clinical review, and all predeclared margins met against each comparator in the claim. |
| Formal red team | Starts only after the value evidence is accepted. Targets the same frozen candidate and examines evaluator gaming, unsafe failures, privacy/security boundaries, misleading reports, and scientific claims. Routine development tests are not this final review. |
| Findings resolved | Reproduce and resolve findings; revalidate affected value evidence and repeat the relevant independent review. Candidate or claim changes invalidate dependent approvals. |
| Main and paper publication | Verify the candidate and evidence again, then use the user's conditional authorization to publish the reviewed revision to `main`. Update the manuscript from those results, render/verify it, and prepare the arXiv resubmission package. Actual submission details and author attestations must come from the authors. |

Evidence manifests must bind candidate, protocol, held-out roster, model/runtime
identity, raw results, analysis, clinical review, and later red-team artifacts
by content hashes. Hashes establish content identity; they do not prove
reviewer independence or registration timing. A reporting CLI alone cannot
prevent an operator from bypassing the required publication procedure.

## Current evidence and gaps

- Engineering checkpoint `82d1685`: 1,757 local tests passed, two skipped;
  all six remote checks passed. This does not pass the value gate.
- Local Nemotron/MedGemma smoke tests establish a tool round trip and two
  diagnostic labels; longer task trials remain incomplete diagnostics.
- The opt-in IR-002 certificate proves four mechanical checks for one
  profile. It measures zero safety criteria and no clinical interpretation.
- Three historical rubric false passes remain explicitly documented.
- No registered common-protocol comparator study, operator-value study,
  independent clinical calibration, or final formal red-team review has
  been completed for the proposed release.

The next implementation work improves installation reliability, honors
task-specific policy additions, and makes run evidence easier to inspect.
Those capabilities can support a comparative pilot; they cannot by themselves
clear this release gate.
