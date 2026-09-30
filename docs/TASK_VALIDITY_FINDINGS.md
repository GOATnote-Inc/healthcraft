# Task validity findings

This is an engineering audit of supplied synthetic facts, tool behavior,
and verifier evidence. It is not a clinical adjudication or a replacement
for the published benchmark. Historical tasks and results remain unchanged.

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
