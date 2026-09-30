# Native HealthCraft contract for an original synthetic EHR workflow

Read-only engineering feasibility supplement, 2026-09-30. Parent proposal: `/private/tmp/healthcraft-ehr-comparator-feasibility-20260930.md`. This document adds no external benchmark claims and does not change published HealthCraft tasks, criteria, results, source, or the comparator proposal. No model calls, downloads, installs, network calls, external comparator execution, real/deidentified patient data, or clinical inference were used.

## Observed source and reproduction

Observed repository HEAD: `5cd2955502e373d969b66817162587170ce79e8f`, with an actively edited working tree. The exact selected source hashes before and after the offline probe are stored in `/private/tmp/healthcraft-ehr-note-contract-probe-20260930.json`; they matched during execution. These hashes include server, read/mutation handlers, state, entity type, care/imaging projections, recorder and discovery schema. This is development evidence, not a frozen release artifact. Later fixes require fresh observations with new artifact names.

Reproduction (a fresh, exclusive output is required; the recorded file already exists):

```sh
cd /Users/kiteboard/healthcraft
.venv/bin/python /private/tmp/healthcraft-ehr-note-contract-probe-20260930.py
```

The script creates only fresh in-memory synthetic worlds and an exclusive `/private/tmp` JSON file. It validates every request against the real published parameter schema, invokes `create_server(world).call_tool`, records full real responses and audit indices with `ExecutionRecorder`, and inspects separately persisted note entities. Its first setup attempt failed before any tool calls because the temporary probe tried to serialize a dataclass directly; the correction applies `dataclasses.asdict` to snapshots. The successful execution has nine reference calls and seven idempotency-control calls, zero model calls. This is an in-process handler check, not a network MCP or Harbor execution.

## Reusable public tool and state contracts

| Surface | Exact useful contract | Boundary |
|---|---|---|
| `WorldState(start_time=aware_datetime)` | Isolated empty entity store; `put_entity`, `snapshot`, `list_entities`, `get_entity`, append-only copied audit snapshots | Store APIs are coordinator-only. Returned live entity dictionaries are not an agent sandbox. Keep dynamic physiology off. Do not seed unrelated patients or manufacture missing clinical data. |
| `Patient` / `Encounter` | Frozen dataclasses, patient/encounter links, explicit `dob=None`, `esi_level=None`, `arrival_time=None`, `triage_time=None`; no need for generators | Use original explicitly authored dataclasses, not random patient/encounter generators. Creation/update metadata is the simulation clock, not an observation timestamp. |
| `searchPatients({name})` | Actual `status: ok, data: list` of IDs, MRN, name, DOB, sex; name is substring search | Not unique patient identification. Proposed two patients intentionally have the same synthetic name and distinct MRNs. Hard cap 10, no pagination cursor. |
| `searchEncounters({patient_id})` | Actual `data: list` of encounter ID, patient ID, complaint, ESI, arrival, disposition; max 10 | Discovery return description differs from actual list shape. Inclusive date-time filters exclude unknown arrival; use patient filter without invented dates in this fixture. |
| `getPatientHistory({patient_id})` | Flattened serialized patient plus `encounter_ids` and insurance; preserves `prior_visit_ids` | Not a nested `patient` object. Dedicated medication/allergy entities replace corresponding patient collections if present. Avoid those extra collections in the minimal fixture. |
| `getEncounterDetails({encounter_id})` | Full detached serialized encounter, including raw source-bearing care/imaging and `clinical_notes` | No row-level independent read endpoint. Response provenance must bind patient ID, encounter ID, source ID and source path. A source path alone repeats across patients and encounters. |
| `updateEncounter({encounter_id, notes, idempotency_key?})` | Exact string appended as `('Progress Note', text)` to `clinical_notes`; separate `clinical_note` stores content, patient ID, encounter ID, author and world-clock timestamps; updates encounter `updated_at` | Response is full updated encounter, not documented narrow receipt, and does not expose the new note ID. `notes` is a string, not structured JSON. Embed a versioned JSON document as that string for deterministic checking, then render separately. Avoid unrelated advertised `status`/`disposition_details` fields; this workflow only needs notes. |
| Readback + store verification | `getEncounterDetails` reads appended exact text; coordinator `list_entities('clinical_note')` proves separate persisted content and both links | An `ok` response or audit entry alone is not proof of mutation. Compare note-set delta with baseline, require exactly one intended new linked note, existing notes unchanged, unrelated encounters/patients/source collections unchanged. |
| `ExecutionRecorder` | Detached request, response, synchronous call ID, real world audit index; enforces exactly one new audit entry | Call IDs are harness identities, not provider IDs. Unknown-tool path currently lacks a world audit entry and recorder raises; a harness must retain that failed attempt rather than discard it. |
| `trajectory_completion` and unassessed markers | Existing completion/linkage checks and report guards can be reused for actual native model trajectories | Completion, source reconciliation, persisted action and grader availability are distinct axes. A correct write followed by interruption is persisted action success plus incomplete execution. |

