# Temporal source transport audit at 7d9e54b

Read-only engineering audit, 2026-09-30. No clinical adjudication, grading,
models, paid services, formal red team, task changes or repository edits.

## Reproduction and binding

`reproduce.py` imports the frozen `snapshot/src` tree and loads frozen task
YAMLs. `snapshot-manifest.json` binds 323 copied Python/task/schema inputs with
SHA-256 before and after copying, all equal. HEAD is
`7d9e54b88b9a7b45e5b6a0f0e09307d521ee2d41`; injector SHA-256 is
`a483147ee1499c4a1b0516817c35e841a990fcb4b9690b2e95984e689a0a29fe`.
The copy prevents concurrent root edits from changing this audit's evidence.
`reproduction.json` captures actual in-process MCP responses, not model claims.
`shape-inventory.json` separates corpus shapes from synthetic boundary probes.
`python310-reproduction.json` captures the independently run Python3.10 case.

## Findings

1. **Explicit arrival is overwritten, and date retrieval changes.**
   `inject.py:337-345` selects setting.time as encounter_time, then
   `inject.py:602-603` assigns both arrival_time and triage_time to it, ignoring
   patient.arrival_time. All 205 tasks load; 196 have a top-level patient. Of 19
   explicit top-level arrival_time fields, 16 differ from setting.time and every
   one of those 16 produces zero results from an actual searchEncounters bounded
   exactly to its authored arrival instant. The other three match coincidentally.
   Example TR-024: source arrival10:45, setting13:15, returned arrival13:15. The
   original 10:45 survives in an `Arrival Time` clinical note, so the information
   is not wholly absent: the structured timestamp contradicts the note.
   Another 12 arrival_time fields belong to TR-008's nested roster; they are
   outside default single-patient injection, a previously identified profile gap.

2. **Structured lab fields become Python repr text; explicit time is replaced.**
   `_parse_labs` at inject.py:162-192 stringifies every non-string value and
   stamps all results with its caller's scenario time. It sets unit and
   reference_range to empty strings. TR-024 patient.labs_available.hs_ctni_t0
   authors time10:50Z, integer value18, unitng/L, reference URL14ng/L, and an
   interpretation. getEncounterDetails returns the whole dict as value text,
   empty unit/reference, timestamp13:15, and abnormal=true. The original fields
   remain readable inside the repr; this is loss of structured fidelity plus
   false timestamp substitution, not complete disappearance of the numbers.

   Across the five recognized patient lab groups there are 991 entries:
   677 strings, 69 integers, 102 floats, 143 dicts across55 tasks. Most dicts are
   panels, not a single value/unit result. For example CR-003 CBC and BMP; CR-013
   co-oximetry includes several family members and a group `units` description;
   MW-005 pre_arrest_labs is nested laboratory data. A fix must not flatten these
   into purported single-patient scalar results or discard nested members.

3. **Python3.10 substitutes machine time for standard authored Z timestamps.**
   datetime.fromisoformat(setting_time_str) on Python3.10.18 rejects trailing Z;
   inject.py catches the exception and uses datetime.now(timezone.utc). Actual
   TR-024 arrival and lab timestamp became2026-09-30T09:00:42.650425+00:00,
   with scenario2026-01-15T13:15Z and world2026-01-15T07:00Z. Python3.14 parses
   the same Z string, so the source defect changes behavior across supported
   runtimes. This is not seeded noise. Missing/invalid setting times use the same
   nondeterministic fallback on all runtimes.

4. **Abnormality is guessed from substrings, including metadata.**
   `_parse_labs` searches the stringified whole value for `low`, `high`,
   `positive`, etc. TR-024's `below single-draw rule-in` contains `low`, setting
   abnormal=true without an explicit authored boolean. Absence of one of these
   words yields false, which is not evidence of a normal result. This is a
   transport/unknown-value concern; the audit makes no clinical ruling about
   whether TR-024's assay result is abnormal.

## Current consumers and test gap

- entities/encounters.py:53-62 restricts LabResult.value/unit/reference_range to
  strings, timestamp to datetime, abnormal defaultsFalse. Encounter permits
  unknown arrival_time/triage_time already.
- read_tools.py:46-87 `_arrival_instant` already rejects missing/naive/date-only
  instants, preserves RFC3339 fractional ordering and supports Python3.10 by
  normalizing Z. search_encounters:99-157 uses that arrival instant for inclusive
  bounds; do not weaken this consumer to hide injection discrepancies.
- get_encounter_details:342-384 serializes dataclasses without changing labs.
  The discrepancy is introduced in injection, not this getter. Its optional
  physiology overlay adds current_vitals separately.
- Other runtime references found by `.labs`, `["labs"]`, `get("labs")` are the
  injector and read serializer, rather than a numeric laboratory evaluator.
- tests/test_tasks/test_inject.py currently asserts lab count and display names
  for string inputs, not field values, time, units, type or collection grouping.
