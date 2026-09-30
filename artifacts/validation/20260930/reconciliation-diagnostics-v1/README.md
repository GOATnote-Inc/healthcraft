# Reconciliation diagnostics v1 prototype validation

This package preserves completed TDD and ordinary peer-review evidence for the
`healthcraft-reconciliation-explanation/v1` diagnostic sidecar. It explains
scope-exclusion differences and observed write, storage and readback evidence
without changing the oracle, adding a score or adjudicating clinical correctness.
It contains no browser validation, new model inference or formal red team.

## Recorded validation

- **27 diagnostic tests + 68 unchanged oracle tests = 95 tests** passed on each
  of Python 3.10, 3.12 and 3.14. The [implementation receipt](receipt.json) and
  three `green-py*.log` files retain those results. They are repeated checks of
  overlapping tests, not 285 distinct tests or a new full-repository suite.
- Initial [RED](red.log): 25 tests failed before the module existed. The later
  [write-attribution RED](red-write-attribution.log) retained one failure and
  25 passes: an acknowledgement followed by a real same-text write must not
  retroactively attribute storage to the earlier call. Intermediate GREEN logs
  are retained alongside final compatibility results.
- [Independent review](peer-review.json): 71 offline checks passed on the four
  existing v3 evidence files; all 50 original-document pointers resolved. The
  reviewer also reran the same 95-test local suite. This is additional checking
  of saved evidence, not additional model trials or three independent runtime
  reruns by the reviewer.
- Scoped lint passed per the receipt. [Root `make lint`](make-lint.log) retained
  115 existing unrelated archive/deliverable errors. Those files were not fixed,
  and this package does not claim a clean full-workspace lint run.

The peer review verifies detached deterministic outputs, canonical input/output
bindings, invalid-provenance refusal, unchanged oracle checks, exact exclusion
differences and pointers to original evidence. It distinguishes the observed
readback in the saved MedGemma traces from the oracle's content-qualified
`readback:false`. A final-state matching note does not establish unique
per-call creation; the sidecar explicitly states that limitation. The exact
[peer checker](peer_check.py.txt) and an earlier
[offline v2 explanation capture](actual-v2-explanations.json) are retained.
No prior model artifact was edited or reclassified.

## Frozen scope and provenance

Before copying, the prototype source and test were checked against their frozen
hashes:

- `diagnostics.py`: `cb17f6e3065ce0d40a755b31b04392bcb784e562b4b1e8c91bb3472edb0cda51`
- `test_diagnostics.py`: `fbd90b0f0d73b71611bfc1c36ff3c9c98b4b272c3f064ee12bbf486ce634b558`

[source-identity.json](source-identity.json) records those identities; exact
source/test snapshots are stored as `.py.txt` files under `source-snapshots/`.
This is the sidecar prototype checkpoint, without the separately developed
CLI or renderer. Observation fidelity, conflict fidelity, retrieval coverage,
clinical validity and safety remain unassessed by this sidecar. Input hashes
and consistent receipts are not execution authentication. No score, pass or
clinical-readiness claim is introduced.

[manifest.json](manifest.json) hashes every payload except itself and records
the original path for each copied file. All 15 copied originals were rechecked
unchanged. No runtime, cache, model weights or raw model outcome files were
copied; the saved evidence files remain in their original immutable cohorts.
Packaging performed no test rerun, browser operation, model or daemon call,
source edit, staging or commit.
