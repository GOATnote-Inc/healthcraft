# Task validity findings

This is an engineering audit of supplied synthetic facts, tool behavior,
and verifier evidence. It is not a clinical adjudication or a replacement
for the published benchmark. Historical tasks and results remain unchanged.

## Action and grading fidelity: 2026-09-30 development follow-up

Reproductions at `5bc224f` exposed two executable defects. A valid
`createClinicalOrder` request for a stat potassium measurement created a
random follow-up task with unrelated work, staff and timing. The repair
preserves exact order details, priority and indication, links the order to a
deterministic clinical task, and uses simulation time. Unspecified deadlines
and assignees remain unknown. Real-tool tests cover all six order kinds,
four priorities, idempotent retries, collisions, and subsequent task completion.

The server also accepts `create_clinical_order`, but the evaluator previously
failed to recognize that spelling. A successful, persisted heparin order
violated NEG-001-C02 through the camelCase spelling and incorrectly passed
the same criterion through the snake_case alias, in both live evaluation
and replay. Matching now uses the server's `TOOL_NAME_MAP` for registered
aliases while preserving original audit entries and existing success/error
semantics. Historical result files are not rewritten.

The small grader regression suite had additional accounting defects: the
string `"false"` was coerced to true, an incorrect safety label could remove
a critical false pass from its gate, and an empty suite could pass. Strict
types, task-derived safety checks and explicit missing-denominator reporting
now prevent these cases. Its 55 synthetic audit/parser fixtures have no
verified independent physician adjudication. They are engineering regression
expectations, not clinical calibration; all existing expected labels are
preserved.

The following issues remain open and block stronger validity claims:

- SCJ-012-C02's v9/v10 overlay accepts any medication order, including
  acetaminophen, for an assertion requiring broad-spectrum antibiotics
  within an hour. Fixing tool spelling does not repair that semantic and
  temporal mismatch. It requires a separately reviewed rubric revision.
- Temporal source replacement was subsequently repaired in local development;
  see [authored observation fidelity](AUTHORED_OBSERVATIONS.md). The earlier
  capture remains unchanged. The repair preserves direct vitals/labs and
  explicit arrival/triage facts, but does not validate authored clinical
  content, historical/multi-patient timing, or observation availability.

The [original captures and hashes](../artifacts/evaluation-integrity/20260930/action-grading-review-v1/README.md)
retain the defects before repair. Regression coverage lives in
[order action tests](../tests/test_mcp_tools/test_order_action_fidelity.py),
[tool alias tests](../tests/test_evaluator_integrity/test_tool_aliases.py), and
[grader contract tests](../tests/test_evals/test_grader_goldset_contract.py).

## Action evidence follow-up at 5cd2955

Three further real-tool false passes were reproduced and repaired locally:
`admitted` failed a check written with `admit`; medication words in a lab
order's indication earned medication credit; and a changed idempotent retry
received credit even though only the original order persisted. The
[execution and report contract](EXECUTION_REPORT_INTEGRITY.md) describes the
field bindings, conflict handling, deduplicated replay semantics and retained
negative-intent checks. Seven authored safety criteria use the affected
`disposition matching admit` form. The repair changes future evaluation
behavior without editing those criteria or rewriting historical results.

## Authored care and imaging: subsequent local repair

The `aa21717` source audit reproduced 37 fabricated administration rows from
active orders or management in five tasks, including 20 default oral routes.
Actual discharge output repeated these inventions. Other tasks retained
reported treatment only in narrative and could receive a false “No medications
administered” summary. Encounter interaction validation could silently miss
those reports. The [care contract](CARE_IMAGING_FIDELITY.md) now preserves 22
reviewed fields as source assertions, keeps unknown administration explicit,
and returns unavailable encounter validation while retaining known findings.

The imaging audit found discarded scalar reports, ignored `result` fields,
unknown study labels defaulting to X-ray, and scenario time replacing authored
time. The new projection preserves six reviewed imaging groups, typed fields
only when explicit, and raw observations with provenance. Eight reviewed
conditional guidance fields stay withheld. Source roles and pending status
do not establish performed studies. These changes repair future executions;
they neither regrade the unchanged historical results nor adjudicate the
clinical content. Independent review and comparative-value gates remain open.

## IR-002: prior encounter retrieval

