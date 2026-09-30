# Local Nemotron interoperability feasibility

Two attempts were scheduled and both completed, with no retries. Each used the
same installed Nemotron alias to discover four synthetic encounter IDs and
retrieve their source observations. Each made five real tool calls and six
model requests, passed the separate mechanical retrieval check, and closed its
resource session. This is an adapted retrieval exercise, not the original
CC-022 nursing-delegation task or a comparative clinical benchmark.

| Arm | Scheduled / completed | Retrieved members | Real tool calls | Model responses |
|---|---:|---:|---:|---:|
| HealthCraft native `run_agent_task` | 1 / 1 | 4 / 4 | 5 | 6 |
| Pinned NVIDIA NeMo Gym `SimpleAgent` | 1 / 1 | 4 / 4 | 5 | 6 |

`summary.json` preserves the full denominator, source verification, and all ten
unassessed clinical criteria for each arm. The required Gym numeric reward is
scoped to mechanical retrieval; it is not HealthCraft's Eq. 1 benchmark reward.
All benchmark scores are null and zero clinical/safety criteria were assessed.

## Frozen configuration and execution

- Installed alias: `counsel-nano-q5:latest`; digest
  `36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8`.
- Ollama 0.34.4, native `/api/chat`, loopback port 11434 only.
- Context 32,768; seed 42; temperature 0; thinking disabled; 2,048 output
  tokens per response; maximum eight responses; 120-second provider timeout;
  600-second whole-attempt bound.
- Gym source `82e1834ccf2dd578af26a1abc686c15e17569594`, Apache-2.0, isolated
  Python 3.13.14 environment. Native arm used project Python 3.14.3.
- Identical initial system/user content and canonical three-tool schemas.
  Each fresh world contains only the four authored roster pairs, without
  seed-world distractors. No expected IDs or observations enter the prompt.
- Clean process environments with no hosted credentials; no model downloads,
  service changes, hosted inference, judges, or training calls.

The exact executed harnesses are `native_arm.py` and `gym_arm.py`. They require
the local paths recorded in the artifacts and reject existing output directories.
Native used `--execute-local`; Gym used `--live`. Their fake modes were checked
first in the [offline contract evidence](../nemo-roster-contract/README.md).
The parent additionally bounded the Gym process group to 600 seconds because
async cancellation alone cannot immediately stop its blocking provider thread.
No timeout occurred. The model service was already running and was not changed.

The Gym attempt used actual SDK agent/model/resource interfaces and routing
through in-process ASGI. Only provider requests used a network socket. It does
not test distributed server startup, network MCP transport, or a training loop.

## What matches, and what does not

The first native request objects are exactly equal. All twelve actual model
requests match the fixed sampler/context/thinking settings. Later request text
is not byte-identical: HealthCraft's native agent serializes returned tool JSON
with spaces, while Gym preserves compact FastAPI JSON. This difference was
identified before the Gym live attempt and retained rather than adjusted after
seeing one arm's output. Both keep the same source data and tool semantics.

All 339 recorded source/configuration hashes remained unchanged for each arm.
All five captured tool results in each arm replayed exactly in a fresh world;
the independent source verifier covered all four members. Native's additional
request/trajectory-prefix check is in `native-post-validation.json`.

Native ran first, then Gym. Raw durations (9.15 and 4.81 seconds respectively)
remain in the artifacts as diagnostics. Sequential order, cache warmth,
interpreter/controller differences, and one attempt per arm preclude a latency
or reliability comparison. The different prompt, world, budget, and corrected
schema also prevent treating this as a measured improvement over the older
incomplete original-task CC-022 diagnostic.

## Evidence and remaining scope

`native/` and `gym/` retain immutable schedules, raw parsed provider chat
envelopes, trajectories/framework captures, resource snapshots, verification,
and cleanup. `promotion-manifest.json` hashes every copied file and lists 21
omitted metadata envelopes: raw model/runtime inventory can contain private
filesystem paths and is unnecessary to reproduce chat evidence. Normalized
model identity/capabilities remain. Originals are unchanged in temporary storage.
These are parsed JSON captures, not authenticated byte-level network recordings.

This artifact demonstrates one local interoperability path. It establishes no
advantage over NVIDIA, Corecraft, Baseten, Archangel Health, or other systems;
no medical accuracy, clinical safety, healthcare outcome, or deployment claim;
and no prospective study or formal red-team result. The release value gate
remains open.
