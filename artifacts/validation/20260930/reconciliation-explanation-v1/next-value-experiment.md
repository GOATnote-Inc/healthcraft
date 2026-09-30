# Next value experiment: evidence-review usefulness

Proposed 2026-09-30; no participants, new executions, labels or results acquired.
This is a bounded plan, not registration or release approval.

**Run a small human reviewer crossover on fresh synthetic reconciliation traces.**
The question is whether source-linked explanations let clinical-AI researchers
produce a *correct, evidence-supported incident report* faster than a competent
raw-evidence workflow. This advances end-user evidence beyond model/transport
feasibility. Another Nano/MedGemma run on the exposed v1 fixture would not answer it.

## The comparison that is actually available

- **Candidate:** the same immutable tool/audit/store evidence plus the HealthCraft
  report and new diagnostic sidecar: acknowledged write calls, matching final
  notes, observed readback, exact exclusion differences and links to original
  evidence. Freeze the final candidate and rendered review surface first.
- **Baseline:** an honestly labeled *adapted Harbor/raw-artifact review workflow*:
  the same organized source records, instruction, requests/responses, snapshots,
  independent boolean oracle result, terminal logs and raw verifier metrics;
  usable navigation/search, but no HealthCraft automated explanation or pointer
  shortcuts. Do not deliberately handicap it with disorganized files. Supply
  the same underlying information and documentation in both arms.
- Pin Harbor 0.8.0 at `22b83271db78ef4bcbeb2402cdd154979cf87912` and the Microsoft
  component below. This is a comparison of review workflows built around those
  interfaces, **not HealthCraft versus the official HealthAgentBench benchmark**.
  Hold execution transport and trace constant within a case; otherwise the
  study confounds evidence presentation with agent behavior.
- If included, Microsoft's unchanged CSV metrics appear identically in both
  arms as a separate narrow finding-retrieval result. Never use its 1% precision
  threshold, or Harbor's connectivity reward, as the definition of a valid
  reconciliation report. That would compare different contracts.

## Minimal fixed feasibility study

Propose **8 independent intended-user researchers × 8 fresh cases = 64 assigned
review opportunities**. These numbers bound a usability/variance pilot; they
are not a power justification for the release margins. Recruitment and reviewer
independence still require real people and authorization; no outreach is proposed
for the agent to perform now.

1. Use v1–v3 and their disclosed defects for tutorial/training only. Independently
   author eight new synthetic base cases with new source values, relationships
   and event arrangements, not merely renamed copies of the exposed case. Keep
   the requested work to exact record attribution, unknowns, unresolved source
   reports, note persistence and readback. No diagnosis or treatment labels.
2. Include valid traces and distinct ordinary development controls: incorrect
   exclusions, wrong-target attribution, acknowledgement without storage,
   duplicate storage, real readback of an incorrect note, interruption after a
   real write, and insufficient/provenance-invalid evidence. Freeze the mix and
   use actual handler/controller captures for mutations; label deliberate test
   handlers explicitly in coordinator provenance. Do not edit saved model output
   to manufacture an alleged model failure. Models are unnecessary for this study.
3. Two independent engineering reviewers author/check a coordinator casebook
   directly against immutable source records, call order and final snapshots,
   without using the sidecar's outputs as truth. Preserve disagreement before
   adjudication. These are engineering source labels, not clinical gold labels.
4. Randomize each participant to four candidate and four baseline cases; balance
   each case across arms and counterbalance order. A person sees each case once,
   preventing answer memorization. Mask model/framework identity where possible;
   a visibly different interface cannot be double-blinded. Outcome assessors
   receive standardized submitted reports without assignment/arm labels.
5. Give both arms equal tutorials and the same report template. Freeze a proposed
   10-minute active-review cap per case before collection; approve the cap with
   users using tutorial cases only. Record elapsed and active time separately,
   with explicit pause rules; use the same timing mechanism in both interfaces.
   The roster, output template, thresholds and analysis code must be frozen
   before any held-out reviewer answers, with an independent registration receipt.

A **valid report** names the correct case/patient/encounter; separates controller
completion, acknowledged action, observed storage, actual readback and correct
reconciliation; identifies the requested source differences with resolvable
pointers; and preserves errors, missing evidence and unassessed status. When the
casebook says evidence is insufficient, a supported `unassessable` answer can be
valid; guessing an outcome cannot. Blanket “nothing was stored” after an invalid
stored note and treating readback as correctness are explicit report errors.
All assessed fields and critical-error rules must be predeclared.

## Outcomes and honest decision rule

Use the existing release proposal's estimand: **ratio of mean restricted operator
active time to a valid report**. Charge the full cap to invalid, abandoned,
missing or timed-out reports, including fast wrong answers. Retain every assigned
opportunity; no successful-only timing, best-of selection or retry replacement.
Report valid-completion proportion and wrong-attribution/false-success errors
separately, with case and participant identifiers for clustered analysis.