The audit at commit `31511e8` seeded the actual world, injected IR-002,
and called the real MCP handlers. The task specifies four prior visits:
December 18 and 27, 2025, and January 3 and 9, 2026.

| Surface | Observed behavior |
|---|---|
| Injection | Creates one current encounter, `ENC-641A154E`, linked to `PAT-641A154E`; no four historical encounter entities. |
| `searchEncounters` | Returns the current encounter for that patient. At the audit commit, `date_from`/`date_to` were ignored, including an impossible 2030 interval. |
| `getPatientHistory` | Returns empty `prior_visit_ids` and only the current encounter in `encounter_ids`. |
| `getEncounterDetails` | Preserves all four supplied visit descriptions as a flattened `Prior Ed Visits 30 Days` clinical note on the current encounter. The facts are therefore partly reachable, not wholly absent. |
| C01-C03 | Tool-name checks can pass after only `searchEncounters` and `getPatientHistory`, even for another patient, without reading the detailed note or producing an answer. This is not a full-task pass. |

The task patient YAML is not included wholesale in the agent's initial
prompt. Finding the historical narrative requires retrieving the current
encounter. The static preflight cannot prove that an agent can retrieve
four linked historical records, because those records are not materialized.

The subsequent search repair enforces inclusive RFC3339 time bounds,
including equivalent timezone offsets and exact fractional-second ordering.
Invalid or reversed bounds return an error; records with missing or
uninterpretable arrival instants are excluded from bounded queries.
Unbounded searches retain their prior behavior. This fixes ignored filters
without materializing or fabricating historical visit times. Future
date-only records need a separate, explicit calendar-date contract.

Sources: [task](../configs/tasks/information_retrieval/task_002_encounter_lookup.yaml),
[injection](../src/healthcraft/tasks/inject.py),
[read tools](../src/healthcraft/mcp/tools/read_tools.py), and the independently
labeled [counterexample report](../artifacts/evaluation-integrity/20260930/grader-challenges-v10.json).

## IR-001: assertion and tool mismatch

IR-001-C03 asserts that the agent checked drug cross-reactivity, but its
check accepts `checkResourceAvailability`, a bed/staff/equipment tool.
The saved replay counterexample supplies only a bed response and receives
credit. The local diagnostic also found no matching cephalexin reference
through the available knowledge/reference searches. A source-backed
knowledge repair requires separate review; a resource lookup is not
substitute evidence.

## Required versioned repair and certificate

An opt-in `linked-history/v1` profile and actual-execution mechanical witness
now implement the first experimental slice, documented in
[Reference certificates](REFERENCE_CERTIFICATES.md). They preserve the original
task and default injection. Promotion into a benchmark task revision still
requires the validity and clinical review below.

The next task revision should retain the historical version and declare
the revised task, injection profile, tool schema, and verification contract
in its run identity. The following acceptance conditions are concrete:

1. Materialize exactly the historical facts supplied by the task as four
   deterministic, patient-linked records. Preserve date-only precision and
   raw disposition text; do not invent event times, triage, vitals, or treatment.
2. Expose those records through real tools. A reference sequence must retrieve
   all four distinct visits and persist a faithful summary on the current
   encounter. An actual tool execution certificate is distinct from the
   current replay-only fixtures.
3. Bind verification to the intended patient, time scope, response IDs,
   returned facts, and persisted target note. Successful tool status alone
   is insufficient. The world audit records call parameters and result
   status, but not the returned clinical facts required for this contract.
4. Require negative cases for wrong patient, empty history, omitted visit,
   duplicated visit, outside-window data, failed/unanswered requests, and
   unrelated or empty documentation. Positive controls must pass too.
5. Report mechanical coverage for C01/C02/C03/C07 separately from the
   unassessed clinical reasoning criteria C04/C05/C06/C08. Do not present
   the certificate as physician validation or a revised full-task score.

Broader clinical claims still require the independent review and held-out
evaluation described in the [design roadmap](EVALUATION_DESIGN_ROADMAP.md).

## Versioned roster observations and a content-review finding

The opt-in [roster profile](ROSTER_PROFILES.md) exposes selected observations
from the six tasks whose root-level patient collections were omitted by the
loader. The 33 records have distinct patient/encounter identities and retain
source attribution. Recommendations and answer labels are withheld using
explicit per-collection field selectors. These sparse projections are
experimental, non-FHIR records; missing clinical facts remain unknown.

