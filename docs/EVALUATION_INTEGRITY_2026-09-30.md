# Evaluation integrity and local-model development

This change starts renewed development with measurement correctness. It does
not revise historical benchmark scores, change the Eq. 1 reward, or establish
clinical superiority. Task definitions, rubric overlays, and existing
`results/` artifacts are unchanged.

## Defects reproduced before fixes

Regression tests were written and observed failing before each behavioral
fix. The new tests exercise complete replay, live judging, orchestration,
retry readers, and local tool interaction rather than checking source text.

| Defect | Corrected behavior | Regression coverage |
|---|---|---|
| Replay and training evaluation dropped the requested rubric channel. | Temporal criteria use the selected channel; unknown channel names raise. | `test_replay_contract.py`, `test_reward_channel.py` |
| Replay paired tool responses positionally despite available call IDs, and treated malformed responses as successful. | Persist call IDs; require matching affirmative tool evidence. Legacy ID-less recordings remain supported with their positional limitation. | `test_replay_contract.py`, `test_local_models.py` |
| JSON string `"false"` could become Boolean true in saved/live judge results. | Require actual booleans. Invalid verdicts carry a typed grading error, fail closed, and cannot poison ensemble caches. | `test_verdict_types.py` |
| Resume accepted a filename match after task, prompt, grader, environment, model, or dynamic-state changes. | Content identity includes the task/prompt/overlay, executable source and grading vocabulary, dependency/OpenEM data, routing and available model/runtime metadata. Incompatible or corrupt checkpoints are preserved and refused. | `test_checkpoint_provenance.py` |
| Error trajectories changed safety accounting when resumed; returned API errors could still receive normal scores. | Preserve partial traces and explicit failure stages; interruption and grader failures receive zero reward and separate error accounting. Missing judging is visible as incomplete coverage. | `test_checkpoint_provenance.py` |
| Exhausted tool budgets and token truncation looked like finished trajectories. | Record incomplete termination explicitly and retain the trace. | `test_agent_completion.py` |
| Retries overwrote prior evidence, and retry artifacts could be counted as extra trials. | Create numbered attempts and summaries exclusively. Shared readers select one latest attempt per trial. Resume can repair a missing log entry from its saved trajectory. | `test_checkpoint_provenance.py`, `test_retry_readers.py` |
| A log-write failure could overwrite a successfully saved trajectory with an error shell. | Preserve the saved evidence and surface the persistence error. | `test_checkpoint_provenance.py` |
| `validateTreatmentPlan` rejected its advertised patient/object inputs, crashed on structured allergies, and silently ignored a requested protocol. | Support canonical and legacy inputs, normalize names without changing records, enforce patient/encounter ownership, and explicitly reject unsupported protocol validation. Return the advertised `interactions` field. | `test_treatment_plan_contract.py` |
| Same-clock patient registrations overwrote earlier records and invented unprovided clinical history. | Allocate distinct deterministic identities and linked untriaged encounters; retain supplied demographics and leave missing clinical data unknown. | `test_mutation_contract.py` |
| Structured allergies crashed medication orders and record updates; encounter notes were acknowledged but discarded. | Interpret structured allergy names, preserve record details, and persist notes on the correct patient encounter. | `test_mutation_contract.py` |
| Nested caller/response dictionaries could rewrite records and audit evidence after a call. | Detach structured records, returned data, recorded parameters, public audit views, and world audit snapshots. Registration also retains arrival mode and explicitly unverified supplied insurance data. | `test_mutation_contract.py`, `test_audit_snapshots.py` |
| Discharge ignored canonical medication/instruction/follow-up fields and could mutate disposition before a documentation error. | Validate before the state transition; preserve supplied content in linked, retrievable notes. Missing instructions, follow-up, and medication continuation remain explicitly unspecified. | `test_discharge_contract.py` |
| A truncated judge response could count as a valid verdict if its JSON happened to parse. | Require normal completion before parsing; incomplete or blocked responses carry a grading error. The native smoke also checks completion before dispatch and before declaring success. | `test_verdict_types.py`, `test_local_model_smoke.py` |
| Encounter searches ignored advertised date bounds. | Apply inclusive, timezone-aware bounds without rounding fractional seconds; reject invalid/reversed bounds and omit unknown arrival instants from bounded searches. | `test_encounter_date_filters.py` |

## Local integration

