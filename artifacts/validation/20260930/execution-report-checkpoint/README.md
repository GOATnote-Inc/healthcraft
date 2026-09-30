# Execution, action and report checkpoint validation

Engineering validation on frozen staged exports based on `5cd2955`,
2026-09-30. No historical results, task YAML, rubric overlays or verdict
fixtures changed. No comparative-value study, clinical validation, formal
red team, remote update or manuscript revision is represented here.

| Check | Observed result |
|---|---|
| Final actual `make test` | 2,982 passed, 7 skipped; 265.98 seconds pytest time |
| Final actual `make lint` | Ruff check and format passed; 333 Python files |
| Python 3.10 focused compatibility | 999 passed, 32 skipped |
| Python 3.12 focused compatibility | 999 passed, 32 skipped |
| Actual optional NeMo Gym SDK, Python 3.13 | 44 passed; two dependency deprecation warnings |
| `make smoke` | 48 checks passed; 205 tasks, 24 tools |
| `make grader-goldset` | 55 engineering fixtures; zero errors or verdict mismatches |
| Captured action replay | Three reproduced false passes corrected; three controls retain expected outcomes |
| Real note/readback replay | Changed text/target rejected; identical retry creates one note; distinct key permits intended write |
| Free local Nemotron integration | One attempt completed, two responses, one persisted synthetic order; zero clinical/safety criteria assessed |

## Candidate binding and preserved failures

`initial-candidate.json` binds the first export. Its full suite recorded
**2,981 passed, 7 skipped, one failed**: an older test explicitly expected
changed priority/indication to receive a deduplicated success. The same
expectation failed both initial compatibility runs (998 passed, 32 skipped,
one failed). These logs and process receipts remain intact.

The test was corrected to require an identical request's successful retry,
a changed request's `idempotency_conflict`, and unchanged persisted order/task.
No production code changed between the first and final exports. Among the
579 declared code/config/prompt/test/launch inputs, only
`tests/test_mcp_tools/test_order_action_fidelity.py` differs. Final full,
compatibility and lint runs are in `final/`; other successful checks still
bind the identical production inputs from the initial export.

`final-candidate.json` and `manifest.json` bind the final input hashes and
validation artifacts. The actual `make lint` ran in a tracked-index export:
the workspace also contains unrelated, untracked research/deliverable files
with 115 existing lint findings, which were neither staged nor edited.

`validation-runner.py.txt` is the exact outer runner. Process receipts record
commands, clean environment, source directory, wall-clock duration and exit
status. Offline checks used no model or provider APIs; the separately bounded
[local Nemotron probe](../../../local-order-probe/20260930/execution-repair-v2/README.md)
used only the installed loopback model and is captured in its own manifest.
No paid calls, downloads or automatic inference retries were made.

The SDK tests imported the existing optional NeMo Gym checkout pinned at
`82e1834ccf2dd578af26a1abc686c15e17569594`; no external comparator task ran.
Skipped tests and deprecation warnings are retained in logs. The 55 grader
fixtures and all test counts are software regression evidence, not independent
clinical calibration or population error estimates.

[Development reproductions](../../../evaluation-integrity/20260930/execution-report-v1/README.md)
retain pre-fix behavior, failing TDD controls, ordinary independent review,
repaired action/note replay and the offline report fixtures. Hashes establish
content identity and drift checks, not external authenticity or reviewer
credentials. Publication remains governed by the
[release evidence plan](../../../../docs/RELEASE_EVIDENCE_PLAN.md).
