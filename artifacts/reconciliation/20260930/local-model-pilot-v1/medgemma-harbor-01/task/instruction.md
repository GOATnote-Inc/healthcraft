# Synthetic source reconciliation

This is an original synthetic record-retrieval and documentation exercise. It does not ask you to diagnose, select treatment, determine which chart is clinically correct, or make a safety assessment.

The target is patient `PAT-AAAAAAAA`, MRN `SYNTHETIC-A`, at current encounter `ENC-AAAAAAAA`. Two synthetic patients share the name Rowan Example. Identify records by their patient and encounter identifiers, not the name alone.

Use `searchPatients`, `searchEncounters`, `getPatientHistory`, and `getEncounterDetails` to retrieve the records. Review all eight supplied source rows: six belong to the target's current encounter, one belongs to a different encounter of that patient, and one belongs to the other patient. Do not merge records merely because item names or reported times resemble one another.

Preserve every target-current row exactly, including its source identifier, status, raw field values and nulls. Requested or planned work does not establish completion. A pending imaging study does not establish findings or acquisition time. A missing status or time remains unknown; it is not automatically an error. A source assertion about administration is not a newly executed administration in this simulation.

When two records explicitly share an `event_id` and have opposing `reported_status` values, document their unresolved contradiction together. Do not choose which report is true or invent a resolution. Cite records outside the target-current scope as exclusions with their actual patient and encounter identifiers.

Persist exactly one note on the target encounter using `updateEncounter`. Supply a JSON document encoded as the `notes` string, with these fields:

- `schema_version`: `healthcraft-reconciliation-note/v1`.
- `patient_id` and `encounter_id`: the target identifiers.
- `observations`: one object for each of the six target-current source rows. Each object contains `source_id`, `patient_id`, `encounter_id`, `source_collection`, `source_path`, and `source`. `source` is the entire exact original row, including its `source_id`; do not replace it with a summary.
- `unresolved_conflicts`: one object per directly evidenced contradiction, containing `source_ids` (the referenced source identifiers), `event_id`, and `field` (the name of the conflicting field).
- `scope_exclusions`: one object for each of the two out-of-scope source rows, containing `source_id`, `patient_id`, `encounter_id`, and `reason`. Use `other_encounter` for the target patient's other encounter and `other_patient` for a different patient.

A `source_path` is an RFC 6901 JSON Pointer within the encounter's original `patient_data`. For care arrays, append the row index to the collection path, such as `/active_orders/0`. Native tool projections display the collection prefix as `/patient/active_orders`; omit `/patient` in the note's path. Imaging rows use the original mapping key, such as `/imaging_pending/study_01`, with `~` escaped as `~0` and `/` as `~1` inside keys. Record identity includes patient, encounter and source ID; a path alone is not unique across patients.

Do not add treatment recommendations, fabricated values, clinical conclusions, new orders or changes to the source records. Do not write notes to the other encounters. If retrying an identical note request, reuse its `idempotency_key`; changed requests require a different key and must not create an additional note for this exercise.

After writing, call `getEncounterDetails` again for the target encounter and check the persisted note content. Conclude only after this readback, reporting any execution or persistence failure explicitly. An acknowledgement of a tool call alone is not proof that the intended note was stored.
