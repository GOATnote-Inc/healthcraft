# Original synthetic reconciliation capture

Nine scheduled scripted executions were captured from one frozen code candidate.
All nine expected development outcomes matched, and all nine optional Microsoft
CSV verifications completed. This is ordinary software validation, not the
formal red team, a model study, clinical validation or evidence of superiority.

Open the [review report](report.html), [declared roster](roster.json) or
[bundle](bundle.json). Each trial directory contains the actual in-process
requests/responses, pre-dispatch journal, audit, before/after world snapshots,
independent oracle receipt and raw secondary-verifier output.

| Execution | Source fidelity | Correct note persisted | Readback | Complete | CSV reward |
|---|---|---|---|---|---|
| Faithful reference | yes | yes | yes | yes | 1 |
| Omitted source | no | no | no | yes | 1 |
| Invented administration | no | no | no | yes | 1 |
| Silently resolved conflict | no | no | no | yes | 0 |
| Wrong-patient citation | no | no | no | yes | 1 |
| Wrong-patient write | no | no | no | yes | 1 |
| Acknowledgment without persistence | yes | no | no | yes | 0 |
| Duplicate note writes | yes | no | no | yes | 1 |
| Interrupted immediately after write | yes | yes | no | no | 1 |

All nine have valid evidence binding. The persistence and readback columns
require the **correct** note; they do not claim that an invalid note was never
stored or retrieved. The acknowledgment control installs a deliberate test
handler that returns success without writing; it is not a claim that the
production handler still has that defect. Seven CSV rewards are positive,
including six nonreference executions. The CSV verifier's narrower task is
retrieval of a disagreement cluster; it cannot verify note fidelity,
persistence, completion or healthcare value. This is not a reproduction of
Microsoft's original benchmark or evidence that it failed its own contract.

## Inputs, runtime and reproducibility

- Fixture: `synthetic-ed-reconciliation/v1`, eight original synthetic source
  rows across two same-name patients and three encounters. No patient-derived
  records or upstream corruption labels are used.
- Canonical scenario SHA256:
  `b8237a08c4d3b234a44024c743b3ff9f0280f1d7e9f5562f882421485f0cd1c6`.
- Baseline Git commit: `da26867e3f65abc526bcfcd19fd9f8567507cbe6`.
  The [candidate receipt](frozen-candidate-receipt.json) binds the exact 601
  source/configuration/test/launch inputs, including new uncommitted code at
  capture time. The baseline commit alone does not identify that candidate.
- The [initial source identity](source-identity.json) was saved before trials;
  all 139 execution-source hashes match after the run.
- Actual optional runtime: Python 3.12.8, pandas 3.0.1, NumPy 2.5.3,
  python-dateutil 2.9.0.post0 and six 1.17.0. Existing same-Python core packages
  were appended after the optional environment's site directories. Exact
  versions and paths appear in [runtime.json](runtime.json). This is not the
  full upstream Docker environment.
- Microsoft source revision:
  `bcbb8085fd549469e2dc7455f4bfd68a1b98895a`. Its source and MIT license remain
  byte-identical and are copied with each secondary verification. See the
  [integration guide](../../../../integrations/healthagentbench/README.md).
- [Capture command and environment](capture.json), [captured runner](capture.py.txt)
  and [stdout](capture.log) preserve the actual invocation. The runner clears
  inherited environment variables, including hosted-model credentials.
- The upstream `turn_count` means recorded synchronous tool invocations in
  these scripted executions. There are **zero model turns and zero model
  calls**. Counts must not be compared with terminal-agent/model turns.

To run the current checkout, follow the
[workflow guide](../../../../docs/SYNTHETIC_RECONCILIATION.md) and use a new
output directory. The captured runner/reviewer contain original absolute local
paths; they are execution records, not portable installation scripts. A new
environment must be prepared explicitly, with its own runtime receipt.

## Validation and limits

The [independent saved-artifact review](independent-review.json) passed 316
checks: all suite hashes, candidate inputs, source identities, journal/call/audit
links, pure oracle replay, independent CSV arithmetic and HTML links/escaping.
The [checker](independent-review.py.txt) is preserved. This was read-only
ordinary development review; it did not rerun models or the upstream grader.

The [validation checkpoint](../../../validation/20260930/reconciliation-checkpoint/README.md)
retains TDD RED/GREEN logs, focused optional-runtime tests and full-suite process
receipts. Existing benchmark task definitions, result files, scoring channels
and manuscript remain unchanged.

The suite's [manifest](manifest.json) covers its original 130 files. The later
`capture-manifest.json` additionally covers the capture/runtime receipts,
review and these notes. Hashes establish local content consistency, not
third-party execution attestation.

These open engineering labels do not assess clinical correctness or safety:
both coverage counts are zero and the benchmark score is null. No MedGemma,
Nemotron or other model was invoked in this capture. No Harbor lifecycle,
independent label-isolation boundary, matched model comparison, operator study
or physician validation is established. HTML checks are static; browser visual
QA remains unverified. Comparative value must be demonstrated before the
requested formal red team, remote main and manuscript steps.
