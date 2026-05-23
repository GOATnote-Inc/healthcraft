#!/usr/bin/env bash
# HealthCraft RL training launch wrapper (PR-D / WS-6).
#
# Usage:
#     make rl-train
#     scripts/rl_train.sh [config_path] [extra_slime_args...]
#
# Default config: configs/rl/slime_grpo.yaml
# Requires:
#   - slime installed (https://github.com/THUDM/slime)
#   - SGLang server reachable (defaults to http://127.0.0.1:30000/v1)
#   - Megatron-LM checkpoint of the open-weights base model
#   - H100 (or equivalent) GPUs
#
# This is the OPERATOR launch wrapper. See docs/RL_RUNBOOK.md for the
# full pre-flight checklist + H100 provisioning.
#
# Score ≠ clinical readiness — the model this trains is a research
# artifact. Held-out prospective physician-blind validation is required
# before any deployment conversation. See docs/RL_COUPLING.md.

set -euo pipefail

CONFIG=${1:-configs/rl/slime_grpo.yaml}
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
export TIMESTAMP

echo "==> HealthCraft RL training"
echo "    config:    $CONFIG"
echo "    timestamp: $TIMESTAMP"

# --- Pre-flight checks (fast; fail loud) ----------------------------------
[ -f "$CONFIG" ] || { echo "ERROR: config not found: $CONFIG"; exit 1; }
[ -d "configs/rl" ] || { echo "ERROR: configs/rl dir missing"; exit 1; }
[ -f "configs/rl/seeds_train.txt" ] || { echo "ERROR: seeds_train.txt missing"; exit 1; }
[ -f "configs/rl/seeds_eval.txt" ] || { echo "ERROR: seeds_eval.txt missing"; exit 1; }
[ -f "configs/rl/reward.yaml" ] || { echo "ERROR: reward.yaml missing"; exit 1; }

# Verify seed pool disjoint-invariant (eval must NEVER leak into train).
.venv/bin/python -c "from healthcraft.rl.seed_pool import SeedPool; SeedPool.load_default()" \
    || { echo "ERROR: SeedPool failed invariant — check seeds_{train,eval}.txt"; exit 1; }

# Verify SGLang reachable (the trainer connects to it).
SGLANG_URL=${SGLANG_BASE_URL:-http://127.0.0.1:30000/v1}
if ! curl -fsS --max-time 3 "$SGLANG_URL/models" >/dev/null 2>&1; then
    echo "ERROR: SGLang server not reachable at $SGLANG_URL"
    echo "       Start it first; see docs/RL_RUNBOOK.md §3 (Bring up SGLang)."
    exit 1
fi

# --- Launch slime ---------------------------------------------------------
shift || true
exec python -m slime.train \
    --config "$CONFIG" \
    --output-dir "results/rl/run-$TIMESTAMP" \
    "$@"
