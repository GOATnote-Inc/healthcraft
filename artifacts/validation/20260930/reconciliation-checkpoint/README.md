# Reconciliation checkpoint validation

The exact 601 source/configuration/test/launch inputs in [candidate.json](candidate.json)
were exported to an isolated checkout and remain byte-identical to the repository
at finalization. Baseline commit: `da26867e3f65abc526bcfcd19fd9f8567507cbe6`.
The receipt includes new code, so that baseline alone does not identify the candidate.

| Check | Outcome |
|---|---|
| Full `make test`, loopback enabled | 3148 passed, 14 skipped, 260.66s |
| `make lint` on isolated candidate | Ruff checks and formatting passed; 347 Python files |
| Reconciliation tests, Python 3.10 | 166 passed, 7 optional-pandas skips |
| Reconciliation tests, Python 3.12/pandas 3.0.1 | 173 passed; actual unchanged upstream verifier included |
| `make smoke` | 48 passed, zero failures/warnings |
| Existing engineering grader fixtures | 55 cases, zero mismatches/errors |

The initial sandboxed [full run](full-tests.log) had 3,113 passing tests,
14 skips and 35 setup errors: existing local HTTP-server fixtures could not bind
sockets (`PermissionError: Operation not permitted`). The same candidate was
rerun with local loopback access. Both runs' started/finished receipts and raw
logs are retained; no production/test changes occurred between them.

The process runners clear inherited environment variables and provide explicit
candidate import paths. No hosted-model credentials are loaded. The optional
Python 3.12 runtime appends an existing same-Python core/test site directory after
its own pandas/NumPy environment. This is not a full upstream Docker environment.

The ordinary working directory also contains unrelated, untracked research and
deliverable Python files with 115 pre-existing lint findings. They are excluded
from this exported repository candidate and are not modified or hidden by a
new Ruff exclusion.

The [TDD evidence](tdd/manifest.json) preserves 34 observed RED/GREEN logs and
supporting receipts. Early failures reflect absent/stubbed new APIs; later
failures reproduce source-binding, baseline-fidelity, report and failure-accounting
defects before their repairs. These logs record development execution; they are
not an independently labeled clinical calibration set. Saved reviewer controls
cover grader failure after a real write, visible source drift, durable initial
identity, and prevention of invalid-provenance negative-control credit.

The [captured nine-execution bundle](../../../reconciliation/20260930/native-verifier-v1/README.md)
has zero model calls, zero clinical/safety criteria and no benchmark score.
All nine expected engineering outcomes matched and all nine optional CSV metrics
completed. No clinical or comparative-value claim follows from these tests.
Formal red team, remote main and manuscript changes remain gated on value evidence.
