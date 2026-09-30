# Restricted local order integration probe

One authorized, free, native Ollama attempt on 2026-09-30; no inference retries.
This probes literal instruction following through one advertised MCP tool in an
isolated synthetic world. It is not an unrestricted clinical agent evaluation.

## Observed result

The attempt completed with two model responses and one actual `createClinicalOrder`
call in 5.933 seconds (outer process: 6.004 seconds). The actual tool response,
audit entry, persisted order and linked clinical task preserve the explicit
`urgent` priority, synthetic indication, nested details, encounter linkage and
world clock. No provider error, truncation or missing completion provenance was
observed. The independent action-fidelity check and integration check passed.

`report.json` contains the request, actual execution recorder calls, world audit,
final persisted state, complete trajectory, normalized provider exchanges,
source hashes, runtime package versions and separate completion/fidelity outcomes.
`trajectory.json` is an exact standalone copy of its trajectory object, including
the execution-time frozen/sealed review context. That context has been validated
against the captured user/system/tools/turns. No human review labels were created.
`process-status.json` and the logs preserve subprocess completion and limits.

## Pinned runtime and bounds

- Model: `ollama:counsel-nano-q5:latest`, family `nemotron_h_moe`, quantization `Q5_K_M`.
- Digest: `36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8`.
- Ollama: `0.34.4`, loopback `http://127.0.0.1:11434`.
- Seed 42; context 8192; temperature 0; thinking disabled.
- Predeclared maximum: four actual model requests, 256 output tokens per response.
- Each model or capability request has a 45-second wall-clock deadline; inference
  has a 180-second between-call deadline; the outer subprocess has a 300-second limit.
- Zero automatic retries, no downloads, no cloud fallback, no MedGemma invocation.

All 347 source/config/schema/prompt hashes and the recorded runtime package/model
identities agree before and after execution. These hashes bind the captured
candidate and detect drift; they do not establish third-party authenticity.

## Reproduction

Use a new output path; the CLI refuses to overwrite an existing file before
inspection or inference. The installed model and source versions must be checked
against the recorded hashes if a repeat is compared with this attempt.

```sh
.venv/bin/python scripts/local_order_probe.py \
  --agent-model ollama:counsel-nano-q5:latest \
  --output /new/exclusive/path/report.json \
  --max-responses 4 --max-output-tokens 256 --timeout 45
```

The original command also ran under `subprocess.run(..., timeout=300)`; see
`process-status.json` for the exact invocation. Reproduction is not an instruction
to rerun automatically. Seeded decoding does not promise identical generations
across runtimes; actual order IDs use UUIDs.

## Scope and validation limits

Grading is disabled; benchmark score and unused trajectory reward/pass/safety
fields are null. Clinical and safety criterion coverage are both zero. The only
stored criterion is unassessed and retained to make the review context explicit.
This outcome does not demonstrate clinical appropriateness, physician validation,
patient benefit, comparative advantage, general model reliability or deployment
readiness. The model was asked to transport an explicitly provided synthetic
action; no patient diagnosis or treatment decision was evaluated.

Development checks before execution: 159 relevant tests passed, including raw
Ollama envelopes, completion, persisted action fidelity and review-context capture.
Scoped Ruff check/format and git diff checks passed. Repository-wide `make lint`
remains blocked by 115 preexisting findings in unrelated research/deliverable files.
