# Source-bound incident review and validity adjudication

This opt-in v2 workflow lets an operator report what happened, which record was
involved, and which captured facts support the report. A separate form records
human judgments about that report's validity. It supports the native v2 casebook
and the saved local MedGemma/Nemotron cohort without running a model or calling
an API. The [v1 tutorial](OPERATOR_REVIEW.md), rewards, benchmark tasks and
historical results remain unchanged.

This is an engineering development workflow. Form acceptance is not evidence
that a report is correct. The software does not authenticate reviewers, establish
independence, or produce a clinical score, product ranking or performance estimate.
Actual intended-user feasibility, independent validity review and a registered
comparison remain necessary. Formal red team and publication remain behind the
user-value gate.

## Issue an operator packet

Choose an explicit ordered mapping of opaque review IDs to source attempt IDs.
A failed or incomplete attempt is a valid review assignment. The full source
inventory and raw manifest hash are checked before the packet is issued.

Save a build configuration, for example `/tmp/hc-incident-config.json`:

```json
{
  "expected_sha256": "8a9b76acf23ff921b40533de66d507c795ca9a8e15a3dab0270ba21471c89c5d",
  "selections": {
    "review-a": "REC2-003/designated",
    "review-b": "REC2-004/designated",
    "review-c": "REC2-007/designated",
    "review-d": "REC2-008/designated"
  },
  "protocol": {
    "protocol_id": "incident-development-01",
    "purpose": "engineering_development"
  },
  "assignment": {
    "assignment_id": "operator-development-01",
    "operator_id": "development-operator",
    "presentation": "assisted"
  }
}
```

```bash
python scripts/operator_incidents.py build \
  artifacts/reconciliation/20260930/casebook-native-v2/run/manifest.json \
  --config /tmp/hc-incident-config.json \
  --output-dir /tmp/hc-incident-packet-01
```

Distribute **only `public/`** to the operator. Its `report.html` is self-contained:
open it in a browser, inspect the source documents, complete the form and export
JSON. The root manifest is coordinator metadata containing source paths and the
explicit source selection; it is not an operator handout. Keep it with the source
bundle for import. Always use a new output directory.

Use `presentation: "raw"` for the same original evidence without derived
assistance. Both views receive `task`, `scenario`, `evidence` and `runtime`.
The assisted view adds source-cited claims to inspect, never filled answers.
It distinguishes acknowledgement, newly stored notes, retrieved text, ownership,
source discrepancies and capture gaps. Missing linkage stays unknown. Its claims
are mechanical diagnostics that can themselves be wrong; inspect their sources.

Model packets retain the captured task context. Scripted packets explicitly label
the retrospective review contract, rather than implying that text was given to
an old actor. Private expected outcomes, verifier judgments and the hidden
complete original of an incomplete capture are excluded. Captured error strings
and free text remain exact and can reveal a control or model identity; no blinding
is claimed.

For the local cohort, use
`artifacts/reconciliation/20260930/local-casebook-pilot-v1/run/manifest.json`,
raw SHA-256 `d547c265469013c272a107c87506bf29d1bc9ca836ebe564a892f053ad810a8c`,
and explicit attempt IDs such as `REC2-001/medgemma` or `REC2-002/nano`.
No successful-run filter or new inference is performed.

## Report and import

The operator independently enters the requested patient/encounter, six evidence
questions, incident summary and findings. A finding records its category, claim,
observed patient/encounter (independently nullable), implicated source IDs and
citations. Requested and observed identities are separate. Empty findings do not
mean “no incident”; that requires an explicit assessment. All judgments start blank.

Citations use `{ "document": "evidence", "pointer": "/completion" }` with strict
RFC 6901 pointers. An optional `decoded_json_pointer` navigates strictly parsed
JSON inside a captured string. Duplicate JSON keys, missing fields and pointers
into unavailable documents are rejected. A real null inside an available document
can be cited. Cite an existing parent when explaining a missing field. A resolving
but irrelevant citation passes structural checks; a human must assess relevance.

Null judgments preserve typed drafts and valid citations as pending. Malformed
citation JSON blocks browser export while retaining the current form. Export before
closing or reloading: there is no persistent browser draft store or session recorder.
Timing is either explicitly uncollected or self-reported; no measured activity or
time endpoint is inferred.

