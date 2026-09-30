# NeMo Gym counter integration probe — 2026-09-30

This is a bounded integration feasibility record for a synthetic arithmetic counter. It is not a clinical benchmark, red-team exercise, or comparison demonstrating product superiority.

## Outcome

The pinned, unmodified NeMo Gym resource server, simple agent, and model adapter can import and run locally in a separate CPU environment. Deterministic counter contracts passed. One actual local Nemotron trajectory reached Ollama, returned through Gym's response converter, and reached the counter verifier, but exhausted its 512-token output budget before issuing a tool call. A successful live model → tool → model roundtrip remains unproven.

| Accounting | Observed |
|---|---:|
| Scheduled / started trajectories | 1 / 1 |
| Completed agent trajectories | 0 |
| Incomplete agent trajectories | 1 |
| Model requests / model-issued tool calls | 1 / 0 |
| Input / output tokens | 288 / 512 |
| Elapsed probe time | 22.19 seconds |
| Initial / final / expected counter | 3 / 3 / 6 |
| Upstream recorded reward | 0.0 |

HTTP 200 means the request completed, not the agent task. Ollama returned `finish_reason=length`; Gym preserved `status=incomplete` and `incomplete_details.reason=max_output_tokens`. The counter verifier returned `mask_sample=false`, so reward/masking alone cannot identify completion. No attempt was rerun or removed from the denominator.

Five deterministic checks passed without network/model access: the shipped sanity test, seed/tool/readback and reward-0/reward-1 verification, cookie session isolation, observed same-session reseed behavior, and invalid-input rejection without mutation. Reseeding is **not a reset** in the shipped example: after reaching 6, `initial_count=100` leaves the value at 6. See `counter-contract-result.json` for actual request/response records.

## Scope and provenance

- Upstream: [NVIDIA-NeMo/Gym at 82e1834ccf2dd578af26a1abc686c15e17569594](https://github.com/NVIDIA-NeMo/Gym/commit/82e1834ccf2dd578af26a1abc686c15e17569594), Apache-2.0. Tracked upstream source remained unchanged. `source-and-dependencies.json` records revision, source hashes, installed versions and package license metadata. See `UPSTREAM_ATTRIBUTION.md` and `UPSTREAM_LICENSE.txt`.
- Installed model: `counsel-nano-q5:latest`, Nemotron family `nemotron_h_moe`, 31.6B, Q5_K_M, digest `36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8`. No model weights were downloaded or copied. Sanitized local metadata is in `model-manifest.json`.
- Runtime: Python 3.13.14, macOS arm64, uv 0.11.24, 136 frozen core packages. The selected core plan contains no Torch, CUDA, FlashInfer, Triton, or vLLM inference engine. Approximate compatible wheel payload: 248 MB; installed runtime environment: 830 MB. The pure-Python ANTLR runtime was built from its 117 KB sdist. No optional development, telemetry, sandbox, codec, or training extras were requested.
- A separate Python 3.14 bootstrap venv held uv only. Its initial stock uv 0.7.19 dry-run could not interpret current dependency exclusions, so it was not used for the actual dependency installation. Python 3.13.14 was downloaded under the probe directory to avoid native builds needed by the installed Python 3.14.
- The three upstream server classes were instantiated directly, with a fresh world/session and explicit loopback sockets. The CLI launcher, head server, environment wrapper, remote data loaders, and distributed Ray execution were not exercised. No source was modified to make the probe run.

## Settings are not matched to HealthCraft

The wire request used temperature 0, `parallel_tool_calls=false`, `reasoning_effort=low`, and `max_tokens=512`; the simple agent allowed at most five model steps. The alias's stored context default is 8192. No context or seed override appeared on the wire. Reasoning was actually produced; `low` did not disable thinking.

These differ from the parent task's reported HealthCraft native settings: context 32768, seed 42, and `think=false`. Consequently this probe cannot support a cross-platform performance comparison. `local-trajectory-01/assessed-outcome.json` makes these differences and the incomplete-trial denominator explicit. A future comparison requires verified equivalent sampling/context/thinking controls before collecting outcomes.

## Captured evidence and isolation

`local-trajectory-01/` contains the exact materialized input, resolved configuration, raw `/run` response, upstream Ollama transport request/response, pass-through ASGI request/response logs for each component, original trial accounting, and a separate assessed outcome. Native `ng_trajectory` observability was disabled; these local raw logs provide the evidence for this probe and do not establish the upstream CLI's capture completeness.

The process ran with a clean environment, no inherited hosted API credentials, telemetry disabled, and Hugging Face offline flags. The only model endpoint was `http://127.0.0.1:11434/v1`; the API key was the literal dummy value `local-not-used`. A Python audit hook rejected non-loopback socket connections/binds and external DNS lookups. This is a process-level guard, not a kernel-level network attestation. Captured connection addresses were loopback. No hosted inference, patient data, judge calls, or remote publication was used.

The harness had a 120-second request timeout and a 150-second process alarm. The completed run took 22.19 seconds. All three temporary server ports were independently checked afterward and returned `ECONNREFUSED`; see `server-cleanup-check.json`. Ollama was released to the parent task. The original Ollama service was not stopped or reconfigured.

## Minimal next step

Before a clinical workflow adapter, define an explicit local-model request contract with the same context, seed, thinking policy, and output budget as HealthCraft, then test its mappings. A later authorized run should establish one completed model-issued counter tool roundtrip. Preserve this incomplete attempt separately. For a common synthetic clinical workflow, add an explicit fresh-session/reset contract, independent intended-patient/fact/persistence verification, and completion-aware scheduled-trial accounting. Those components do not yet exist in this probe.

`COMMANDS.md` records commands actually executed; it is not a promise that re-running all commands against existing paths is safe. `promotion-manifest.json` lists small artifacts suitable for review/preservation. Do not promote the source checkout, virtual environments, runtime download, cache, or raw local model information file.
