#!/bin/bash
# Run scripted, ungraded HEALTHCRAFT smoke checks. No model inference.
# Usage: ./run_eval.sh [TASK_ID] [simulation flags]
# Flags may also be supplied directly, e.g. --tasks IR-001 --trials 1.

set -euo pipefail

MODEL="${HEALTHCRAFT_MODEL:-simulated}"
TRIALS="${HEALTHCRAFT_TRIALS:-5}"
SEED="${HEALTHCRAFT_SEED:-42}"
LOG_LEVEL="${HEALTHCRAFT_LOG_LEVEL:-INFO}"

SIMULATION_ARGS=(simulate --model "${MODEL}" --trials "${TRIALS}" --seed "${SEED}" --log-level "${LOG_LEVEL}")
if [[ $# -gt 0 && "${1}" != -* ]]; then
    SIMULATION_ARGS+=(--tasks "${1}")
    shift
fi
# Omission lets the runner allocate a fresh directory under /app/results.
# An explicitly selected directory must not exist; old results are immutable.
if [[ -n "${HEALTHCRAFT_RESULTS_DIR:-}" ]]; then
    SIMULATION_ARGS+=(--results-dir "${HEALTHCRAFT_RESULTS_DIR}")
fi
exec python -m healthcraft "${SIMULATION_ARGS[@]}" "$@"
