# Imaging source audit and proposed visibility contract

Read-only engineering audit, 2026-09-30, HEAD
`aa21717d0fa6454e4e7af51d3f50206ec2c6026b`. No clinical validation,
models, formal red team, paper/repository edits or publication.

## Reproducibility

`reproduce.py` executes real `inject_task_patient` and `getEncounterDetails`
from the immutable `snapshot/src` copy against copied YAML. Manifest contains
326 source/task/tool-schema SHA-256 hashes, equal before/after copying and
again after actual replay. Injector hash:
`ca324d4c8a99a8518b2bbde2150f286ab46e67795f29e6330eee2dac45d26516`.
Use snapshot inputs because root is concurrently repairing medication transport.

`reproduction.json` contains source subtrees and actual MCP output for every
screened candidate; `summary.json` contains mismatch counts; `selector-inventory.json`
contains the complete entry/field inventory and eight exact private withheld paths.
The initial broad lexical screen intentionally retains its one false positive,
SCJ-022 patient_echo, which subsequent explicit scope excludes. Evidence is not
silently rewritten to hide the classification correction.

## Corpus and actual behavior

All205 tasks scanned;196 have a top-level patient. Exact imaging collections:

| Direct key | Tasks | Entry behavior today |
|---|---:|---|
| imaging |69|107 entries:74dicts become studies;32strings and1bool disappear|
| imaging_results |2|4 string entries retained only in a formatted clinical note|
| imaging_pending |1|2 string entries retained only in a formatted clinical note|
| imaging_available |1|1 string entry retained only in a formatted clinical note|
| bedside_echo |1|1 whole dict retained only in a formatted clinical note|
| fast_exam |2|1string and1dict retained only in formatted clinical notes|

The proposed explicit selector covers117 source entries across76 tasks:
76dict/40string/1bool. This is NOT a performed-study count. It includes metadata,
recommendations, pending and conditional statements. SCJ-022 patient_echo is a
roster person named Echo, not an echocardiogram; never recursively collect it.

Current `_parse_imaging` at inject.py:194-255:

- Skips every non-dict child, while `imaging` is excluded from catch-all notes.
  Examples: IR-020 appendicitis report, SCJ-018 CT/CTA statements, TR-018 CT/CTA
  reports, MW-026 `NOT YET OBTAINED`, TR-025 pending CTP/CTA. These entry texts
  are absent from returned imaging AND related notes. This does not claim that
  equivalent facts never appear elsewhere in task descriptions.
- Projects only findings/impression. All38 authored `result` fields disappear,
  including CR-006 CTA pulmonary embolus text and TR-025 CT head result.
- Of74 returned studies,65 carry XR and9 CT.49 received the fallback XR, including
  labels bedside_echo, mri_lumbar and ct_head_noncontrast. No source entry in this
  catalog explicitly supplied a modality or body_part property: all74 typed
  values are derived from keys, not transported source metadata.
- All74 studies receive scenario time;73 have no generic source time and one has
  a different explicit time. TR-025 authors06:45Z but tool returns06:40Z. This
  report does not resolve the task's future-relative timestamp inconsistency.
- 60entries lack impression.14 of those copy findings into an unauthored
  impression;46 become empty impressions. Four authored findings strings lose
  trailing newline whitespace.36 read_by fields and detailed nested-region
  observations are not transported in structured source form.
- Controls reproduce truncated synthesized impression, null becoming literal
  `"None"`, explicit MR/heart becoming inferred XR/cardiac mri, and a nested
  findings dict raising KeyError when sliced to synthesize impression.

The exact direct-entry field inventory (including types/counts) is in
selector-inventory.json. All observed field values inside dict entries are
strings. Important classes: findings24, impression14, result38, read_by36,
interpretation3, status3, generic time1, prehospital_ecg_time1; nested region
observations (ovaries/adnexa/testicles, FAST regions, head/chest/abdomen/pelvis,
echo chamber/function descriptors) remain source text without flattening.

## Exact visibility policy proposed before implementation

1. Select direct patient `imaging`, `imaging_results`, `imaging_pending`,
   `imaging_available` as named collections, not arbitrary lexical matches.
   Select direct `bedside_echo` and `fast_exam` as single source records. Do not
   recurse into prior visits, other patients, source_data, rubric metadata,
   expected sequences or a patient key merely containing echo/CT-like letters.
2. Keep a detached observation-only source_data tree and RFC6901 source_path,
   source_collection and exact study_label. Separate entry provenance from any
   assertion that an imaging acquisition occurred. CR-005 imaging/read_by is
   collection metadata; CC-025 skeletal_survey_recommended:true is a
   recommendation. They need metadata/guidance roles or a separate metadata
   surface, not conversion into performed studies.
3. Strict-string explicit modality/body_part/findings/impression/result/status
   may populate distinct fields exactly. Missing/wrong-typed fields remainNone;
   preserve raw supported types. Do not guess modality from label, body part from
   a key, findings from result, impression from findings, or status from a key or
   prose. Scalar strings go report_text only. Keep whitespace and newlines.
