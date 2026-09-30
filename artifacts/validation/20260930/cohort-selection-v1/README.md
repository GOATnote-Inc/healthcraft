# Cohort selection and execution status validation

A request for `CR-001,MISSING` previously executed only CR-001. Duplicate
authored IDs could satisfy the search's early stop, execute a task twice, and
omit another requested task. Invalid definitions and `.yml` files could also
disappear from explicit selections. A direct API call with zero trials could
save an empty summary marked grading-complete. These behaviors are captured
in the [original offline audit](audit/findings.md).

Both public CLI and API now validate the supplied task directory and the
complete requested roster before creating run output or accessing providers.
The opt-in strict loader rejects parser/load failures, empty criteria,
unsafe task/category path components, duplicate task IDs and IDs that collide
when compared without case. Explicit lists reject unknown, repeated or empty
IDs. Trial/cap counts must be positive integers; the API rejects booleans too.
Both `.yaml` and `.yml` files work. All requested IDs are checked before an
intentional task cap, and execution uses task-ID order.

The CLI prints a returned summary before exiting nonzero for a top-level
error or recorded execution errors. Actual raised and returned agent errors
retain their captures and remain nonzero on cached resume. Completed rubric
failures and deliberately ungraded diagnostics still exit zero when execution
itself succeeds. Neither exit status establishes clinical correctness or
grading completeness.

## Evidence

| Check | Result |
|---|---|
| Final full suite with local socket fixture access | 3662 passed, 58 skipped in 273.02s (0:04:33); [log](validation/full-suite.log) |
| Cohort TDD | 44 initial failures; four empty-rubric failures; two case-collision failures; [receipt](cohort/receipt.json) |
| Final focused cohort/exit/resume/loader checks | 90 passed on each Python 3.10/3.12/3.14; [receipt](cohort/receipt.json) |
| Broader compatibility before the additive case-collision guard | 640 passed on each Python 3.10/3.12/3.14; [logs](cohort/compat-final-py314.log) |
| CLI status and retained evidence | Four failures before the change; all nine final exit tests included above; [receipt](cli/receipt.json), [RED](cli/red-capture.log) |
| Independent development review | 80 boundary checks and 95 focused tests passed; [review](peer/peer-review.json), [checks](peer/boundary-results.json) |
| Public subprocess rejection | Missing ID rejected before API-key lookup/preflight despite `--max-tasks 1`; no output directory; [receipt](validation/invalid-cli.json) |
| Isolated `make lint` | Passed on 741 declared inputs, 374 Python files; [receipt](validation/lint-receipt.json), [hashes](validation/lint-inputs.json) |

Counts overlap and must not be added. The broader workspace `make lint` still
reports 115 existing errors in unrelated untracked archive/deliverable files
([log](validation/root-make-lint.log)). The isolated snapshot excludes those
files and immutable raw artifact/result collections.

Existing unit-test loader stubs now accept the strict keyword. Two vendor-guard
fixtures now select a valid cohort, so they reach the guard they test; their
original missing/empty rosters correctly reject earlier. The initial failures
are retained. An intermediate command named a nonexistent loader test file
and ran no tests; its log is retained alongside the corrected successful runs.
No recorded verdict fixture or existing result was changed.

The independent checks cover invalid requests preserving existing output,
caps that cannot hide invalid entries, expansion/reduction of selected cached
cohorts, identical resume, changed-task refusal and append-only error retries.
Resume probes hold environment identity constant to isolate cohort semantics.
They use offline agent/client stubs and synthetic in-memory worlds.

## Scope and provenance

Strict cohort loading uses the existing task parser plus the stated integrity
checks. It is not full authored-task JSON Schema validation, clinical
satisfiability validation, or protection against concurrent filesystem
mutation. Legacy lenient loading and the general evaluator's empty-rubric
semantics remain unchanged outside strict evaluation selection.

The [checkpoint](checkpoint.json) binds all changed files to the parent commit.
[Original copy records](copied-originals.json) identify selected temporary
evidence by path and content hash. Some intermediate logs referenced inside
original receipts remain outside this compact package. Checker scripts are
saved as `.py.txt`; paths in logs are historical, not portable commands.
The manifest hashes every package payload except itself. Hashes identify
bytes; they do not authenticate reviewers or execution.

No model calls, paid services, clinical review, formal red-team work, remote
publication or manuscript edits were performed for this change. These repairs
improve evaluation integrity but do not demonstrate superior end-user or
healthcare value. The requested value → formal red team → remote main and
paper release order remains in force.
