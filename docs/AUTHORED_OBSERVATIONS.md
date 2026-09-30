# Authored observation fidelity

The default task injector preserves authored index-patient vital signs,
laboratory entries, and explicit arrival/triage instants. This repairs source
transport; it does not validate clinical content, establish clinical stability,
or change historical scores. Task YAML, rubric channels, and saved results
remain unchanged. New runs must use their new source/checkpoint identity.
Reproducing an old execution requires its original code and inputs.

## Observation contract

Each projected vital-sign set and lab entry carries a `source_path` JSON
pointer, detached `source_data`, `timing_status`, and `source_time_keys`.
Source paths distinguish similarly named entries and preserve collection
membership. All supported direct patient vital collections coexist; neither
an `or` expression nor array position selects a preferred observation.
`vitals_series` and `serial_vitals` preserve source positions. Nested prior
visits and other patients are not reassigned to the current patient.

Numeric vital fields accept actual finite numbers; text such as `3T`,
`assisted`, and `undetectable` remains verbatim in `source_data` and has an
unknown numeric projection. Orthostatic panels retain their grouping without
inventing a single heart rate or blood pressure. Existing bilateral BP
projection remains available alongside both raw arm readings.

Non-finite numbers and cyclic source containers are rejected before either
injected entity is written; malformed laboratory projections cannot leave a
partial patient. Each laboratory entry remains one entry, including nested panels. Scalar
strings and numbers retain their types. Structured entries project only
explicit scalar `value`, string `unit`, an unambiguous string
`reference`/`reference_range`, and strict boolean `abnormal`. Missing values
are null. Prose is not parsed into diagnoses, units, assay thresholds, or
normality. For example, `below` no longer triggers an abnormal flag because
it contains the substring `low`. Multi-subject panel content retains its
original grouping; it is not flattened into purported single-patient results.

## Time and uncertainty

An observation timestamp requires a complete, timezone-aware authored instant.
Original offsets, `Z`, and arbitrary fractional precision survive unchanged.
Comparisons use UTC whole seconds plus exact fractional digits and behave
consistently on Python 3.10, 3.12, and 3.14. No date, timezone, midnight, arrival
offset, or post-treatment interval is inferred from a label or scenario clock.

Vital measurement aliases are `time`, `timestamp`, and `time_of_vitals`.
Lab aliases are `time`, `timestamp`, and `time_of_result`. The generic name
`time` retains its source role; this projection does not assert specimen
collection time. Multiple aliases must identify the same instant. Distinct
roles such as `last_documented`, `issued`, `updated_at`, and `drawn_time`
remain raw fields and are not coalesced into measurement/result time.

Unresolved instants are null with one of `missing`, `date_only`, `time_only`,
`naive`, `unresolved`, `invalid`, `unsupported`, or `conflicting`. Supported
explicit instants have status `explicit`. Leap-second source text is preserved
but classified `unsupported`, since Python datetime cannot represent it.
Unknown arrival/triage time stays null. Bound searches exclude unknown arrival
instants; unbounded encounter retrieval remains available. Entity creation and
update times use the simulation clock, not the machine clock. The separate
`linked-history/v1` profile retains its existing current-encounter arrival
anchor policy; it no longer assigns that anchor to unknown triage/vital times.

These distinctions follow FHIR's separation of [clinically relevant observation
time and availability](https://hl7.org/fhir/R4/observation-definitions.html),
[dateTime precision](https://hl7.org/fhir/R4/datatypes.html#dateTime),
[resource update time](https://hl7.org/fhir/R4/resource.html#Meta), and
[specimen collection time](https://hl7.org/fhir/R4/specimen-definitions.html#Specimen.collection.collected_x_).
This native projection is not a FHIR Observation export or a claim of conformance
to the [Vital Signs profile](https://hl7.org/fhir/R4/observation-vitalsigns.html),
which requires measurement time. The separate source-document FHIR export
retains its existing contract.

## Transfer consumer

The existing transfer heuristic now determines the latest observation by
explicit time, independently of storage order. Unresolved chronology,
conflicting readings tied at the latest instant, or missing/nonnumeric required
values cannot support its positive result. Existing thresholds are unchanged.
The heuristic is not a clinical stability assessment or legal determination;
it does not validate freshness, source plausibility, observation availability,
or the text of a transfer justification. Transfer policy and clinical content
still need independent review.

## Verification and limits

Focused regressions exercise real `getEncounterDetails`, bounded
`searchEncounters`, and `processTransfer`, including previously lost coexisting
vitals, incorrect arrival timestamps, structured lab fields, qualified GCS,
uncertain timing, and exact fractional ordering. The offline catalog certificate
checks raw source records and time fields through real tool calls, accounts
for all scheduled tasks, and binds its inputs and outputs by hashes. Typed
value/unit/reference/abnormal projections have separate focused tests; they
are not certified by the catalog witness. It supplies no clinical,
safety, model-performance, or superiority score.

The scope is direct index-patient vital collections, the five recognized lab
groups, and explicit direct arrival/triage fields. Broader historical and
multi-patient events require their own reviewed profiles. The subsequent
[care and imaging repair](CARE_IMAGING_FIDELITY.md) removes the legacy
administration and imaging defaults under its own source contract; those
fields are not certified by this observation witness. Task time and world time are distinct, and
this repair does not establish a future-observation availability policy.
Authored clinical assertions, SCJ-012's antibiotic rubric mismatch, and other
content findings remain open. See [task validity findings](TASK_VALIDITY_FINDINGS.md)
and the [release evidence plan](RELEASE_EVIDENCE_PLAN.md).

The [frozen checkpoint evidence](../artifacts/validation/20260930/observation-checkpoint/README.md)
contains the catalog certificate and validation logs. Run a fresh offline witness
with `python scripts/certify_observation_fidelity.py --output /tmp/new-observation-certificate.json`.
The output must not already exist. Exit 0 means mechanical concordance, 1 means
mismatch/drift, and 2 means an input/runtime failure; none denotes clinical validation.
