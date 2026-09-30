# Offline reconciliation explanation validation

The new renderer and CLI turn the bounded diagnostic sidecar into a readable
report with exact input copies and content hashes. They separate acknowledged
writes, notes in final state, actual target reads and the unchanged oracle's
content-qualified checks. They do not create a clinical label or new reward.

| Check | Result | Evidence |
|---|---|---|
| Complete repository suite with local socket access | 3,532 passed; 45 skipped; 274.77 seconds | [Full log](cli/full-test-loopback.log) |
| Diagnostic + oracle + renderer + CLI integration | 141 passed | [Focused log](cli/integration-green.log) |
| Renderer TDD | 31 failed before module creation, then 31 passed on Python 3.10, 3.12 and 3.14 | [Receipt](renderer/receipt.json) |
| CLI TDD | 13 missing-module failures; 13 passes; two additional binding failures; final 15 passes | [Initial RED](cli/red.log), [binding RED](cli/binding-red.log), [final GREEN](cli/final-green.log) |
| Independent renderer checks | 56 static checks; all 50 pointers displayed; 126 overlapping related tests passed | [Review](renderer/peer-review.json) |
| Independent CLI checks | 36 actual-v3/failure checks; 15 tests passed | [Review](cli/peer-review.json) |
| Final import-order supplement | Nine checks and 15 tests passed; non-import AST/function bodies unchanged | [Supplement](cli/peer-review-import-order.json) |
| Isolated `make lint` | Passed on 735 declared inputs; 368 Python files formatted | [Receipt](cli/isolated-lint-final.json), [input hashes](cli/lint-inputs.json) |

Counts overlap and must not be added. The earlier
[diagnostic validation](../reconciliation-diagnostics-v1/README.md) is a separate
frozen package: 27 diagnostic tests plus 68 unchanged oracle tests on three
Python versions, with an independent 71-check actual-evidence review.

The first complete-suite attempt retained 3,464 passes, 33 failures and 35 setup
errors because the filesystem/network sandbox denied loopback socket binds.
Its [unaltered log](cli/full-test.log) remains present. Rerunning with authorized
local socket access passed the complete suite; no code correction was needed
for those failures. Skips remain skips.

The first isolated lint run found one import-group issue: Ruff had classified
the not-yet-created renderer as third-party while the CLI was being developed.
Sorting those same imports fixed it. The final broader workspace lint still
reports [115 pre-existing errors](cli/root-lint-final.log) in unrelated untracked
archive/deliverable files. Those files were not changed. The isolated candidate
excludes those directories and raw artifacts/results; it is not a claim that
the whole working directory is lint-clean.

## Bound source and derived reports

The [four actual-attempt reports](../../../reconciliation/20260930/local-model-pilot-v3-explanations-v1/README.md)
were generated offline before the import-only correction. Their source inventory
matches the retained [earlier CLI bytes](cli/cli-before-import-order.py.txt), as
does the original CLI peer receipt. The final source snapshots are in `source/`.
The import-order supplement verifies identical non-import AST and function
bodies. The full successful suite uses the final source. Existing reports were
not regenerated or silently replaced.

All four derived oracle results equal the original complete result objects;
all 181 original cohort payloads were rechecked unchanged. The export refuses
existing output directories and mismatched prior-verification objects, checks
the explanation's canonical input/oracle bindings, preserves strict JSON types,
and writes a completion manifest only after its payload files. A simulated
payload-write failure retained a partial directory without a manifest, and a
retry refused that directory without changing it.

The [copy inventory](copied-originals.json) records exact temporary source paths
and hashes; those paths are historical provenance, not portable instructions.
Executable checker/driver snapshots use `.py.txt`. The package manifest hashes
every payload and excludes only itself. The CLI source inventory identifies
Python source, not a complete reproducible runtime. Hashes identify content;
they do not authenticate execution or independent review.

## Remaining value evidence

HTML validation was static (standard-library parsing and text inspection).
Browser visual QA, accessibility evaluation and independent user testing were
not performed. The renderer displays source pointers as inert text. Explanation
coverage remains limited to writes/storage/readback/exclusions; observation and
conflict content, retrieval coverage and clinical validity remain unassessed by
this sidecar. The full original oracle remains authoritative for its contract.

The [next-value experiment proposal](next-value-experiment.md) is planning only:
no participant data, registered protocol, fresh held-out casebook or clinical
review was acquired. These engineering checks and four exposed development
attempts do not establish user time savings, healthcare benefit or superiority.
The value → formal red team → remote main and manuscript gate remains open.
