# Executed commands

All relative commands below used `/private/tmp/healthcraft-nemo-gym-probe` unless a `cd` is shown. Network/download and loopback execution were explicitly authorized. The first sandboxed Git fetch failed DNS resolution; the same exact pinned fetch succeeded with network permission. No credentials were embedded in commands. These paths now exist: do not replay commands blindly or overwrite their artifacts.

```bash
mkdir /private/tmp/healthcraft-nemo-gym-probe
cd /private/tmp/healthcraft-nemo-gym-probe
git init upstream
git -C upstream fetch --depth 1 https://github.com/NVIDIA-NeMo/Gym.git 82e1834ccf2dd578af26a1abc686c15e17569594
git -C upstream checkout --detach FETCH_HEAD

# Inspected source before execution: pyproject/lock/license; resource, agent,
# adapter, base server, client and test entrypoints/configuration.
# Bootstrap uses an already installed interpreter; does not change HealthCraft.
/opt/homebrew/bin/python3.14 -m venv /private/tmp/healthcraft-nemo-gym-probe/.venv
/private/tmp/healthcraft-nemo-gym-probe/.venv/bin/python -m pip install \
  --dry-run --only-binary=:all: \
  --report /private/tmp/healthcraft-nemo-gym-probe/uv-install-plan.json uv==0.11.24
/private/tmp/healthcraft-nemo-gym-probe/.venv/bin/python -m pip install \
  --only-binary=:all: --no-deps uv==0.11.24

cd /private/tmp/healthcraft-nemo-gym-probe/upstream
UV_PROJECT_ENVIRONMENT=/private/tmp/healthcraft-nemo-gym-probe/.venv \
/private/tmp/healthcraft-nemo-gym-probe/.venv/bin/uv \
  --cache-dir /private/tmp/healthcraft-nemo-gym-probe/uv-cache sync \
  --frozen --dry-run --inexact --no-default-groups --no-dev --no-install-project \
  --python /opt/homebrew/bin/python3.14 --no-python-downloads

# The lock and compatible wheel tags were inspected without importing upstream.
# footprint.json records cp314 gaps; footprint-cp313.json records the chosen path.
cd /private/tmp/healthcraft-nemo-gym-probe
/private/tmp/healthcraft-nemo-gym-probe/.venv/bin/uv \
  --cache-dir /private/tmp/healthcraft-nemo-gym-probe/uv-cache python install \
  3.13.14 --install-dir /private/tmp/healthcraft-nemo-gym-probe/python --no-bin

cd /private/tmp/healthcraft-nemo-gym-probe/upstream
UV_PROJECT_ENVIRONMENT=/private/tmp/healthcraft-nemo-gym-probe/runtime-venv \
UV_PYTHON_INSTALL_DIR=/private/tmp/healthcraft-nemo-gym-probe/python \
/private/tmp/healthcraft-nemo-gym-probe/.venv/bin/uv \
  --cache-dir /private/tmp/healthcraft-nemo-gym-probe/uv-cache sync \
  --frozen --no-default-groups --no-dev --no-install-project \
  --python 3.13.14 --no-python-downloads \
  > /private/tmp/healthcraft-nemo-gym-probe/core-install.log 2>&1

cd /private/tmp/healthcraft-nemo-gym-probe
env -i PATH=/private/tmp/healthcraft-nemo-gym-probe/runtime-venv/bin:/usr/bin:/bin \
  NEMO_GYM_OTEL_ENABLED=0 WANDB_MODE=disabled HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
  /private/tmp/healthcraft-nemo-gym-probe/runtime-venv/bin/python \
  /private/tmp/healthcraft-nemo-gym-probe/counter_contract_probe.py

# Exactly one actual trajectory; creates local-trajectory-01 exclusively.
env -i PATH=/private/tmp/healthcraft-nemo-gym-probe/runtime-venv/bin:/usr/bin:/bin \
  NEMO_GYM_OTEL_ENABLED=0 WANDB_MODE=disabled HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
  HF_HOME=/private/tmp/healthcraft-nemo-gym-probe/hf-cache \
  /private/tmp/healthcraft-nemo-gym-probe/runtime-venv/bin/python \
  /private/tmp/healthcraft-nemo-gym-probe/local_trajectory_probe.py \
  > /private/tmp/healthcraft-nemo-gym-probe/local-trajectory-process.log 2>&1

/private/tmp/healthcraft-nemo-gym-probe/.venv/bin/uv \
  --cache-dir /private/tmp/healthcraft-nemo-gym-probe/uv-cache pip freeze \
  --python /private/tmp/healthcraft-nemo-gym-probe/runtime-venv/bin/python \
  > /private/tmp/healthcraft-nemo-gym-probe/installed-dependencies.txt

# Read-only local model metadata; no generation, pulling, or model changes.
curl --silent --show-error --max-time 5 http://127.0.0.1:11434/api/tags
curl --silent --show-error --max-time 5 http://127.0.0.1:11434/api/show \
  -H 'Content-Type: application/json' -d '{"model":"counsel-nano-q5:latest"}' \
  > /private/tmp/healthcraft-nemo-gym-probe/installed-model-info.json
```

The `api/tags` inventory was read before execution, and `api/show` after execution. Raw model information is deliberately excluded from promotion because its Modelfile contains a local model-store path. `model-manifest.json` retains only the relevant sanitized fields and hashes. Post-run standard-library scripts computed hashes/license metadata, checked three loopback ports for `ECONNREFUSED`, and summarized the already saved outputs; none called a model.

The actual install skipped the project build (`--no-install-project`); harnesses import source explicitly from the pinned checkout. No optional component installer, `gym env start`, or default hosted-model quickstart was executed. Exact server/model configurations and request bodies are retained in the trajectory directory.