```bash
python scripts/operator_incidents.py import \
  /tmp/hc-incident-packet-01/manifest.json /tmp/operator-response.json \
  --output-dir /tmp/hc-incident-import-01
```

The importer saves exact input bytes and all assigned cases/questions. Missing,
partial, unassessed and abstained answers remain distinct. Malformed submissions
retain a full pending denominator; invalid timing is recorded separately without
deleting an otherwise usable report. Structurally accepted target IDs or claims
are never corrected to match the source. Validity remains pending.

If the original source moved, pass `--source-manifest-override PATH` to import or
adjudication-build; its raw hash and whole inventory must still match. Imports also
require the issuing implementation. These hashes establish byte consistency, not
participant identity or execution authenticity.

## Independently judge a specific report

Save `/tmp/hc-adjudication-config.json`:

```json
{
  "assignment": {
    "assignment_id": "review-development-01",
    "adjudicator_id": "reviewer-a",
    "role": "initial"
  },
  "prior_records": null
}
```

```bash
python scripts/operator_incidents.py adjudication-build \
  /tmp/hc-incident-packet-01/manifest.json /tmp/operator-response.json \
  --config /tmp/hc-adjudication-config.json \
  --output-dir /tmp/hc-adjudication-packet-01

python scripts/operator_incidents.py adjudication-import \
  /tmp/hc-adjudication-packet-01/manifest.json /tmp/reviewer-response.json \
  --output-dir /tmp/hc-adjudication-import-01
```

Again distribute only `public/`. The initial reviewer sees the original permitted
source documents and submitted report, without operator assistance, presentation
assignment or other reviewers' judgments. The assignment binds the exact raw
operator submission hash; editing that report creates a different review context.
Invalid operator input is retained coordinator-side and cannot supply valid report
citations. Missing reports and unfinished reviewer work stay pending.

Four checks cover target attribution, incident accuracy/completeness, evidence
support and uncertainty handling. Assessed checks require rationale plus both
source citations and pointers into the original report. Explicit overall valid,
invalid or unassessed decisions must agree with the entered checks. The software
checks that consistency but does not supply a truth label. Reviewer qualifications,
conflicts and independence are self-reported declarations.

## Preserve disagreement and resolve explicitly

Use an explicit roster mapping each assigned initial reviewer ID to their imported
`manifest.json`, or `null` if missing. Paths are relative to the command's working
directory. Reimporting a record does not create another assigned reviewer.

```bash
python scripts/operator_incidents.py summary \
  /tmp/hc-adjudication-packet-01/manifest.json \
  --records /tmp/hc-reviewer-roster.json \
  --output-dir /tmp/hc-adjudication-summary-01
```

Each assigned reviewer × report remains counted, including missing work. Differing
explicit decisions remain disputed; there is no majority vote. For resolution,
issue another adjudication with `role: "resolver"`, a different reviewer ID and
`prior_records` set to that same roster object. At least two initial reviewers are
required. Only disputed cases without pending initial judgments are assigned.
The resolver sees those original judgments, starts with blank answers and records
a separate decision. Original judgments are retained.

Import the resolver response, then pass its import manifest with
`summary --resolver-record PATH`. Resolution binds all original import hashes;
changing an initial submission invalidates the old resolution. Resolver opportunities
are counted separately. Pending, abstained or unassessed resolution does not erase
a dispute. The role checks compare declared IDs, not real identities.

## Validation and limits

CLI exit 0 means issued or structurally recorded, never clinically correct.
Exit 1 means invalid submitted bytes were retained. Exit 2 means preflight or
filesystem failure; inspect stderr. Outputs are exclusive and do not overwrite
original captures or submissions. No score or comparative statistic is emitted.

Tests exercise raw/assisted source equivalence, incomplete and failed captures,
strict citations, draft retention, actual HTML JavaScript export through Node,
immutable imports, original-source binding and disagreement resolution. Static
form and JavaScript checks do **not** establish visual usability or accessibility;
browser visual QA has not been performed. Intended-user testing remains pending.
