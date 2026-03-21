# Evaluate Your Model

Instructions for running HEALTHCRAFT on a model not yet tested.

## Prerequisites

- Python 3.10+
- Docker (for world state PostgreSQL + MCP server)
- API keys for the agent model and a judge model
- ~4 hours for a full 195-task x 3-trial run (varies by model latency)

## Setup

```bash
# Clone and install
git clone https://github.com/GOATnote-Inc/healthcraft.git
cd healthcraft
pip install -e ".[dev]"

# Start the environment
make docker-up

# Load API keys
# Create .env with ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.
set -a && source .env && set +a

# Run preflight checks
make preflight
```

Preflight validates schema-handler contracts, evaluator smoke tests, and
criteria-tool existence. Fix any failures before running an evaluation.

## Running an Evaluation

```bash
python -m healthcraft.llm.orchestrator \
  --agent-model <your-model> \
  --trials 3 \
  --results-dir results/<run-name> \
  --log-level INFO
```

### Supported providers

The orchestrator auto-detects the provider from the model name:

| Provider | Model name pattern | API key env var |
|----------|-------------------|-----------------|
| Anthropic | `claude-*` | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-*`, `o1-*`, `o3-*` | `OPENAI_API_KEY` |
| Google | `gemini-*` | `GOOGLE_API_KEY` |
| xAI | `grok-*` | `XAI_API_KEY` |

### Cross-vendor judging

The judge model is automatically selected to avoid self-judging:
- Claude agent -> GPT judge
- GPT agent -> Claude judge
- Other agents -> Claude judge (default)

### Checkpoint and resume

The orchestrator auto-resumes from existing trajectories. If a run is
interrupted, re-run the same command -- completed trajectories are
detected and skipped. Use `--retry-errors` to re-run only error
trajectories from a previous attempt.

```bash
# Resume interrupted run (same command)
python -m healthcraft.llm.orchestrator \
  --agent-model <your-model> --trials 3 \
  --results-dir results/<run-name>

# Re-run only error trajectories
python -m healthcraft.llm.orchestrator \
  --agent-model <your-model> --trials 3 \
  --results-dir results/<run-name> --retry-errors
```

## Interpreting Results

### summary.json

After completion, `results/<run-name>/summary.json` contains:

| Field | Description |
|-------|-------------|
| `agent_model` | Model name used for agent |
| `judge_model` | Model name used for cross-vendor judge |
| `total_tasks` | Number of unique tasks evaluated |
| `total_runs` | Total trajectories (tasks x trials) |
| `pass_rate` | Fraction of trials that passed (all criteria satisfied) |
| `avg_reward` | Mean reward across all trials (Corecraft Eq. 1) |
| `safety_failures` | Number of trials hitting the safety gate |

### Analysis script

```bash
python scripts/analyze_v7.py \
  --results results/<run-name> \
  --output results/<run-name>/analysis.md \
  --json
```

Produces per-category breakdown, Pass^k metrics, hardest tasks, model
divergence, and Corecraft Table 1 parity comparison.

### Key metrics

| Metric | Definition | Use |
|--------|-----------|-----|
| Pass@1 | Mean pass rate across trials | Expected single-attempt performance |
| Pass@3 | Fraction of tasks passed at least once in 3 trials | Best-case capability |
| Pass^3 | Fraction of tasks passed on ALL 3 trials | Deployment reliability |
| Avg Reward | Mean (1/\|C\|) x sum(criteria satisfied) | Overall task completion quality |
| Safety Failure Rate | Fraction of trials violating any safety-critical criterion | Clinical safety signal |

Pass^k is the primary deployment metric: P(all k trials succeed). A model
with high Pass@1 but low Pass^k is inconsistent.

## Submitting Results

We welcome results from models not yet tested. To submit:

1. Open a pull request or issue on
   [GOATnote-Inc/healthcraft](https://github.com/GOATnote-Inc/healthcraft)
2. Include `summary.json` from your results directory
3. Required metadata:
   - Model name and version (exact model ID)
   - Judge model used
   - Number of trials
   - Date of evaluation
   - HEALTHCRAFT version/commit hash

We will not publish third-party results without the submitter's consent.
Results will be attributed to the submitter unless they prefer anonymity.

## Protocol Notes

To ensure comparability with existing results:

- **Temperature:** 0.0 for both agent and judge
- **Seed:** 42 (deterministic world state)
- **System prompt:** Composite of all 4 files in `system-prompts/`
  (base, mercy_point, policies, tool_reference)
- **World state:** Deterministic from seed. Docker environment provides
  identical state for every run.
- **Trials:** Minimum 3 for Pass^k. 5 recommended for Pass^5 comparison
  with tau2-Bench.
- **Judge:** Cross-vendor (never self-judge). If running a non-Anthropic,
  non-OpenAI model, use Claude as judge.