Source implementations: `src/healthcraft/entities/{patients,encounters}.py`, `world/state.py`, `mcp/server.py`, `mcp/tools/{read_tools,mutate_tools}.py`, `tasks/{history_execution,care_projection,imaging_projection}.py`, `trajectory.py`. Existing real note/readback tests: `tests/test_mcp_tools/test_mutation_contract.py`, especially the note persistence/idempotency tests. Existing history/roster certificates show detached records + real audit linkage + independent source verification, but their task-specific expected-fact logic is not a drop-in oracle for a new fixture.

## Source representation and identity

Reuse `AuthoredCareRecord(source_collection, source_path, source_data)` and `project_authored_care`: one group preserves an entire selected direct field without converting planned or reported care into `MedicationAdministration`. Reuse `ImagingStudy`/`project_imaging`: typed status/fields are exact supplied strings; raw source data retains an independently authored `source_id`; missing timing stays `None`/`missing`; pending is not a result. These projections do not create a clinical truth adjudication.

The original fixture must own stable globally unique source IDs and a manifest mapping each ID to its patient, encounter, collection and raw JSON Pointer, e.g. `(fixture_sha256, PAT-AAAAAAAA, ENC-AAAAAAAA, SRC-A04, /patient/treatments_given/0)`. `source_path` on grouped care points to the collection, so the per-entry index remains necessary. Validate identity uniqueness, exact links, finite JSON and collisions before any world mutation. Preserve source order and exact strings; don't infer aliases, administration status, dates, timezone, dose, route, diagnosis or availability.

Do not insert hidden `expected`, `gold`, `answer`, `is_error`, cluster or criterion labels in any world entity or tool response. The source manifest exposed to the agent may identify records and collection semantics but must not label which are conflicting. Hidden oracle facts live outside the agent filesystem/store. A hash detects changed content; it does not authenticate a transcript or prove isolation.

## Minimal original fixture proposal

Version: `synthetic-ed-reconciliation/v1`, an explicitly unassessed engineering pilot. Two patients with the same synthetic name `Rowan Example` and different MRNs; three encounters: target current `ENC-AAAAAAAA`/`PAT-AAAAAAAA`, other-patient current `ENC-BBBBBBBB`/`PAT-BBBBBBBB`, and target prior `ENC-CCCCCCCC` with unknown arrival. No invented DOB, age, triage, vitals, diagnosis, administered-care events or clinical significance. An explicit synthetic world clock anchors writes only. No FHIR-conformance claim for this projection.

The actual offline probe supplies these eight original source records. Drug tokens are intentionally opaque synthetic labels, so no pharmacologic correctness is implied.

| Record | Scope / authored assertion | Independently authored expected treatment of the evidence |
|---|---|---|
| SRC-A01 | Target current `active_orders`: `synthetic_medication_A`, order ORDER-A01, status planned, time null | Preserve as a plan; time unknown; do not assert administration. |
| SRC-A02 | Target current `current_management`: repeat observation, kind non_drug, status requested, explicit time 14:10Z | Preserve requested non-drug work; do not turn into medication or completed work. |
| SRC-A03 | Target current `current_management`: `synthetic_medication_B`, status null, time null | Preserve legitimate unknowns, not an error solely because missing. |
| SRC-A04 | Target current `treatments_given`: chart A reports EVENT-A01 / synthetic_medication_C administered at 14:05Z | Cite together with A05 as incompatible source assertions for the same stated event; do not choose truth. |
| SRC-A05 | Same event/item/time as A04; chart B reports not_administered | Same unresolved contradiction. The fixture does not establish which source is false. |
| SRC-A06 | Target current `imaging_pending`: STUDY-A01, XR chest, status pending, time null | Preserve pending and unknown time; do not invent imaging findings/acquisition. |
| SRC-A07 | Target patient's other encounter: reported synthetic_medication_A administration, event time null | Attribute to the other encounter; don't carry it into target-current care. |
| SRC-B01 | Different patient: reported synthetic_medication_C administration at 14:05Z | Do not merge merely because name/item/time resemble target records. |

The agent gets the target MRN/current encounter identifier and a source-reconciliation instruction, not this expected-treatment column. Source access is otherwise identical in both arms. If the pilot requests exact coverage of all eight records, expose that collection scope as the task instruction; don't silently grade unrelated hidden retrieval requirements. The more focused alternative is six target-current records plus explicit exclusion controls tested offline; freeze one option before execution.

