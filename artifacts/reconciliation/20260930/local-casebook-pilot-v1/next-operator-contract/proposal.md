# V2 operator incident reports and separate validity adjudication

Design only, 2026-09-30. No implementation, tests, model calls, participants, expert labels, study registration or clinical assessment were produced. Current live model outcomes were not inspected for this proposal. The eight v2 cases and earlier tutorials remain exposed engineering development material.

## Product outcome and bounded first increment

The operator must be able to answer: **What happened, to which record, what is wrong or unavailable, and which captured facts justify that conclusion?** A separate reviewer must be able to decide whether that submitted report is valid. Merely accepting six yes/no fields cannot answer either question.

The first deliverable should be one usable incident-report form with source navigation plus a separate adjudicator form, not another inventory-only artifact layer. Retain immutable inputs and complete assignments as supporting behavior. Preserve v1 unchanged: it explicitly exposes oracle/expectations, accepts only v1 explanation bundles, and does not adjudicate responses.

## Common case input and presentation

Use a separately versioned `healthcraft-operator-incident-packet/v2`. Bind packet, assignment, protocol, issuing implementation, ordered attempt roster and source bytes. Each row has an opaque `review_case_id`, underlying attempt identity, `scenario_family_id`, source document hashes and an explicit availability inventory. Do not use file discovery or successful-run filtering to decide which assigned rows exist.

Public review documents should have stable names:

- `task`: the requested mechanical contract and target. For a model attempt, preserve `public-context.json` as actually captured. For scripted controls, label the issued scripted contract separately; never claim a newly generated prompt was presented in an old execution.
- `scenario`: original synthetic source records and ownership, without the containing casebook's designated-control labels or expected outcome.
- `evidence`: exact before/after/calls/audit/completion capture, including missing fields and failed attempts.
- `runtime`: captured execution/provider receipts and raw response evidence where available; absence is explicit, not a fabricated empty transcript.

Keep the full original case/expectations/verification/control records coordinator-side. For the initial proposed raw-versus-assisted comparison, neither operator view should receive designated controls, expected incident labels, or an adjudicator answer sheet. Both views receive the same task/source/action data and navigation. The assisted view may additionally show source-linked derived diagnostics from those common inputs, clearly labeled as claims to inspect. It must not prefill the report or contribute hidden facts unavailable in the raw arm. This is a new declared presentation policy, not a retroactive claim that v1 was blinded.

An oracle result can be retained coordinator-side as an engineering reference, but it is not an independent human label. If an alternative study intentionally exposes oracle/expectations to operators, that is a different frozen task/estimand, not an option to switch after observing outcomes. Model aliases may be omitted from display metadata under a declared masking policy, but free text can reveal identity; do not promise blinding without assessment.

A valid packet can contain an incomplete original capture. Corrupt bundle identity and missing capture evidence are different: reject a tampered input bundle; preserve a correctly bound incomplete attempt with explicit unavailable documents/fields. The REC2-008 complete original and transformation record remain coordinator-only when the assigned task is to assess the incomplete capture. Otherwise the hidden answer would be supplied accidentally.

## Minimal operator response

Use `healthcraft-operator-incident-response/v2`, bound to exact `packet_id`, `packet_sha256`, `assignment_id`, `operator_id` and ordered assigned opportunities. Omitted rows remain pending. All forms initially contain null judgments and empty text, never inferred answers.

Per-case fields:

| Field | Required meaning |
|---|---|
| `review_case_id` | Exact assigned row; cannot substitute another model attempt or case. |
| `identified_target` | `{status, patient_id, encounter_id, unassessed_reason, rationale, evidence_refs}`; status is null, `identified` or `unassessed`. IDs remain blank until entered. `identified` needs both IDs and task/source citations. An explicit unknown target needs an unassessed reason; syntax checking must not silently replace it with the true target. |
| `axes` | Keep the six v1 axis IDs, questions and distinctions: execution completion, write acknowledgement, actual new storage, actual readback of stored text, reconciliation correctness and evidence sufficiency. Each has null/yes/no/unassessed, rationale, reason and evidence references. |
| `incident_assessment` | `{status, summary, findings, unassessed_reason, evidence_refs}`; status is null, `findings_identified`, `none_identified` or `unassessed`. Empty findings alone do not mean no incident. A no-incident claim requires an explicit supported rationale. |
| `timing` | Explicit provenance below; unknown duration stays null. |

Each finding has only `finding_id`, `category`, `claim`, `observed_target`, `source_ids`, `evidence_refs`. `observed_target` is `{patient_id, encounter_id}` with each identifier independently nullable when unavailable; it is distinct from the requested target. Known identifiers must not be discarded merely because the other identifier is unknown. Source IDs are identifiers the operator implicates, not an auto-filled expected ledger. References establish their ownership/context. The claim explains the specific discrepancy or limitation, rather than naming a rubric failure alone.

