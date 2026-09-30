# Authored care and imaging fidelity

Task injection now preserves reported care and imaging context without turning
plans into completed treatments or filling missing imaging fields. These are
source-transport repairs, not clinical adjudication. They change future tool
responses and prompt/schema identities; historical task YAML, rubric channels,
results and manuscript remain unchanged.
The original V8 composed-prompt fixture is retained unchanged. The intentional
tool-description changes have a separate development snapshot,
`tests/fixtures/prompt_snapshots/source_fidelity_composed.txt`; they do not
describe the prompt used in historical runs or the current published paper.

## Care assertions and administration events

`Encounter.authored_care` contains one detached source group per supplied,
reviewed direct patient field. Each group has `source_collection`, a
`source_path` JSON pointer and exact `source_data`. Nested mappings, list order,
nulls, status text and time text survive. No text parser infers a medication,
route, dose, administration status or administration time.

The 22 selectors are explicit in
[`care_projection.py`](../src/healthcraft/tasks/care_projection.py). They cover
32 supplied groups in 29 of the 205 catalog tasks, including active orders,
current management, reported treatments, field interventions, prescriptions,
resuscitation and transfusion records. This is a bounded reviewed inventory,
not exhaustive extraction of medications from all task prose. Home medication
history retains its separate existing representation. Prior visits and other
patients are not reassigned to the index encounter.

Previously, `active_orders` or `current_management` became
`MedicationAdministration` rows, including non-drug care, plans and holds.
The converter invented a default oral route and scenario-clock administration
time. Conversely, reported treatments elsewhere could be missed. These rows
are no longer fabricated. Empty `meds_administered` means that no structured
administration records were established; it does not mean no drugs were given.
Existing explicitly structured administration records keep their contract.

`processDischarge` preserves source care in a separately labeled section.
With no structured administration records, its treatment line says
“Medication administration not established by available records.” This text
also reaches the persisted discharge note. It does not certify the clinical
accuracy or completeness of the rest of the discharge workflow.

`validateTreatmentPlan` now advertises optional `encounter_id` alongside its
required `patient_id`. Patient-only checks say that they exclude encounter
medication context. With proposed medications and unresolved authored care,
the tool returns `unresolved_medication_context` and marks encounter drug
interactions unassessed. It retains findings from independently executable
allergy, interaction and directive checks in `details.known_findings`.
Uncertainty is not itself a contraindication. Procedure-only checks continue
within their existing scope. The drug table and other clinical heuristics
remain limited; neither `valid` nor absence of a warning is clinical clearance.

This distinction follows FHIR's separate concepts for
[medication requests](https://hl7.org/fhir/R4/medicationrequest.html),
[reported medication statements](https://hl7.org/fhir/R4/medicationstatement-definitions.html)
and [administration events](https://hl7.org/fhir/R4/medicationadministration-definitions.html).
The native source groups are not FHIR MedicationAdministration resources.

## Imaging observations and conditional guidance

The reviewed selectors are `imaging`, `imaging_results`, `imaging_pending`,
`imaging_available`, `bedside_echo` and `fast_exam`. Four named collections
accept mappings or null; the two standalone fields preserve their raw value.
Each observational entry retains its label, collection, JSON pointer, source
role and detached source data. A metadata label or recommendation is not a
performed study. In the current catalog, 117 source entries in 76 tasks become
115 public records after the two whole-entry exclusions below.

Typed modality, body part, findings, impression, result and status require an
explicit authored string. A scalar string is report text only; a boolean
remains a source assertion. Unknown study labels no longer default to X-ray,
findings are not copied into an absent impression, and nested findings are not
flattened into an invented clinical conclusion. Whitespace and original raw
value types remain available.

Generic `time`, `timestamp` and `time_of_study` aliases follow the
[explicit-time contract](AUTHORED_OBSERVATIONS.md): a complete aware instant
is preserved exactly, otherwise the timestamp stays null with its uncertainty
status. The catalog has one such explicit instant and 114 unresolved/missing
ones. This does not establish acquisition time or a result-availability policy.
[Imaging acquisition](https://hl7.org/fhir/R4/imagingstudy-definitions.html),
[report effective/issued time](https://hl7.org/fhir/R4/diagnosticreport-definitions.html)
and [requested performance time](https://hl7.org/fhir/R4/servicerequest-definitions.html)
are distinct concepts. The native projection does not claim FHIR conformance.

An exact task/path visibility review withholds eight conditional guidance
fields in MW-006, MW-009 and SCJ-017: six nested expected-result fields and two
whole conditional entries. These were not visible through the legacy imaging
projection. Three public notices identify only the affected collection and
omitted-field count, without disclosing target names or values. The injector
also excludes those collections from its fallback clinical-note renderer.
Unreviewed `expected`, `expected_*` or `*_if_ordered` keys within the selected
trees fail before entity mutation. This narrow check is not a general answer
leakage detector. New task formats need a fresh visibility review.

## Verification and remaining limits

TDD regressions use actual injection, MCP handlers and persisted discharge
notes. They exercise lost care, invented administrations, missed interaction
context, partial findings, nested imaging, explicit time, unknown fields and
conditional guidance. The separate catalog witness uses independent reviewed
selectors to compare source care, typed imaging, raw observations, omissions,
identities and audit entries. It retains all 205 scheduled tasks, including
nine without an index-patient section; those nine are unassessed by this
projection. Clinical and safety outcomes are unassessed for every task.

The [frozen checkpoint evidence](../artifacts/validation/20260930/care-imaging-checkpoint/README.md)
contains both catalog witnesses and the final validation logs. The
[baseline reproductions](../artifacts/evaluation-integrity/20260930/care-imaging-v1/README.md)
retain the original defects and failing development checks.

```sh
python scripts/certify_care_imaging.py --output /tmp/new-care-imaging-certificate.json
```

The output path must be new. The certificate hashes code and configuration
and stores the actual outputs; checkpoint manifests hash the completed
artifact separately. These hashes are not independent authentication or
clinical review. The certificate supplies no benchmark score. A separate
[local source-reading probe](LOCAL_MODELS.md#care-source-reading-probe) tests
literal model transcription of a small synthetic fixture, not treatment
reasoning or autonomous tool use.

Clinical content, broad medication reconciliation, observation availability,
versioned rubric corrections, independent physician review and prospective
comparative value remain open. See [task validity findings](TASK_VALIDITY_FINDINGS.md)
and the [release evidence plan](RELEASE_EVIDENCE_PLAN.md). These repairs do not
satisfy the superiority gate or authorize publication claims.
