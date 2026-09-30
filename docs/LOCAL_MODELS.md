# Free local evaluation

HEALTHCRAFT accepts installed Ollama models as `ollama:<model-name>`. This
provider uses Ollama's native API without API keys. Its endpoint must be
loopback, HTTP proxies and redirects are disabled, and cloud model aliases are
rejected. Evaluation never downloads weights or switches providers. A local
agent defaults to deterministic grading only; use an explicit local judge to
evaluate the remaining `llm_judge` criteria.

The [optional NeMo Gym integration](../integrations/nemo_gym/README.md) uses
the same native local-model transport. In the separate
[four-record feasibility exercise](../artifacts/comparators/20260930/nemo-roster-local-v1/README.md),
Nemotron completed one attempt in each framework, with all four members
retrieved through five tool calls and six model responses per arm. This is
ungraded source retrieval, not a clinical benchmark or performance comparison.

A separate [restricted order probe](../artifacts/local-order-probe/20260930/order-transport-v1/README.md)
completed once with two Nemotron responses and one actual tool invocation.
The requested nested details, priority, indication and simulation time were
checked against the persisted order, linked task and audit. Source/model/runtime
identities remained unchanged. This is literal instruction following through
one advertised tool, with zero assessed clinical or safety criteria.

`scripts/local_order_probe.py` reproduces that bounded integration contract
using a new output path, at most four native requests and explicit request
deadlines. The adapter preserves missing completion reasons as unknown rather
than inventing a normal stop. New orchestrator runs also preserve missing-judge
coverage and [review context](CLINICAL_REVIEW.md) in their trajectories.
Native chat envelopes must identify an assistant message before their content
or tool calls can reach the runner; missing or other roles are protocol errors.

## Care source-reading probe

`scripts/local_care_probe.py` supplies the same actual synthetic tool outputs
as text to the installed Nemotron and MedGemma models. A fresh world executes
`getEncounterDetails`, `validateTreatmentPlan` and `processDischarge`; the
fixture checks source groups, unknown administration status and persisted
documentation before any inference. Each model gets one request to copy four
literal fields. MedGemma's lack of native tool capability is therefore not
treated as a failed tool-use attempt.

```sh
env -i PATH=/usr/bin:/bin .venv/bin/python scripts/local_care_probe.py \
  --output /tmp/new-local-care-probe.json --timeout 45 --max-output-tokens 768
```

The probe uses loopback Ollama, no downloads or paid fallback, a fixed seed,
temperature zero and an 8192-token context. It unloads each model after its
request. Scheduled attempts, raw native envelopes, incomplete/failed outputs,
mechanical field comparisons and before/after provenance remain in the new
output file. Source-reading agreement is not clinical correctness; the
report has no clinical, safety, benchmark or superiority score. This deliberately
small fixed-text test is not a native tool-use assessment or model ranking.

In the [recorded two-attempt diagnostic](../artifacts/local-care-probe/20260930/source-reading-v1/README.md),
both models completed. Nemotron copied all four requested fields exactly;
MedGemma wrapped its output in a Markdown fence and failed the predeclared
strict JSON check. Both original outputs remain, with no retry or output repair.

## Choose roles from runtime capabilities

