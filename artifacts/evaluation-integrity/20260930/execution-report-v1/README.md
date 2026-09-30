# Execution, action and report development evidence

Baseline: `5cd2955502e373d969b66817162587170ce79e8f`. These are ordinary
development reproductions and TDD logs, not clinical validation, formal red
teaming or comparative-value results. Existing `results/` files were untouched.
`manifest.json` binds copied captures to their hashes and original paths.

- `agent-protocol-red.log`: 9 failing / 1 passing regression before the runner
  repair. Malformed later responses escaped after real state mutation;
  malformed batches could execute work; a post-action exception lost the
  partial return value. The positive control permits sequential ID reuse.
- `action-audit-reproduction.json` and the matching `.py.txt` reproduce three
  false passes with real handlers, persisted state, live grading and replay.
  `action-evidence-red.log` has 14 failing / 6 passing initial controls.
  The audit findings document the exact authored checks and limited repair.
  `action-repaired-replay.json` records the new evaluator's verdicts for the
  six unchanged captured cases: all three demonstrated false passes are
  corrected and the three controls retain their expected outcomes. These are
  isolated criterion replays, not newly measured full-task performance.
- `report-audit.json` and `.py.txt` capture unassessed flags and mismatched
  saved evidence still showing clean passes. `report-repair-red.log` has
  33 failing / 47 passing initial controls. `report-repair-replay.json`
  reapplies the repaired reader to the preserved pre-fix fixtures and records
  corrected incomplete outcomes without changing their raw bytes.

`report-fixtures/` preserves the seven exact synthetic inputs. The
[repaired offline report](repaired-report.html) shows one valid recorded-pass
control and six incomplete cases. `report-render-summary.json` records the
reader output and source identity. Static generation was checked; browser
visual QA was not performed. These are software fixtures, not model trials.
Additional RED logs cover malformed grading metadata and deduplication markers.
`action-strict-response-red.log` preserves 10 failing controls for duplicate
keys and non-finite saved responses before the strict replay parser repair.
`note-contract-pre-fix.json` and its `.py.txt` retain an original synthetic
note/readback probe: identical retries saved one note, but changed content or
target returned success without the requested write. Its acquisition used
the explicitly hashed working tree, not a clean baseline checkout.
`mutation-retry-red.log` records 64 failing / 42 passing initial controls for
the four shared-guard callers, registered aliases, typed request bodies,
readback, unchanged state and legacy behavior before that repair.
The additional key-validation RED log records 40 failures for supplied
non-string falsy keys before that boundary was corrected. The two independent
review JSON files retain ordinary development checks, not clinical or formal
red-team assessments. `note-contract-repaired.json` repeats the original
note/readback controls on the frozen staged candidate: changed requests
return conflicts, identical retry keeps one note, and a distinct key permits
the other intended write. This involved zero models or external frameworks.
The comparator source manifest records inspected upstream source paths and
Git blob IDs; [the feasibility proposal](../../../../docs/SYNTHETIC_EHR_COMPARATOR.md)
contains the pinned links and limitations.

The files include local paths and synthetic fixture text for reproducibility.
They do not contain real patient data or API credentials. Audit source hashes
refer to acquisition-time inputs, not an assertion that final production files
still equal the baseline. Final validation is recorded separately.
