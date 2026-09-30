# Executable task reference certificates

The experimental `linked-history/v1` profile gives IR-002 four linked
historical encounter records and executes a mechanical reference witness
against the real in-process MCP handlers. The linked-history profile remains
opt-in. Published task definitions, rubric channels, and historical results
remain unchanged. Later [default-injector repairs](AUTHORED_OBSERVATIONS.md)
preserve authored observations and unknown times in new executions.

This closes one prerequisite for a future task revision: proving that the
required source facts can be retrieved and persisted. It does not establish
clinical reasoning quality or certify the original task as fully valid.

## Run without a model

```bash
make certify-history
.venv/bin/python scripts/certify_history_task.py \
  --output /tmp/healthcraft-ir002-certificate.json
```

The CLI seeds Mercy Point, applies the profile, executes the reference, and
prints a JSON report or creates a new output file exclusively. An existing
file is never overwritten. Exit codes are 0 for a complete mechanical witness,
1 for a failed mechanical check, and 2 for invalid evidence or a runtime/input
error. There are no model calls, API keys, downloads, or network dependencies.

## Source precision and execution

The profile copies the task's four visits verbatim into deterministic,
patient-linked records. Each has a `visit_date`, `date_precision="day"`, and
`arrival_time=null`. It preserves the raw disposition, including
`admitted (observation)`, without inventing arrival times, triage, vitals,
or treatments. Invalid input, identifier collisions, and reapplication fail
before modifying the supplied world.

The calendar contract is explicit: **2025-12-16 ≤ visit date < 2026-01-15**,
the 30 calendar dates before the setting's declared local date. It is not
a rolling 720-hour interval. Existing instant-bounded encounter searches
exclude these records because their arrival instants are unknown.

The reference controller receives target IDs and that window, without the
task's expected visit facts. It calls patient-scoped `searchEncounters` and
`getPatientHistory`, follows the returned links through `getEncounterDetails`,
filters the returned dates, writes a structured source-fact summary through
`updateEncounter`, and reads the current encounter back. The ordinary
positive witness uses eight calls.

The recorder snapshots full requests and responses and binds each call to
its world audit entry. Its unique call IDs identify synchronous harness
operations; they are not provider message IDs. The verifier independently
reads the source task, checks visit identity and field grouping, and inspects
new linked documentation and final state. It does not reuse the historical
tool-name-only rubric checks.

## What the checks mean

| Historical criterion | Mechanical evidence checked here |
|---|---|
| IR-002-C01 | Discovery and history belong to the intended patient and cover the linked visits in the declared calendar scope. |
| IR-002-C02 | Four distinct source visits were actually returned. Four repeated calls do not suffice. |
| IR-002-C03 | Returned complaints, diagnoses, dispositions, and notes match the correct source visit. Swapping diagnoses between visits fails. |
| IR-002-C07 | A structured summary contains the retrieved facts and is newly persisted on the correct encounter, with successful readback. |

These are mechanical analogues of the four criteria, not replacement
benchmark verdicts. C04, C05, C06, and safety-critical C08 remain unassessed.
The report has no reward or full-task pass field and measures zero safety
criteria. Exact structured copying tests source concordance and persistence;
it does not evaluate the quality of a freeform clinical summary.

Regression tests falsify the witness with wrong-patient discovery, empty
history, missing and duplicate visits, altered or out-of-window facts,
failed or missing responses, documentation written too early or on another
encounter, missing readback, and pre-existing or unpersisted notes. Malformed
evidence is an error, not a successful negative control.

## Reproducibility and limits

Reports include task-byte hashes, executable source and schema hashes, environment
identity, seed/world-preparation mode, complete captured calls, and a
recomputable trace digest. The profile normalizes construction timestamps
for its subject; it does not claim the entire seeded world is byte-identical.
Content hashes identify recorded inputs and detect changed bytes. They do
not attest third-party transcript authenticity.

This witness covers one engineering-authored profile through in-process
handlers. It does not test MCP network transport, FHIR conformance, model
performance, clinical judgment, or clinical readiness. The original
[task validity findings](TASK_VALIDITY_FINDINGS.md) and independently
labeled [grader challenges](../configs/evaluation/grader_challenges_v1.json)
remain applicable to the historical task and grader. Broader validation is
tracked in the [evaluation design roadmap](EVALUATION_DESIGN_ROADMAP.md).