The provider checks `/api/tags` and `/api/show` before evaluation. Tool agents
must declare `tools` capability; text-only models are rejected as agents before
any task runs. A model's name is insufficient evidence of tool support.
[Ollama documents native chat messages and tool calls here](https://docs.ollama.com/api/chat).

The inspected development machine has an Apple M4 Max with 48 GiB unified
memory. Its existing local weights, inspected on 2026-09-30, are:

| Local alias | Runtime family | Quantization | Declared role |
|---|---|---|---|
| `counsel-nano-q5:latest` | Nemotron hybrid MoE, 31.6B | Q5_K_M | Tool agent |
| `counsel-medgemma-27b-text-q5:latest` | Gemma3, 27B | Q5_K_M | Text-only diagnostic judge |
| `counsel-cascade-8b-q5:latest` | Qwen3, 8.2B | Q5_K_M | Tool agent |

These aliases are specific to that machine. Run `ollama list` on another
machine and use its installed names. HEALTHCRAFT records the installed model
digest, runtime version, family, quantization, context size, decoding seed, and thinking setting
in checkpoint identity. Changing those settings requires a new results
directory. Local agent/judge pairs must come from different recognized model
vendors; aliases of the same weights cannot bypass the guard.

MedGemma is useful for inexpensive diagnostic experiments, but its output is
not a validated clinical reference standard. Google's model card says it was
not evaluated or optimized for multi-turn applications. This integration uses
its text completion capability for judge prompts; it does not turn MedGemma
into a native tool agent. [MedGemma model card](https://huggingface.co/google/medgemma-27b-text-it).

## Run the integration smoke first

Start the installed Ollama service, then use the repository environment:

```bash
HC_OLLAMA_NUM_CTX=8192 .venv/bin/python scripts/local_model_smoke.py \
  --agent-model ollama:counsel-nano-q5 \
  --judge-model ollama:counsel-medgemma-27b-text-q5 \
  --output /tmp/healthcraft-local-smoke-01.json
```

The smoke requires Nemotron to call `getEncounterDetails`, executes the call
against a real seeded synthetic world, returns the tool result to the model,
and checks that the response identifies that encounter. It then runs a known
positive and negative text fixture through the diagnostic judge and its JSON
parser. The report labels this as an integration smoke, with no benchmark
score. Existing output reports are never overwritten.

## Evaluate tasks

Use `healthcraft evaluate` (or `python -m healthcraft evaluate`) for the same
orchestrator and options shown below. The separate `simulate` command makes no
model calls and refuses real model names; its ungraded smoke artifacts are not
model evaluation results.

```bash
.venv/bin/python -m healthcraft.llm.orchestrator \
  --agent-model ollama:counsel-nano-q5 \
  --judge-model ollama:counsel-medgemma-27b-text-q5 \
  --tasks IR-001 --trials 1 --seed 42 --rubric-channel v10 \
  --results-dir results/local-nano-medgemma-01
```

Use a fresh directory for changed weights, decoding settings, tasks, prompts,
or grading configuration. Check `evaluation_mode`, `grading_complete`,
`ungraded_criteria`, infrastructure errors, judge errors, and trajectory evidence
before interpreting reward. Local smoke
checks and small-model judge results are development evidence, not comparable
frontier leaderboard results or clinical readiness evidence.

Without `--judge-model`, local runs make no judge calls. Criteria requiring an
LLM judge remain unverified; their resulting scores are incomplete diagnostics.
The provider refuses a cloud judge for a local agent even when paid API keys
are present in the environment.

For experimental multi-patient source retrieval, use the separate
[roster observation profile](ROSTER_PROFILES.md). Its runs are entirely
ungraded, and summary score/safety metrics are null. This prevents an altered
observation contract from inheriting unvalidated clinical benchmark scores.

| Variable | Default | Purpose |
|---|---|---|
| `HC_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Loopback Ollama origin |
| `HC_OLLAMA_NUM_CTX` | `32768` | Context window requested for each call |
| `HC_OLLAMA_SEED` | `42` | Local generation seed |
| `HC_OLLAMA_THINK` | `0` | Set `1` to enable native thinking for supporting models |

Temperature defaults to zero. A seed improves repeatability within a fixed
runtime but does not establish bitwise equivalence across hardware/runtime
versions. Keep the 32K default for full task prompts; the smaller context above
is for the deliberately short smoke. Ollama manages model loading; the two
large models need not remain resident together.

## Initial local evidence: 2026-09-30

The [native smoke report](../artifacts/local-models/20260930/native-smoke.json)
passed: Nemotron made and consumed a real seeded encounter lookup, and MedGemma
correctly distinguished the two judge sanity fixtures. Total wall time was
25.121 seconds. This establishes runtime integration only.

The first [IR-001 diagnostic trajectory](../artifacts/local-models/20260930/ir001-nano-medgemma/trajectories/information_retrieval/IR-001_ollama:counsel-nano-q5_42_t1.json)
exposed a completion-accounting defect: Nemotron exhausted all 25 tool rounds,
ended on a tool result, and never produced a final answer, yet the earlier
runner graded the partial trajectory. Its historical `reward=0.5714` and
`error_runs=0` are **not a valid completed benchmark result**. The immutable
artifact predates the completion-limit fix. The current runner preserves such
traces and marks them incomplete, as it does for truncated model responses.

The trace also demonstrates why MedGemma remains a diagnostic judge: it
credited IR-001-C04 using a symptom found in a tool result even though the
agent never articulated that reasoning. Separately, IR-001-C03 currently checks
`checkResourceAvailability` although its assertion and expected sequence concern
cross-reactivity lookup. Those task/grading issues require a separately
versioned rubric audit; this local integration did not alter benchmark tasks.

The immutable [CC-022 native roster diagnostic](../artifacts/local-models/20260930/cc022-roster-nano/README.md)
also predates an interface correction: its tool schemas advertised exactly
8 hexadecimal characters in patient/encounter IDs, while the roster supplied
12-character IDs. Its incomplete execution is therefore confounded by an
inconsistent interface and cannot be attributed solely to the model or policy.
The three retrieval schemas now accept exactly 8 or 12 uppercase hexadecimal
characters. The historical artifacts and task/profile IDs remain unchanged;
new trials require a new output directory and checkpoint identity under the
corrected schemas.
