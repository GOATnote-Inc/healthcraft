# Experimental roster observations

`roster-observations/v1` makes selected authored observations from six
multi-patient tasks reachable through existing patient and encounter tools.
It creates 33 distinct patient/encounter pairs across eight source collections.
It is an opt-in execution diagnostic: it has no validated clinical rubric,
benchmark score, or training reward contract. Published task files, historical
results, and default task injection remain unchanged.

## Run a local diagnostic

With an installed tool-capable Ollama model and the repository environment:

```bash
HC_DYNAMIC_STATE=0 .venv/bin/python -m healthcraft.llm.orchestrator \
  --agent-model ollama:counsel-nano-q5 \
  --scenario-profile roster-observations/v1 \
  --tasks CC-022 --trials 1 --seed 42 \
  --results-dir artifacts/roster-profiles/cc022-local-01
```

Choose a new output directory for a new experiment. The example alias is an
installed model on the development machine; use an installed tool-capable
alias on another machine. See [local model operation](LOCAL_MODELS.md).
This command is an example, not a report of an executed run.

The profile disables judging automatically. There is no `--no-judge` flag;
omit `--judge-model`. An explicit judge or dynamic physiology is rejected,
including `HC_DYNAMIC_STATE=1`. Select one supported task ID with `--tasks`;
`--tasks all` includes unsupported tasks and fails profile validation. All
selected source records are validated before trial execution.

## Reviewed observation contract

Only the following fields are projected. Field names refer to the original
task YAML. An allowed field is copied if supplied; no missing value is inferred.

| Task | Root collection | Members | Observation fields | Withheld fields |
|---|---|---:|---|---|
| CC-022 | `patients_requiring_action` | 4 | `bed`, `summary` | `acuity`, `needed_actions`, `time_sensitivity` |
| CC-027 | `incoming_ambulances` | 3 | `unit`, `patient_summary`, `eta_minutes` | `acuity` |
| CC-028 | `incoming_patients` | 7 | `triage_tag`, `summary` | `needs` |
| IR-018 | `patients_requiring_iv_fluids` | 7 | `id`, `condition` | `priority`, `fluid_need`, `esi` |
| IR-023 | `patients_on_norepinephrine` | 3 | `id`, `condition`, `current_dose`, `trend`, `antibiotics` | `note`, `estimated_duration` |
| IR-023 | `patients_at_risk` | 2 | `id`, `condition`, `status` | `note` |
| IR-023 | `icu_requests` | 2 | `id`, `condition` | `current_vasopressor` |
| IR-025 | `incoming_patients` | 5 | `ems_id`, `age`, `sex`, `ems_report`, `ems_triage` | `actual_priority`, `note` |

The selector treats answer-bearing, mixed, or unattributed assessment fields
as withheld whole fields. It does not split clinical prose to extract a
supposedly safe fragment. Withheld paths and reasons appear in profile context
for provenance; their values are not copied into the projected records.
Additional unknown row fields require review and cause validation to fail.
Reported EMS triage and casualty tags remain authored observations or identity
labels, not verified clinical priorities.

The original task description remains visible and may itself contain guidance
or answer-bearing information. This profile therefore does not establish a
blinded reasoning evaluation. Withheld information and missing source facts
may limit full-task solvability; making the selected observations reachable
does not establish that every original criterion can be satisfied.

## Records and retrieval

The builder creates sparse dictionary records with `authored_observations`,
task/source identity, and profile version. Each encounter links to its own
patient, has `arrival_time: null`, and starts with empty `clinical_notes`.
These are experimental, non-FHIR projections, not complete clinical records.
No name, birth date, triage level, vital signs, treatment, arrival instant,
bed allocation, or other absent fact is fabricated. Incoming people are not
marked as having arrived, and ICU requests are not converted into ED arrivals.

IDs are deterministic from profile version, task ID, collection, and source
identity. Duplicate labels, malformed records, wrong counts, unsupported task
IDs, and existing ID collisions fail before any profile record is added.
Reapplying the profile to the same world fails rather than overwriting it.
Records are not merged with seeded people merely because a bed or label
matches. Context and observation values are copied, preventing caller aliases
from rewriting the projection.

The appended agent context contains the roster labels, patient IDs, encounter
IDs, and source context. The agent retrieves observations using:

```text
getEncounterDetails({"encounter_id": "<roster encounter ID>"})
getPatientHistory({"patient_id": "<roster patient ID>"})
```

Direct IDs matter: ordinary searches retain their existing filters and
pagination limits. Sparse roster records do not acquire searchable names or
known arrival times. Support for this projection does not establish that
every clinical mutation or workflow accepts sparse records.

## Evidence and interpretation

The orchestrator records `scenario_context`, including `profile_version`,
`source_sha256`, `contract_sha256`, membership, and withheld-field provenance.
The source hash covers canonical parsed task data; it is distinct from a
raw YAML file hash. Checkpoint identity includes the selected scenario
profile, task source, executable environment, prompts, and model settings.
Changing the profile, source, implementation, or local model identity cannot
silently reuse a checkpoint with a different identity.

