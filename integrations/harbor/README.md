# Original synthetic reconciliation through Harbor

This optional adapter runs the same public five-tool reconciliation exercise
through a private HealthCraft service and a terminal client in Harbor 0.8.0.
It uses original synthetic records. It does not download or execute an upstream
patient-data task, and it is not an official HealthAgentBench benchmark result.

The coordinator grades source fidelity, the actual stored note and readback
using HealthCraft's independent mechanical oracle. The captured Harbor task's
own verifier checks terminal connectivity only. A no-op can receive its reward
of `1` while failing every required persistence action. Neither reward is a
clinical or patient-outcome measure.

## Pinned components

- Harbor 0.8.0, commit `22b83271db78ef4bcbeb2402cdd154979cf87912`,
  [Apache-2.0 source](https://github.com/harbor-framework/harbor/tree/22b83271db78ef4bcbeb2402cdd154979cf87912).
  Wheel SHA-256: `1ccbc327c0bbd204d828b995dc47307c92df2c1e58d625f5ac1b90808553b9fd`.
- Official Python 3.12 slim Bookworm image manifest:
  `sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e`.
  The included dependency lock targets Python 3.12 on Linux aarch64.
- The terminal client is the standalone standard-library file
  `src/healthcraft/reconciliation/terminal.py`. The agent image contains that
  file and Python, without the HealthCraft world or expected answers.
- The private backend uses real HealthCraft handlers, source-preserving
  projections, idempotency and audit logging. Its dependencies are installed
  offline with hashes. Build contexts must be staged explicitly; do not copy
  the repository, credentials or result directories into an agent image.

The local SDK runtime uses an intentionally reduced dependency closure for
actual `Trial.create`, `Trial.run`, DockerEnvironment and task checksums.
It is not a metadata-complete Harbor installation. The first reduced runtime
omitted `pathspec`; the resulting failed scheduled attempts are retained.
The corrected runtime contains 65 pinned distributions. Set
`LITELLM_LOCAL_MODEL_COST_MAP=True` and `LITELLM_MODE=PRODUCTION` **before imports**
to avoid a remote pricing-map lookup and automatic `.env` loading. No LiteLLM
completion call or cloud-model fallback is used.

## Transport and visibility

The agent sees only the public instruction, five discovered schemas and real
tool responses. A separate coordinator credential finalizes the backend and
writes evidence to a private mount; the public route cannot retrieve its world
snapshot or expected-answer file. Credentials must differ. Finalization is
write-once. HTTP framing errors, rejected tools, lost responses and incomplete
execution remain separate from successful actions.

Attach the agent and backend to an explicitly internal Docker network. Harbor
0.8.0's `allow_internet=false` sets `network_mode:none`, which also prevents
access to that local service; the captured task therefore uses
`allow_internet=true` plus the internal network. The flag itself is not an
egress guarantee. Inspect the actual task container and report only the
network checks actually observed. On the tested Docker Desktop runtime,
internal-only networking did not publish a backend host port. The direct arm
therefore uses a fixed coordinator `docker exec` HTTP bridge to backend
loopback. This is **direct HTTP via the coordinator**, not native model MCP
calling, and it is not a measure of operator effort or interface latency.

Before agent execution, the helper runs a fixed standard-library probe inside
the actual Harbor task container: backend TCP reachability, one TCP connection
to `1.1.1.1:443`, hostname, and absence of five specified private paths. The host
then inspects that container's `Networks`, `Mounts` and `Image`; it does not dump
environment variables. Raw probe exits/output and the inspection are retained.
These observations cover that container at setup time. A blocked connection to
one destination and absence of selected paths do not establish comprehensive
egress control or isolation.

Harbor's shared `/logs/verifier` mount is writable during the agent phase.
Consequently its reward file is not an independently trusted task-success
signal. The host coordinator's private state capture and independent oracle
remain authoritative for this narrow development exercise. This is a tested
research harness, not a general multitenant clinical service or a completed
formal security review.

## Scripted lifecycle

Prepare an original task directory containing `instruction.md`, `task.toml`,
`environment/docker-compose.yaml`, and `tests/test.sh`. Start a fresh private
backend on the task's internal network. Provide the public token only to the
agent container through `HC_RECONCILIATION_TOKEN`, and its service origin through
`HC_RECONCILIATION_URL`. The token files and private evidence mount belong only
to the coordinator/backend. Use exclusive output directories for every attempt.

With the pinned optional SDK runtime and source checkout on `PYTHONPATH`:

```bash
LITELLM_LOCAL_MODEL_COST_MAP=True LITELLM_MODE=PRODUCTION PYTHONPATH=src:. \
  /path/to/harbor-runtime/bin/python scripts/harbor_reconciliation_trial.py \
  --task-dir /path/to/original-task --output-dir /tmp/hc-harbor-reference-01 \
  --patient-id PAT-AAAAAAAA --encounter-id ENC-AAAAAAAA --mode reference \
  --timeout-sec 180
```

The host supervisor must impose a hard process deadline in addition to SDK
cancellation, finalize the private session on success or failure, retain every
scheduled attempt, and remove only its own containers/networks. Use
`EnvironmentConfig(delete=False)`; the default cleanup can remove images.
Preserve raw CLI exits/output, the actual Harbor result, backend journals and
source/runtime identities. A normal controller termination is not a passed
oracle or a clinical-readiness claim.

The [v4 scripted controls](../../artifacts/reconciliation/20260930/harbor-transport-v4/README.md)
record four scheduled attempts and zero model calls. Both references passed
the five mechanical checks after ten tool calls, including an identical write
retry and exact note readback. Both no-ops failed the required source/persistence
checks; the Harbor no-op still received its connectivity reward. Earlier infrastructure
failures remain retained. These controls establish the exercised lifecycle,
not model performance or clinical value.

## Local model lifecycle

The model adapter uses the same `CommandController` and native Ollama client as
the direct HTTP arm. It sends text messages with `tools=None` to the fixed
loopback origin `http://127.0.0.1:11434`. The model must return one strict JSON
command: `{"action":"call","name":"<advertised tool>","params":{}}` or
`{"action":"finish"}`. The adapter executes fixed terminal commands, never
model-authored shell. It does not repair malformed responses or retry a failed
attempt. The five tools are `searchPatients`, `searchEncounters`,
`getPatientHistory`, `getEncounterDetails` and `updateEncounter`.

Prepare a frozen model configuration with exactly these five top-level fields
and all nine settings. This is a template: replace the alias, model digest and
prompt digest before use; placeholder digests are rejected.

```json
{
  "model": "REPLACE_WITH_INSTALLED_ALIAS",
  "expected_digest": "REPLACE_WITH_64_LOWERCASE_HEX_MODEL_DIGEST",
  "expected_runtime": "0.34.4",
  "initial_messages_sha256": "REPLACE_WITH_64_LOWERCASE_HEX_PROMPT_DIGEST",
  "settings": {
    "max_model_responses": 16,
    "max_output_tokens": 4096,
    "num_ctx": 32768,
    "seed": 42,
    "temperature": 0.0,
    "think": false,
    "request_timeout_seconds": 240,
    "attempt_timeout_seconds": 900,
    "keep_alive": 0
  }
}
```

Freeze `initial_messages_sha256` from the actual public instruction and tool
discovery before inference. The exact calculation is
`hashlib.sha256(canonical_json(controller.snapshot()["messages"]).encode("utf-8")).hexdigest()`,
using `CommandController` and `canonical_json` from
`healthcraft.reconciliation.controller`. Both arms repeat that calculation
against their actual inputs before constructing or preflighting the model
client. Missing or invalid configuration fails preparation; a digest mismatch
retains the observed messages in `initial-prompt.json` and fails before model
access. Do not replace the expected digest to accept a changed prompt after
observing an outcome. Preflight requires matching model/runtime identities;
postflight checks them again when execution permits. Missing postflight after
interruption is retained and cannot establish completion. The shared
configuration disables thinking; the native
client omits the unsupported `think` wire field for completion-only models.

Run one separately scheduled Harbor model attempt with a fresh backend and
exclusive output directory:

```bash
LITELLM_LOCAL_MODEL_COST_MAP=True LITELLM_MODE=PRODUCTION PYTHONPATH=src:. \
  /path/to/harbor-runtime/bin/python scripts/harbor_reconciliation_trial.py \
  --task-dir /path/to/original-task --output-dir /tmp/hc-harbor-model-01 \
  --patient-id PAT-AAAAAAAA --encounter-id ENC-AAAAAAAA --mode model \
  --model-config /path/to/frozen-model.json --timeout-sec 900
```

The patient/encounter arguments remain required by this CLI; model mode does
not add them to the controller's messages. Its task information comes from the
actual instruction and tool responses. The corresponding direct HTTP runner
accepts the same frozen model configuration:

```bash
PYTHONPATH=src:. /path/to/harbor-runtime/bin/python \
  scripts/reconciliation_model_trial.py \
  --model-config /path/to/frozen-model.json \
  --instruction /path/to/original-task/instruction.md \
  --output-dir /tmp/hc-direct-model-01 --backend-container BACKEND_CONTAINER_ID
```

For both arms, the parent supervisor must enforce a **900-second hard process
deadline** covering runtime startup, setup/probes, preflight, inference, tool
dispatch and postflight. Backend container startup precedes that phase; bounded
cleanup and private finalization follow it. The common native request/socket
timeout is **240 seconds**, including metadata checks. Harbor's
`--timeout-sec 900` and the controller's deadline are cooperative limits;
async cancellation cannot terminate a blocked native client thread. Late
thread events may be journaled but cannot restore completion or dispatch a
new command after cancellation. A supervising process is still required.

Retain `scheduled.json`, the normalized configuration, initial prompt, raw
terminal exchanges, agent receipt and Harbor result, including failures and
timeouts. Harbor's `initial-prompt.json`, `model-events.jsonl` and
`terminal-exchanges.jsonl` are under the trial's `agent/` log directory. The
direct runner writes `initial-prompt.json`, `model.jsonl`, `controller.jsonl`
and `transport.jsonl` in its output directory. An explicit model `finish` is
termination only. Neither a
CLI argument, exit code, controller completion nor Harbor connectivity reward
declares source fidelity, persistence or clinical success. Obtain the separate
mechanical checks from the finalized private backend; clinical assessment
remains unassessed. The scripted evidence linked above contains no model runs.

## Explicit structured command decoding

The [first model pilot](../../artifacts/reconciliation/20260930/local-model-pilot-v1/README.md)
retains four command-format failures before tool use. It used the five-field
configuration above, with no native `format` field. Its results are unchanged.

An optional sixth configuration field, `command_format`, selects a separately
versioned decoding condition. Obtain its exact `{version, sha256}` identity
from `command_format_identity()` in
`healthcraft.reconciliation.controller`; the version is
`healthcraft-reconciliation-command/v2`. Freeze this identity before the new
roster starts. Both adapters validate it before model access and pass the same
identity to the controller and local client. Unknown versions, changed schema
digests, missing identity members and explicit null are rejected. Omitting the
sixth field retains the original unconstrained wire behavior.

The native Ollama request receives a top-level `format` JSON Schema with two
closed alternatives: a call with an advertised tool name and object parameters,
or a finish marker. Parameters remain open; their actual validation belongs to
the tool handlers. The schema contains no expected source facts or note content.
Its identity is separate from `initial_messages_sha256`, because message hashes
do not cover decoding settings. The complete native schema is recorded before
dispatch, alongside raw responses and errors.

Ollama documents [native structured output](https://docs.ollama.com/capabilities/structured-outputs)
and its pinned runner supports a [subset of JSON Schema](https://github.com/ggml-org/llama.cpp/blob/b11081/grammars/README.md).
Constrained decoding does not replace strict response parsing, native completion
checks, tool validation, source verification or readback. An unsupported format
fails the attempt; no unconstrained fallback, fence repair or retry is applied.
Changes after inspecting an earlier cohort require a fresh protocol and roster,
and cannot be presented as a held-out comparison.

The [third local cohort](../../artifacts/reconciliation/20260930/local-model-pilot-v3/README.md)
exercised both transports after a tested macOS source-path alias repair. Four
attempts completed with 22 native requests, 18 tool calls and four stored notes.
Saved native requests matched at every turn across arms within each model.
All four notes failed the independent reconciliation contract because scope
exclusions were wrong. MedGemma performed note readback; Nano did not. Reading
back an incorrect note does not satisfy the oracle's correct-note verification
axis. This is an open-fixture development result, not a reliability estimate,
clinical assessment, operator study or superiority claim. The earlier format
and preparation failures remain in their original cohorts.
