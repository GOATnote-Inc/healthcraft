# Partial evidence preserved separately from contract failures

`REC2-002/medgemma` retrieved all five authored source rows before writing. Its note includes all three required current-encounter source IDs with exact raw source objects and both prior-encounter exclusions exactly. Its three observation descriptors still have incorrect `source_path` values, and it does not perform the requested post-write readback. This is a path/traceability and readback failure, not evidence that those raw values or exclusions were changed.

`REC2-004/nano` retrieved all five authored source rows, included the five required current-encounter source IDs with exact raw source objects, and retained the correct three-member unresolved conflict group without majority resolution. Its five observation paths are wrong, it adds an invalid exclusion object for the current encounter without a source ID, and it does not read the note back. The conflict group itself is correct under the mechanical source contract.

Across the 14 strictly parseable stored notes, 44 target-row descriptors differ only in `source_path`; their raw source rows match exactly. Nine target rows are omitted across four notes. Four prior-encounter rows are copied exactly but misattributed as current-encounter observations across two notes. These are distinct conditions. The one duplicate-key note is not assigned a per-field content verdict by the strict parser. None of these comparisons establishes whether an authored clinical assertion is true.

Exact expected and observed objects, note IDs, source references, and evidence pointers are retained in `roster-diagnostics.json`. The two selected cases below are bound to those original rows in `partial-evidence.json`.
