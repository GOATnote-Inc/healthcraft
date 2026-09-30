# Offline independent review workflow

**Status: review tooling, not clinical validation.** The builder creates blank
assignments; it does not create expert labels. The importer records submissions
without authenticating the reviewer, adjudicating disagreement, computing a
clinical accuracy estimate, or approving a release. Existing engineering
goldset labels and counterexamples are not substitutes for independent clinical
adjudication. The release sequence remains in
[RELEASE_EVIDENCE_PLAN.md](RELEASE_EVIDENCE_PLAN.md).

## Evidence and masking contract

The unit is one **captured trajectory × effective criterion** opportunity. Every
effective criterion on every selected trajectory is assigned. There is no
best-of-trials reduction. Explicit file lists retain every supplied attempt;
directory discovery also retains every attempt and uses the shared known-sidecar
filter only to exclude generated summaries and grading files. The manifest
records candidate counts and those exclusions. A malformed selected attempt
blocks export rather than being skipped. The private manifest identifies each
attempt and its original trial group. Operators must predeclare their sampling and retry policy;
this workflow does not turn a selected sample into representative population
evidence.

Only trajectories with valid execution-time
`metadata.review_context` (`clinical-review-context/v1`) are accepted. That
snapshot binds the normalized authored task, effective criteria, channel,
checkpoint, scenario context, actual system/request text, tool definitions, and
full saved turn list. It is not clinical ground truth. Historical trajectories
without this capture are rejected; current task files are never silently joined
to old results. A complete capture can describe an interrupted execution.

Each output directory has two deliberately separate parts:

- `reviewer/packet.json`, `packet.md`, and `response-template.json`: opaque case
  and item aliases; exact presented text; ordered visible messages, tool calls,
  and responses; captured tool definitions; assertion and dimension text.
  Structured tool-call IDs are consistently replaced with local aliases.
- `coordinator/manifest.json` and immutable source snapshots: original identities
  and paths, raw-file and context digests, task/criterion/attempt mappings,
  safety flags, protocol, assignment, completion status, and original recorded
  assessment data inside the private source snapshots.

**Share only `reviewer/`.** Do not distribute its parent directory, coordinator
files, or the ordinary evidence report, which contains model and assessment
information. The reviewer payload does not include authored hidden state,
expected actions, rubric check expressions, model identity, recorded verdicts,
or automated explanations. No hidden copy of the raw trajectory is embedded.
Markdown quotes untrusted evidence inside fences; instructions in a transcript
remain data. No network service or external asset is required.

This is **model-visible evidence review**, not a privileged review of every
world-state fact. Missing information may make a criterion unassessable.
Assertions themselves can reveal an expected answer or a recognizable task;
reviewers must assess the assertion's validity, not assume it. Known exact model
names in exported evidence block generation without rewriting that evidence.
This narrow check cannot detect every alias, self-identification, or stylistic
clue. Reviewers report blinding as intact, suspected, or broken. There is no
claim of guaranteed anonymization.

Digests detect changes relative to the captured artifacts. They do not establish
authentic execution, an independently registered protocol, reviewer identity,
expertise, or honest attestations. Coordinator snapshots permit offline import
even if the original run directory has moved; a changed snapshot is rejected.

## Operator steps

1. Before examining review outcomes, record the candidate version, inclusion
   and exclusion rules, sampling, unit of analysis, intended strata, and treatment
   of interruptions and retries in a protocol. Create one independent assignment
   per reviewer. For the planned clinical study, recruit and verify qualified
   reviewers outside this software; record conflicts and protect independent
   submissions before subsequent adjudication. No outreach is automated.
2. Build one packet for each assignment using captured trajectories. Verify that
   the private selected roster matches the predeclared cohort. Distribute only
   that assignment's reviewer directory and its reviewer alias.
3. The reviewer edits a copy of `response-template.json`, not the packet. Import
   the completed copy into a new receipt directory. Preserve initial independent
   submissions before any adjudication. A changed response is a distinct
   submission artifact, never an overwrite of an earlier receipt.
4. Keep pending, unassessed, and disagreement states visible. This version has no
   multi-reviewer adjudication or calibration aggregator; do not interpret a
   receipt as an adjudicated reference label or a clinical gate pass.

Minimal `protocol.json` (replace these planning placeholders before a study):

```json
{
  "protocol_id": "review-pilot-001",
  "version": "1",
  "purpose": "engineering_pilot",
  "sampling_plan": "Describe the frozen trajectory selection and retry policy.",
  "eligibility_rule": "Describe the intended review cohort and exclusions."
}
```

`purpose` may also be `clinical_adjudication`; that label alone confers no
clinical validity. Additional protocol fields are preserved privately. Minimal
`assignment.json`:

```json
{"reviewer_id": "reviewer-001", "role": "independent"}
```

