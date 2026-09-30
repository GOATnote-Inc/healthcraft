# Harbor 0.8.0: bounded local terminal integration plan

Source inspection dated 2026-09-30. This is implementation feasibility, not an
executed Harbor task, a clinical benchmark result, or an isolation attestation.
No patient data, task bootstrap, model calls, or repository modifications were
used for this inspection.

## Immutable source and license

- Official release: https://pypi.org/project/harbor/0.8.0/; Python >=3.12.
- Official tag `v0.8.0` peels to
  `22b83271db78ef4bcbeb2402cdd154979cf87912`.
- Wheel `harbor-0.8.0-py3-none-any.whl` SHA-256:
  `1ccbc327c0bbd204d828b995dc47307c92df2c1e58d625f5ac1b90808553b9fd`.
- Apache-2.0 license SHA-256:
  `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`.
- BaseAgent, Verifier and LICENSE fetched from that commit are byte-identical
  to their wheel copies. Other inspected files come directly from the hashed
  wheel. `manifest.json` records the source files initially extracted.
- Commit source: https://github.com/harbor-framework/harbor/tree/22b83271db78ef4bcbeb2402cdd154979cf87912
- Current documentation has evolved beyond this release; use pinned code for
  signatures. In particular the pinned task schema defaults to `1.2`.

## Real lifecycle and external native agent

Use the real `await Trial.create(config)` then `await trial.run()`; instantiating
the abstract Trial directly is not the entrypoint. Local TaskConfig(path=...)
avoids registry and git-task downloads. Example imports/configuration:

```python
from harbor.models.trial.config import (
    AgentConfig, EnvironmentConfig, TaskConfig, TrialConfig,
)
from harbor.trial.trial import Trial

config = TrialConfig(
    task=TaskConfig(path=task_dir), trial_name=unique_trial_name,
    trials_dir=exclusive_parent,
    agent=AgentConfig(import_path="our_module:NativeOllamaAgent"),
    environment=EnvironmentConfig(type="docker", delete=False),
)
trial = await Trial.create(config)
result = await trial.run()
```

BaseAgent requires static `name()`, `version()`, async `setup(environment)` and
async `run(instruction, environment, context)`. Constructor accepts logs_dir,
model_name, logger, mcp_servers, skills_dir and **kwargs. AgentContext provides
token counts, cost and arbitrary metadata; it has no native completion field.
Populate context and host-side append-only raw records incrementally so timeouts
retain attempted calls, not only a successful final summary.

`environment.exec(command, cwd=None, env=None, timeout_sec=None, user=None)`
returns ExecResult(stdout, stderr, return_code). Pinned Docker executes
`docker compose exec ... main bash -c command`, merges stderr into stdout and
uses the configured agent user. Do not execute model-authored shell. Parse one
strict JSON command and construct an allowlisted, safely quoted CLI invocation.
Both local models can use the same `tools=None` native Ollama text protocol;
the custom host agent makes no LiteLLM completion calls or provider fallback.

Primary code:
- https://github.com/harbor-framework/harbor/blob/22b83271db78ef4bcbeb2402cdd154979cf87912/src/harbor/agents/base.py
- https://github.com/harbor-framework/harbor/blob/22b83271db78ef4bcbeb2402cdd154979cf87912/src/harbor/trial/trial.py
- https://github.com/harbor-framework/harbor/blob/22b83271db78ef4bcbeb2402cdd154979cf87912/src/harbor/trial/single_step.py

## Container topology and cleanup

Task layout is instruction.md, task.toml, environment/, tests/test.sh, optional
solution/solve.sh. The Docker provider supports environment/docker-compose.yaml
plus extra compose files and multiple services. Its command endpoint always
targets `main`. A private `healthcraft-ehr` sidecar can hold the synthetic world
and recorder; `main` receives only the public CLI, schemas, instruction and a
limited per-trial public-operation credential. Oracle assertions/coordinator
finalization must not be exposed through that credential.

Set task `[environment] allow_internet=true` **only because the framework's
false setting appends `main.network_mode: none` after all other compose files**.
False cannot reach either a backend sidecar or host.docker.internal. Attach both
services solely to an explicitly `internal: true` Compose network, then verify
the actual local Docker behavior. Do not equate the Harbor flag with egress
permission or claim a stronger isolation guarantee than tested. Prefer host
coordinator finalization via scoped Docker exec into the owned backend. If a
backend port is published, bind only host loopback and test that the agent
credential cannot access coordinator operations.

Compose order: resource override, build/prebuilt, task compose, extra compose,
mount override, then no-network override when disabled. The build template adds
`main.build.context=${CONTEXT_DIR}` and `sleep infinity`; task compose may
override it. `environment.docker_image` with force_build=false selects the
prebuilt template instead. Without that path Harbor runs `compose build` for
the project; define separate build contexts explicitly and retain bash in main.
Container build-time network availability is separate from runtime networking.

Default cleanup `delete=true` uses `down --rmi all --volumes --remove-orphans`.
Use `delete=false` for this probe so cleanup runs scoped `down` without removing
referenced images. Remove only separately identified owned volumes/artifacts.
No existing patient-data image or unrelated container should be inspected,
started, modified or removed.

Primary code/docs:
- https://github.com/harbor-framework/harbor/blob/22b83271db78ef4bcbeb2402cdd154979cf87912/src/harbor/environments/docker/docker.py
- https://github.com/harbor-framework/harbor/blob/22b83271db78ef4bcbeb2402cdd154979cf87912/src/harbor/environments/docker/docker-compose-no-network.yaml
- https://docs.docker.com/reference/compose-file/networks/#internal

