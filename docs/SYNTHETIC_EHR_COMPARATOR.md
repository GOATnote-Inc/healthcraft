# Synthetic emergency EHR comparator feasibility — 2026-09-30

Status: source inspection only. No external code executed, environments installed, dataset/labels downloaded, cloud/model calls, contacts, or repository changes. This does not establish a working comparator, clinical validity, or superiority. It respects HealthCraft's value-evidence → formal-red-team → publication gate.

## Decision

Implement an **original synthetic emergency EHR reconciliation task in the HealthAgentBench/Harbor task format**, with HealthAgentBench's small deterministic data-quality verifier used unchanged as a secondary compatibility output. Add a framework-independent source-and-persistence oracle for the actual workflow. Start with scripted reference and negative executions; defer any model or operator comparison until both runners are demonstrably equivalent in information access and the protocol is frozen.

The proposal avoids dependencies not established for the published MedAgentBench action benchmark: its public loop does not execute POST writes and its reference grader is outside the repository. If implemented and validated, it would extend the NeMo four-record retrieval pilot by letting a reviewer inspect source contradictions, unknown status/time, cross-patient attribution, a persisted reconciliation note, and separately classified execution/grader failures.

Use the description **“HealthCraft-authored synthetic Harbor workflow, adapted from HealthAgentBench's task/verifier interface.”** Do not call its results the HealthAgentBench benchmark score, MedAgentBench replication, physician validation, or a test of treatment appropriateness.

## Exact source pins and inspected material

