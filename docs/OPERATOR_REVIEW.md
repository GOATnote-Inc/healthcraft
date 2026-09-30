# Offline operator review tutorials

The operator review workflow lets a researcher inspect a captured reconciliation
attempt, record judgments with source citations, and export a response for later
adjudication. It preserves unanswered questions and malformed submissions so
that reporting cannot quietly count only completed reviews.

This first contract accepts exposed engineering tutorials only. It does not
recruit or authenticate reviewers, measure usability, adjudicate their answers,
or establish clinical or comparative value. The existing
[clinical review workflow](CLINICAL_REVIEW.md) remains separate.

## Build a packet

Select explanation bundles created by `scripts/explain_reconciliation.py`
with `--source-context`.
Give every selected attempt an explicit case ID. Each bundle must contain its
complete manifest and copied inputs; historical paths recorded inside a bundle
are not followed. Duplicate source identities are rejected, rather than silently
deduplicated or counted as additional attempts.

Create a protocol JSON file:

```json
{"protocol_id":"tutorial-01","purpose":"engineering_tutorial"}
```

Create an assignment JSON file using your own reviewer alias:

```json
{"assignment_id":"assignment-01","reviewer_id":"reviewer-alias","presentation":"assisted"}
```

Then run:

```bash
python scripts/operator_review.py build \
  --case case-01=/tmp/hc-reconciliation-explanation-01 \
  --protocol /tmp/operator-protocol.json \
  --assignment /tmp/operator-assignment.json \
  --output-dir /tmp/operator-packet-01
```

Repeat `--case` to include additional bundles in the stated order. The output
directory must be new. Source bytes are copied unchanged, and the oracle and
explanation are recomputed to check their consistency. A new controlled
`report.html` is generated from the verified JSON; imported HTML is preserved
as source material, not executed as the review interface. The manifest binds
the packet, blank response template, report and source snapshots.

The packet also records the verifier and renderer implementation digests. An
implementation mismatch stops import rather than silently interpreting an
issued packet with changed code. Preserve the issuing revision for replay;
these selected source digests are not a complete environment capture.

Open `report.html` locally, enter responses and download the response JSON.
Alternatively, edit a copy of `response-template.json` using a text editor.
Keep the original packet unchanged. The HTML works offline and does not send
responses or evidence to a service. Browser visual QA and human usability
testing have not been performed.

`presentation` may be `raw` or `assisted`. Both expose the same scenario,
captured evidence, expectations and oracle, with the same response questions.
The assisted interface additionally presents the derived explanation. These
are tutorial presentation options, not a registered comparison experiment.
Source model identities and authored expectations are visible; these packets
are not blinded.

## Record six distinct judgments

| Question | Meaning |
|---|---|
| Execution completion | The attempt recorded normal termination. |
| Write acknowledgement | A write returned a success acknowledgement; a retry is not necessarily a new write. |
| Storage | A new note exists in the captured final state, even if its target or content is wrong. |
| Readback | A later successful retrieval returned stored note text; incorrect content can still have been read back. |
| Reconciliation correctness | The requested target, source facts, exclusions and persistence requirements were met. |
| Evidence sufficiency | The available evidence supports the requested assessment. |

Use `yes`, `no` or `unassessed`. A blank judgment remains pending. Every
substantive answer needs a rationale and at least one resolvable citation into
that case's source documents, for example:

```json
{"document":"evidence","pointer":""}
```

This example cites the whole evidence document. Prefer a specific pointer
shown in the source navigation when possible. Document names are `scenario`, `evidence`,
`expectations` and `oracle`. Pointers use RFC 6901 escaping (`~0` for `~`, `~1`
for `/`). To cite decoded JSON inside a string, add `decoded_json_pointer`
after pointing to the original string. A missing-field claim should cite its
existing parent and explain the absence.

Unassessed answers require a rationale and one of `insufficient_evidence`,
`conflicting_evidence`, `outside_scope` or `reviewer_abstention`. Supplied
citations are still validated. Timing is either `not_collected` or explicitly
`self_reported`. Active and elapsed seconds are optional nonnegative finite
numbers; a self-reported timing entry needs at least one value and a note.
Unknown values remain null, and active time cannot exceed elapsed time when
both are supplied. No clock is automatically
started, and self-reported time is not an instrumented measurement.

## Preserve a response

```bash
python scripts/operator_review.py import \
  /tmp/operator-packet-01/manifest.json \
  /tmp/downloaded-response.json \
  --output-dir /tmp/operator-receipt-01
```

Import rechecks the issued packet and its source snapshots before accepting
response data. It preserves exact submitted bytes and a receipt accounting for
every assigned case and all six questions. Omitted cases or questions remain
pending. A case with all questions explicitly abstained is distinguished from
a case left unassessed for missing evidence or other reasons. A malformed
response to a valid packet creates an `invalid_submission` receipt with all
assignments pending.
Changed or invalid packet evidence stops import before receipt creation.

Exit `0` means the response was structurally recorded, `1` means an invalid
submission was preserved, and `2` means a command, packet or filesystem error.
No exit code means the judgments are correct. Reimporting a response does not
create another independent reviewer; analyze assignment identities and
submission hashes, not receipt-directory counts. Reviewer aliases and timing
remain unauthenticated declarations.

Existing output directories are refused. A filesystem failure can leave an
incomplete new directory without a completion manifest; retain it and use a new
directory for another attempt. Hashes identify content and detect accidental
changes; they do not authenticate authorship or execution.

This tutorial is an optional developer diagnostic, not a required evaluation or
release step. A future operator study would need fresh cases, defined outcome
assessment and all assignments retained; clinical claims need separate clinical
evidence. Repository and paper publication follow the
[automated release workflow](RELEASE_EVIDENCE_PLAN.md).