For this small pilot report raw paired/blocked outcomes and uncertainty; do not
claim the 64 assignments are independent observations. Predeclare participant
and case effects, the clustering/interval method and handling of disagreement
with a statistician or competent independent reviewer. Estimate usability issues
and variance for a **new**, powered confirmatory cohort; do not extend this pilot
until significance or retrofit margins after seeing outcomes. The release plan's
proposed upper time-ratio bound <=0.80 and lower valid-completion difference bound
>=-0.02 stay unchanged. This pilot is unlikely to establish the latter tight
bound and must not be advertised as doing so. A promising estimate advances
planning, not the release state.

## Small missing implementation, not another infrastructure benchmark

- A versioned fresh casebook and fixed assignment manifest; the current scenario
  loader/oracle deliberately pins one exposed case. Fresh cases need an explicit
  opt-in versioned contract and independent expectations, not silent replacement
  of today's pin or reuse of current scores. Reuse real handlers and recorder.
- Two equivalent offline review surfaces and a small response/timing importer
  that binds assignment, case, candidate, packet and response hashes. Keep
  incomplete/missing submissions and original responses immutable. Check actual
  rendered usability before enrollment; static HTML checks alone do not do that.
- A standardized incident-report scorer against the independently authored
  casebook, with blinded human resolution of ambiguous submissions. No LLM judge
  is required. The existing clinical-review packet contract cannot be silently
  reused for these arbitrary evidence bundles: it requires execution-captured
  `review_context`, and intentionally excludes automated explanations. Use a
  separately versioned operator-study packet and do not weaken that boundary.

## Runnable alternatives and missing evidence

| Component | Established local execution | Remaining claim boundary |
|---|---|---|
| HealthCraft native records/oracle/report | Nine scripted controls; v3 four completed model attempts, four stored but incorrect notes; sidecar distinguishes actual readback from correct-note verification. | One exposed development fixture; no user outcomes, new-case generalization or clinical labels. |
| Harbor 0.8.0 | Actual Trial lifecycle, terminal public-tool CLI and local-model controller; same saved native request objects within each model across v3 arms. | Connectivity-only task verifier; original synthetic adaptation, not an independent Microsoft EHR simulator or runtime-performance result. |
| HealthAgentBench CSV verifier | Unchanged pinned function, pandas 3.0.1, original synthetic CSV labels; raw outputs captured. | Retrieves labeled disagreement clusters; cannot assess persisted note correctness, patient action or clinical benefit. |
| MedAgentBench | Public GET/session interface inspected. | Public POST loop acknowledges without executing writes; reference grader is separately distributed and uninspected. Full synthetic action comparison remains unestablished, not a competitor failure. |
| NeMo Gym | Counter and adapted four-record retrieval feasibility captured. | Reconciliation/action review comparison not implemented; adding another framework does not substitute for user evidence. |
| Corecraft / Archangel Health / Baseten | Primary product/paper context only for this workflow. | No eligible matched executable study here. Do not infer superiority from unavailable access or unrelated published scores. |

Still missing for **healthcare value**: independent emergency-physician review of
scenario plausibility and importance, blinded clinical labels where clinical
claims are intended, disagreement adjudication, and calibrated uncertainty over
a sufficiently broad held-out case distribution. Two reviewers plus a third
adjudicator are proposed in the release plan. Neither engineering reviewers,
MedGemma, better explanations nor successful commands replace that work.
Researcher time savings on synthetic records do not establish patient benefit.
The ordered value → formal red team → publication gate therefore remains open.

## Primary sources and local evidence used

No fresh internet claims or code/data downloads were needed; source links below
are immutable pins already inspected and recorded in the comparator documentation.

- [Microsoft executable CSV evaluator, pinned source](https://github.com/microsoft/HealthAgentBench/blob/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/tasks/ehr_data_quality_task_combined/tests/harbor_evaluator.py): actual metric contract; [MIT notice](https://github.com/microsoft/HealthAgentBench/blob/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/LICENSE).
- [Harbor pinned source](https://github.com/harbor-framework/harbor/tree/22b83271db78ef4bcbeb2402cdd154979cf87912): Apache-2.0 runtime reused by the actual local Trial adapter.
- [MedAgentBench pinned task loop](https://github.com/stanfordmlgroup/MedAgentBench/blob/99260117137b09f04837a8c18d18a1107efa55ae/src/server/tasks/medagentbench/__init__.py) and [evaluation dispatcher](https://github.com/stanfordmlgroup/MedAgentBench/blob/99260117137b09f04837a8c18d18a1107efa55ae/src/server/tasks/medagentbench/eval.py): inspected execution/grader availability boundary, not a judgment of published benchmark validity.
- Local authority: `docs/RELEASE_EVIDENCE_PLAN.md`, `docs/SYNTHETIC_EHR_COMPARATOR.md`, `docs/CLINICAL_REVIEW.md`; native-verifier-v1 and local-model-pilot-v3 artifact READMEs; diagnostics peer review at `/private/tmp/healthcraft-reconciliation-diagnostics/peer-review.json`.

No upstream patient-derived data, clinical labels, outreach, model calls, new
clinical claims, formal-red-team work or publication is part of this proposal.
