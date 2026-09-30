# Local casebook candidate validation inventory

This is an index for packaging existing evidence from the current implementation turn. It does not copy model outcomes, rerun tests, contact Ollama, or modify repository sources. `inventory.json` records 81 existing scoped files (868,473 bytes), their original paths, suggested package destinations, sizes and SHA-256 hashes. `package-list.tsv` is the same exact file selection for a copier; Python helper snapshots are suggested as `.py.txt`.

All 13 final source/test/schema identities in the index match the frozen peer receipts. The parent supervisor is `0374d8325cba4ba5c425026e2f1cd14f8aa3198918762f7b8967caaed7637e3f`; its test is `fa27845e462faf748dc987431453949d3a25f270c12a144fc34a5ec9c18b4211`. Full hashes for worker, public context, controller, native JSON parser, cohort and CLI are in the index.

| Evidence group | Meaningful checks retained |
| --- | --- |
| Parent supervisor | 28 initial RED failures; three capture-evidence RED failures; partial-receive and blocked-send RED failures; 34 final own tests; 172 combined tests on Python 3.10, 3.12 and 3.14. |
| Worker | 30 initial RED failures; 34 own tests; 139 compatibility tests on three runtimes. Public-only config, prompt identity, durable request capture, exact reply protocol, fresh postflight and delivery failures. |
| Public context | 25 initial missing-module errors; 104 final public-context/controller tests per runtime. Exact five public tool schemas and common instruction, instantiated only with public target IDs. |
| Native JSON/body capture | 13 initial failures and four additional string-argument failures; 153 source tests plus 43 independent peer controls, 196 combined per runtime. Duplicate/nonfinite/invalid UTF-8 rejection and exact successful-HTTP body retention. |
| Cohort | 21 initial missing-module errors, eight accounting/grader failures, one output-collision failure; 35 final tests. Full planned denominator, independent grading errors, actual writes/readbacks, retained failures and source drift. |
| Integration peer | 177 focused tests; 18 independent cohort probes per runtime. Both exact formerly hanging IPC probes now return in roughly 0.62–0.65 seconds for a 0.5-second deadline, retaining actual writes/audit and stopping child/I/O threads. |
| Frozen plan | 49 structural and identity checks. Sixteen planned slots across eight cases and two models, with no repeated attempts. These are planned slots, not executed trials. |
| Candidate lint | Original root lint failure retained. Isolated candidate `make lint` passed across 799 inventoried inputs / 411 Python files. |

Counts overlap and repeat across runtimes; they must not be summed into a unique-test count or model-trial denominator. The initial completion review predates the repairs and is retained to explain why strict completion binding and native parsing were necessary.

The parent reported the full suite still running when this inventory was made. `/private/tmp/healthcraft-local-casebook-final/full-suite.log` is deliberately excluded from hashes and the package list until the parent confirms it is final. This inventory makes no full-suite result claim.

Four optional raw IPC reproduction directories are listed separately, including pre-fix externally terminated runs and post-fix actual state/journals. They are not in the compact package list. The selected receipts already retain the two failing controls, corrected outcomes, execution digests, cleanup states and exact stderr. One nonblocking CPython 3.14 `BytesIO` finalizer error is disclosed in the peer receipt.

The metadata preflight group records the earlier permission-blocked read and the successful authorized metadata-only read. It is a prior observation, not a fresh attestation. The final public messages are 10,486 canonical UTF-8 bytes; byte length is not a token count or a truncation guarantee. Earlier proposal-based context-size files are excluded to avoid confusing them with the frozen instruction.

This is ordinary development validation, not formal red team, clinical validation, ranking evidence, or deployment readiness. Case labels share an engineering authoring process and still await independent review. Child process separation is not a hostile-code filesystem sandbox, and terminating a child does not cancel a request already dispatched to the Ollama daemon. No actual model outcome, immutable result, dependency cache or runtime binary is included.
