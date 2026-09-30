# Local models on the v2 reconciliation casebook

This opt-in cohort applies the same public text-command workflow to installed
Nemotron Nano and MedGemma weights on all eight development cases. It measures
source attribution, conservation and persisted documentation. Clinical and
safety criteria remain unassessed; there is no benchmark score or model ranking.

The [frozen plan](../configs/evaluation/reconciliation_model_v2/local-pilot-plan.json)
names all sixteen case/model pairs before inference: in case order, Nano then
MedGemma. Each target has an initial-message hash; both models receive the same
messages for that target. Only target patient/encounter IDs vary in the shared
instruction. Expected rows, counts, conflicts and controls are not supplied.

## Reproduce with installed weights

```bash
.venv/bin/python scripts/reconciliation_local_cohort.py \
  --plan configs/evaluation/reconciliation_model_v2/local-pilot-plan.json \
  --expected-sha256 c6b21023c6eaac2ae1bf0dd764656cf109fc3d1e465fbe07d9347430afa82d49 \
  --output-dir /tmp/hc-local-casebook-v2-new
```

Use a new output directory. The command validates the whole casebook, model
settings and public prompt hashes before output creation or model access.
Aliases must already exist in local Ollama; there are no downloads or paid/cloud
fallbacks. Changing prompts, weights, runtime or settings requires a new plan
identity and evidence directory. Responses are never repaired or retried.

| Setting | Frozen value |
|---|---|
| Runtime | Ollama 0.34.4 |
| Nano alias | `counsel-nano-q5:latest` |
| MedGemma alias | `counsel-medgemma-27b-text-q5:latest` |
| Weight identities | Exact SHA-256 digests in the plan |
| Context / output tokens | 32,768 / 4,096 |
| Maximum model responses | 16 per attempt |
| Seed / temperature / thinking | 42 / 0 / disabled |
| Native request timeout | 240 seconds |
| Worker deadline | 900 seconds, including startup and identity checks |
| Model residency | `keep_alive=0` |

MedGemma uses text completion with a JSON command schema, not native tool
calling or clinical judging. Nano uses the same text-command interface.
Requests omit the thinking field when a model does not advertise it.

## Evidence and termination

The parent owns each fresh native world. A spawned worker receives only public
instructions, schemas and model settings, and sends one validated tool command
at a time. The parent executes real handlers and returns their actual results.
Scenario and expectation documents stay out of worker inputs. This is an input
and process boundary, not a hostile-code filesystem sandbox.

The parent supervises startup, inference and pipe communication with the worker
deadline. Stopping the worker preserves any actual writes in the parent's world.
Native handlers run synchronously in the parent. Worker termination does not
prove that an already dispatched Ollama daemon request was cancelled.

An accepted finish also requires normal worker exit, fresh matching model/runtime
identities, consistent request accounting and the expected public prompt. A
failure receipt cannot become completed execution. The independent v2 verifier
then checks the captured source, state and audit. Normal execution can still
fail the reconciliation content checks.

Each attempt retains its case/configuration/context, durable model/controller
journals, native tool calls, audit, world snapshots, worker identity/cleanup,
mechanical verdict and literal stored/read-back note counts. Exact successful
HTTP response bodies are captured before JSON parsing, including invalid JSON.
HTTP failures retain bounded error detail rather than a full body. Request
counts record attempts, not independently attested server inferences.

Duplicate JSON keys, nonfinite numbers and ambiguous string-encoded tool
arguments are rejected before they can select another patient or masquerade as
a normal stop. Readback counts respect duplicate-note multiplicity: one retrieved
copy cannot stand in for two stored notes. Actual storage and retrieval remain
distinct from the stricter content-qualified verification checks.

The fixed roster retains failed, interrupted, unattempted and ungradable cases.
An interruption stops later attempts but preserves their planned rows. Ordinary
model failures do not remove later pairs. Recording errors remain explicit where
the filesystem permits; a catastrophic output failure can leave a partial
directory without a completion manifest. Preserve that directory separately.

Exit `0` means all executions completed with assessable mechanical evidence and
unchanged implementation identity. It does **not** require task success. Exit `1`
records incomplete, interrupted or changed-implementation execution; exit `2`
reports preflight or output failure. Inspect the separate verification fields.

## Interpretation

Cases and expectations share an engineering authoring ledger. Independent human
label review, operator timing, valid-report adjudication and registered comparison
remain pending. One exposed attempt per model/case cannot establish reliability
or superiority. Earlier v1 pilots remain immutable under their issuing version.
Repository and paper publication follow the
[automated release workflow](RELEASE_EVIDENCE_PLAN.md). Human label review and
operator studies remain future research, not release prerequisites.