A JSON note string can have `schema_version`, target patient/encounter IDs, `observations` with exact source references and preserved field values, `unresolved_conflicts` with the pair of source references plus common event ID, and `scope_exclusions` when explicitly requested. No model-produced safety verdict or clinical reward. The independent oracle must parse this schema and compare authored expected facts directly; it must not render the same expected note with the agent's renderer or accept keyword presence as proof. Natural prose can be generated for the review interface after verification and labeled as rendering.

For secondary HealthAgentBench verifier compatibility, A04/A05 could be a single manually authored source-conflict cluster and both source rows eligible citations, under an explicitly documented synthetic label policy. Calling either source factually wrong would overstate the fixture. Planned/pending/unknown records are not error rows. Keep the upstream verifier's unchanged permissive precision threshold and raw outputs separate from the stricter exact-fact, attribution and persistence result; neither becomes a clinical score.

## Confirmed missing correctness boundary

`updateEncounter` uses `_is_idempotent_replay(world, tool_name, key)`, which matches a prior successful tool/key without comparing encounter or payload. The offline probe demonstrated:

1. Initial target note persists as one encounter-note entry and one separate linked clinical_note.
2. Identical retry returns `ok, deduplicated=true` and remains one note (correct control).
3. Same key with changed text returns `ok, deduplicated=true`; changed text is not persisted.
4. Same key for the other patient's encounter returns `ok, deduplicated=true`; that requested note is not persisted.
5. Different key on the other patient persists the requested second note (control).

This is an acknowledgement/action mismatch, not a wrong-patient write. Real request/response/audit/readback/store evidence is in the probe JSON. Proposed TDD repair: bind note idempotency to the original complete relevant request and target, fail changed requests with explicit `idempotency_conflict` before mutation, retain exact retry and opt-out legacy semantics. Verify dataclass and dict worlds, preserved notes and patient linkage, no partial mutation, typed values and canonical tool-name aliases if supported. No production changes made by this audit.

Bounded static extent: the same generic helper is still called by `updateTaskStatus`, `updateEncounter`, `updatePatientRecord`, and `applyProtocol`. The order handler now uses a separate payload-bound contract in the active working tree. Only `updateEncounter` was dynamically reproduced in this audit; don't generalize a tested outcome to every caller without its own probe. A further persistence-drift/idempotency contract should be explicitly decided: replay should not be considered proof if a stored note was removed or altered out of band.

## Smallest implementation sequence

1. Repair the confirmed note idempotency mismatch with red/green tests before a frozen comparator fixture can rely on writes.
2. Author immutable original fixture + independent hidden expectation JSON/schema, without changing any of the 205 published task files. Build a deterministic, all-or-nothing loader creating explicit Patient/Encounter entities and source projection snapshots; attach profile and fixture/source identity to context.
3. Write a separate strict verifier first. Tests must reject wrong patient/encounter/source citation, omitted source, invented status/time/completed care, invalid unknown handling, success acknowledgement without persisted note, duplicate note, source mutation, changed fixture/oracle identity, missing/malformed evidence and interrupted completion. Faithful controls must preserve contradictions as unresolved and unknowns as unknown. Failure of the verifier itself is a separate state, not a model failure or zero clinical score.
4. Run a scripted reference using actual server + ExecutionRecorder, store baseline/final snapshots and separate readback. The current orchestrator `prepare_task_environment` recognizes only the roster profile; this new profile is not automatically supported. Initially keep a small dedicated opt-in harness and unassessed report until source capture can bind the multi-patient fixture explicitly. Do not force it through a one-patient Task snapshot that drops auxiliary records.
5. Add the narrow terminal/Harbor bridge to the same underlying session and allowed tools; don't grant direct Python/store/hidden-file access just to make the terminal arm work. The boundary must actually be exercised/isolation-tested before claiming equivalent access. Preserve each arm's encoding/interface differences and every planned attempt.
6. Only then install the small optional pinned verifier environment and execute the separate secondary compatibility check under parent authorization. No official patient data/bootstrap. A later local model protocol needs a frozen manifest, all scheduled trials, strict call/output/time bounds, raw completion envelopes, before/after model/source identity and separate execution/action/evidence/grader outcomes.

Clinical/safety outcomes remain unassessed, `benchmark_comparable=false`, `benchmark_score=null`, and profile metadata must reach trajectory, experiment and report consumers. No result here establishes clinical relevance, model superiority, safety, patient benefit, a MedAgentBench replication, or an official HealthAgentBench benchmark result.
