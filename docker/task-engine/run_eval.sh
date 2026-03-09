#!/bin/bash
# Run HEALTHCRAFT evaluation suite
# Usage: ./run_eval.sh [--task-id TASK_ID] [--model MODEL] [--trials N] [--seed SEED]

set -euo pipefail

TASK_ID="${1:-all}"
MODEL="${HEALTHCRAFT_MODEL:-claude-opus-4-6}"
TRIALS="${HEALTHCRAFT_TRIALS:-5}"
SEED="${HEALTHCRAFT_SEED:-42}"

echo "=== HEALTHCRAFT Evaluation ==="
echo "Tasks:  ${TASK_ID}"
echo "Model:  ${MODEL}"
echo "Trials: ${TRIALS}"
echo "Seed:   ${SEED}"
echo "==============================="

python -m healthcraft.eval_runner \
    --tasks "${TASK_ID}" \
    --model "${MODEL}" \
    --trials "${TRIALS}" \
    --seed "${SEED}" \
    --results-dir /app/results
