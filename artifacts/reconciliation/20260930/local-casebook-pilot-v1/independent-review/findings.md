# Independent review of the completed local development cohort

All 945 prepared checks passed. The 16 scheduled attempts and their outputs are retained; 15 executions completed and one stopped after a tool error. All 16 saved mechanical verifications reproduce exactly and remain not verified. No mismatch between the saved cohort, its frozen plan, source identity, full file inventory, or saved verification was found.

## Recorded execution and state

- 116 native request attempts and 116 exact raw response bodies; every body parsed strictly and recorded `done=true`, `done_reason="stop"`. No response truncation or request retry is recorded. Fifteen explicit finish commands and 101 tool commands account for all 116 responses.
- 101 tool calls and 101 matching audit entries: 100 successful calls and one `not_found` response.
- 15 acknowledged writes, 15 new notes, no deduplicated writes, and no extra notes. Two later successful reads returned the exact stored text; the other 13 notes had no post-write readback.
- 34 successful encounter-detail reads in total, including those two post-write reads. Across the 16 attempts, 84 of 100 expected source-row appearances were retrieved exactly; seven attempts left part of the closed cohort unretrieved.
- All 16 fresh before/after model identities matched the declared digest/runtime. All child processes and IPC helper threads stopped. Source files and captured artifacts were unchanged by review.

| Attempt | Execution | Requests | Tools | Notes | Text readbacks | Exact source rows retrieved |
|---|---|---:|---:|---:|---:|---:|
| REC2-001/nano | completed | 7 | 6 | 1 | 0 | 5/6 |
| REC2-001/medgemma | failed | 6 | 6 | 0 | 0 | 5/6 |
| REC2-002/nano | completed | 8 | 7 | 1 | 0 | 5/5 |
| REC2-002/medgemma | completed | 8 | 7 | 1 | 0 | 5/5 |
| REC2-003/nano | completed | 6 | 5 | 1 | 0 | 2/6 |
| REC2-003/medgemma | completed | 10 | 9 | 1 | 1 | 6/6 |
| REC2-004/nano | completed | 6 | 5 | 1 | 0 | 5/5 |
| REC2-004/medgemma | completed | 6 | 5 | 1 | 0 | 5/5 |
| REC2-005/nano | completed | 6 | 5 | 1 | 0 | 5/6 |
| REC2-005/medgemma | completed | 8 | 7 | 1 | 0 | 6/6 |
| REC2-006/nano | completed | 6 | 5 | 1 | 0 | 4/7 |
| REC2-006/medgemma | completed | 8 | 7 | 1 | 0 | 6/7 |
| REC2-007/nano | completed | 7 | 6 | 1 | 0 | 4/4 |
| REC2-007/medgemma | completed | 8 | 7 | 1 | 1 | 4/4 |
| REC2-008/nano | completed | 6 | 5 | 1 | 0 | 6/11 |
| REC2-008/medgemma | completed | 10 | 9 | 1 | 0 | 11/11 |

## Retained tool error

`REC2-001/medgemma` passed patient ID `PAT-20010002` as the `encounter_id` in its sixth `getEncounterDetails` call. The actual handler returned `{"code":"not_found","message":"Encounter PAT-20010002 not found","status":"error"}`. The controller retained `reason="tool_error"`; the worker retained `failure_stage="tool_response"` and `RuntimeError: Tool returned an error; this attempt will not retry`. The supervisor preserved a failed execution with the nested original error. No note was written and no retry or finish command followed.

## Source-content and traceability findings

These are overlapping exact-data categories, not clinical labels or a scoring system. Fourteen stored notes are strict JSON objects; one note cannot be parsed because its serialized text repeats top-level `patient_id` (and also `encounter_id`). The malformed note is retained and excluded from per-field counting.

- Twelve parseable notes contain 44 target-source descriptors with incorrect `source_path`. Every one of those 44 corresponding raw `source` rows matches the authored original exactly, including nulls, time literals, and scalar types; the changed descriptor field is only the path. Examples include retaining the `/patient` namespace, omitting array indices, or inventing path components such as `/item/synthetic_item_501`.
- Four parseable notes omit nine required target rows in total. Two of these notes copy the example layout with empty observation arrays (`REC2-004/medgemma` and `REC2-007/medgemma`).
- Two notes (`REC2-002/nano`, `REC2-007/nano`) include four prior-encounter rows as current-encounter observations and rewrite their encounter ID to the target. Their raw source assertion values are preserved; their attribution and inclusion are incorrect.
- Ten parseable notes omit required exclusion source IDs. Five include exclusion objects without `source_id`. `REC2-008/medgemma` additionally marks three other-patient sources as `other_encounter`.
- `REC2-004/medgemma` omits the authored three-source opposing-report group. `REC2-005/medgemma` adds a conflict between two distinct event IDs whose reported statuses are both `administered`; the source contract defines no such conflict.
- `REC2-007/nano` adds an extra top-level `source_id` field.

`REC2-003/medgemma` and `REC2-007/medgemma` genuinely read back their stored note text. The oracle readback check remains false because it qualifies readback by a correct note and complete source retrieval. The literal readback count of two must not be presented as zero reads, nor as two verified reconciliations. Likewise, the false persisted-action check is content-qualified and does not mean no note was stored.

## Bindings and limits

`peer-review.json` records the 945 checks, all saved versus recomputed verdicts, exact request observations, complete captured-file SHA256 inventory, and frozen source inventory. `roster-diagnostics.json` adds every attempt, exact expected/observed note differences with evidence/expectation pointers, returned source rows, the actual handler/audit error, category denominators, and complete input bindings.

The cases are exposed engineering development fixtures with shared source/expectation authoring and independent review still pending. Clinical correctness, clinical safety, healthcare value, held-out generalization, and human adjudication are unassessed. These observations establish no model ranking or superiority. Request and token counts are recorded/provider-reported observations, not independently attested inference. No source, run artifact, or historical result was changed; no model or tool action was executed during review.

| Review file | SHA256 |
|---|---|
| peer-review.json | `b1fb91a48e62ba70857670f2c424c18c937c29bc4c1ef741b8e752128e68b667` |
| roster-diagnostics.json | `c0437168c222f352537fe1566fa4bdb1072cd4295d9fe05380cd3ec17d7e71b6` |
| check_live.py | `34817cf7fc43a1a5a113b572f645484e55d170e218dbd943d8337ee3113fa0cb` |
| summarize_live.py | `ec848e657eb74c2e92499f66c9a36741ba085330f44f9b95d48764d5998fdf2b` |
