# Resumable offline review workbench

The optional workbench opens an existing v2 operator or adjudication assignment
with on-demand source navigation and saved-response loading. It keeps the original
packet, source documents, blank template and response schema unchanged. The
[original incident workflow](OPERATOR_INCIDENTS.md) remains the authority for
submission import and validity accounting.

## Open an assignment

```bash
python scripts/operator_workbench.py build \
  /path/to/original-assignment/manifest.json \
  --output-dir /tmp/hc-review-workbench-01
```

Distribute only the new directory's `public/` subfolder. Open its `report.html`.
Every original assigned case remains present. Source fields are displayed on
request; an assisted claim opens its cited source through the same navigator.
Missing capture stays unavailable, and a real null remains an inspectable value.
Raw strings and strict decoded JSON are separate representations of the captured
text. Numeric display must preserve captured values rather than round them through
JavaScript's numeric representation.

The whole original issuer must validate before the workbench is created. Output
must be outside the issuer and its original evidence directories. Existing output
directories are never overwritten. A new view also cannot be placed beneath an
existing manifest inventory, including a prior reviewer import.

## Save, resume and submit

The workbench uses the original v2 response format. Export pending work as response
JSON before closing. Choose that saved file and preview it in a workbench for the
**same original assignment**; packet, assignment and reviewer/operator identity
must match. Apply the preview explicitly, or cancel to retain current work. Undo
restores the form as it was immediately before the last applied file, including
unfinished text. A file
from another assignment must be rejected rather than transplanted to the current
case. Loading must preserve explicit judgments, nulls, text, findings and citations,
without inventing answers or discarding unsupported fields. Invalid input must leave
the current form intact.

The loader accepts complete, ordered responses exported by the form. It rejects
unsupported manually edited shapes, unknown or duplicate fields, incomplete case
rosters, and numeric values that JavaScript cannot preserve exactly. A rejection
does not replace current work. The original importer can accept some response
shapes that this optional form cannot resume; retain those files and submit them
through the original workflow.

Loading an exported response does not authenticate its author or assess its claims.
A new export is a new file/revision, not an overwrite of a previously imported
submission. No browser activity timer, automatic server save or network service is
provided. Keep original submissions and choose revisions explicitly.

Use the ORIGINAL issuer manifest when importing the exported response:

```bash
# Operator response
python scripts/operator_incidents.py import \
  /path/to/original-assignment/manifest.json /path/to/response.json \
  --output-dir /tmp/hc-operator-import-new

# Adjudicator or resolver response
python scripts/operator_incidents.py adjudication-import \
  /path/to/original-adjudication/manifest.json /path/to/response.json \
  --output-dir /tmp/hc-adjudication-import-new
```

Do not supply the workbench manifest to those importers. It identifies the display
artifact, while the original manifest identifies the assigned review contract.

## Verify and move files

```bash
python scripts/operator_workbench.py verify \
  /tmp/hc-review-workbench-01/manifest.json
```

Verification reconstructs the complete display from the pinned original issuer
and issuing implementation. Changed source, template, HTML, unexpected files or
implementation hashes cause failure. If the original issuer moved, pass
`--issuer-manifest-override /new/path/manifest.json` to `verify`; the raw manifest
must remain identical. For operator packets whose underlying source moved, the
existing `--source-manifest-override` mechanism is available on both commands.
Adjudication packets retain their original coordinator snapshots and do not use
that source override.

## What this change can establish

Static artifact size and generated markup counts can show reduced eager output.
Node tests can check source navigation, field restoration and export semantics.
Neither proves browser responsiveness, visual usability, accessibility, operator
accuracy or time savings. Intended-user feasibility remains the next evidence step.

This is a separately versioned development view. Retain its manifest when recording
which view was issued. A v2 response identifies the original assignment; it cannot
prove which interface a person used. Any future comparative study must freeze the
view and its assignment procedure before acquiring outcomes. Existing exposed
cases and script-generated demonstrations are not held-out or human outcomes.

The independent-review, healthcare-value, formal-red-team and publication gates
remain as specified in the [release evidence plan](RELEASE_EVIDENCE_PLAN.md).

The [development demonstration](../artifacts/operator-review/20260930/workbench-v1/README.md)
reissues saved native, local-model and synthetic reviewer assignments in this view.
It records exact packet/template identity and static page sizes. No new model run,
participant response, clinical judgment or user-performance outcome is introduced.
