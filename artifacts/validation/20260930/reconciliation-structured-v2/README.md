# Structured-command v2 development validation

This package records ordinary TDD, bounded peer review and source preparation for
`healthcraft-reconciliation-command/v2`. It contains **no model-trial evidence**,
clinical assessment or benchmark score. The protocol is an exploratory follow-up
to the observed [v1 format failures](../../../reconciliation/20260930/local-model-pilot-v1/README.md),
using an open synthetic fixture. It is not an externally registered or held-out
comparison, a formal red team, or evidence of clinical or product superiority.

The intended model-wire change is an opt-in native Ollama `format` JSON Schema
for the existing call-or-finish envelope. Initial messages, five public tool
schemas, model identities and budgets stay fixed. Tool parameters remain an
unrestricted object. Strict parsing, explicit completion, actual tool execution
and the independent source/persistence oracle remain authoritative; valid JSON
or `finish` alone is not successful reconciliation. Coordinator source guards
and failure accounting were strengthened separately. See the captured
[protocol](protocol.json) and [primary-source research](research.md).

## Recorded checks

| Check | Final observation | Evidence |
|---|---|---|
| Repository test suite | 3,455 passed; 45 skipped; 267.93 seconds | [Full log](full-test.log) |
| Shared controller | 79 passed on each of Python 3.10, 3.12 and 3.14 | [Receipt](controller/receipt.json) |
| Direct/Harbor adapters | 80 passed, 8 subtests passed, 1 warning using actual Harbor 0.8.0 SDK with fake transport | [Receipt](adapters/validation.json), [log](adapters/final-green.log) |
| Controller peer review | 26 checks, no blocking findings | [Review](controller-peer-review.json) |
| Adapter peer review | 42 checks, no failed checks; 24 selected regression tests passed | [Review](adapter-peer-review.json), [test log](adapter-peer-tests.log) |
| Temporary failure-accounting helper | 11 passed on each of Python 3.10, 3.12 and 3.14 | [Validation](failure-accounting-validation.json) |
| Extracted coordinator controls | 9 passed on Python 3.12 and 3.14 | [Final review](driver-review-v2.json) |
| Isolated candidate lint | Passed over 729 declared input files; 362 Python files formatted | [Receipt](isolated-lint.json), [log](isolated-lint.log) |

Counts overlap and must not be summed. Component, peer and full-suite runs reuse
many tests; subtests are reported separately. The temporary helper/driver tests
live outside the repository test tree. Skipped tests and the retained SDK warning
are not represented as passes. All model/provider responses in these development
checks are stubs; no live inference or Docker execution occurred in the peer or
extracted-driver controls.

The full log records `.venv/bin/pytest tests/ -q`. Adapter command receipts retain
exact interpreter arguments and environment overrides. The actual optional SDK
runtime was kept first on the import path, with existing Python 3.12 pytest
packages appended. Helper/driver validation receipts retain their commands.
The package does not contain or install either runtime.

## Failures and corrections retained

- Controller RED: 29 failed and 50 passed before implementation. Adapter RED
  includes an earlier 10-failure helper-unavailable phase, then two focused
  validators rejecting the new sixth configuration field.
- The helper's initial RED is a missing-module collection error before its
  implementation. Its later tests cover preserved raw results, partial/malformed
  evidence, finite JSON, repeat finalization and the full scheduled denominator.
- The controller peer receipt describes a checker correction from exact exception
  class matching to `isinstance(ValueError)` for `JSONDecodeError`; this was not
  a product defect or product-source change.
- The [initial generated-driver check](generated-driver-review.log) retained
  7 passes and 1 hash mismatch while the authorized import-order correction
  changed the driver. [Initial preparation](preparation-initial.json) and
  [corrected preparation](preparation.json) are both preserved. Final checks use
  the consistent corrected pair and pass.
- Component `make lint` logs retain 115 unrelated archive/deliverable errors from
  the broader working directory. The separate final isolated candidate lint
  passed; this is not a claim that those unrelated files were fixed.

## Source and evidence boundaries

The [initial driver review](driver-review.json) identified setup-failure accounting
and launch source-binding gaps. The [final review](driver-review-v2.json) checks
five kinds of candidate/manifest drift, schema mismatch, project-import failure
and a stubbed image-build failure. Each failure accounts for all four scheduled
attempts without inventing oracle results or tool outcomes. Existing partial
execution remains unknown. The parent timeout supervises its direct child and
is not a guarantee that every descendant or in-flight Ollama request terminates.

The corrected driver SHA-256 is
`45ffb4f3c0a29819f3bb083d7ba5f9faf199ac5cdb72f29df619e3254937e62b`.
The [runtime candidate manifest](source-identity/candidate-manifest.json) binds
442 files; the [validation input manifest](validation-inputs.json) binds the
broader 729-file candidate used for isolated lint. These are distinct scopes.
Python helper, test, reviewer and coordinator snapshots use `.py.txt` filenames
and preserve their exact original bytes. Absolute paths inside original receipts
are historical provenance, not portable execution instructions.

[manifest.json](manifest.json) hashes every payload file and records each copied
file's original path, size and SHA-256. It excludes only itself. All copied
originals were rechecked unchanged. No existing artifact or `results/` file was
modified, and no model evidence, runtime, cache, model weight or downloaded
vendor source is included. The value-comparison, formal-red-team and
remote/manuscript release gates remain separate and open.
