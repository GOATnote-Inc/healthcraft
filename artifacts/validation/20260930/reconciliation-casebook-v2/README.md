# Reconciliation casebook v2 development checkpoint

The new pinned development casebook contains eight original synthetic scenarios
with 50 source rows. Variable native worlds execute real reads, writes,
idempotent retries and readbacks. A separate verifier rechecks authored source
contracts and bindings; no fixture/controller generates its expected labels.
Scenario and expectation authors used a shared ledger, disclosed throughout.
Independent clinical/human label review is pending. An initial fixture receipt
incorrectly said independently authored; its adjacent provenance erratum
corrects that wording without replacing the original receipt.

TDD reproduced the missing v2 interfaces and a shared completion defect:
false/zero/empty error values previously allowed apparent completion. Strict
validation now rejects malformed receipts while retaining real error/action
evidence. Five saved v1 results remain canonically unchanged, including all
four real local-model pilot captures. Existing captures were not modified.

Ordinary development review also reproduced and repaired a control-retention
defect: an unexpected readback failure after a real stored note must remain
captured when the planned omission transformation cannot run. The runner
requires both a deliberate omission and a verified complete original; a
provenance failure by itself cannot count as a matched omission control.

The [documented CLI execution](../../../reconciliation/20260930/casebook-native-v2/README.md)
retains all 16 scheduled attempts and matches each declared mechanical pattern.
No model calls, participant outcomes or clinical/safety criteria are included.
Each attempt and failure remains in the fixed roster; source drift withholds
an overall successful control result. Output is exclusive and inventoried.

Full repository suite: 4170 passed, 58 skipped in 282.51s (0:04:42)
Inventoried make lint passes for 787 inputs, including 401 Python files.
Workspace make lint still reports 115 existing unrelated archive violations.
Source-bound owner and peer checks cover Python 3.10, 3.12 and 3.14; their
counts overlap and should not be added as distinct tests. Raw RED/GREEN logs
and intermediate test-setup failures are retained. The read-only task-validity
audit reproduces existing semantic rubric gaps; those channels are unchanged.

403 payloads in prior model/report/tutorial/checkpoint manifests were checked
unchanged. No results or manuscript files were edited. A valid engineering
control is not a valid clinical/operator report: fresh held-out cases,
independent labels/participants, registered comparative evaluation, v2 review
adjudication and instrumented timing remain unfinished. These ordinary checks
are not the gated formal red team. No remote push or publication occurred.
