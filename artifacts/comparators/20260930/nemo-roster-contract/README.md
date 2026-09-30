# Offline NeMo Gym roster contract probe

This is an ordinary integration check using scripted provider responses, not model performance, clinical validation, training evidence, or a benchmark result. No model was loaded or called. No remote service, hosted API, or TCP server was used. An audit hook rejected network socket connections.

The actual pinned NeMo Gym `SimpleAgent` called HealthCraft's optional native model component and roster resource component through in-process ASGI transports. The resource component used real HealthCraft MCP handlers and the independent server-held retrieval verifier. Only the Ollama transport was scripted. Prompts contained no expected patient IDs, encounter IDs, observations, count, or clinical answers.

The initial four scheduled cases all failed with HTTP 422 before any provider call: the pinned SDK requires `strict` on a Responses function-tool wrapper. `initial-caller-failures.json` retains every scheduled failure and the relevant raw validation entries; unrelated union-alternative validation errors are counted but omitted. This was corrected in the caller fixture by adding `strict: false`; the canonical tool parameter schemas were unchanged.

The corrected four scheduled cases are all retained in `corrected-report.json`:

| Scripted case | Model-shaped requests | Captured tool calls | Retrieved members | Mechanical result |
|---|---:|---:|---:|---|
| Complete | 3 | 5 | 4 | Passed, reward 1 |
| Truncated final message | 3 | 5 | 4 | Incomplete, reward 0 |
| Truncated tool generation | 1 | 0 | 0 | Incomplete, reward 0; no tool dispatched |
| Step limit after retrieval | 2 | 5 | 4 | Incomplete, reward 0; no final response |

All returned reports keep `benchmark_score: null`, `benchmark_comparable: false`, `grading_complete: false`, and zero measured clinical/safety criteria. Every corrected case closed its resource session after capturing its snapshot. The step-limit case deliberately used a two-response cap; the other cases allowed eight responses. All used the same system/user prompts and native options planned for the later comparator: context 32768, seed 42, temperature 0, thinking disabled, 2048 output tokens per response. The installed alias and digest were represented by scripted metadata; these tests do not verify installed weights or runtime availability.

## Reproduction

The existing isolated runtime was Python 3.13.14 with FastAPI 0.135.2, HTTPX 0.28.1, Pydantic 2.13.4, OpenAI SDK 2.44.0, and aiohttp 3.14.1. NeMo Gym was the unmodified checkout at `82e1834ccf2dd578af26a1abc686c15e17569594`. The default HealthCraft environment does not require Gym. No dependency was installed for this probe.

From this workspace, the exact corrected invocation was:

```bash
PYTHONPATH=/Users/kiteboard/healthcraft/src:/Users/kiteboard/healthcraft:/private/tmp/healthcraft-nemo-gym-probe/upstream \
NEMO_GYM_OTEL_ENABLED=0 \
/private/tmp/healthcraft-nemo-gym-probe/runtime-venv/bin/python \
/private/tmp/healthcraft-nemo-fake-fullstack.py
```

`fake_fullstack_probe.py` is an exact copy of that executed script. It can be run with the same command after substituting its path for the final script argument. It writes a new temporary output directory for every invocation; it does not modify this evidence. Its absolute workspace path reflects this development run and must be changed to reproduce elsewhere. The source hashes observed before the probe are in each report. `provenance.json` records the pinned Gym revision, HealthCraft HEAD and dirty state observed after the probes, plus the archived script/report hashes. This was an uncommitted development source snapshot, not a release qualification.

The full corrected report includes requests, SDK responses, independent certificates, tool captures and fake native payloads. Native capture files were also created in the temporary output directory named by the report; they are not required to interpret the archived record and are not copied here. This check does not establish TCP deployment behavior, model quality, reproducibility of stochastic inference, clinical benefit, or comparative superiority.

## Scope of the later matched feasibility protocol

The first native `/api/chat` request was compared with the HealthCraft arm and matched exactly. Later prompts retain each framework's normal tool-result encoding: HealthCraft uses `json.dumps` spacing, while Gym preserves the compact FastAPI JSON response text. The parsed tool data match, but byte strings and tokenization can differ. No serialization override was applied. This is an interoperability feasibility check with matching initial requests and generation settings, not an all-turn wire-equivalence test or performance comparison. No live inference result is contained in this artifact.
