# Automated release and evidence workflow

The current publication policy, updated on 2026-09-30, permits repository and
paper releases from this physician-engineer-led project through automated
engineering validation and explicit evidence accounting. It supersedes the
earlier local-only sequence of comparative value, formal red team, then
publication. Human-in-the-loop review, recruited operators and external
clinical sign-off are not required release steps. Automated adversarial checks
and an independent agent release audit remain part of the current release
validation; removing human prerequisites does not remove those checks.

This policy changes publication timing, not the strength of the evidence.
Clinical readiness, better patient outcomes and superiority over Corecraft,
Archangel Health, Baseten or other platforms remain unestablished. Historical
results and frozen artifacts are preserved under their original contracts.

## Release workflow

1. **Identify the candidate.** Record the source revision, dependency/runtime
   identities, task and rubric versions, prompts, tool schemas and generation
   settings. Preserve existing results; changed contracts get new identities.
2. **Validate the implementation.** Run relevant TDD regressions, the full test
   suite and lint, plus supported-runtime and optional-adapter checks where
   applicable. Retain failures, corrections, skips and exact commands. Checks
   establish their tested engineering properties, not clinical validity.
3. **Exercise adversarial failure cases.** Run automated checks against the
   release candidate for false success, omitted failures, corrupted or substituted
   evidence, unintended writes and publication-package omissions. Retain the
   independent agent audit, resolve blocking findings and rerun affected checks.
   State the tested scope; this is not independent human or clinical validation.
4. **Validate the evidence.** Check manifests, source hashes, full scheduled
   rosters, raw request/response captures and persisted actions. Recompute
   deterministic checks where supported. Distinguish execution completion,
   task success, unavailable grading and clinical criteria not assessed.
   Never repair an old failed attempt into an apparent success.
5. **Publish the verified revision and materials.** Publish source, documentation
   and release evidence to GitHub. Build and inspect the paper and prepare its
   arXiv materials from the same documented evidence. Report submission and
   acceptance status only when confirmed; available materials are not proof
   of an arXiv submission. Keep credentials and model weights out of the release.

Automated checks must not turn missing evidence into a pass. Document unresolved
limitations and their affected claims alongside the release. A new feature or
rubric change needs its own reproducible checks; a software release does not
require every research objective below to be complete.

## Evidence available and its limits

- [Evaluation integrity](EVALUATION_INTEGRITY_2026-09-30.md) records execution,
  replay, grading and accounting repairs. Passing regressions demonstrates
  those contracts, not validity of every authored task or clinical judge.
- [Task-validity findings](TASK_VALIDITY_FINDINGS.md),
  [authored observations](AUTHORED_OBSERVATIONS.md) and
  [care/imaging fidelity](CARE_IMAGING_FIDELITY.md) distinguish source-preserving
  repairs from unresolved clinical meaning and observation-availability policy.
- [Local MedGemma/Nemotron testing](LOCAL_MODELS.md) retains actual provider
  envelopes and incomplete attempts. The [eight-case local pilot](RECONCILIATION_LOCAL_MODELS.md)
  uses exposed, engineering-authored cases. It supports source-level diagnosis
  of those runs, not clinical calibration or general model rankings.
- [Reference certificates](REFERENCE_CERTIFICATES.md) and the
  [development casebook](RECONCILIATION_CASEBOOK.md) exercise actual retrieval,
  ownership and note persistence with positive and negative controls.
  Mechanical verification is separate from clinical interpretation; the
  casebook and its expectations share an authoring ledger.
- [FHIR source export](FHIR_SOURCE_EXPORT.md) has bounded offline R4 structural
  validation for selected source resources, not full entity-graph conformance.
  [NeMo Gym adapters](../integrations/nemo_gym/README.md) and
  [synthetic reconciliation](SYNTHETIC_RECONCILIATION.md) establish specific
  interoperability and verifier contracts, not comparative clinical benefit.
- [Criterion packets](CLINICAL_REVIEW.md), the [operator tutorial](OPERATOR_REVIEW.md),
  [incident forms](OPERATOR_INCIDENTS.md) and [offline workbench](OPERATOR_WORKBENCH.md)
  are optional developer diagnostics. Their imports preserve supplied judgments
  and missing responses; they neither authenticate expertise nor form a required
  production, evaluation or publication workflow.

Validation receipts are attached to their specific source revision. Test counts
from overlapping suites must not be added as if they were independent studies.
Content hashes identify bytes; they do not prove clinical truth, independent
label authorship or execution by a trusted external party.

## Future comparative and clinical research

The initial intended users are clinical-AI teams developing and evaluating
agents. Whether the environment improves their decisions, work time or patient
outcomes remains a research question. More tests, more entities or a lower model
pass rate alone do not answer it.

A future comparative study should predeclare the claim, eligible alternatives,
versions, common workflows, budgets, primary endpoint and analysis before new
outcomes. Keep failures and missing assignments in the denominator, report
uncertainty and exposure, and distinguish exploratory pilots from held-out
studies. Operator timing and independent clinical calibration are optional
research programs, not repository-release dependencies. Any clinical claim
must be supported by evidence appropriate to that claim; model consensus and
medical-model branding do not establish clinician validation.

| Alternative | Evidence boundary for a future comparison |
|---|---|
| [MedAgentBench](https://github.com/stanfordmlgroup/MedAgentBench) | The inspected public loop acknowledges POSTs without executing writes; its separately distributed reference grader was not inspected. End-to-end equivalence remains unestablished. Patient-derived published scores are not a baseline for new synthetic cases. |
| [HealthAgentBench](https://github.com/microsoft/HealthAgentBench) | A pinned CSV verifier and original synthetic Harbor lifecycles were exercised. CSV and connectivity rewards test different contracts from persisted source-correct notes. These adaptations do not establish superiority over the original benchmark. |
| [NeMo Gym](https://github.com/NVIDIA-NeMo/Gym) | Pinned local probes establish bounded interoperability. Shared settings or successful retrieval do not establish a clinical or statistical performance margin. |
| Corecraft, Archangel Health, Baseten | Equivalent executable workflows and comparison evidence are still needed. Product descriptions and unrelated published scores cannot support a numerical superiority claim. |

Label adaptations explicitly. An unavailable comparator is `not_demonstrated`,
not a failed competitor. The [design roadmap](EVALUATION_DESIGN_ROADMAP.md) and
[source/license review](SYNTHETIC_EHR_COMPARATOR.md) record reuse boundaries.

The current release includes automated adversarial checks and a separate agent
audit with retained findings. Their scope is distinct from ordinary regression
tests and from an external human red-team campaign. A future independent
campaign can broaden coverage of evaluator gaming, misleading reports, unsafe
failures and privacy/security boundaries. That future campaign and human
participation are not prerequisites for publishing the current research software
and accurately scoped paper.
