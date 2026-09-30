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
| [MedAgentBench](https://github.com/stanfordmlgroup/MedAgentBench) | EHR retrieval/action workflows through a reviewed common synthetic adapter. | Pinned public loop acknowledges POSTs without executing writes; reference grader is separately distributed and uninspected. End-to-end feasibility remains unestablished. Published patient-derived scores are not a baseline for new synthetic cases. |
| [HealthAgentBench](https://github.com/microsoft/HealthAgentBench) | Portable task execution and review of a valid result. | Pinned CSV verifier and an original synthetic Harbor lifecycle exercised. Four scripted transport controls match independent mechanical outcomes; no model/operator comparison is established. The CSV and connectivity rewards cannot establish persisted clinical-action correctness. |
| [NeMo Gym](https://github.com/NVIDIA-NeMo/Gym) | Rollout, verifier, and evidence integration effort on the same workflow. | A pinned counter probe remained incomplete. A later adapted four-record retrieval attempt completed once in each framework under shared native settings. This establishes local interoperability, not a clinical workflow or comparative performance margin. |
| Corecraft, Archangel Health, Baseten | Equivalent executable workflows and review procedures where accessible. | Numerical superiority is not demonstrated. Product descriptions and unrelated published scores cannot fill missing comparisons. |

Adapted comparisons must be labeled as adapted. An unavailable alternative
is `not_demonstrated`, never a failed competitor. A result against one named
baseline cannot support a claim about all available products. Primary-source
design context and licensing decisions are in the
[evaluation design roadmap](EVALUATION_DESIGN_ROADMAP.md).
The [synthetic EHR comparator proposal](SYNTHETIC_EHR_COMPARATOR.md) records
exact source pins, code/data license boundaries, verifier semantics and the
next engineering controls. A proposed adaptation is not a working comparator.

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
  diagnostic labels; the original full clinical-task trials remain incomplete
  diagnostics. A later simplified retrieval exercise completed in both frameworks.
- The opt-in IR-002 certificate proves four mechanical checks for one
  profile. It measures zero safety criteria and no clinical interpretation.
- The [roster profile](ROSTER_PROFILES.md) makes 33 selected source records
  reachable across six tasks, while withholding designated answer fields.
  Its execution diagnostics remain ungraded pending clinical-content review.
- The [source-preserving FHIR export](FHIR_SOURCE_EXPORT.md) represents those
  33 members as 99 linked resources. A pinned offline R4 validator reported
  zero errors, 99 optional-narrative warnings and 33 unassessed MIME terminology
  checks. This does not validate source clinical claims or all entity types.
- The [optional NeMo Gym adapters](../integrations/nemo_gym/README.md) share
  native local-model settings and canonical tool schemas with HealthCraft.
  SDK/session/conversion tests establish bounded integration contracts; they
  do not measure clinical benefit or establish a comparative performance margin.
- The [two local retrieval attempts](../artifacts/comparators/20260930/nemo-roster-local-v1/README.md)
  each completed with all four members retrieved through five tool calls and
  six Nemotron responses. Sources remained unchanged and tool outputs replayed
  exactly. Later tool-result encoding differs between frameworks, both runs
  are ungraded clinically, and no performance or superiority claim follows.
- The [pinned NeMo Gym feasibility record](../artifacts/comparators/20260930/nemo-gym-feasibility/README.md)
  preserves the single incomplete counter trial and exact request settings.
  Thinking, context, seed, and output settings differ from HealthCraft's;
  it is not a matched performance comparison or healthcare-value evidence.
- The [offline review workflow](CLINICAL_REVIEW.md) binds new trajectories to
  their actual prompts, tools and effective criteria, creates masked reviewer
  packets, and records independent submissions without inventing expert labels.
  Independent reviewer recruitment/verification, adjudication and calibration
  remain unperformed.
- [Action/grader repairs and open task-validity findings](TASK_VALIDITY_FINDINGS.md)
  distinguish corrected execution/alias defects from unresolved rubric meaning
  and observation-availability problems. The [authored observation repair](AUTHORED_OBSERVATIONS.md)
  conserves direct vital/lab source facts and unknown times. Passing these
  regression fixtures does not establish independent clinical adjudication.
- The [care and imaging repair](CARE_IMAGING_FIDELITY.md) keeps authored care
  distinct from completed administrations and preserves direct imaging facts
  without default modality, impression or time. Its mechanical witness and
  local source-reading probe do not adjudicate treatment or comparative value.
- The [execution and report repair](EXECUTION_REPORT_INTEGRITY.md) preserves
  interrupted action evidence, binds retries to their requests, removes three
  reproduced false criterion passes and checks frozen report provenance.
  Its local Nemotron round trip confirms one literal synthetic action only;
  it does not establish clinical or comparative performance.
- The [original synthetic reconciliation workflow](SYNTHETIC_RECONCILIATION.md)
  uses actual handlers, a pinned independent source/persistence oracle and nine
  scripted controls over eight records. The optional unchanged Microsoft CSV
  verifier assesses a separate retrieval contract. Its [evidence bundle](../artifacts/reconciliation/20260930/native-verifier-v1/README.md)
  is complemented by a [real Harbor scripted lifecycle](../artifacts/reconciliation/20260930/harbor-transport-v4/README.md), but does not establish operator
  benefit or clinical validity; all clinical criteria remain unassessed.
- The [first reconciliation model pilot](../artifacts/reconciliation/20260930/local-model-pilot-v1/README.md)
  records one Nano and one MedGemma attempt through each transport, with identical
  initial messages and native request settings within each model. All four
  failed the frozen command format after one response, before tool use. No
  attempt was retried or repaired. These outcomes diagnose an interface
  limitation; they do not measure clinical performance or comparative value.
- Separate [structured-command cohorts](../artifacts/reconciliation/20260930/local-model-pilot-v3/README.md)
  reached real note writes through both transports after a TDD repair of a
  filesystem-alias preparation defect. The final four-attempt cohort terminates
  normally but fails source reconciliation because scope exclusions are wrong.
  Stored notes and observed readbacks remain distinct from verification of the
  requested correct note. Earlier format/setup failures are preserved; no
  clinical criterion, operator endpoint or superiority margin is assessed.
- No registered common-protocol comparator study, operator-value study,
  independent clinical calibration, or final formal red-team review has
  been completed for the proposed release.

Installation constraints, task-specific policies, and offline evidence review
are implemented locally. Current work improves authored-record reachability,
preserves unassessed outcomes throughout analysis/export paths, and establishes
executable comparator feasibility. These capabilities can support a future
comparative pilot; they cannot by themselves clear this release gate.
