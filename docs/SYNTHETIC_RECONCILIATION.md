# Synthetic source reconciliation

This opt-in engineering exercise retrieves original synthetic EHR sources,
preserves unresolved statements, and writes a note through real HealthCraft
handlers. An independently authored oracle checks the evidence. It assesses
**zero clinical or safety criteria and produces no benchmark score**.

The open fixture is `synthetic-ed-reconciliation/v1`: eight source rows across
two same-name patients and three encounters. Six rows belong to the target
current encounter; one belongs to that patient's other encounter and one to
the other patient. This is a development case, not a held-out evaluation set.
Published task definitions and benchmark metrics are unchanged.

## Run from a source checkout

Use a new output directory for each execution. Existing directories are refused.
Neither command calls a model, downloads patient data, or starts Harbor.

```bash
python scripts/reconcile_synthetic_ehr.py --output-dir /tmp/hc-reconciliation-native-01

# Optional unchanged Microsoft CSV verifier, using the documented optional runtime:
python scripts/reconcile_synthetic_ehr.py --output-dir /tmp/hc-reconciliation-csv-01 --upstream
```

The [optional integration README](../integrations/healthagentbench/README.md)
records the pinned source/license, Python/pandas requirements and failure
statuses. Missing optional dependencies remain explicit unavailable evaluations;
they do not trigger installation or fallback. The CLI returns nonzero when
controls do not match, source identity cannot be confirmed, or a requested
secondary verifier does not complete every scheduled evaluation.

See the frozen development [report](../artifacts/reconciliation/20260930/native-verifier-v1/report.html)
and [artifact record](../artifacts/reconciliation/20260930/native-verifier-v1/README.md)
for commands, identities, raw outputs and limitations. HTML review is static;
browser visual QA is not recorded.

## What is checked

The [scenario](../configs/evaluation/reconciliation_v1/scenario.json) contains
observations and identifiers, not expected answers. The public
[instruction](../configs/evaluation/reconciliation_v1/instruction.md) requests
all eight rows, correct patient/encounter attribution, six exact current-source
observations and two explicit scope exclusions. Unknown status/time remains
unknown, planned work is not converted into administration, and opposing
reports for the same event remain unresolved. No treatment recommendation or
choice of which chart is true is requested.

The scripted reference reads actual `getPatientHistory`, `searchPatients`,
`searchEncounters` and `getEncounterDetails` responses. It stores strict JSON
under `healthcraft-reconciliation-note/v1` through `updateEncounter`, retries
that identical request, and reads it back. Source pointers refer to the
original encounter `patient_data`; note contents retain exact raw rows.

The separate [oracle](../src/healthcraft/reconciliation/oracle.py) uses pinned,
independently authored expectations and reports five axes:

| Axis | Required evidence |
|---|---|
| Evidence binding | Scenario/expectation identity, coherent snapshots, requests, responses and audit linkage |
| Source fidelity | Exact retrieved source facts, attribution, unresolved conflict and scope exclusions |
| Persisted action | One target-linked note and encounter append, with unrelated state unchanged |
| Readback | Actual post-write retrieval matching the stored target encounter |
| Execution completion | Recorded normal controller completion and successful linked calls |

Completion is distinct from a correct source account or a persisted write.
A write followed by interruption remains visible. Invalid provenance cannot
count as a successful negative control. Hashes bind content; they do not
attest that a third party executed it faithfully.

## Development controls and the secondary CSV contract

Nine declared controls exercise faithful execution, omitted source, invented
administration, silently resolved conflict, wrong-patient citation,
wrong-patient write, acknowledgement without persistence, duplicate write,
and interruption after a real write. Their expected development outcomes
match in offline regression execution; they are not nine model trials.

With `--upstream`, CSV submissions derive from conflict citations in the
**actual stored notes**. The pinned Microsoft HealthAgentBench verifier runs
unchanged on original synthetic labels, retaining its own raw artifacts.
Its positive-reward condition is full contradiction-cluster recall and at
least **1% row precision**. It cannot verify note fidelity or persistence.
For example, an invented-administration note can retain the correct conflict
citations and receive CSV reward `1` while the independent strict check fails.
That reflects different contracts, not an upstream benchmark failure or
HealthCraft superiority. These are not official HealthAgentBench scores.

Each new bundle retains the planned roster, initial source identity, request
journal, before/after world snapshots, audits, verification receipts and
per-trial errors. Final source-capture failure is explicit and source drift is
visible in the report. Failed or missing evidence stays in the denominator.
The in-process runner is not an agent sandbox. A separate [Harbor transport adapter](../integrations/harbor/README.md) exercises the real pinned SDK and a private backend. Its [four scripted controls](../artifacts/reconciliation/20260930/harbor-transport-v4/README.md) complete with expected source/persistence outcomes through direct coordinator HTTP and Harbor terminal interfaces. Earlier setup-failure rosters are retained. Harbor reward remains connectivity-only; it is not the independent task verdict.