```bash
python scripts/clinical_review.py build path/to/captured-run \
  --protocol protocol.json --assignment assignment.json \
  --output-dir review-packet-001

# Alternatively pass one or more explicit trajectory JSON paths after "build".
python scripts/clinical_review.py import \
  review-packet-001/coordinator/manifest.json completed-response.json \
  --output-dir review-receipt-001
```

Both output directories must be new. Invalid inputs exit with code 2 before
creating the output directory. Filesystem failures can leave an incomplete
directory; retain it for diagnosis and use a new directory after correcting the
problem. No existing trajectory, result, or clinician submission is rewritten.

## Response contract and denominator

The response must retain its schema version, packet ID/digest, assignment ID,
and assigned item IDs. `reviewer_id` must match the private assignment. Supply
`reviewer_attestation` with nonempty `qualification_statement` and
`conflicts_statement` strings and a literal Boolean `independent_review`.
These are self-reports, never verification of qualifications or independence.

For each reviewed row:

- `criterion_validity`: `valid`, `ambiguous`, `clinically_invalid`,
  `insufficient_context`, or `outside_expertise`.
- `verdict`: `satisfied`, `not_satisfied`, or `unassessed`. Boolean values and
  strings such as `"false"` are rejected. A non-valid criterion requires
  `unassessed`; an assessed verdict requires at least one known evidence anchor.
- `unassessed_reason`: null for assessed rows; otherwise one of
  `insufficient_evidence`, `outside_expertise`, `ambiguous_criterion`,
  `invalid_criterion`, `reviewer_abstention`, or `not_applicable`.
- `evidence_refs`: anchors listed on that packet item; `rationale`: nonempty
  explanation; `blinding`: `intact`, `suspected`, or `broken`.

A completely untouched row or an omitted row remains **pending**. Partially
filled rows, unknown fields, duplicate JSON keys/rows, foreign evidence anchors,
and mismatched hashes or identities are rejected, rather than counted as
negative labels. Reviewer abstention is distinct from agent refusal. The
receipt retains the entire assigned roster and counts assigned, submitted,
assessed, unassessed, and pending opportunities.

Receipt identity is the packet/assignment pair. Copying a receipt or importing
the same response into another directory does not create another independent
reviewer. Cross-packet duplicate detection, reviewer identity verification,
adjudication, and revision selection remain coordinator responsibilities.

## Calibration remains pending

Future calibration should compare frozen, valid automated verdicts with
independently resolved clinical labels, preserving pre-adjudication agreement.
Report assigned coverage, missing reviews, abstentions, ambiguous criteria,
unresolved disagreements, grading errors, and incomplete execution separately.
Critical false-pass rates use expert-negative critical opportunities as their
denominator; false-fail rates use expert-positive opportunities. Engineering
counterexamples must not inflate clinical denominators. A disagreement-enriched
sample is not an unbiased estimate of performance on all tasks.

No eligible clinical reference labels means **unmeasured**, not zero errors.
Small samples need uncertainty intervals; repeated criteria and trials within a
case cannot be assumed independent. The release plan specifies prospective
expert/statistical review of margins, clustering, and uncertainty. This tooling
does not calculate or certify those measures. No clinical labels were produced
to implement or test it; all test responses are engineering fixtures.

## Primary-source design references (reviewed 2026-09-30)

- [HealthBench §8.1](https://arxiv.org/html/2505.08775v1) evaluates
  criterion–conversation–response tuples against physician assessments and
  excludes a physician's own labels from that physician's comparison reference.
  This motivates retaining independent records before adjudication. It does not
  establish that our protocol has comparable clinical validation.
- [OpenAI simple-evals HealthBench implementation](https://github.com/openai/simple-evals/blob/main/healthbench_eval.py)
  accepts literal Boolean criterion outcomes; its automated grading and rendered
  graded outputs are not a blinded reviewer packet.
- [HealthAgentBench §3.3](https://arxiv.org/html/2606.31179v1) separates verifier
  labels from agent-visible inputs and obscures identifying dataset labels.
  Its [X-ray task](https://github.com/microsoft/HealthAgentBench/tree/main/tasks/xray_report_correction_case_01)
  uses a majority-vote LLM judge against gated reference reports; this is not
  independent clinical adjudication of HealthCraft.
- [MedAgentBench's runner](https://github.com/stanfordmlgroup/MedAgentBench/blob/main/src/server/tasks/medagentbench/__init__.py)
  retains the full task denominator when some outputs are absent. Physician
  task authorship in its [paper](https://arxiv.org/html/2501.14654v1) is a distinct
  activity from blinded review of a new system's judgments.

These are design references only. No external code, benchmark data, clinical
reference answers, or dependencies are copied. The three linked repositories
publish MIT code licenses; dataset access and reuse conditions are separate.
