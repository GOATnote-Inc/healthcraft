# Structured-decoding checkpoint

`inputs.json` binds 729 source, test and documentation files for this local
checkpoint. The isolated candidate passes `make lint`; raw artifacts, immutable
results and unrelated untracked user directories are excluded. The separately
developed explanation prototype is also excluded from this checkpoint.

The structured-decoding implementation passed the full suite: **3,455 passed,
45 skipped**, recorded in the [v2 validation package](../reconciliation-structured-v2/README.md).
Subsequent real local attempts exposed a macOS path-alias preparation defect.
Its one-line repair passed [53 focused tests](../reconciliation-path-alias/README.md)
and the final related integration run passed **163 tests and 8 subtests** in
the [v3 validation package](../reconciliation-structured-v3/README.md). The earlier
full-suite count is not presented as a rerun after that repair.

The three separately frozen model cohorts retain format, setup and workflow
failures. The final cohort establishes the exercised local transport behavior
on one open synthetic case; no note satisfies the independent reconciliation
contract. No clinical or superiority claim, formal red team, remote publication
or manuscript change follows from this checkpoint.
