# Reconciliation transport validation checkpoint

This package preserves ordinary TDD and integration-test evidence from the September 30 transport/controller work. It contains byte-identical copies of selected temporary logs and receipts; originals remain untouched. It contains no live-model pilot results, model weights, downloaded vendor code, installation caches, credentials or files copied from `results/`.

The final repository test run reports **3,413 passed, 40 skipped** in [full-suite/final-rerun.log](full-suite/final-rerun.log). The preceding run is retained in [full-suite/initial-failure.log](full-suite/initial-failure.log): 1 failed, 3,411 passed, 40 skipped. Its stale test expected an unknown tool to escape world audit. The repaired test uses an intentionally unaudited fake server for the negative control and separately verifies the real unknown-tool error/audit evidence. The repair's RED log and 39-test focused GREEN log are in [history-unknown-audit-test/](history-unknown-audit-test/).

## What the files establish

| Directory | Scope |
| --- | --- |
| `unknown-tool-audit` | Real unknown tool attempts appear in both audit trails; earlier incompatible invariant failure and subsequent checks remain preserved. |
| `service` | Authenticated five-tool public session, actual handlers, private finalization and error accounting. |
| `http-service` | Bounded HTTP transport, malformed requests, authorization, finalization and timeout regressions. |
| `terminal` | Standalone stdlib client, strict finite JSON, local endpoint restrictions, explicit uncertain-write receipts and limits. Final focused runs: 73 tests on Python 3.10, 3.12 and 3.14. |
| `controller` | Common text-command state machine, native envelope capture, identity/termination guards and public-response reference with exact note readback. Recorded combined runs: 177 tests on the three Python runtimes. |
| `direct-model-trial` | One-attempt coordinator runner, durable evidence, exact backend argv and required initial-message digest. Final prompt-guard runs: 36 tests on the three runtimes. |
| `harbor-sdk` | Fake-provider/fake-terminal tests against the installed pinned Harbor SDK, including cancellation and prompt identity. Final log records 26 unittest cases, `OK`. |
| `history-unknown-audit-test` | Stale-test repair and positive unknown-tool recorder coverage. |

A filename containing `red`, `initial` or `progress` is historical development evidence, not a claim about the final candidate. Several first RED logs show intentionally missing new modules or optional-runtime imports. Some intermediate failures are test-fixture defects; for example, the terminal test originally tried to put a null byte into an environment variable. Behavioral regressions, later GREEN output and per-stage receipts remain distinct. Test counts overlap and must not be summed into a larger denominator.

`make-lint`/`lint` logs preserve failures as well. Final full-workspace runs reported 115 existing findings in unrelated archive/deliverable paths. Some earlier logs additionally show a temporary in-progress import issue. Scoped checks passed for the changed files; these logs do not establish that the whole checkout is lint-clean.

## Provenance and reproduction

[manifest.json](manifest.json) records original temporary paths, exact sizes and SHA-256 hashes for each copied file, plus hashes for the package documentation. Copied JSON receipts retain their original stage-specific source hashes. Those hashes describe different development snapshots; they are not one common final source identity. Coordinator final candidate-manifest reconciliation remains separate, including the last test-only repair.

The full-suite logs include their actual emitted command, `.venv/bin/pytest tests/ -q`. The following focused commands are reproducible examples; where an original argv was not captured in a receipt, they are **reconstructed**, not claims about historical command recording:

```sh
.venv/bin/python -m pytest tests/test_evaluator_integrity/test_history_execution.py tests/test_mcp_tools/test_unknown_tool_audit.py tests/test_reconciliation/test_execution.py tests/test_evaluator_integrity/test_audit_log_invariants.py -q
.venv/bin/python -m pytest tests/test_reconciliation/test_terminal.py tests/test_reconciliation/test_controller.py tests/test_scripts/test_reconciliation_model_trial.py -q
.venv/bin/ruff check src/healthcraft/reconciliation/terminal.py src/healthcraft/reconciliation/controller.py scripts/reconciliation_model_trial.py
```

Actual compatibility runs used `/private/tmp/healthcraft-check-py310/bin/python` and `/private/tmp/healthcraft-check-py312/bin/python`; the default virtual environment was Python 3.14. These temporary interpreters are not bundled here. The optional SDK log uses unittest output. A reconstructed command for its two current test modules is:

```sh
PYTHONPATH=src:. LITELLM_LOCAL_MODEL_COST_MAP=True LITELLM_MODE=PRODUCTION \
  /private/tmp/healthcraft-harbor-080-runtime/bin/python -m unittest discover \
  -s tests/test_scripts -p 'test_harbor_reconciliation_*.py' -v
```

The exact original optional-SDK argv was not retained in its receipts. Runtime setup and software/source pins are preserved separately in the [transport-v4 engineering artifact](../../../reconciliation/20260930/harbor-transport-v4/README.md); this package does not duplicate that runtime or its vendor sources.

These tests assess software contracts and evidence retention. They do not establish clinical validity, model reliability, clinical safety, superiority, held-out performance or general sandbox security. Model finish remains termination, not independent task success. This is ordinary TDD and peer review, not the pending formal red-team release gate. Published benchmark metrics, manuscript and remote release are unchanged by this packaging step.
