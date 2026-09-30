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

Operator-value measurement, independent clinical review and held-out
evaluation remain unperformed. Ordinary TDD and peer
review here are not the final formal red team. The release gate remains
[value evidence → formal red team → remote main and manuscript](RELEASE_EVIDENCE_PLAN.md).