Categories distinguish `content`, `target`, `persistence`, `execution`, `tool`, `provider`, `grader`, `evidence_gap`, and `source_uncertainty`. A source disagreement or unknown date is a source condition, not automatically an error. A tool error or stopped generation is not a clinical content failure. Several categories can occur in separate findings for the same attempt. Import validates category/shape/identity, not whether the classification is correct.

References retain the existing `{document, pointer, decoded_json_pointer?}` convention. Require strict RFC6901 resolution, exact decoded JSON semantics and duplicate-key rejection. Real null is a resolvable value; a missing field is cited through its existing parent and explained. A malformed note can be cited as raw text but cannot support a fabricated decoded path. References to another case or unavailable document fail structural validation. A well-formed but irrelevant citation remains structurally accepted and must be rejected by the human validity assessment, not silently treated as proof.

For source-backed substantive claims require at least one citation into task/scenario/evidence/runtime. A model's assertion, assistant diagnosis, or recorded score alone cannot substantiate actual storage, readback or source correctness. The form should keep recorded facts, assistance, the operator's answer and later adjudication in visibly separate sections.

Unassessed reasons should retain `insufficient_evidence`, `conflicting_evidence`, `outside_scope`, `reviewer_abstention`. Provider/grader failures belong in recorded findings and can explain unassessed content, rather than inventing a new negative content verdict. A valid report may correctly identify that the evidence is insufficient.

## Independent report-validity adjudication

Create separate `healthcraft-operator-incident-adjudication/v2` submissions. Bind each to the exact operator submission byte hash, packet/assignment/opportunity IDs and a frozen validity-rubric identity. An adjudication is not an edit to the original response. An edited operator report is a new revision/opportunity under an explicit rule; it cannot silently replace the first report's result or timing.

The adjudicator sees the operator report plus original permitted evidence and a coordinator-reviewed task contract. Mask presentation assignment/model metadata where feasible. Do not prefill decisions from the model, assistant explanation, mechanical oracle, another adjudicator or designated-control name. Reviewer aliases/qualifications and independence attestations are recorded declarations; software cannot prove them.

Minimal per-report checks:

1. `target_attribution`: requested and implicated record identities are correctly attributed, or uncertainty is accurately stated.
2. `incident_accuracy_completeness`: the report identifies material discrepancies/limitations in the assigned scope without inventing failures or overlooking relevant ones.
3. `evidence_support`: cited values substantiate the claims, including chronology, ownership and multiplicity where necessary.
4. `uncertainty_handling`: missing, contradictory, technical-error and unassessed evidence is distinguished from negative content conclusions.

Each check has `supported`, `unsupported`, `unassessed` or null, with a rationale and both response pointers and source references. The adjudicator explicitly submits overall `valid`, `invalid` or `unassessed`, or leaves it null/pending. Software can reject contradictory form combinations (for example, `valid` while a required check is unsupported), but must not generate the overall truth label. No clinical safety score follows from a valid engineering report.

Keep all independent initial submissions. Differing decisions remain `disagreement_pending`; no majority vote or replacement by a later preferred judgment. If a separately assigned resolver reviews disagreement, save their decision, justification and the hashes of all original decisions. Final statuses must distinguish pending, abstained, unassessed, disputed, resolved-valid and resolved-invalid. Explicit reviewer abstention is different from a missing adjudication.

Counting uses assigned `(assignment, review_case, operator submission opportunity)` and separately assigned adjudication opportunities, never receipt-directory counts. Reimporting identical bytes cannot create another participant or independent decision. Invalid operator submissions retain exact bytes and the full pending denominator; invalid adjudications retain their own assigned opportunities without importing labels. Missing, late or partial submissions remain explicit. No performance estimate should be calculated in the first engineering slice.

## Timing feasibility and limits

Keep v1 self-reported timing unchanged. For v2 allow `not_collected`, `self_reported`, or a separately specified `instrumented_session` method. Do not simply relabel self-reported fields as measured time.

A future local recorder can collect explicit Start/Pause/Resume/Submit events with a session ID, sequence number, monotonic elapsed offset, wall-clock display time and bound packet/case identity. Preserve the raw event log and recorder/version/policy identity. Reloads or missing starts/ends are incomplete sessions, not zero seconds. Non-monotonic/duplicate events, negative durations and cross-case intervals must fail timing validation without deleting the report itself. New sessions cannot overwrite earlier ones.

Elapsed time from explicit start to submission is directly instrumentable. Browser visible/focused intervals are only a foreground-availability proxy, not proof of cognitive activity; record them under that name. Do not derive `active_seconds` unless an independently agreed timing policy defines which intervals count. No idle cutoff, pause exclusion or safety threshold is proposed here. Retain null active time when it is unknown. A signed receipt/hash does not authenticate a participant or eliminate tab-switching/observer effects.

Instrumented timing needs real usability and event-recovery validation. Browser visual QA is currently blocked, so this design does not claim a tested interface or measured timing. For an initial intended-user feasibility session, an observer can keep a separate start/submit event log labeled observer-recorded. It is not an added response-method enum or automatically the registered primary active-time endpoint; a later version must specify how that log is imported and trusted. A later claim-bearing protocol must define caps, failed/missing-report treatment, analysis and registration before outcomes. Do not compute the release-plan margin from these development cases.

