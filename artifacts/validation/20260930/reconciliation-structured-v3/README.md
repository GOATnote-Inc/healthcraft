# Structured-command v3 validation checkpoint

This package records related development checks after the one-line filesystem
path-canonicalization repair in the direct model runner. It contains **no model
outcomes** and makes no clinical, safety, ranking or superiority assessment.
This is ordinary engineering validation, not a formal red team.

The [initial integration invocation](integration-tests.log) failed because the
minimal optional Harbor runtime did not include `pytest`. **No tests were
collected**; this was a test-launch failure. The corrected invocation appended
the existing Python 3.12 pytest package path while retaining the optional SDK
runtime first. It passed **163 tests and 8 subtests**. The exact commands,
environment, exit codes and zero-model-call scope are preserved in
[integration-validation.json](integration-validation.json), with the
[corrected log](integration-tests-corrected.log).

The final [isolated lint check](isolated-lint.json) passed over the declared
729-file candidate, with 362 Python files already formatted. The
[log](isolated-lint.log) and [input hashes](validation-inputs.json) preserve that
scope. Raw artifacts, results and unrelated untracked user directories were
excluded; this does not claim those unrelated files passed lint.

The **3,455 passed / 45 skipped** full repository suite ran **before** the alias
repair and remains in the separate [v2 validation package](../reconciliation-structured-v2/README.md).
No new full-suite run is claimed here. Component tests overlap with that earlier
suite, and subtests remain separate; these counts must not be added together.

The [alias preflight](direct-alias-preflight.json) records invocation through the
`/var/...` alias and resolution to `/private/var/...`, with 18 equal before/after
source hashes and zero model calls. The [independent preflight review](preflight-review.json)
records 40 checks with no findings, exact 442-file candidate inventories, and
only `scripts/reconciliation_model_trial.py` changing between v2 and v3. The
reviewed repaired runner SHA-256 is
`5f27ad3c8c38a60c2b5529f4fcf7ae33fef900cefde4889adfa552d6e7e23342`.
Its driver, protocol, prepared-manifest and initial-message identities are
recorded in that receipt. V3 retains the v2 command-format identity and declared
budgets; matching configuration is not proof of identical model outputs.

All eight original receipts/logs are copied byte-for-byte. Absolute paths inside
them record their capture context. [manifest.json](manifest.json) binds each
payload's size and SHA-256 and records original source paths; it excludes only
itself. All copied originals were rechecked unchanged. No source code, previous
artifact, model outcome, runtime, cache or `results/` file was changed or copied
into this checkpoint. Clinical and safety assessment remain unperformed.