- MedAgentBench: `stanfordmlgroup/MedAgentBench@99260117137b09f04837a8c18d18a1107efa55ae` (HEAD dated 2025-11-21). [Pinned source](https://github.com/stanfordmlgroup/MedAgentBench/tree/99260117137b09f04837a8c18d18a1107efa55ae).
- HealthAgentBench: `microsoft/HealthAgentBench@bcbb8085fd549469e2dc7455f4bfd68a1b98895a` (HEAD dated 2026-09-09). [Pinned source](https://github.com/microsoft/HealthAgentBench/tree/bcbb8085fd549469e2dc7455f4bfd68a1b98895a).
- Only source/docs/manifests/licenses were fetched to `/private/tmp/healthcraft-ehr-comparator-source-qak34731`. Its `manifest.json` records paths and Git blob IDs. No task-instance JSON, source patient rows, gold labels, images or model weights were fetched.

## Execution and verifier contracts

### MedAgentBench

The [task class](https://github.com/stanfordmlgroup/MedAgentBench/blob/99260117137b09f04837a8c18d18a1107efa55ae/src/server/tasks/medagentbench/__init__.py) accepts configurable `data_file`, `func_file`, `max_round`, and `fhir_api_base`. Its case input uses at least `id`, `context`, and `instruction`. `start_sample(index, session)` awaits `Session.action()`, injects feedback, and returns `TaskOutput` with completion/error/context-limit/invalid-action/round-limit status. [Default configuration](https://github.com/stanfordmlgroup/MedAgentBench/blob/99260117137b09f04837a8c18d18a1107efa55ae/configs/tasks/medagentbench.yaml) sets eight rounds and localhost FHIR.

The agent speaks one text action per response:

- `GET url?params`: real HTTP GET; appended `_format=json` query parameter. Responses are injected as user-role feedback.
- `POST url` followed by JSON: the pinned loop parses JSON and acknowledges success, but sends no HTTP POST and performs no state mutation (lines 85–91).
- `FINISH([...])`: marks completion, preserving the inner text as `result`; the loop itself does not validate this as JSON.

This is an execution-contract observation, not a claim that the published benchmark is invalid: its absent reference verifier could inspect proposed actions in history. It cannot establish persisted-write correctness from the public loop alone.

The [evaluation dispatcher](https://github.com/stanfordmlgroup/MedAgentBench/blob/99260117137b09f04837a8c18d18a1107efa55ae/src/server/tasks/medagentbench/eval.py) imports `refsol.py`, chooses a function from the case-ID prefix, passes `(case_data, results, fhir_api_base)`, and accepts only `is True`. The pinned Git tree contains only `__init__.py`, `eval.py`, and `utils.py` under this task directory: **`refsol.py` is absent**. The [README](https://github.com/stanfordmlgroup/MedAgentBench/blob/99260117137b09f04837a8c18d18a1107efa55ae/README.md) directs users to a separate Box download and a dataset-containing Docker image. Neither was accessed.

Additional integration constraints: GET transport has no timeout/loopback restriction; framework strips code fences; task and feedback share the user role; code uses AgentBench/Pydantic v1 interfaces. Keep transport and completion differences explicit. The pinned requirements include the older training/model stack (`fschat`, `accelerate`, `transformers`), so installing the whole environment is not a minimal HealthCraft adapter path.

**Accessible:** task/session protocol, configurable synthetic case/function inputs, HTTP retrieval implementation, code license. **Not established:** reference-grader implementation/license, dataset/image redistribution terms, a local synthetic action verifier, actual action persistence, or end-to-end local model operation. Do not mark the unavailable comparator as failed.

### Microsoft HealthAgentBench

This is a terminal-agent task suite, not the same FHIR text-action service. Each task has `instruction.md`, `task.toml`, `environment/`, and `tests/`. [Project metadata](https://github.com/microsoft/HealthAgentBench/blob/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/pyproject.toml) requires Python >=3.12 and pins `harbor==0.8.0`; the broad project dependencies are unnecessary for the small verifier probe.

Selected concrete component: [combined EHR data-quality task](https://github.com/microsoft/HealthAgentBench/tree/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/tasks/ehr_data_quality_task_combined).

- Input visible to the agent: eight EHR table CSVs under `/workspace/data/csv/`.
- Agent output: `/workspace/submission/flagged_rows.csv`, with `table,_row_id` columns. This is an output-file action, not an EHR order or note mutation.
- [Verifier entrypoint](https://github.com/microsoft/HealthAgentBench/blob/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/tasks/ehr_data_quality_task_combined/tests/verify.py) calls `evaluate(submission_csv, labels_path, log_dir)`; the tests directory/labels are described as verifier-only, not mounted during the agent phase.
- [Actual implementation](https://github.com/microsoft/HealthAgentBench/blob/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/tasks/ehr_data_quality_task_combined/tests/harbor_evaluator.py) is a small Python module depending on pandas. `evaluate(submission_csv: Path, labels_parquet: Path, log_dir: Path, turn_count_override: int | None = None) -> float`. Despite the parameter name, it reads **CSV**, not Parquet.
- Newly authored label CSV must contain `table,_row_id,cluster_id,error_family,error_subtype`. All cells load as strings. Duplicate submitted `(table,_row_id)` pairs collapse into a set.
- Outputs: `reward.txt` (binary float), `metrics.json` (cluster recall, row precision, F1, counts, family/subtype recall, turn count), and `verifier_error.txt` for malformed/missing submissions.
- Actual pass threshold: all error clusters found (`recall >= 1.0`) and **row precision >=0.01**. The function docstring still says `>0.5`; executable constants and comparison are the authority. Preserve both the upstream metric and our independent stricter outcome; do not silently redefine its score.
- Malformed agent input generally yields reward zero plus a diagnostic. Invalid/unavailable label files can raise before that handling. An outer harness must preserve a grader/provenance-error outcome and scheduled denominator rather than call this an agent failure.
- [Environment](https://github.com/microsoft/HealthAgentBench/blob/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/tasks/ehr_data_quality_task_combined/environment/Dockerfile) is CPU Python 3.12 with pandas 3.0.1, plus additional data dependencies. The selected task allows internet by default, and its [bootstrap](https://github.com/microsoft/HealthAgentBench/blob/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/tasks/ehr_data_quality_task_combined/environment/bootstrap.sh) downloads/stages MIMIC-IV-demo on cache miss and verifies corruption against gold labels. **Do not run that bootstrap for a synthetic probe.**

**Accessible:** task layout, callable deterministic verifier and schemas, CPU dependency declarations, hidden-verifier lifecycle pattern. **Not established:** local native-Ollama Harbor agent operation, offline container reproducibility, genuine state-mutation evaluation, fairness of terminal-vs-MCP access, or clinical validity for new synthetic cases. The other EHR ETL task also consumes MIMIC demo data and does not provide an emergency clinical-action API.

## Code and data boundaries

- Both public code repositories are MIT: [Stanford license](https://github.com/stanfordmlgroup/MedAgentBench/blob/99260117137b09f04837a8c18d18a1107efa55ae/LICENSE), [Microsoft license](https://github.com/microsoft/HealthAgentBench/blob/bcbb8085fd549469e2dc7455f4bfd68a1b98895a/LICENSE). Preserve the applicable copyright and MIT permission notice with copied/substantial adapted code; identify pin, path, modifications and provenance. HealthCraft's Apache license does not replace those notices.
- Stanford's [official project description](https://stanfordmlgroup.github.io/projects/medagentbench/) states cases derive from deidentified STARR real-patient records. These are outside this task's synthetic-only authorization. The externally hosted `refsol.py` and Docker data terms were not verified; top-level MIT alone is not evidence of those terms.
- The selected HealthAgentBench EHR tasks use **MIMIC-IV Clinical Database Demo v2.2**. Its [official PhysioNet page](https://physionet.org/content/mimic-iv-demo/2.2/) identifies a deidentified real-patient subset and the **Open Data Commons Open Database License v1.0**. Open access does not make it synthetic or MIT. No data reuse is proposed. The repository's README uses `mimiciv-demo` in some links; PhysioNet's live project slug is `mimic-iv-demo`.
- Author wholly synthetic fixtures and independent expected labels; do not transform/copy published patient records or gold labels. Reuse the verifier interface/code only, with attribution. Clinical experts must separately review any claim of scenario plausibility or clinical importance.

## Smallest implementation-ready step

The subsequent [native contract probe and proposal](../artifacts/evaluation-integrity/20260930/execution-report-v1/native-ehr-feasibility.md)
maps real read/note handlers, supplies an original eight-record synthetic
fixture and records its limited in-process note/readback controls. It also
reproduced a retry acknowledgement defect requiring repair before the
comparison harness can rely on note persistence. This is feasibility work;
no common oracle, Harbor execution or clinical comparison has yet run.

Proposed new fixture: `synthetic-ed-reconciliation/v1` (pilot, never a held-out evaluation case). Select a small authored scenario with multiple patients/encounters, dated and unknown-time observations, medication order/statement/administration distinctions, and imaging request/result distinctions. Introduce only explicit structural/source contradictions with independently authored labels. A pending medication or absent acquisition time is not automatically an error.

Common requested work: retrieve the target encounter's relevant source records, list unresolved contradictions/unknowns with exact source references, and persist a source-linked review note on that encounter. Do not ask for diagnosis, treatment selection, medication administration or inference of missing clinical facts.

Artifacts/contracts:

1. Frozen fixture manifest: authored input SHA256, typed/raw source rows, patient/encounter identities, schema/projection versions, planned opportunity IDs. Hidden expected facts/actions are separate and never agent-visible.
2. Native HealthCraft arm: actual read tools plus existing note-update/readback route. Harbor arm: an original synthetic task with a narrow local CLI exposing equivalent information and note mutation, retaining terminal-agent interaction as a disclosed interface difference. Both start from fresh identical worlds; never use official data-staging scripts or grant either arm hidden source labels.
3. Shared verifier: independent expected source facts plus captured reads and final store readback. Require correct patient/encounter, exact cited source/value/status/time (including explicit unknowns), no invented completed care, one intended persisted note, and completion provenance. Its labels are engineering source-fidelity labels, not clinician gold labels.
4. Secondary upstream verifier: convert only the explicitly labeled contradiction findings to `flagged_rows.csv`, invoke the pinned Microsoft verifier unchanged with our synthetic CSV labels, and retain its raw precision/recall/counts/reward. It cannot verify note content, persistence or clinical correctness; keep these outcomes separate.
5. Trial evidence: immutable predeclared trial roster, full raw requests/responses/action receipts, before/after source and runtime identities, final note readback, raw upstream verifier artifacts, shared oracle results, execution/provider/grader errors, abstentions and unassessed clinical criteria. Failed or missing trials remain in the denominator. No best-of selection or retry replacement.
6. First tests without models: faithful reference; wrong-patient citation/write; one source omitted; invented administration/time; valid unknown preserved; tool success acknowledgement without store mutation; duplicate note write; malformed submission; corrupted hidden label input; interrupted run after a valid write. Verify each expected outcome separately. These are ordinary development controls, not the gated formal red team.

Initial runnable boundary, after a future isolated test environment and new synthetic files exist (not executed here):

```python
# Import only the pinned tests/harbor_evaluator.py after source review.
# Caller creates a new exclusive log directory first; labels are not in agent mounts.
reward = harbor_evaluator.evaluate(
    Path("synthetic-submission/flagged_rows.csv"),
    Path("coordinator-only/synthetic-labels.csv"),
    Path("new-exclusive-trial/upstream-verifier"),
    turn_count_override=recorded_turn_count,
)
```

This adaptation tests workflow/evidence portability, not an independent Microsoft EHR simulator. Documented verifier isolation is not yet a verified runtime boundary.

Start with Python 3.12 and the task's pinned pandas 3.0.1 in an isolated optional environment; resolve/pin transitive dependencies before installation. Do not install the full project or add Harbor/pandas to HealthCraft's core dependencies. Actual Harbor 0.8.0 lifecycle and local-model adapter testing follow only after this offline oracle/fixture boundary passes. The exact native model settings and terminal/MCP affordance differences must be frozen before a comparative pilot.

## Intended value and remaining evidence

The proposed deliverable would give an evaluator/reviewer one evidence bundle showing source fidelity, a real persisted action, upstream-verifier behavior and failure accounting on identical synthetic facts. It can support a later study of operator time to a **valid** report, using the already proposed capped-time/complete-denominator contract in `docs/RELEASE_EVIDENCE_PLAN.md`.

It does not yet establish comparable local agent behavior, end-user time savings, independent clinical relevance, grading calibration, held-out generalization, patient benefit, or superiority over either benchmark/product. No model/operator outcomes have been acquired in this research. Published benchmark numbers cannot be compared to results on our new synthetic task.
