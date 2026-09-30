# Local engineering checkpoint

The [validation record](validation.json) binds source/runtime hashes, logs,
the pre-validation staged patch, and explicit limitations. It does not establish
clinical validity, comparative value, or release approval.

| Check | Result |
|---|---|
| Full suite, Python 3.10 | 2,024 passed; 33 skipped |
| Full suite, Python 3.12 | 2,024 passed; 33 skipped |
| Full suite, Python 3.14 | 2,069 passed; 2 skipped |
| `make lint`, clean staged export | Pass; 287 Python files formatted |
| `make smoke` | 48 passed; zero failures |
| `make preflight` | Pass; structural checks only |

The minimal 3.10/3.12 environments do not have all optional SDK and plotting
dependencies; skips are not passed tests. The full checkout also contains
unrelated untracked research archives and deliverables that produce lint
errors. The staged export checks the repository changes without incorporating
those files. Captured comparator scripts remain byte-identical evidence and
are excluded from formatting in `pyproject.toml`.

New regression tests reproduced missing RL patient injection, failed-reset
episode reuse, shared mutable trajectory context, incorrect Gemini function
response names, missing roster records, and ungraded diagnostics leaking into
score/report/export paths before implementation. The reference controller
retrieved 33 roster members in 66 calls. A single native Nemotron task trial
remained incomplete after 25 rounds. A separate pinned NeMo Gym counter probe
also remained incomplete under different settings. Neither is a comparative
healthcare result.

The offline HTML evidence review was generated and checked structurally. Visual
and interactive browser QA remain unverified because the browser URL policy
blocked the earlier local preview; no alternate surface was used.

Historical results and task definitions are unchanged. No formal red-team
review, remote push, manuscript edit, figure generation, or arXiv submission
was performed for this checkpoint. The release order remains governed by
[the value-evidence plan](../../../../docs/RELEASE_EVIDENCE_PLAN.md).