## Verifier visibility and trust limits

SingleStepTrial starts environment, sets up/runs agent, uploads agent logs,
collects artifacts, runs verifier, then stops the shared environment. Verifier
uploads tests/ into /tests only when verify() begins. However /logs/verifier,
/logs/agent and /logs/artifacts are writable host bind mounts from initial
startup. The agent's working container can write reward files before verification;
shared mode does not first clear them. A background process could survive until
the shared verifier starts. Docker exec timeout terminates the client process;
source inspection does not establish termination of every container child.

The default verifier executes test.sh and then reads reward.json (preferred)
or reward.txt. It does not inspect the test command's return code before reading
reward, and its parser is not a strict finite JSON validator. Our coordinator
must independently validate fresh reward files, completion/error state, receipt
and source/backend evidence bindings, and reject stale/malformed values. Never
treat Harbor numeric reward alone as authoritative or a clinical outcome.

Separate verifier mode stops the agent environment first, starts a new verifier
environment from tests/, empties verifier logs and transfers only declared
artifacts. It requires a real separate verifier image/definition; hidden tests
are already part of that verifier image rather than uploaded again. It can
reduce shared-process exposure but still needs an independently bound backend
snapshot. This is a follow-on option, not a claim about the initial shared run.

Primary code:
- https://github.com/harbor-framework/harbor/blob/22b83271db78ef4bcbeb2402cdd154979cf87912/src/harbor/verifier/verifier.py
- https://github.com/harbor-framework/harbor/blob/22b83271db78ef4bcbeb2402cdd154979cf87912/src/harbor/models/task/verifier_mode.py

## First executable controls and minimum steps

1. Freeze original synthetic task, public CLI schemas/instruction, backend,
   container images, dependency pins and exclusive scheduled trial roster.
2. Run real Harbor builtin OracleAgent with solution/solve.sh invoking only the
   public CLI, plus a separate no-op/invalid control, through actual Trial and
   DockerEnvironment. OracleAgent uploads /solution only for its own run. It
   records nonzero shell exit to agent/exit-code.txt but does not raise; check
   that exit evidence and backend completion explicitly.
3. Capture merged CLI output and return codes, independent backend audit/store
   and completion, actual mounted paths/network inspection, verifier upload
   timing, raw reward and Harbor result. Preserve every scheduled trial,
   including setup/build/timeout/verifier errors. Do not retry in place.
4. Only after fake transport and reference controls pass, run any separately
   authorized bounded native-model attempt. Bind the exact initial prompt,
   CLI protocol, native options/digests, budgets and completion rules. Retain
   terminal framing as an explicit difference from native MCP tool calling.

## Dependency resolution and import precautions

No dependency packages had been installed when this design note was authored.
Full PyPI wheel-only dry run (2026-09-30) selected 105 distributions: 224,808,919
compressed bytes and 624,001,900 expanded wheel bytes before bytecode/venv.
The full footprint exceeds the requested approximately 500 MB ceiling.
`dependency-lock.json` and the full requirements lock retain every selected
version, URL and SHA-256. No weights or datasets were fetched; wheel packages
include unused dataset/cloud-client code.

The static real-Trial import roots are jinja2, litellm, pydantic, shortuuid,
tenacity, toml and yaml, plus task.checksum()'s dynamic dirhash dependency. Their exact selected dependency closure, plus core
jsonschema and the unchanged Harbor wheel, is 64 distributions / 62,464,568
compressed / 162,370,268 expanded bytes. This smaller plan intentionally omits
unused Harbor declared dependencies and is **not** a metadata-complete Harbor
installation. Actual import success remains to be tested without stubs.

AgentFactory eagerly imports builtins including Terminus2/LiteLLM, while
EnvironmentFactory lazily imports cloud backends. Before any real import set
`LITELLM_LOCAL_MODEL_COST_MAP=True` and `LITELLM_MODE=PRODUCTION` in a clean
environment. In the selected LiteLLM 1.103.1 wheel these suppress remote cost-map
fetch and default `.env` loading respectively. Set litellm.telemetry=False
after import. A Python socket audit guard during import/control validation can
detect attempted network access; it is not a complete OS egress boundary.

- https://docs.litellm.ai/docs/proxy/custom_model_cost_map
- Actual selected wheel source is retained under litellm-selected-source/;
  source and package hashes are recorded in the resolution artifacts.

Pending evidence: real import of the reduced dependency closure; original-task
Docker build/run; service-only network reachability and no-egress checks; exact
end-to-end source/persistence oracle plus unchanged Microsoft secondary CSV
verifier inside the Harbor lifecycle; model execution (not authorized here).

## Subsequent runtime validation

The approved reduced 64-package closure was installed offline from the exact
hash-checked cached wheels. Actual Trial/BaseAgent/OracleAgent/DockerEnvironment/
Verifier import passed with zero socket/DNS attempts under the Python audit
guard. The selected LiteLLM map reports local forced source and no URL.
All 288 installed Harbor package/license files match their unchanged wheel
bytes. This is still intentionally not a metadata-complete package install.
Twelve optional real-SDK adapter tests pass; their environment.exec transport is
faked against the actual private session for one reference case, not a Docker
lifecycle claim. Runtime details and exact commands are retained alongside this
note in runtime-validation.json, import-validation.json and install logs.
