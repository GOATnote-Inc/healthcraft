# Action and independent-review engineering checkpoint

Validation on 2026-09-30 used an export of the explicitly staged repository
source. The manifest records tested source hashes, verified again against the
working source after completion. Repository sources are bound; this does not
authenticate third-party runtime packages or external clinical claims.

| Check | Result |
|---|---|
| Full `make test`, Python 3.14.3 | 2,375 passed; seven optional-dependency skips |
| Changed-path compatibility, Python 3.10.18 | 248 passed |
| Changed-path compatibility, Python 3.12.8 | 248 passed |
| Actual optional NeMo SDK, Python 3.13 | 36 native-adapter tests and eight resource tests passed |
| `make lint` on tracked export | Passed; 311 Python files formatted |
| `make smoke` | 48 checks passed |
| `make preflight` | Passed; structural checks only |
| Engineering grader fixtures | 55 cases, zero harness errors or label mismatches |

The NeMo native test runner used the pinned runtime's dependencies and appended
the existing pure-Python pytest installation after them; plugin autoload was
disabled. Its three warnings are an unknown pytest option and two dependency
deprecations. The stdlib resource tests also emitted dependency deprecations.
The full core suite's optional skips do not stand in for these SDK checks.

The ordinary working-directory lint command still sees 115 unrelated findings
in untracked research/deliverable files. Those files were neither modified nor
included in this checkpoint. The clean export ran the actual repository lint
target; its log is retained rather than claiming the original directory is clean.

Test-driven repairs cover faithful persisted orders, registered tool aliases,
strict regression-fixture types and safety labels, missing provider termination,
missing-judge accounting, and dynamic-state error checkpoint preservation.
New review tooling captures the actual model interface and effective rubric,
masks structured identities, keeps all supplied attempts, binds both packet
renderings, and retains pending/unassessed opportunities in submission receipts.

A separate [single local Nemotron attempt](../../../local-order-probe/20260930/order-transport-v1/README.md)
completed the restricted literal-order integration probe with two responses and
one tool invocation. All 347 captured source hashes and model/runtime identities
remained unchanged. A blank, one-opportunity review packet was generated from
that captured trajectory as a post-run engineering demonstration. No human
review submission, independent adjudication or clinical label was produced.

All of this is development evidence. Comparative superiority, independent
clinical calibration and patient benefit remain unestablished. The
[release sequence](../../../../docs/RELEASE_EVIDENCE_PLAN.md) is unchanged:
value evidence first, formal red team afterward, then remote/main and manuscript
publication. Nothing here advances those gates automatically.