4. Generic time/timestamp may preserve explicit source instant with timing_status
   and source_time_keys, without calling it acquisition time. A dedicated authored
   acquisition/start/report-issued field remains a separate semantic role rather
   than a substitute alias. Keep prehospital_ecg_time as exactly that source role.
   Do not stamp scenario/world time onto any unprovided event. No date inference
   from labels such as ct_head_0625 or prose `Performed at21:10`.
5. Withhold explicit expected_* values recursively inside selected imaging
   records, and whole conditional `_if_ordered` result entries. Do not merely
   rename them into findings/report_text/source_data or copy them into catch-all
   notes. Private certificate may retain full authored subtree and exact withheld
   paths; public tool output must not contain target values or their raw-subtree
   hashes. Public withheld-path/reason metadata may identify omitted guidance
   without revealing its value. A pending source status remains visible exactly.
6. The current eight withheld paths are:
   - MW-006 /patient/imaging/ct_head_noncontrast/expected_finding
   - MW-006 /patient/imaging/ct_angiogram/expected_finding
   - MW-009 /patient/imaging/ct_results/expected_head
   - MW-009 /patient/imaging/ct_results/expected_cspine
   - MW-009 /patient/imaging/ct_results/expected_chest
   - MW-009 /patient/imaging/ct_results/expected_abdomen
   - SCJ-017 /patient/imaging/skeletal_survey_if_ordered
   - SCJ-017 /patient/imaging/ct_head_if_ordered

   All8 are already absent from legacy getEncounterDetails imaging and notes.
   The first6 occur in dicts whose expected_* keys parser ignores; the last2 are
   dropped string children of handled imaging. Withholding these does not remove
   a currently returned tool fact. It prevents a new raw-source projection from
   newly exposing future answer values. No claim is made that related clinical
   information is absent from user-visible scenario text elsewhere.
7. Preserve remaining nested region observations as data, not recursive inferred
   studies. Do not treat imaging_pending or source status NOTYETPERFORMED as
   completed result availability. Time-preserving repair does not adjudicate the
   source's clinical claims or resolve contradictory source chronology.

## Versioning and compatibility inventory

- ImagingStudy in entities/encounters.py:73-81 currently has five nonoptional
  fields: modality/body_part/findings/impression str, timestamp datetime. Widen
  unknowns and add source fields; retain existing constructor compatibility.
- Encounter.imaging is an immutable tuple; generated baseline encounters set it
  to(). No other source constructor for ImagingStudy was found beyond injector.
- read_tools.get_encounter_details serializes Encounter with dataclasses.asdict;
  new source fields will appear automatically, with deep copies. It does not
  interpret imaging modality or chronology. JSON schema only specifies imaging
  as array and has no per-item required string/enum restriction.
- No direct runtime imaging reader requiring str/non-null was found. Treatment
  plans' imaging_ordered and createClinicalOrder(order_type=imaging) represent
  requested actions, not these report records. They should remain independent.
- No current test directly asserts `_parse_imaging` fidelity. Seed/mutation tests
  check imaging=() only. Full candidate suites and captured tool schema should
  still run because asdict output expands.
- Existing observation certificate verifies vitals/labs raw/time only; do not
  silently imply it covers imaging. Add a versioned independent imaging witness
  or explicit new certificate scope/denominators, including visibility omissions.
- This is a changed runtime observation surface even with unchanged task YAML.
  Bind the new source contract/version and module hashes to checkpoints/artifacts;
  do not reinterpret immutable older trajectories as though they had new fields.
  Because all8 blocked targetvalues were not legacy-visible, no optional profile
  is required merely to preserve that existing nonvisibility. Broader visibility
  changes need an explicit versioned contract before evaluation claims.

## Useful TDD cases

- Real CR-006 result remains in distinct result/source_data; not empty or copied
  to findings; modality/bodypart/time unknown unless explicitly authored.
- Real IR-020 string and MW-026 NOTYETOBTAINED survive report_text unchanged,
  while no completion/result-status/acquisition claims are manufactured.
- Real TR-025 explicit06:45Z preserved exactly as generic source time; no
  substitution with setting06:40 or interpretation of future acquisition.
- Real MW-006/MW-009 expected targets absent from the ENTIRE public response,
  including raw source_data, report_text and notes; exact omitted paths accounted
  privately. Real SCJ-017 conditional entries withheld without targetvalue leak.
- Real CR-005 collection read_by and CC-025 recommendation remain metadata,
  never promoted into clinical results; SCJ-022 patient_echo never collected.
- Real MW-033 bedside echo and TR-022 FAST preserve nested groups without
  flattening or inferred studies. Explicit aliases remain separate semantic fields.
- Null/false/numeric/list/dict nested source and whitespace survive raw transport;
  no `.strip`, `str(None)`, dict slicing or stringification fallback.
- Missing/naive/clock-only/invalid/conflicting timestamps stay unresolved; arbitrary
  fractions/offsets preserved; issued and started do not replace source time.
- Input and returned-source mutation do not change stored evidence; private full
  source remains intact while public visibility projection removes only defined
  guidance paths. Catalog witness accounts117 source entries and8 withheld paths,
  not117 completed imaging studies.
