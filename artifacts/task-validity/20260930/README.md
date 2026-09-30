# Task-validity execution records

## IR-002 reference execution

`ir002-linked-history-v1.json` was created by:

```bash
.venv/bin/python scripts/certify_history_task.py \
  --output artifacts/task-validity/20260930/ir002-linked-history-v1.json
```

The run used Python 3.14.3, seeded Mercy Point (`seed=42`), and the opt-in
`linked-history/v1` profile. Eight actual in-process MCP tool calls retrieved
the four supplied historical visits, wrote their structured source facts to
the current encounter, and read the note back. All four mechanical checks
passed. The source hashes were checked against the files used for this run.

Trace SHA-256:
`beec22fa517fd12aafea792d7750f0e99f287e0f95509d73da58bc5ca4b01757`.

The verifier's 50 regression tests include negative controls for missing
visits, wrong patients, altered facts, fabricated date precision, partial
search results, missing responses, and notes written before retrieval then
reused through idempotency. Another 48 tests cover profile preparation, and
six cover execution/capture/CLI behavior. These are engineering regression
cases, not an independently adjudicated clinical sample or an error-rate
estimate for other tasks.

**Coverage:** four mechanical analogues (C01/C02/C03/C07); C04/C05/C06/C08
unassessed; zero safety criteria measured. There was no model or judge call,
benchmark reward, clinical inference, or modification of historical tasks or
results. This is a source-transport and persistence witness for one profile,
not a full-task pass or model-performance result.

See [the certificate contract](../../../docs/REFERENCE_CERTIFICATES.md) and
[the original validity findings](../../../docs/TASK_VALIDITY_FINDINGS.md).

## Six-task roster reference execution

`roster-observations-v1.json` was created with:

```bash
.venv/bin/python scripts/certify_roster_tasks.py \
  --output artifacts/task-validity/20260930/roster-observations-v1.json
```

Six fresh seed-42 Mercy Point worlds exposed 33 authored roster members.
The reference controller received only patient/encounter IDs and made 66
actual in-process MCP calls: a detail lookup and patient-history lookup for
each member. All six independent source-concordance verifications passed.
Source and runtime hashes captured before and after the cohort matched.

All 63 original clinical criteria remain unassessed; clinical and safety
coverage are zero and the benchmark score is null. This is a source transport
witness, with no model, prioritization, treatment, or clinical-readiness claim.
See the [profile contract](../../../docs/ROSTER_PROFILES.md).

## IR-018-C05 content review

`ir018-c05-content-review.json` preserves a bounded review of one disputed
clinical assertion, primary-source URLs, the original task hash, and population
limits. It does not modify the task, historical scores, or paper. Its clinical
implications require a separately reviewed task revision.