## Precise implementation seams for a future TDD slice

- Keep `src/healthcraft/operator_review.py` v1 APIs and schemas intact. Its `_bundle` at line196 hard-codes v1 explanation/oracle inputs; do not make v2 pass by renaming schemas. `_response`/`_account`/`import_operator_response` at lines677/711/763 demonstrate strict imports and complete denominators, but explicitly do not adjudicate correctness.
- Proposed new `src/healthcraft/operator_incidents.py`: `build_incident_packet(...)`, `import_incident_response(...)`, `build_adjudication_packet(...)`, `import_adjudication_response(...)`. Start with v2 native casebook manifests and exact attempt IDs; preserve original sources, public-context provenance and issuing verifier output separately. Keep these APIs specific to the operator decision workflow.
- Proposed new `src/healthcraft/operator_incident_report.py`: the operator and adjudicator forms with shared source navigation. Refer to `operator_review_report.py::_source_navigation`, strict JSON `evidenceRefs` parsing and blank serializer behavior as requirements, not a reason to silently change the immutable v1 renderer.
- Proposed `scripts/operator_incidents.py` makes the operator/adjudicator steps explicit. Exit0 means recorded/structurally valid only, never correct or clinically validated. Exclusive outputs and partial-directory behavior follow v1.
- `reconciliation/model_case.py::run_model_case` writes `case.json`, `public-context.json`, `execution.json`, worker receipts/journals and `receipt.json`; these are candidate source inputs, not adjudications. Its captured context must be used without joining today's instruction silently.
- `reconciliation/oracle_v2.py::verify_case` supplies five mechanical checks with false defaults on provenance error. Preserve its status and errors; do not render those defaults as independently established no-storage/no-readback facts.
- `reconciliation/model_cohort.py::_observed_actions` is an aggregate literal storage/readback diagnostic, not per-call causal attribution or report validity. A new v2 sidecar should establish per-call chronology/ownership/multiplicity from raw evidence before presenting that association. Do not reuse the v1 `diagnostics.explain_reconciliation` by falsifying a v2 scenario version.
- Proposed tests: `tests/test_operator_incidents.py`, `tests/test_operator_incident_report.py`, `tests/test_scripts/test_operator_incidents.py`. Build the decision form and meaningful end-to-end report/adjudication round trip first; defer study randomization/analysis infrastructure until an actual protocol is specified.

## Meaningful initial failing cases

Use existing scripted development captures for engineering controls, labeled as such; their expected form behavior is not a clinician's judgment.

- Faithful reference: blank packet imports as pending; a syntactically complete but deliberately wrong target remains an operator submission and is not rewritten. A synthetic adjudication fixture can mark its target claim unsupported without claiming a real reviewer did so.
- REC2-002 wrong exclusion: returned note/storage/readback can be real while content is incorrect. A response claiming no storage solely from oracle persisted_action=false must not become automatically valid.
- REC2-003 wrong target: report records requested and observed targets separately; a citation proving an unrelated patient's successful write cannot establish correct-target persistence.
- REC2-004 ACK without storage: acknowledgement is present, final new note is absent. The interface does not collapse both into a single action-success badge.
- REC2-005 duplicate notes: two stored copies and one retrieved copy retain multiplicity. A readback claim must not silently equate one text match with both notes being retrieved.
- REC2-006 incorrect-content readback: actual retrieved text is recorded despite strict readback=false. Literal offsets, nulls and wrong exclusions remain inspectable; neither normalization nor score relabeling repairs them.
- REC2-007 interruption after write: persisted note remains visible; execution incomplete and readback unavailable remain distinct. A provider/tool/grader error never becomes a negative clinical verdict.
- REC2-008 incomplete capture: missing final snapshot does not become zero notes; hidden complete original/control label must be absent from operator packet bytes. Citation of a missing decoded field fails structurally; citation of its available parent can support an insufficiency claim.
- Valid but irrelevant citation passes only structural import; overall report validity remains pending. An assistant's contradictory assertion cannot prepopulate or settle operator/adjudicator judgments.
- Duplicate/foreign case IDs, unknown finding categories, malformed/duplicate JSON keys, model-like yes strings instead of enum values, cross-case references and tampered report hashes retain invalid submissions without dropping assigned rows.
- Two discordant adjudications retain both originals and remain unresolved; importing one twice does not produce agreement. Abstention, missing adjudication and a valid report of insufficient evidence remain distinguishable.
- Optional unknown active time survives. Missing/invalid timing does not erase the operator's report; it remains unavailable for any later time endpoint under the frozen missingness rule.

## Evidence needed beyond implementation

Actual intended-user feasibility observations, independent report validity review, clinically relevant case/error review where claimed, fresh held-out scenario families and independently registered comparative outcomes remain absent. The immediate comparison can only support a narrow assisted-versus-raw review workflow claim after a valid study. It cannot establish superiority over all products or patient benefit. Formal red team and publication remain behind the existing user-value gate.
