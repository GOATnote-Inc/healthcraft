# Optional HealthAgentBench CSV verifier

This adapter runs one unchanged Microsoft HealthAgentBench verifier on
**HealthCraft-authored synthetic CSV inputs**. It is a secondary compatibility
metric. It cannot evaluate source interpretation, a persisted note, treatment
appropriateness, clinical safety, or readiness. It is not an official
HealthAgentBench benchmark result or evidence of comparative superiority.

## Attribution and exact source

- Repository: [microsoft/HealthAgentBench](https://github.com/microsoft/HealthAgentBench).
- Revision: `bcbb8085fd549469e2dc7455f4bfd68a1b98895a`.
- [Original verifier](https://github.com/microsoft/HealthAgentBench/blob/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/tasks/ehr_data_quality_task_combined/tests/harbor_evaluator.py).
- `harbor_evaluator.py.txt`: byte-identical source, stored with a text suffix so
  repository formatters do not modify it. SHA256:
  `7ce0c9808afb5efb031c04e535e22f4fd8cad093b6bd500681c87fef2a8fde5d`.
- Adjacent `LICENSE`: byte-identical Microsoft MIT license, separate from
  HealthCraft's Apache license. SHA256:
  `646f8936b8ddcd14e13e578ff6857e368780b0d1a4f6066bee89211923a373e2`.
- `provenance.json` retains the exact upstream paths and Git blob identities.
  The wrapper pins its bytes as well as the code and license.

No upstream patient records, labels, data-stage script, bootstrap, model or
Harbor dependency is included or invoked. The upstream bootstrap uses
patient-derived data and is outside this synthetic-only integration.

## Callable contract

Use a source checkout; the optional vendored files are outside the installed
core package. The core requirements remain unchanged. Importing the wrapper
requires only the standard library; running the verifier requires pandas.

```python
from pathlib import Path
from healthcraft.reconciliation.upstream import run_upstream_verifier

result = run_upstream_verifier(
    Path("agent-output/flagged_rows.csv"),
    Path("coordinator-only/synthetic-labels.csv"),
    Path("new-exclusive-trial/upstream-verifier"),
    turn_count=recorded_turn_count,
)
```

`turn_count` must be an actual nonnegative integer, including zero. It is always
passed explicitly; upstream ambient turn-count files are never consulted.
An existing output path is rejected, even an empty directory. Invalid caller
turn counts raise before output creation. Every accepted invocation records
one scheduled evaluation, including dependency, label or grader failures.

The output directory contains:

- `report.json`: status, separate upstream reward/metrics, denominator, declared
  turns, wrapper/source/license provenance, Python/pandas versions, input hashes
  and raw-artifact hashes. It does not hash itself.
- `inputs/`: exact input byte snapshots when available. A missing submission is
  left missing for the unchanged upstream verifier to classify.
- `vendor/`: verified source, license and provenance snapshots used for that run.
- `upstream/`: unchanged `metrics.json`, `reward.txt` and, when upstream emits it,
  `verifier_error.txt`. Partial files survive grader failures.

The wrapper validates source hashes before execution and again afterward,
loads verified source bytes through `SourceFileLoader` without cached bytecode,
and checks input/source snapshots for drift. It checks agreement between the
returned reward, raw reward/metrics and declared turn count. These are local
content bindings, not independent execution attestation. This function does
not isolate hidden labels from an agent; the calling runner must do so.

| Status | Upstream reward | Meaning |
|---|---|---|
| `completed` | 0 or 1 | The CSV metric ran, including valid empty submissions |
| `invalid_submission` | 0 | Upstream emitted a submission diagnostic; raw output retained |
| `invalid_labels` | null | Missing/malformed coordinator labels; never an agent failure |
| `unavailable_dependency` | null | pandas could not be imported |
| `provenance_error` | null | Verifier/license/provenance or snapshots failed binding |
| `grader_error` | null | Unexpected import, execution, output or snapshot-preparation failure |

Unhandled upstream exceptions remain grader errors even if a particular agent
CSV provoked them. No fabricated zero replaces a failed grader. The report's
`clinical_assessment`, `persistence_assessment` and `official_benchmark_result`
are always false. Raw outputs are retained even when rejected for use.

## Synthetic label contract and metric limits

The coordinator supplies UTF-8 CSV with exactly these unique header names:
`table,_row_id,cluster_id,error_family,error_subtype`. Column order may vary.
At least one row is required; cells must be nonempty, unpadded and free of NUL.
Duplicate `(table,_row_id)` labels, inconsistent row widths, and conflicting
family/subtype values within a cluster are rejected before grading. This is
stricter coordinator-input validation than the upstream loader; it does not
rewrite the verifier or its score.

For the new reconciliation fixture, two source assertions share one explicitly
authored disagreement cluster:

```csv
table,_row_id,cluster_id,error_family,error_subtype
treatments_given,SRC-A04,EVENT-A01-reported-status,source_disagreement,opposing_reported_status
treatments_given,SRC-A05,EVENT-A01-reported-status,source_disagreement,opposing_reported_status
```

These labels identify disagreement; neither assertion is designated the false
clinical fact. Flagging **either** source catches that cluster. The unchanged
verifier deduplicates submitted row pairs, measures cluster recall and row
precision, and returns 1 only when recall is at least 1 and precision at least
**0.01**. One correct flag among 100 unique flags can therefore pass. Its function
docstring contains an obsolete `>0.5` precision threshold; the executable
constants and behavior are preserved. Keep the independent source-and-persistence
oracle outcome separate, and retain all planned trials without best-of selection.

## Isolated dependency and test procedure

The tested target is Python 3.12 and pandas 3.0.1.
`requirements-verifier.txt` pins the resolved four-package closure and exact
wheel hashes for **macOS arm64 / CPython 3.12**: pandas 3.0.1, NumPy 2.5.3,
python-dateutil 2.9.0.post0 and six 1.17.0. This is a small verifier runtime,
not a recreation of the upstream Docker image (which pins NumPy 2.4.2 and
includes unrelated data packages). Other platforms require a separately
reviewed resolution; do not remove hash checking to force installation.

```bash
python3.12 -m venv /tmp/new-healthcraft-verifier-runtime
/tmp/new-healthcraft-verifier-runtime/bin/python -m pip install \
  --require-hashes --no-deps -r integrations/healthagentbench/requirements-verifier.txt
```

The wrapper records other Python/pandas versions if deliberately used;
`target_runtime_matches` means only Python 3.12 plus pandas 3.0.1, not full
upstream environment equivalence. Install no packages in the core environment
for this integration.

Core tests skip actual-source executions when pandas is unavailable:

```bash
python -m pytest tests/test_reconciliation/test_upstream_verifier.py -q
```

Actual-source tests require pandas and pytest in a compatible isolated testing
runtime. Development validation used the new optional Python 3.12 runtime and
appended an existing Python 3.12 test environment's `site-packages` *after* its
own site directories to obtain pytest; no test package was installed. This
preserves the optional runtime's pandas/NumPy precedence. Seven tests execute
the unchanged source, covering either member of a disagreement cluster,
malformed/missing submission, valid empty output, duplicate collapse and the
1% precision floor. Other tests use an explicitly identified unit stub to test
wrapper failure accounting; they are not evidence of upstream runtime behavior.