Profile diagnostics bypass the historical graders and report no benchmark
or safety outcome. An independent verifier checks retrieved observations
against the source and counts member coverage, without crediting clinical
criteria. Neither record reachability nor agreement with an authored answer
establishes clinical correctness.

A bounded content review flagged IR-018-C05's categorical exclusion of
lactated Ringer's in DKA due to acidosis. The relevant adult consensus permits
balanced crystalloids, including lactated Ringer's, in adults without renal
or cardiac compromise; the task does not supply age or a specific
contraindication. Pediatric guidance and infusion compatibility require
separate interpretation. The [review and primary sources](ROSTER_PROFILES.md#bounded-ir-018-content-review)
preserve these limits. The original task and historical outcomes are unchanged;
a clinical-content correction needs a separately reviewed task version.

## RL task preparation

The RL environment previously reset the synthetic world without injecting
the task's supplied patient. Native evaluation and RL now share task
preparation, so an RL rollout can retrieve that patient and encounter through
the same tools. A failed reset clears the previous episode before preparing
the next one. Experimental roster profiles are available for tool diagnostics,
but are rejected by training-reward computation and cannot enable physiology.
These repairs affect future executions and do not regrade historical runs.

## Broader development inventory: 2026-09-30

A read-only development inventory exercised default injection and the real
`searchEncounters`, `getEncounterDetails`, and `getPatientHistory` handlers
for all 205 tasks in isolated synthetic worlds. Tasks with patient sections
(196) each added one patient and one encounter; nine tasks added neither.
These counts describe injected task entities, not the complete seeded world.
Five subsequent seed-42 spot checks confirmed selected observations.

The following are implementation opportunities, not evidence that every task
is unsolvable. Supplied narratives often remain accessible: all 81 selected
note-backed source strings checked by the inventory appeared in read-tool
outputs. Family counts overlap and count supplied records, not unique
clinical events.

| Family | Observed representation | Next contract to review |
|---|---|---|
| Prior encounters | Seven tasks supply 33 prior visits as current-encounter notes, with no linked prior entities under default injection. Beyond IR-002: CC-020, CC-023, CC-030, IR-004, IR-016, IR-029. | Generalize a versioned linked-history profile while preserving date precision, ownership, and source provenance. |
| Multiple patients | Seventeen tasks contain 84 supplied entries: 47 in current-encounter notes, 33 in root-level collections omitted by the task loader, four in setting context. | Separately identified patients and encounters, with observation fields explicitly separated from grading targets. |
| Temporal collections | Forty-eight tasks contain 292 entries: 228 in notes, 61 in setting text, and three existing typed vitals in TR-006. | Versioned event times, provenance, and observation availability; do not infer missing units or timestamps. |

Omitted root collections occur in CC-022 (`patients_requiring_action`),
CC-027 (`incoming_ambulances`), CC-028 and IR-025 (`incoming_patients`),
IR-018 (`patients_requiring_iv_fluids`), and IR-023
(`patients_on_norepinephrine`, `patients_at_risk`, `icu_requests`). Some
source content may be paraphrased in the task description. Blindly exposing
all YAML fields would also leak answer labels, such as IR-025's
`actual_priority`; a profile needs an explicit observation-field contract.

This inventory was exploratory. Code revision, dirty-state, interpreter,
and task hashes were captured retrospectively, after the TR-017 fix below,
not at outcome acquisition. It must not be used as frozen benchmark or
manuscript evidence. A prospective reproducible inventory needs a new run
with contemporaneous provenance and reviewed family definitions.

## TR-017: social-history value loss

The authored `social_history` is a mapping in TR-017. Converting it directly
to a tuple kept only `occupation` and `tetanus_risk_factors`, discarding
their values. The corrected injector exposes both keys and authored values
through `getPatientHistory`. Existing list-shaped social histories remain
unchanged. A regression test reproduces the loss through the real MCP tool
and verifies preservation after the fix; no clinical facts are inferred.

Sources: [task](../configs/tasks/temporal_reasoning/task_017_tetanus_prophylaxis.yaml),
[injection](../src/healthcraft/tasks/inject.py), and
[regression](../tests/test_tasks/test_inject_social_history.py).
The source change affects future run identities; historical results are not
regraded or rewritten.
