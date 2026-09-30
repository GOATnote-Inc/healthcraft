# Action and grader development captures

These are synthetic, offline engineering reproductions at local revision
`5bc224ff4762b98b12c926780670cd3c17facee9`, captured before the associated
source fixes. They are neither clinical adjudication nor the formal release
red team. No benchmark or superiority claim follows.

- `grader-before.json`: real-tool camel/snake alias behavior, a medication
  assertion mismatch, and malformed engineering-fixture accounting.
- `grader-before-sources.json`: contemporaneous grader input/source hashes.
- `temporal-action-before.json`: original task facts, real tool outputs,
  generated order/task mismatch and selected temporal projection defects.
  Its source hashes were checked before and after the probe.
- `manifest.json`: hashes of byte-identical promoted captures.

The repaired alias/order/fixture paths have dedicated regression tests linked
from [Task validity findings](../../../../docs/TASK_VALIDITY_FINDINGS.md).
The SCJ-012 rubric mismatch and temporal source projection findings remain
open. Existing task definitions, rubric overlays and historical results were
not modified by these repairs. This is exploratory development evidence,
not a preregistered held-out study.
