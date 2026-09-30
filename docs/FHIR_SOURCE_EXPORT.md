# Source-preserving FHIR export

The additive `roster-source-fhir/v1` exporter makes the 33 reviewed roster
members available as 99 linked FHIR R4 resources. It preserves selected source
facts without turning source prose into coded diagnoses or inventing missing
clinical data. It supports the six tasks listed in
[the roster profile contract](ROSTER_PROFILES.md), not the whole entity graph.

```bash
.venv/bin/python scripts/export_roster_fhir.py \
  --output-dir artifacts/fhir/roster-source-01
```

Use a new directory. The command validates every source record before writing,
records executable source hashes, writes six collection Bundles, and writes
`manifest.json` last. Existing exports are never overwritten. If an I/O failure
leaves a partial directory without a manifest, it is not a completed export.
The command does not contact a model, terminology server, or FHIR server.

Python callers use
`healthcraft.world.fhir_projection.export_roster_sources(task, context, world)`.
The returned envelope contains the Bundle, canonical content hashes, source and
selector hashes, resource coverage, and explicit validation status. Callers must
prevent concurrent world mutation during the synchronous export.

## Representation contract

Each reviewed member produces three resources:

| Resource | Meaning |
|---|---|
| Patient | Stable profile identity only; unknown optional demographics omitted. |
| Encounter | Stable identity and patient link; required status is `unknown`; required class carries the R4 data-absent-reason extension with `unknown`. |
| DocumentReference | Exact selected observations and source provenance, serialized as canonical JSON in an inline `application/json` attachment. Subject and encounter references bind it to the same member. |

FHIR R4 permits a document reference to describe a serialized object with a
MIME type. The new reference has `status=current`; this does not assert a final
clinical diagnosis or document verification.
[R4 DocumentReference](https://hl7.org/fhir/R4/documentreference.html).
The Encounter status and class representation follow the
[R4 Encounter definition](https://hl7.org/fhir/R4/encounter.html) and
[data-absent-reason extension](https://hl7.org/fhir/R4/extension-data-absent-reason.html).

Source-reported age, sex, condition, triage tag, and treatment-related prose
remain source observations in the attachment. They do not become verified
Patient demographics, Conditions, orders, or encounter times. Source bed and
ambulance labels do not establish resource allocation or arrival. No optional
null/empty FHIR placeholders, timestamp, diagnosis coding, narrative inference,
US Core profile claim, or external reference is added.

Patient and encounter resource IDs match the profile. Bundle references use
stable UUID URNs. Document IDs bind to attachment content, and the Bundle ID
binds to its entries. These hashes detect drift; they do not authenticate a
third-party file. Original tasks, profile dictionaries, tool responses, patient
adapters, and historical results remain unchanged.

## Validation boundaries

The exporter independently checks the source contract and final records using
the same source-based verifier as the mechanical retrieval certificate. It
does not create retrieval evidence or audit calls. Missing members, changed
observations, source/selector hash drift, wrong identities, and broken patient
ownership fail before export. Local checks also require unique resource
identities, resolved Bundle references, and matching document/encounter patients.

The export's `structural_fhirpath` and `terminology` fields are always `not_run`.
Its `conformance_complete` flag is false. A prior successful validation cannot
silently validate a new export. Official validator evidence must be retained
separately and bound to the exact Bundle hashes and validator/package versions.
FHIR JSON Schema alone does not check every invariant or terminology binding.
[HL7 validation guidance](https://hl7.org/fhir/R4/validation.html).

The [2026-09-30 frozen export validation](../artifacts/fhir/20260930/roster-source-v1/validation/README.md)
checked all six exact Bundles with official validator 6.10.4 and R4 4.0.1.
It reported zero errors/fatals, 99 optional-narrative warnings, and 33 MIME-type
information issues with terminology access disabled. Source hashes remained
unchanged; the independent reference controls rejected all three altered
fixtures. This is structural/FHIRPath evidence for those bytes only.

`healthcraft.world.fhir_validation.parse_validator_outcomes` reads independent
OperationOutcome evidence, retains warnings and information, and fails closed
on malformed, missing, or error outcomes. Process exit zero alone is not
sufficient. With terminology disabled, a successful structural/FHIRPath result
still cannot establish complete conformance. Supplied provenance is recorded,
not authenticated by this parser.

This view excludes agent-added notes, generated seed facts, withheld answers,
and unreviewed enrichment. It is not a complete world snapshot, EHR integration,
or clinical record. Linked-history profiles, the legacy FHIRStore's general
validation behavior, and comprehensive representation of all 14 entity types
remain outside this implemented scope. Benchmark scores are null, all original
criteria remain unassessed, and zero clinical or safety criteria are measured.
