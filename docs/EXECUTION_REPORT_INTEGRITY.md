# Execution and report integrity

These local repairs address reproducible software defects at `5cd2955`.
They are ordinary development work, not a formal red-team campaign, clinical
calibration or evidence of superiority. Historical results, task YAML, rubric
overlays and verdict fixtures are unchanged. Publication follows the
[automated release workflow](RELEASE_EVIDENCE_PLAN.md); external human review
is not an engineering-release dependency.

## Execution evidence survives interrupted work

The native agent runner validates the whole normalized response before
recording an assistant action or dispatching tools. Content, call structure,
nonempty names/IDs and finite JSON values are required. Supplied arguments
must be objects; omitted arguments retain the existing empty-object default.
IDs must be distinct within one pending batch; an ID may be reused after
its previous response is complete. A malformed later response retains all
previous turns and returns an incomplete trajectory to the orchestrator.

For JSON-representable invalid responses, `agent_protocol_error` preserves
the exact normalized adapter response and round. A cycle, non-finite value
or non-JSON object is explicitly uncapturable; it is not stringified into
apparently valid evidence. This is normalized adapter evidence, not a native
provider envelope that the runner never observed.

If dispatch or response serialization throws, the runner stops the batch,
keeps the requested calls and earlier responses, and records the failing
call, stage and unknown outcome. The exception may occur after state
mutation. There is no fabricated tool response, implicit rollback or
immediate retry. Callers must inspect actual state before deciding on recovery.
`total_tool_calls` counts requested calls; it is not a count of dispatched or
persisted actions when a batch is interrupted. Actual responses and state
evidence must be inspected separately.
The orchestrator saves this partial execution, leaves all criteria ungraded,
and resumes from the immutable error checkpoint unless an explicit retry
is requested. Request copies prevent a client or handler from rewriting
captured arguments through shared mutable objects.

## Positive action evidence is field-bound

Three real-handler reproductions exposed false criterion passes:

- NEG-001-C01 failed to recognize `disposition='admitted'` because its check
  uses `admit`. The evaluator now binds this check to the disposition field
  and recognizes the published enum. Unrelated note text does not substitute
  for a disposition. Negative safety checks still consider attempted actions,
  including requests that the tool rejected.
- CR-030-C05 accepted a basic metabolic panel order whose indication said
  “Avoid phentolamine.” Positive medication checks now require a medication
  order and the medication identity in `details.medication` or `details.name`.
  Explicit legacy flat medication fixtures remain supported. This is a
  narrower evidence binding, not validation of dose, route or clinical need.
- A changed retry could receive the old acetaminophen order with
  `deduplicated=true` while its new phentolamine request earned credit.
  Within the existing `(encounter_id, order_type, idempotency_key)` identity,
  changed effect-bearing details, priority or indication now yield
  `idempotency_conflict` without changing the original order or linked task.
  Identical retries still return that one order. The key is not global across
  encounters or order types. Missing optional fields remain distinct from
  explicitly supplied values; JSON scalar types are preserved.

The live evaluator and replay exclude deduplicated entries from new positive
and temporal action evidence. Original successful actions retain credit.
Replay preserves the saved marker; malformed marker values make that response
unknown rather than silently counting a new action. These changes do not
repair broad or clinically ambiguous authored checks. Open examples remain
in [task validity findings](TASK_VALIDITY_FINDINGS.md).

An independent development review also reproduced conflicting duplicate JSON
keys in imported tool content overriding that marker. Replay uses one strict
decoder for status, error code and deduplication. Duplicate keys at any depth,
non-finite constants and overflowing numbers cannot supply positive action
evidence. The original response text and attempted action remain unchanged.

## Shared mutation retries bind the target and request

An original synthetic note/readback probe found that `updateEncounter` could
acknowledge changed text or a different patient's encounter using a previous
key while persisting neither requested change. The shared guard also served
`updateTaskStatus`, `updatePatientRecord` and `applyProtocol`. Real-handler
regressions cover each caller with dictionary and dataclass entities.

Their namespace remains `(registered tool, key)`, with camelCase and
snake_case aliases treated as the same tool. An identical finite JSON body,
excluding only the key itself, may deduplicate. A changed target or body
returns `idempotency_conflict` before mutation. Missing optional fields,
supplied context and JSON scalar types remain distinct, even where a legacy
handler ignores a supplied field. Failed attempts do not reserve the key.
Original audit bodies and names are preserved. Distinct keys, no-key calls
and the explicit legacy flag opt-out retain their existing behavior.

This does not add an exactly-once transaction across process failure or
out-of-band state changes. Existing registration deduplication, terminal
task-state behavior and protocol-step generation are outside this repair.
An audit retry match is not independent proof that a stored note still exists;
the proposed reconciliation verifier must also inspect persisted state.

## Reports check saved evidence bindings

The report shares the canonical unassessed-run markers with other evidence
consumers. A run marked unassessed or not benchmark-comparable cannot display
a clean pass or assessed score. Partial grading retains known per-criterion
verdicts as recorded evidence; an experimental profile remains wholly
ungraded. Raw saved scores and verdict fields are preserved for inspection.

When a sealed `review_context` exists, its source/interface/trajectory
bindings must validate. Criterion coverage is checked against the exact
frozen IDs, not only a row count. Missing, extra and duplicate entries,
conflicting declared counts and malformed grading metadata remain visible.
An invalid context invalidates bound verdicts. Legacy files without a saved
context show unknown provenance and are never rebuilt from current YAML.
Hashes detect content changes; they do not authenticate authors or reviewers.

## Evidence and limits

[Pre-fix reproductions and TDD failures](../artifacts/evaluation-integrity/20260930/execution-report-v1/README.md)
include real-tool state/readback, live evaluation and saved replay. Regression
coverage includes an actual orchestrator run and unchanged checkpoint resume,
batch interruption after mutation, positive actions and identical retries,
partial report evidence and mutated saved bindings.

Tests establish these software contracts only. Provider adapters may reject
native envelopes before normalization; this change does not add universal
native-envelope capture. A tool acknowledgement alone is still insufficient
for full action correctness. Patient attribution, exact returned facts,
clinical appropriateness and many authored rubric meanings require additional
independent verification. A separate [free local Nemotron round trip](../artifacts/local-order-probe/20260930/execution-repair-v2/README.md)
completed two model responses and one literal synthetic order through this
runner. Its action-fidelity check passed; clinical and safety coverage remain
zero. No clinical review, comparative outcome or browser visual QA was
performed as part of these repairs.