The [first local-model pilot](../artifacts/reconciliation/20260930/local-model-pilot-v1/README.md)
records all four scheduled attempts: one per model and transport. Both Nano
attempts used the wrong command shape; both MedGemma attempts added Markdown
fences. Each stopped after one response, before any tool action or note write.
The frozen strict parser made no repairs or retries. These are command-format
failures, not clinical findings or a model ranking.

The separately frozen [structured-output follow-up](../artifacts/reconciliation/20260930/local-model-pilot-v2/README.md)
reached real note writes in Harbor, while both direct attempts exposed a macOS
filesystem-alias preparation bug. That one-line path repair was reproduced with
TDD before the [third cohort](../artifacts/reconciliation/20260930/local-model-pilot-v3/README.md).
All four third-cohort attempts terminated normally and stored one note each;
none satisfied the independent reconciliation contract. The notes contain
incorrect scope exclusions. An actual stored note is distinct from the oracle's
content-qualified `persisted_action` check; likewise, reading back an incorrect
note does not satisfy its `readback` check. All earlier attempts remain retained.

The optional native command schema is identified separately from the prompt
hash. Changing this decoding condition created a new development cohort; it
did not repair or replace the first pilot's failed responses. These open-case
attempts provide software and workflow diagnostics, not a held-out reliability
estimate or comparator performance claim.

## Explain a recorded attempt

The offline explanation separates successful write acknowledgements, notes in
the final store, actual post-write retrieval, and the oracle's stricter
content-qualified checks. It identifies missing, unexpected, duplicate and
misattributed scope exclusions with pointers into the original evidence and
expectations. It does not diagnose observation/conflict fidelity, retrieval
coverage or clinical validity. Those areas remain explicitly unassessed by the
explanation; the underlying oracle is unchanged.

```bash
PYTHONPATH=src python scripts/explain_reconciliation.py \
  --scenario configs/evaluation/reconciliation_v1/scenario.json \
  --expectations configs/evaluation/reconciliation_v1/expectations.json \
  --evidence artifacts/reconciliation/20260930/local-model-pilot-v3/medgemma-direct-01/backend/session/evidence.json \
  --output-dir /tmp/hc-reconciliation-explanation-01
```

Open `report.html` in the new output directory. The bundle preserves exact input
bytes, recomputed `verification.json`, `explanation.json`, and a file-hash
manifest. An optional `--verification` accepts a standalone earlier oracle
result and refuses a mismatch. Existing output directories are never replaced.
Unavailable provenance produces an unavailable report, not zero event counts.
Exit code 0 means an explanation is available, including for a failed
reconciliation; it does not mean the task passed. Exit code 2 indicates an
unavailable explanation or a creation error. A partially written directory has
no completion manifest and must be retained separately from a new attempt.

This command performs no model or tool execution. Hashes establish content
identity, not authenticated execution. The HTML uses no scripts or external
assets; automated structure/escaping checks are distinct from browser visual
QA and human usability testing.

Add `--source-context` to create a report with navigable evidence excerpts in a
new output directory. Each source reference opens a section in the same HTML
file showing the exact captured value and its labeled surrounding context.
Expected values remain labeled as expectations, separate from recorded evidence.
Embedded JSON notes are decoded only for navigation; their raw text is retained.
Missing fields and undecodable note content are marked unavailable, distinct
from an explicit JSON `null`; captured raw text stays visible.

This opt-in mode verifies all four content bindings before rendering excerpts.
Incomplete or changed bindings stop report creation. Internal links and native
disclosures require no scripts, external assets or network access. The manifest
records the rendering mode/version; input bytes, explanation and oracle verdicts
are unchanged. The default report keeps its original inert pointer display.

The [four saved-attempt reports](../artifacts/reconciliation/20260930/local-model-pilot-v3-explanations-v1/README.md)
show the distinction directly: all four attempts stored a note; the two MedGemma
attempts also read it back. All four still failed the required source exclusions.
These reports preserve the original verdicts and inputs.

The [source-context versions](../artifacts/reconciliation/20260930/local-model-pilot-v3-source-context-v1/README.md)
add navigable excerpts to those same four tutorial attempts. Their captured
inputs, explanations and oracle results remain byte-identical; no models were
rerun. Static source/pointer checks pass, while browser visual QA and independent
usability testing remain unperformed.

Operator-value measurement, independent clinical review and held-out
evaluation remain unperformed. Ordinary TDD and peer
review here are not the final formal red team. The release gate remains
[value evidence → formal red team → remote main and manuscript](RELEASE_EVIDENCE_PLAN.md).

The separate [operator review tutorial](OPERATOR_REVIEW.md) packages these
recorded attempts into an offline response form with source citations. It
preserves pending questions and invalid submissions for later adjudication;
it does not turn tutorial responses into study or clinical outcomes.
