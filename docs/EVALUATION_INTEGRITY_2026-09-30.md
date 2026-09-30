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

## Local integration

The optional Ollama provider uses installed weights and native tools over a
loopback endpoint. It rejects remote aliases, redirects, proxies, unavailable
models, unsupported tool agents, and invalid agent/judge vendor pairings.
MedGemma is a text-only diagnostic judge in the inspected runtime; Nemotron
and Qwen are tool-capable agents. No hosted API spending or weight downloads
were needed. See [local setup](LOCAL_MODELS.md).

The native smoke demonstrates a real tool round trip and two known-label
judge cases. A full IR-001 diagnostic exposed an incomplete 25-call search
loop that the earlier runner scored anyway. The corrected run records
zero reward, one incomplete/error run, seven ungraded criteria, and no
asserted clinical safety failure excluding errors. These are diagnostic
observations, not estimates of model quality. The raw evidence and its
limitations are in [the local run notes](../artifacts/local-models/20260930/README.md).

## Compatibility and limits

Validation at this development checkpoint: `make test` **1,442 passed, two
skipped**; `make preflight` passed; the canonical-number structural audit
passed. `make lint` passed against an export of the staged repository
source (251 Python files). The development checkout additionally contains
untracked research archives and presentation scripts with 115 unrelated
lint errors; those files were excluded from the commit and clean export.

The subsequent treatment-plan fix has **39 dedicated regressions** (36
failed before the fix), with **116 passing** across the MCP tool and grader
gold-set checks. Independent review exercised canonical medication objects
against all 196 task-injected patients without a normalization/internal
error. The existing drug/allergy rules remain limited simulation rules;
this contract repair does not validate their clinical coverage.

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