The optional Ollama provider uses installed weights and native tools over a
loopback endpoint. It rejects remote aliases, redirects, proxies, unavailable
models, unsupported tool agents, and invalid agent/judge vendor pairings.
MedGemma is a text-only diagnostic judge in the inspected runtime; Nemotron
and Qwen are tool-capable agents. No hosted API spending or weight downloads
were needed. See [local setup](LOCAL_MODELS.md).

The native smoke demonstrates a real tool round trip and two known-label
judge cases. A subsequent run with completion guards passed both again
in 28.926 seconds on the installed local models. A full IR-001 diagnostic exposed an incomplete 25-call search
loop that the earlier runner scored anyway. The corrected run records
zero reward, one incomplete/error run, seven ungraded criteria, and no
asserted clinical safety failure excluding errors. These are diagnostic
observations, not estimates of model quality. The raw evidence and its
limitations are in [the local run notes](../artifacts/local-models/20260930/README.md).

## Compatibility and limits

Validation after the date-filter repair and reference certificate: `make test` **1,757 passed, two
skipped**; `make preflight` passed; the canonical-number structural audit
passed. `make lint` passed against an export of the staged repository
source (266 Python files). The full suite requires localhost HTTP test
servers, so it ran with local-server permission after the sandboxed attempt
could not bind `127.0.0.1`. The development checkout additionally contains
untracked research archives and presentation scripts with 115 unrelated
lint errors; those files were excluded from the commit and clean export.

The date repair has 58 regressions. Initial date-bound tests exposed 46
failures; later precision and Python 3.10 compatibility cases also failed
before their fixes. Fractional seconds remain exact even when the runtime's
timestamp parser supports fewer fractional digits. Date-only historical
records remain excluded from instant-bounded searches; see the separate
[task validity findings](TASK_VALIDITY_FINDINGS.md).

The subsequent treatment-plan fix has **39 dedicated regressions** (36
failed before the fix), with **116 passing** across the MCP tool and grader
gold-set checks. Independent review exercised canonical medication objects
against all 196 task-injected patients without a normalization/internal
error. The existing drug/allergy rules remain limited simulation rules;
this contract repair does not validate their clinical coverage.

Both named and anonymous whitepaper PDFs build and pass the repository's
verification checks. All 18 pages were rendered for layout review. The
historical result tables remain byte-identical; current architecture,
inventory, reward-boundary, and adjudication descriptions were corrected
against the implementation and released evidence.

Historical V8 and channel replay locks remain unchanged. Old trajectories
are still replayable; they cannot prove compatibility for live checkpoint
resume without the new provenance. Use a fresh output directory for changed
experiments. Read the [retry reader contract](RESULTS_READERS.md) before
using historical analysis scripts on new runs.

Content hashes identify recorded inputs; they are not cryptographic
attestations that a provider served a particular model. Hosted aliases can
change behind the same name. Seeded decoding does not promise bitwise
equivalence across runtimes. Versioned task validity, adjudicated grader
calibration, and held-out transfer remain separate work, described in the
[source-linked design roadmap](EVALUATION_DESIGN_ROADMAP.md).

The existing IR-001 cross-reactivity assertion points to a resource check,
and relevant medication references were not found during the diagnostic.
Those are task-validity audit leads. They are not silently repaired by
changing a historical rubric or treating a low model score as sufficient
evidence that the task is well designed.

## Executable counterexamples

The opt-in [IR-002 execution certificate](REFERENCE_CERTIFICATES.md) now adds
an eight-call reference witness against real tool handlers. Its isolated
profile materializes four linked date-only visits; its independent verifier
checks patient/date scope, grouped source facts, and newly persisted notes.
The 104 focused regressions include seven reviewer-added failures observed
before tightening the verifier. The [saved report](../artifacts/task-validity/20260930/ir002-linked-history-v1.json)
passes four mechanical checks and explicitly leaves all four clinical
criteria, including safety, unassessed. This is a versioned experiment,
not a replacement score for the historical IR-002 task.

`make grader-challenges` runs independently authored synthetic replay
fixtures against the real grader. Its first seven cases cover only two
criteria and expose three false passes: an unrelated bed lookup for an
allergy cross-reactivity assertion, another patient's encounter history,
and empty history where the task specifies prior visits. Failed, missing,
and mismatched tool responses are rejected, and the complete-history
positive control passes. These cases measure no safety criteria; safety
rates are therefore **null**, not zero.

The CLI exits 1 for a mismatch and 2 for a harness error. `--report-only`
allows inspection of known mismatches but does not suppress harness errors.
The [saved v10 report](../artifacts/evaluation-integrity/20260930/grader-challenges-v10.json)
includes the fixture, source, task, and overlay hashes; use
`--output NEW_PATH.json` to save a report without overwriting prior evidence.
Neither the fixture labels nor the seven-case rates are clinical ground
truth, representative error estimates, or new benchmark results.

