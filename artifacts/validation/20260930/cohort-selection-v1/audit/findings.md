# Bounded frontier cohort selection audit

Ordinary development review; no repository edits, provider access, model calls, or formal red-team work. Reproduction scripts use real task parsing, world preparation, capture, and summary paths. Client construction, preflight, and agent execution are replaced by offline stubs. Sources are hash-bound in `reproduction.json`; HEAD was 09e48c11f149735533f801f78ba7a38b83fe8384 with the current authorized entrypoint working changes.

## 1. Invalid or incomplete requested cohorts reach provider boundaries

`orchestrator.py:346-367` constructs explicit selection using a set, appends every matching file, breaks on list length, never checks missing IDs, and scans only `.yaml`. The `all` path calls `loader.py:166`'s warning-and-skip loader. Selection follows results directory creation and client/capability construction (`orchestrator.py:280-298`). CLI `_api_preflight` precedes all task selection (`1078-1099`). The actual cloud preflight makes a chat call; no such call was made in these probes.

Confirmed cases:

- Requested `CR-001,DOES-NOT-EXIST`: executes CR-001 once and emits a one-task summary without any missing-ID warning/error.
- Two sorted CR-001 files followed by CR-002, requested `CR-001,CR-002`: executes CR-001 twice, never executes CR-002, then encounters the existing immutable trajectory path and returns a persistence error. The duplicate was not rejected before execution.
- `all` with one valid file and one malformed file: warning only, then a reduced one-task summary.
- Explicit `CR-001,CR-002` with malformed CR-002: silently executes only CR-001.
- Explicit `CR-001,CR-002` with valid `b.yml`: silently executes only CR-001, although `all` supports `.yml`.
- Public CLI with wholly missing ID: calls preflight stub, then constructs client stub, then returns exit 1. Validation is too late even for a wholly invalid cohort.

Narrow next TDD contract: resolve and validate the entire requested roster before output creation, client construction/capability checks, cloud preflight, or any trial. Use one strict selection helper in both API and CLI. Support `.yaml` and `.yml`; reject missing IDs, duplicate authored IDs, malformed authored tasks for `all`, malformed explicit requested tasks, and empty explicit ID tokens. Do not infer discovery completion from selected list length. Decide and test explicit repeated IDs (reject clearly or documented single selection), and validate missing IDs before applying an intentional `max_tasks` cap. Include positive exact comma-separated selection and unchanged deterministic selection order/resume controls.

## 2. Direct API nonpositive trials create empty grading-complete summaries

`run_frontier_evaluation` has no direct positive-integer trial guard. Both `trials=0` and `trials=-1` construct a client and save summary with `total_tasks=1`, `total_runs=0`, `error_runs=0`, `pass_rate=0.0`, and `grading_complete=true`. No model call was made in either probe. CLI argparse already rejects these values, so this is an API-path discrepancy.

Narrow TDD contract: strict positive integer `trials` (exclude bool) before side effects in both entry paths. Validate `max_tasks` when supplied similarly; preserve positive valid behavior. Rejection should leave no output or summary and touch no provider factory/preflight.

## 3. CLI runtime-error exit semantics need an explicit policy

One actual captured offline `RuntimeError` from the agent stub produces `error_runs=1`, `grading_complete=false`, a saved error trajectory, and public CLI exit 0. An independently completed synthetic pattern-criterion failure produces `error_runs=0`, `grading_complete=true`, `passed=false`, and exit 0. The latter is an ordinary evaluation outcome, not an infrastructure failure, and should not be relabeled as an execution error.

This is a confirmed behavioral distinction, not an instruction to make every failed rubric exit nonzero. If the CLI promises execution-success exit semantics, add a targeted contract where infrastructure/grader/transport errors return nonzero after retaining the printed summary and all captured evidence, while completed ordinary rubric failures continue returning zero. Do not use `total_passed`/pass rate to decide process success. Existing top-level error dictionaries already exit 1.

## Evidence

- `reproduce.py`, `reproduction.json`, `reproduction.log`: nine frozen-input cases, zero model calls.
- `clinical-failure-control.py`, `ordinary-rubric-failure-control.json`: independent completed synthetic rubric-failure control, zero model calls.
- No source or immutable result files were modified. Temporary output directories are recorded in the receipts.