- Existing date-filter tests cover dict/dataclass aware/unknown/naive boundaries,
  not real authored tasks passing through injection into those filters.

## Shape contract to preserve

Observed corpus shapes:

- Scalar strings with literal units/ranges/qualifiers, including `<1.0 mg/dL`,
  `>20,000 ng/mL`, `pending — NOT YET DRAWN`, `NOT YET OBTAINED`, and panel prose.
  Preserve these literally; do not infer numeric values, timing, units, completed
  collection status or normality from prose.
- Scalar integers/floats, with no separate unit/time supplied. Preserve numeric
  type in raw/source value; absence of units or event time remains unknown.
- Structured scalar TR-024 record: time/value/unit/reference/interpretation.
  Preserve numeric18 and each exact authored field separately; distinguish
  source time from scenario clock and retain the literal timestamp.
- Structured panels with arbitrary keys and nested values: preserve grouping,
  names and source paths; no flattening or reassigning ownership. SCJ-005 includes
  a `drawn_time` within type_and_screen; that is collection evidence, not proof of
  result availability at that instant. CR-013 uses `units`, not `unit`.
- Additional lab keys (`labs_pending`, `prior_labs`, `labs_not_ordered`,
  `labs_pre_transfusion`, `serial_labs`) currently reach clinical notes, not the
  parsed labs tuple. Preserve this fact and avoid claiming complete structured
  lab coverage. IR-030 serial_labs uses HH:MM times and numeric serial values.
- For the selected temporal key scan (`time`, `time_of_vitals`, `arrival_time`,
  `timestamp`, `collected_at`), 345 strings are aware ISO,38 are bare clock times,
  and3 are annotated/pending text. This is not a census of every possible temporal
  key: drawn_time and semantic key suffixes require separate handling.

Boundary cases to support explicitly (synthetic controls, not claimed corpus
observations): null/missing time or value/unit; naive datetime; date-only;
aware datetime object from YAML; offset time; arbitrary fractions; conflicting
`time`/`timestamp`; nested qualifiers; duplicate-looking panel names; malformed
containers and nonfinite numbers. Missing, invalid, clock-only and naive values
must not silently acquire a timezone, date, event time, or measured result.

Minimal contract proposal:

1. Store a detached JSON-compatible authored lab payload plus exact source path,
   so display/typed projections remain auditable. Prefer an additive raw/source
   field or an explicitly versioned observation projection over repr-only values.
   Preserve nested dict/list/numeric/null types. Copy on ingestion and tool read.
2. Project only explicit scalar result metadata into value/unit/reference fields.
   Retain unknown metadata and distinction between drawn/collection/result times.
   Keep interpretation as authored text; abnormal is unknown unless an explicit
   strict boolean supplies it. Do not derive clinical truth from keywords.
3. Authored aware arrival wins over scenario time. Preserve literal source and
   precision. Explicit unknown/naive/malformed arrival must not become setting.time.
   No-explicit-arrival legacy fallback, if retained, should be documented as
   assumed scenario initialization and separate from source-attested arrival.
4. Use one shared explicit-time parser: normalize trailing Z for Python3.10,
   preserve aware offsets/precision as needed, reject timezone invention. A
   missing/invalid scenario clock should be a clear validation error or a
   deterministic world-clock fallback labelled initialization, never wallclocknow.
5. Do not manufacture triage time from arrival or scenario time. Source arrival,
   triage, collection and result events are different facts. Preserve uncertainty.
6. Group/key order may be deterministic, but do not sort observations into a
   clinical sequence based on invented times. Preserve raw order/source paths.

## High-value regression tests

- Real TR-024 inject→actual MCP getter: source arrival10:45; T0 lab10:50;
  value18 as number, unitng/L/reference/interpretation exact; source dict intact.
  Separate source vs scenario timestamps and no invented abnormal boolean.
- All19 real explicit-arrival tasks: direct equality of instant; exact bounded
  search returns that encounter; neighboring outside bound excludes. Repeat on
  Python3.10/3.12/3.14. Do not alter protected task definitions.
- Missing/invalid setting/time inputs produce stable error/unknown/labelled world
  fallback across two runs; no dependency on datetime.now.
- CR-003 panel, CR-013 multi-subject panel and MW-005 nested pre-arrest data retain
  grouping and literal strings/numbers. Caller and tool-response mutation cannot
  mutate stored raw content.
- SCJ-005 drawn_time remains collection metadata, never inferred result_time.
- Unknown/null/naive/date-only/HH:MM/offset/fraction boundary tests; explicitly
  distinguish unsupported unresolved times from timezone-aware event instants.
- Pending/not-drawn strings do not become completed results or timestamped
  measurements. Numeric0, booleanFalse and empty values cannot be lost by `or`.
- Conflicting timestamp/reference aliases remain visible or reject clearly;
  no silent precedence. Structured dict without `value` stays a panel.

Changing protected clinical assertions is outside this repair. TR-024 prose
contains clinical interpretations requiring independent review; preserving its
source faithfully does not establish their validity.
