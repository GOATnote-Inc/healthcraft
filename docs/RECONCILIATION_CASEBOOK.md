# Source reconciliation development casebook v2

The opt-in v2 path exercises source ownership and persisted actions across
eight original synthetic cases. It expands the single exposed v1 fixture;
it does not change published benchmark tasks, rubric channels or rewards.
Its useful engineering question is whether an agent's source account actually
reached the intended encounter and was retrieved again with its facts intact.

**These are development cases with engineering-authored expectations and
independent review pending.** They assess zero clinical or safety criteria.
Their declared families are descriptions, not evidence of statistical
independence. They are not held-out cases or a registered comparative study.

## Execute and inspect

From a source checkout with the project dependencies installed:

```bash
python scripts/reconciliation_casebook.py --output-dir /tmp/hc-casebook-v2-01

# One case, faithful reference only, still validates the entire source book:
python scripts/reconciliation_casebook.py --case REC2-006 --mode reference \
  --output-dir /tmp/hc-casebook-v2-02
```

The default schedules a faithful reference and a designated development
control for every case: 16 executions, no model calls or downloads. Existing
output directories are refused. Explicit `--casebook` inputs also require a
separately supplied canonical `--expected-sha256`; a digest in an untrusted
file cannot authenticate that same file.

Each run retains real request/response journals, before/after snapshots,
native middleware audits, controller completion, and the verifier receipt.
The manifest lists scheduled attempts, expected control outcomes, observed
checks, runtime identity, source implementation hashes and output file hashes.
An unexpected outcome or retained execution error produces a nonzero exit.
Success means the constructed engineering controls behaved as declared; it
is not a model pass rate, clinical result or superiority result.

The frozen [native execution record](../artifacts/reconciliation/20260930/casebook-native-v2/README.md)
contains all sixteen scheduled development attempts and their source bindings.

The source [casebook](../configs/evaluation/reconciliation_v2/casebook.json)
contains 50 records across 15 patients and 22 encounters: 31 current-target
records, 19 scope exclusions and three unresolved conflict clusters.

| Case | Distinct source relationship | Designated control |
|---|---|---|
| REC2-001 | Current, prior and other-patient sources; unknown and planned values | Faithful note, identical retry and readback |
| REC2-002 | One patient with two prior encounters, including unknown arrival | Incorrectly label a prior source as another patient |
| REC2-003 | Three patients; event identifier reused across ownership boundaries | Store target content in another patient's encounter and read it there |
| REC2-004 | Three reports for one event, including two opposing one; no majority resolution | Test handler acknowledges the write without changing the store |
| REC2-005 | Different event IDs share an item and time | Two actual note writes with different idempotency keys |
| REC2-006 | Equivalent clock-offset literals, opposing reports and unknown status | Invent status, omit a conflict member, then retrieve the incorrect note |
| REC2-007 | Future planned time and prior unknowns | Interrupt after the first actual write, before readback |
| REC2-008 | Larger three-patient roster and multiple pending studies | Explicitly omit final capture evidence while preserving the complete original |

The last control is a **deliberate capture transformation**, not an actual
interrupted execution. Its complete original capture and full native journal
remain alongside the incomplete derivative. Other control parameters change
before tool dispatch. The acknowledgement-only case uses a clearly designated
defective test handler under the real validation and audit middleware. None
of these constructed controls is represented as a model failure.
If the original execution fails before the planned capture omission, its
partial evidence and original error remain intact, and the omission is marked
unapplied. That unexpected failure cannot satisfy the designated control.

## Contract and provenance

Source scenarios and expectation receipts are separate files. Their authors
used a shared source ledger; this is disclosed and does not count as independent
label authorship or physician adjudication. The loader verifies the whole
inventory, including unselected cases, before execution. It rejects altered
hashes, duplicate IDs/JSON keys, nonfinite values, missing/unlisted files,
symlinks and expectations that contradict their source ownership or literals.

The reference controller receives public target IDs and actual tool responses.
It does not receive expectation rows. The v2 verifier reads source contracts
directly without importing the fixture or controller; it checks the authored
expectations again, then uses the shared mechanical evidence checks.
Case, casebook, source and expectation digests must match the execution binding.
Hashes establish content identity and consistency, not authenticated execution.

The five checks are provenance, exact source fidelity, one correct persisted
target note, content-qualified readback, and completed execution. Actual storage
and retrieval can occur while the latter content-qualified checks fail, as the
wrong-target and incorrect-content controls demonstrate. Coverage counts use
each case's actual source and target-row totals; there is no fixed eight-row
denominator and no benchmark score.

The v2 fixture is deliberately bounded: one same-name cohort per case, one to
eight patients, one to sixteen encounters, at most nine encounters per patient,
and one to 128 source rows. Searches therefore remain below the ten-result
truncation boundary. Birth dates are unknown and initial notes/vitals/labs are
empty. This is not general patient matching, pagination or clinical reasoning.
Status and source timestamp literals are preserved, including unknown values
and equivalent offsets. Conflicts concern opposing literal administration
reports for the same event; the verifier never decides which report is true.

The shared verifier also repairs malformed completion receipts: `error: false`,
zero or empty containers are invalid provenance, not successful completion.
Normal absent/null errors retain the prior verdict. Real error objects preserve
available storage/readback evidence while withholding execution completion.
Existing captures are immutable; new verification uses the current implementation.

## Remaining work

The v1 explanation and operator tutorial are not v2 adjudicators. A future
review contract must capture the operator's identified patient/encounter and
incident, separate actual storage/readback from correctness, and determine
whether the report is valid. Response format acceptance alone cannot do that.
The casebook command currently emits inspectable JSON and journals, not a new
browser interface or visually verified workflow.

Local MedGemma/Nemotron attempts on v1 remain exposed development observations;
they are not rerun or relabeled by this casebook. V2 model testing, independent
clinical review, registered assignments, instrumented operator timing and
held-out comparative outcomes remain separate work. The release sequence stays
[value evidence → formal red team → main and paper](RELEASE_EVIDENCE_PLAN.md).
