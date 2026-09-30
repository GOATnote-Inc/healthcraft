# Optional NeMo Gym interoperability components

These experimental components provide native Ollama transport and a four-record
source-retrieval resource. They do not establish clinical correctness, benchmark
comparability, training benefit, or superiority. HealthCraft's default install
does not import Gym or acquire additional dependencies.

The supported Gym source revision is
[`82e1834ccf2dd578af26a1abc686c15e17569594`](https://github.com/NVIDIA-NeMo/Gym/commit/82e1834ccf2dd578af26a1abc686c15e17569594).
Gym is Apache-2.0; these components implement its published Python interfaces.
The native model component checks the source checkout's revision and tracked
cleanliness at construction. A wheel without that checkout is not supported.
The separately recorded counter feasibility probe is an earlier experiment with
different inference settings; it is not a matched result for these components.

## Native model component

`native_ollama.NativeOllamaModel` implements Gym's `SimpleResponsesAPIModel`
Responses and Chat Completions methods. Its dependency-free core is
`healthcraft.integrations.nemo_native.NativeOllamaBridge`. It reuses HealthCraft's
`OllamaClient` payload construction, local-only endpoint validation, disabled
proxy routing, redirect refusal, capability checks and no-retry transport.

Construct it with `NativeOllamaModelConfig` specifying:

| Field | Contract |
|---|---|
| `host` | Explicit loopback IP, such as `127.0.0.1`; no wildcard bind |
| `port`, `name`, `entrypoint` | Gym server fields; direct in-process tests use an empty entrypoint |
| `base_url` | Local Ollama origin; defaults to `http://127.0.0.1:11434` |
| `model` | Exact already-installed local alias; no cloud alias or downloads |
| `expected_digest` | Required installed weight digest; checked before every generation |
| `expected_runtime` | Required matching Ollama version; defaults to reviewed `0.34.4` |
| `capture_dir` | Existing directory receiving new exclusive per-attempt directories |
| `output_budget` | Required positive integer; request budget must match when supplied |
| `timeout` | Positive finite native HTTP timeout in seconds; default 300 |

Every native generation sends `stream:false`, `think:false`, and exactly
`options={num_ctx:32768, seed:42, temperature:0.0, num_predict:output_budget}`.
The matched profile requires the installed model to declare thinking capability;
tool-bearing requests also require tools capability. It rejects a nonempty
thinking response, a changed model/runtime identity, or a mismatched response
model. Other native sampler options remain omitted, as in HealthCraft's native
client. Equal requests and seeds do not promise identical output across hardware
or runtime changes.

The bridge accepts text messages and function tools only. It preserves message
order and text, function argument JSON types, and matched function results. Tool
IDs assigned by this bridge are adapter IDs, not native provider IDs. Pending
duplicate IDs and orphaned results fail; an ID reused after its result is valid.
Function names returned by the model must have been advertised in that request.
There is no forced tool choice or strict schema-constrained decoding support.
Streaming, the Anthropic Messages API, images/audio/video, hosted tools, reasoning
replay, previous-response state, nondefault sampler options and arbitrary
`extra_body` are rejected. HTTP requests are checked before SDK normalization.

Native `done=true, done_reason=stop` produces a completed response; a completed
blank narrative is valid. Calls in that response still require tool execution
and another model turn before an episode can finish. `length` is incomplete with
`max_output_tokens`; `content_filter` remains a separate incomplete outcome.
Missing/unknown completion provenance, refusal, malformed output and unexpected
thinking produce an error with captured evidence. Partial calls retain incomplete
status. No token IDs, reasoning-token counts or cache-hit counts are invented;
missing usage remains unknown.

Each bridge attempt creates a unique directory containing the incoming request,
individual parsed native request/response envelopes (including metadata reads),
normalized provenance, and either a converted response or an error. Files use
exclusive creation. A process killed before completion can leave a request with
no terminal file; this is an unfinished attempt, not success or an absent trial.
These are parsed JSON envelopes, not byte-level network captures or attestations.
Metadata responses may contain local filesystem paths; inspect captures before
publishing them. Invalid HTTP requests rejected before model dispatch remain
HTTP validation failures and do not create native attempt directories.

Use direct construction with `ServerClient` in a controlled harness. There is no
automatic install/startup script or live model run in this directory. Configure
all servers on loopback, disable telemetry explicitly with
`NEMO_GYM_OTEL_ENABLED=0`, clear inherited model routing overrides, set a positive
SimpleAgent `max_steps`, and use an outer process timeout. Cancelling an async
wrapper does not terminate a running blocking HTTP request; the native timeout
and outer process bound remain necessary. Training token-ID capture is not
supported by this adapter.

Why native transport: [Ollama's compatibility API](https://docs.ollama.com/api/openai-compatibility)
does not expose per-request context size. The reviewed
[v0.34.4 compatibility converter](https://github.com/ollama/ollama/blob/b2da9e468af2479058ae18c6d908ed29de410684/openai/openai.go#L574)
also supplies a `top_p=1.0` default absent from the native HealthCraft request.
`reasoning_effort=none` maps to thinking off in that converter, but does not solve
the context/default mismatch. No guessed compatibility `extra_body` behavior is
used here.

## Four-record resource component

`roster_resources.RosterResourcesServer` wraps
`healthcraft.integrations.nemo_roster.RosterSessions`. Its fixture key is
`cc022-roster-source-retrieval/v1`. A fresh session contains exactly four
projected patients and encounters from the authored CC-022 `bed`/`summary`
observations. It is a separate mechanical task; all clinical benchmark criteria
remain unassessed. `MECHANICAL_PROMPT` contains no roster IDs or expected facts.

The model discovers IDs through `searchEncounters`, then uses
`getEncounterDetails` and optionally `getPatientHistory`. All three invoke real
HealthCraft handlers and the execution recorder. `tool_definitions()` returns
the canonical published schemas. For Gym Responses requests, advertise each as
`{"type":"function", **definition, "strict":false}` (the pinned Gym input type
requires the explicit `strict` field); both compared harnesses must use the same
prompt, tool definitions and native settings.

The seed/run payload includes `fixture_key` and an opaque nonempty `episode_id`.
`/seed_session` returns a `resources_session_id` and no source oracle. Session
cookies isolate worlds, repeated matching seed requests are idempotent, and
conflicting seeds fail. Close with the same session cookie and
`{"resources_session_id": returned_id, "episode_id": original_episode_id}`.
The harness must preserve its evidence before close, then close in `finally`;
SimpleAgent does not perform this cleanup itself.

Verification uses the server-held source/context and captured real tool calls.
Mechanical retrieval and completed execution are reported separately from
clinical assessment. Gym's required numeric reward is explicitly a mechanical
retrieval measurement, never the HealthCraft benchmark score. A parent harness
must preserve every scheduled attempt, including masked infrastructure failures,
and must not silently retry. Stateless external reverification is unsupported.

## Offline verification

Core tests need only HealthCraft's existing development environment:

```sh
python -m pytest tests/test_integrations/test_nemo_native.py -q
python -m unittest discover -s tests/test_integrations -p test_nemo_roster_resources.py -v
```

Optional SDK tests require an existing isolated Gym runtime and the exact pinned
source checkout. The pytest command additionally requires pytest to be available
in that test environment; Gym's runtime dependencies do not include pytest.
`GYM_SOURCE` and `GYM_PYTHON` below are explicit local paths;
these commands do not install packages, start TCP servers or call models:

```sh
PYTHONPATH="$PWD/src:$PWD:$GYM_SOURCE" NEMO_GYM_OTEL_ENABLED=0 \
  "$GYM_PYTHON" -m pytest tests/test_integrations/test_nemo_native.py -q
PYTHONPATH="$PWD/src:$PWD:$GYM_SOURCE" NEMO_GYM_OTEL_ENABLED=0 \
  "$GYM_PYTHON" -m unittest discover -s tests/test_integrations \
  -p test_nemo_roster_resources.py -v
```

The native tests use stub transport with actual Gym types and FastAPI TestClient
when installed. They prove tested conversion/session contracts, not live model
completion. No clinical comparison, training run, or formal red-team campaign
has been performed by these tests.

The 2026-09-30 SDK validation did not install pytest into the isolated runtime.
It appended the existing HealthCraft development environment's site-packages
after the runtime's own paths to borrow pure-Python pytest, with plugin autoload
disabled. The installed Gym dependencies retained path precedence. The exact
local invocation was:

```sh
PYTHONPATH=src:.:/private/tmp/healthcraft-nemo-gym-probe/upstream \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 NEMO_GYM_OTEL_ENABLED=0 \
  /private/tmp/healthcraft-nemo-gym-probe/runtime-venv/bin/python - <<'PY'
import sys
sys.path.append('/Users/kiteboard/healthcraft/.venv/lib/python3.14/site-packages')
import pytest
raise SystemExit(pytest.main(['tests/test_integrations/test_nemo_native.py', '-q']))
PY
```

Those paths describe that local validation, not a portable installation recipe.
It produced 36 passing tests, plus an unused `asyncio_mode` configuration warning
and two upstream TestClient deprecation warnings. The resource unittest command
does not require pytest.
