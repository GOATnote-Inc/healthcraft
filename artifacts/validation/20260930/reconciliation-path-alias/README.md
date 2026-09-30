# Direct-runner source path alias repair

This is a development validation record for the one-line source-identity repair in
`scripts/reconciliation_model_trial.py`. On macOS, a script invoked through `/var`
can have an unresolved `__file__` while its computed repository root resolves to
`/private/var`. The old `relative_to(ROOT)` then failed during preparation before
any model request. The repair resolves the script path before computing its
repository-relative source hash; paths genuinely outside the root still fail.

The existing [v2 cohort](../../../reconciliation/20260930/local-model-pilot-v2/)
remains a separate, unchanged record. This test package does not replace those
attempts or report a model, clinical, or comparative result. No inference was
performed for the repair tests.

- [RED log](red.log): three failing alias regressions and one passing
  outside-root rejection control before the production repair.
- [GREEN log](green.log): all 53 direct-runner tests passed after the one-line
  repair, using the existing isolated Harbor Python 3.12 runtime.
- The portable tests import the actual script through a temporary checkout
  symlink, verify exact relative hashes and drift detection, retain the failed
  attempt denominator, and reject both a directly outside-root script and a
  symlink that resolves outside the root.
- [Scoped Ruff](ruff.log), [format](format.log), and
  [diff whitespace](diff-check.log) checks passed.
- [Repository lint](make-lint.log) exited 2 with 115 pre-existing violations in
  `.research-archives/`; scoped changed-file checks passed. This package does
  not claim a clean repository-wide lint run.

[validation.json](validation.json) records the exact commands, environment
overrides, exit codes and final source/test hashes. [red-command.json](red-command.json)
records the pre-repair test command. Pytest was made available by appending the
existing Python 3.12 test environment's site-packages; it was not installed into
the optional Harbor runtime. Plugin autoload was disabled, causing the recorded
unknown `asyncio_mode` configuration warning.

All eight source logs/receipts were copied byte-for-byte from the repair's
private temporary directory. [manifest.json](manifest.json) hashes the copied
files and this README, and binds the production and test revisions. It excludes
itself. No source, historical result, frozen candidate, or driver was modified
when this package was assembled.
