# Empty-rubric and process-weight development checkpoint

Two assessment defects are repaired with failing tests captured before the
production changes. An undefined rubric previously produced a passing task in
several grading paths. Separately, training could award a process bonus while
`w_process=0` when a nonempty rubric had no available clinical reward term.

Assessment entry points now reject missing or empty task criteria with a
configuration error. Direct evaluation, replay, standalone grading, simple-evals
and RL reward/episode entry points share the guard. Standalone and simple-evals
validate the selected authored rubric cohort before judging/writing or applying
the replay limit. Legacy task loading remains permissive for inspection.
All 205 canonical tasks already have nonempty rubrics; this defect does not
establish that the published corpus's existing outcomes were affected.

Training now preserves the configured process weight when both clinical terms
are absent or abstained. The raw capped process signal remains diagnostic.
Existing clinical-to-clinical weight redistribution and the safety/restraint
gate remain unchanged. The Eq. 1 reduction source is unchanged, and historical
replay verdict tests pass. A prior environment fixture now has an explicit
synthetic criterion because training episodes require an assessable task.

## Validation

- Core guard RED: 8 failed, 3 passed; focused GREEN: 105 passed; replay checks: 70 passed.
- Standalone/simple-evals RED: 16 failed, 2 passed; compatibility: 103 passed on each of Python 3.10, 3.12 and 3.14.
- RL guard RED: 20 failed, 2 passed; compatibility before the process change: 163 passed on each runtime.
- Separate process-weight RED: 13 failed, 25 passed; focused GREEN: 38 passed; combined RL compatibility: 201 passed on each runtime.
- Independent peer review: 24 cases passed on each runtime, including eight process-weight checks; no production findings.
- Full suite: 3751 passed, 58 skipped in 270.27s (0:04:30).
- The shell wrapper failed after the suite completed because its status variable is reserved in zsh; the full test log and invocation receipt preserve this bookkeeping error separately.
- Isolated `make lint`: 745 inventoried inputs, 378 Python files; passed. Workspace `make lint` retains 115 pre-existing unrelated archive violations.

Receipts bind source and evidence hashes. The RL guard receipt intentionally
records the intermediate reward source before the separate process-weight
correction; the process receipt and final checkpoint bind the final source.
Early checker/fixture setup mistakes are retained and identified in receipts;
the reported RED counts use corrected tests run before production fixes.

No model or hosted judge calls were used. Tests used synthetic fixtures and
local server fixtures. Existing results, task definitions, paper and remote were
not changed. This is ordinary development validation, not the requested formal
red team. Comparative end-user and healthcare value remains unproven; the
formal red team, remote-main update and manuscript revision remain deferred.
