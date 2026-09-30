# Local casebook model plumbing: engineering validation

This package records TDD and ordinary peer review for the public-context builder, model worker, parent-owned native-world supervisor, strict native response parser, and full-denominator cohort runner. It contains **no live model outcomes** and makes no model ranking, clinical, benchmark-readiness or formal-red-team claim.

The final candidate passed `make test`: **4,316 passed, 58 skipped in 294.29 seconds**, exit 0, Python 3.14.3. The exact log and source-bound receipt are in [final-validation](final-validation/full-suite-receipt.json).

`make lint` passed in the isolated candidate inventory of **799 files, including 411 Python files**. The root invocation's **115 diagnostics** remain visible in the original log; archived and unrelated files were excluded from the isolated check, with every included input hashed. This is not a claim that root lint passed. See [candidate-lint](candidate-lint/lint-receipt.json).

| Scope | Preserved evidence |
| --- | --- |
| Parent supervisor | 28 initial RED failures; three missing/corrupt-capture RED failures; partial-frame and blocked-reply RED failures. Final 34 own tests and 172 supervisor/worker/public-context/controller tests on each of Python 3.10, 3.12 and 3.14. |
| Worker | 30 initial missing-module RED failures; 34 final own tests, 139 compatibility tests per runtime. Public-only configuration, pre/postflight identity, durable journals, strict IPC and terminal delivery failure. |
| Public context | 25 initial missing-module errors; 104 final tests per runtime. Common public instruction, canonical five-tool schemas and actual initial-message hashes for all eight cases. |
| Native JSON parsing | 13 initial failures and four later string-argument failures. Final 153 source tests plus 43 independent peer controls, 196 combined per runtime. Duplicate keys, nonfinite values, invalid UTF-8 and string-encoded arguments fail closed with captured native response bytes. |
| Cohort accounting | 21 initial missing-module errors, eight accounting/grader failures and one output-collision failure; 35 final tests. Complete planned denominator, retained failures, actual writes/readbacks and source-drift detection. |
| Independent integration review | 177 focused tests and 18 cohort checks per runtime. Both previously blocking IPC reproductions finish at about 0.62–0.65 seconds for a 0.5-second budget, preserving actual state and stopping the child and I/O threads. |
| Frozen plan review | 49 structural/identity checks for 16 unique planned slots: eight cases × two models. These are plan checks, not model trials. |

These counts overlap and repeat across runtimes; do not add them into a unique-test or model-attempt count. Initial mistakes and corrected commands/assertions are retained. The initial completion review predates the repairs and explains the completion-binding and parser defects; it is not final-candidate behavior.

[The historical integrity review](historical-integrity/receipt.json) verified **2,371 regular files across 11 prior bundles**: 1,202 manifest-listed payload files, 11 top manifests, and 1,158 otherwise unlisted build-tree files bound to exact archive members. It found unchanged bytes during review. This is manifest/byte consistency, not execution authenticity; archived candidate source was not replaced with current code or used to rerun old outcomes. The [remaining user-value gap](historical-integrity/next-user-value-gap.md) is a review note, not an implemented study or participant result.

`packaging-receipt.json` maps all **110 copied files** to their original paths and hashes. `manifest.json` hashes every packaged payload, including this README and the packaging receipt, excluding only itself. `selection-index/` preserves the earlier 81-file selection and original source inventory: its pending-suite language is superseded by `final-validation/`. Its original index manifest describes the prepackaging source filenames; Python helper snapshots are stored as `.py.txt` and their exact byte-preserving destination mapping is in the packaging receipt.

Two small pre/post-fix partial-frame raw captures are included under `ipc-raw/`. The large blocked-reply trees contain repeated synthetic megabyte note bodies and are omitted; original and corrected receipts, cleanup state, persisted-action checks, execution digest and exact stderr remain in `supervisor-cohort-peer/`, with the fixed attempt receipt in `ipc-raw/`. One nonblocking CPython 3.14 `BytesIO` finalizer error during send interruption is disclosed there.

The prior metadata-only preflight is included as a saved observation, not a fresh runtime attestation. The frozen public messages are 10,486 canonical UTF-8 bytes; byte count does not establish token count or absence of truncation. Earlier proposal-based context measurements are excluded. Wrapper and validation scripts in `helpers/` are exact source snapshots and were **not executed during packaging**.

Case labels share an engineering authoring process and independent review remains pending. A worker's completion establishes termination and matching captured identities, not correct reconciliation. Request counts describe recorded native dispatch attempts, not guaranteed inference executions. The child receives public configuration only, but process separation is not a hostile-code filesystem sandbox, and terminating it cannot cancel a request already dispatched to Ollama. The value-comparison, formal-red-team and remote/paper release gates remain open.