Profile runs report `evaluation_mode: "profile_diagnostic"`,
`grading_complete: false`, `benchmark_comparable: false`, and
`benchmark_score: null`. All original criteria remain ungraded. The legacy
trajectory `reward: 0.0`, `passed: false`, and failed safety-gate fields are
placeholders for an unassessed result, not measured clinical failure or an
Eq. 1 benchmark score. Summary `pass_rate`, `avg_reward`, `total_passed`,
`safety_failures`, and `safety_failures_excl_errors` are `null`, making the
absence of assessment explicit. Read `ungraded_criteria`, `error_runs`, and
`safety_not_assessed_runs` with the trajectory. Interrupted runs also retain
the ungraded profile context; an execution error does not establish a
clinical safety failure.

The separate `verify_roster_retrieval(task, context, calls, world)` helper in
[`roster_certificate.py`](../src/healthcraft/tasks/roster_certificate.py)
checks exact observation retrieval and final record concordance against
authored source data. It requires ordered synchronous captures containing
`id`, `name`, `params`, `response`, and `audit_index`. The IDs identify harness
captures, not provider tool calls. A complete certificate requires successful
`getEncounterDetails` evidence for every roster member; retrieving one member
repeatedly does not cover others. This helper is separate from clinical task
grading and is not automatically invoked by the orchestrator command above.

Its `roster-retrieval-mechanical/v1` result measures source transport only:
zero clinical or safety criteria are assessed. The world audit binds call
metadata and status, not the complete returned payload. Captured responses
and the final world are trusted in-process evidence; content hashes do not
authenticate an externally supplied transcript.

`HealthCraftEnv.reset(..., scenario_profile="roster-observations/v1")` exposes
the same opt-in projection to environment callers and rejects combining it
with dynamic physiology. The training reward
function rejects a trajectory carrying a scenario profile in
`metadata.scenario_context`; no training reward contract has been validated
for these records. Preserve that metadata when transporting a trajectory.
Neither a successful retrieval certificate nor a completed local run
demonstrates clinical superiority, safety, or deployment readiness.

The [six-task reference execution](../artifacts/task-validity/20260930/roster-observations-v1.json)
retrieved all 33 members through 66 audited calls, with unchanged source/runtime
provenance. All 63 original criteria remain unassessed. A separate
[native Nemotron trial](../artifacts/local-models/20260930/cc022-roster-nano/README.md)
on CC-022 exhausted 25 tool rounds without retrieving detailed observations
or producing a final response. The scripted witness and incomplete model
trial are different forms of evidence and must not be combined into a score.

Experiment logs retain profile, grading, and completion markers. The analysis
script keeps all selected trials in its counts and nulls benchmark metrics
for a cohort containing unassessed records. Planner historical rates exclude
unassessed entries after retry selection. Benchmark replay, release builders,
and paper metric tooling reject explicitly unassessed inputs instead of
silently scoring them or dropping them from a benchmark denominator.

## Bounded IR-018 content review

A separate review flagged the categorical lactated Ringer's (LR)
contraindication/suboptimality premise in `IR-018-C05`, attributed there to
lactate metabolism during severe DKA acidosis. The task and rubric have not
been changed. The reviewed YAML SHA-256 is
`580af4a4cefe52de8fa7eb5a1478fdfb38ed23eb94a977b62b63810297faff87`.
The preserved [review artifact](../artifacts/task-validity/20260930/ir018-c05-content-review.json)
contains the exact assertion, population limits, source locations, and
review provenance.

The 2024 joint adult hyperglycaemic-crisis consensus permits isotonic saline
or balanced crystalloids, explicitly including Ringer's lactate, in adults
without renal or cardiac compromise. It does not support a blanket
acidosis-based exclusion. This is an endorsed expert consensus report,
not itself an ADA Standards recommendation.
[Adult consensus, Fluid therapy](https://link.springer.com/article/10.1007/s00125-024-06183-8).
The [2026 ADA hospital Standards](https://diabetesjournals.org/care/article/49/Supplement_1/S339/163925/16-Diabetes-Care-in-the-Hospital-Standards-of-Care)
retain crystalloid pathways adapted from that consensus; the review accessed
publisher-indexed text when direct HTML retrieval failed.

Pediatric protocols require separate interpretation. The
[ISPAD 2022 guideline, sections 6.3.2–6.3.3](https://www.ispad.org/static/6dd62eae-c8cb-4b4a-84e1efc768505746/Ch11PediatricDiabetes.pdf)
specifies saline for initial resuscitation and allows balanced salt solutions,
including LR, for subsequent deficit replacement. The
[Canadian Paediatric Society guidance](https://cps.ca/en/documents/position/current-recommendations-for-management-of-paediatric-diabetic-ketoacidosis)
also recognizes balanced crystalloids as pediatric DKA options. These sources
do not justify extrapolating adult volumes or monitoring to children.

The authored Bed 7 record gives no age or case-specific organ compromise.
Saline remains an acceptable option; the review does not establish that LR
is mandatory or universally superior. Insulin admixture and IV-line
compatibility were outside scope. C05 is one of ten binary criteria and is
not marked safety-critical: faithful enforcement of its disputed premise
could change one criterion and all-criteria pass status, but no model grading
effect was measured. A clinical-content correction needs separate versioned
review of the linked description and fluid-need wording; this observation
is neither a full task validation nor a formal red-team assessment.