The existing preflight check is now labeled **Verifier Syntax Reachability**
to describe what it actually proves. A green structural preflight does not
establish task solvability. Fixing these semantic defects requires reviewed,
versioned task/evidence contracts and accessible reference data, with new
positive and counterexample trajectories. Historical task YAML, overlay
definitions, and scores remain unchanged in this repair.

The [task-validity findings](TASK_VALIDITY_FINDINGS.md) document the actual
IR-002 tool behavior, distinguish narrative history from linked encounters,
and specify the next versioned reference-execution certificate.

## Subsequent local development checkpoint

The user subsequently required demonstrated comparative end-user and
healthcare value before formal red-team review, remote-main publication,
and further manuscript updates. The [release evidence plan](RELEASE_EVIDENCE_PLAN.md)
records that order and proposed measurements. This checkpoint is local
engineering work; it does not satisfy the comparative-value gate. The
earlier draft PR remains a prior engineering checkpoint, and the paper has
not received additional edits during this phase.

Additional TDD repairs:

- `system_prompt_append` was documented but discarded by the task loader.
  Live and simulated evaluation now append its literal text once after the
  chosen base or override. Unspecified append values preserve prior prompt
  bytes. Changed policy additions invalidate checkpoint reuse. Long literal
  overrides no longer raise `ENAMETOOLONG` on Python 3.10/3.12.
- Provider pauses, filters, refusals, unknown finish reasons, and inconsistent
  pending tool calls no longer masquerade as completed agent execution or
  dispatch mutations. Original evidence and distinct termination metadata
  remain recorded. Valid blank completion after tool actions remains supported.
- TR-017's authored social-history mapping values now survive injection and
  appear through the actual patient-history tool; existing list inputs remain
  unchanged.

The new [offline evidence report](EVALUATE_YOUR_MODEL.md#offline-evidence-review)
selects numeric latest attempts, exposes original sources, criterion evidence,
and complete traces, and keeps malformed records visible. It separates
execution errors, incomplete/unknown completion, ungraded criteria, abstention,
and rubric failures. Historical `PARSE FAILURE (fail-closed):` evidence is
classified as a grader error even when the archived boolean says `true`.
All saved values remain available; the report does not regrade or correct
historical results. Its content and HTML structure were tested; a browser URL
policy blocked local-file preview, so visual/interactive QA remains incomplete.

Installation commands, CI, and Docker build recipes now consume
`constraints-security.txt`, which pins patched versions of five selected
dependencies. The legacy lock no longer pins HealthCraft itself to an old Git
revision. Actual clean editable development installs succeeded on Python
3.10.18 and 3.12.8; the existing 3.14.3 environment received the five upgrades.
All three environments passed `pip check`. Docker recipes were inspected,
not rebuilt during this local checkpoint.

| Verification | Result |
|---|---|
| Full suite, Python 3.10.18, clean development extras | 1,847 passed, 14 skipped; 98.63 s |
| Full suite, Python 3.12.8, clean development extras | 1,847 passed, 14 skipped; 79.60 s |
| Full suite, Python 3.14.3, existing environment with optional dependencies | 1,859 passed, two skipped; 239.64 s |
| Final report and retry-reader suite, all three runtimes | 71 passed on each |
| `make preflight` | Passed; structural validity only |
| `make smoke` | 48 checks passed, zero failed |
| `make lint`, clean export of staged repository | Passed; 272 Python files formatted |

Full-suite counts precede the last report-only historical parse-marker
refinement; its seven additional regression cases and the affected reader
integration were then tested on every runtime in the 71-test suite. The
minimal development environments omit the optional Google SDK tests; the
existing environment exercises them. Untracked research archives retain their
previous unrelated lint errors and are excluded from the staged export.

The refreshed [native local smoke](../artifacts/local-models/20260930/native-smoke-dependency-refresh.json)
passed in 34.535 seconds: Nemotron completed a real encounter tool round trip,
and MedGemma distinguished two known text fixtures. Its
[provenance](../artifacts/local-models/20260930/native-smoke-dependency-refresh.provenance.json)
records runtime/model identity, upgraded dependencies, start/end times, and
116 unchanged source/configuration hashes. This remains integration evidence,
not a benchmark score or clinical validation. No hosted model calls, weight
downloads, or formal red-team review were performed in this phase.
