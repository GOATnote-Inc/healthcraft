# Evaluate Your Model

Instructions for running HEALTHCRAFT on a model not yet tested.

## Prerequisites

- Python 3.10+
- The native runner uses an in-memory synthetic world; Docker is optional.
- For free local tests: an Ollama service with already installed weights.
  See [local model setup and measured limitations](LOCAL_MODELS.md).
- For hosted evaluation: supported agent/judge clients and their API keys.
  Judge calls and retries can incur costs; start with a bounded task selection.
- The published corpus has 205 tasks. Runtime depends on selected tasks,
  trials, tool-round limits, model latency, and judging configuration.

## Setup

```bash
# Clone and install
git clone https://github.com/GOATnote-Inc/healthcraft.git
cd healthcraft
python -m pip install -c constraints-security.txt -e ".[dev,eval]"

# Run preflight checks
make preflight
```

Preflight validates schema-handler contracts, evaluator smoke tests, and
criteria-tool existence. Fix any failures before running an evaluation.
This structural check does not certify clinical validity or grader accuracy.

For a hosted run, load the required provider keys from a gitignored `.env`:

```bash
set -a && source .env && set +a
```

Local Ollama runs require no provider keys. They refuse cloud fallback and
never download weights automatically.

## Running an Evaluation

```bash
python -m healthcraft.llm.orchestrator \
  --agent-model <your-model> \
  --judge-model <different-vendor-judge> \
  --tasks IR-001 --rubric-channel v10 \
  --trials 3 \
  --results-dir results/<run-name> \
  --log-level INFO
```

Replace the placeholders with supported, exact model identifiers. Remove
`--tasks IR-001` only when ready to run the full corpus. A short development
run is not a comparable leaderboard evaluation.

### Supported providers

The orchestrator auto-detects the provider from the model name:

| Provider | Model name pattern | API key env var |
|----------|-------------------|-----------------|
| Anthropic | `claude-*` | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-*`, `o1-*`, `o3-*` | `OPENAI_API_KEY` |
| Google | `gemini-*` | `GOOGLE_API_KEY` |
| xAI | `grok-*` | `XAI_API_KEY` |
| Ollama | `ollama:<installed-name>` | None; loopback only |

Provider routing does not imply support for every new model's API contract.
For example, the existing OpenAI Chat Completions adapter is not a validated
Responses adapter for Astra tool use. Verify a model's request and termination
contract before launching a full evaluation.

### Cross-vendor judging

The judge model is automatically selected to avoid self-judging:
- Claude agent -> GPT judge
- GPT agent -> Claude judge
- Other hosted agents -> Claude judge (default)
- Local agents -> deterministic checks only, unless an explicit local judge
  is selected. Local agent and judge must use different recognized vendors.

Missing or failed judgments stay ungraded. A local model judge is diagnostic;
its verdict is not an independently validated clinical reference standard.

### Checkpoint and resume

The orchestrator auto-resumes from existing trajectories. If a run is
interrupted, re-run the same command -- completed trajectories are
detected and skipped. Use `--retry-errors` to re-run only error
trajectories from a previous attempt. Retried trajectories and changed
summaries are written as new attempts; existing evidence is preserved.
Changing task content, prompts, model identity, or evaluation settings requires
a new results directory. Resume rejects incompatible run identities.

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

The first summary is `results/<run-name>/summary.json`; later changed summaries
use numbered files. Inspect the latest summary and its selected attempts.
Relevant fields include:

| Field | Description |
|-------|-------------|
| `agent_model` | Model name used for agent |
| `judge_model` | Model name used for cross-vendor judge |
| `total_tasks` | Number of unique tasks evaluated |
| `total_runs` | Total trajectories (tasks x trials) |
| `pass_rate` | Fraction of trials that passed (all criteria satisfied) |
| `avg_reward` | Mean reward across all trials (Corecraft Eq. 1) |
| `safety_failures` | Fail-closed gate count, including execution errors; not a count of clinical harm |
| `error_runs` | Execution or infrastructure errors, including incomplete agent runs |
| `safety_failures_excl_errors` | Gate failures excluding execution errors; still depends on grading coverage |
| `evaluation_mode` | Full, deterministic-only, or local diagnostic mode |
| `grading_complete` | Whether all required criteria received a judgment |
| `ungraded_criteria` | Required criteria without a valid judgment |

### Offline evidence review

```bash
python scripts/build_evidence_report.py results/<run-name> \
  --output /tmp/healthcraft-evidence-review.html
```

Open the self-contained HTML file in a browser. It selects the latest attempt
for each trial, preserves corrupt attempts as visible problems, and exposes
recorded criterion evidence and full traces. Filters help find execution
errors, incomplete runs, unknown completion, and ungraded criteria. The report
does not rerun models, repair historical scores, or establish clinical validity.
Choose a new output filename for each report; existing reports are preserved.

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
| Pass^3 | Fraction of tasks passed on ALL 3 trials | Empirical repeated-trial reliability |
| Avg Reward | Mean (1/\|C\|) x sum(criteria satisfied) | Overall task completion quality |
| Safety Failure Rate | Fraction of trials violating assessed safety-critical criteria | Rubric safety diagnostic; report errors and unassessed coverage separately |

Distinguish empirical all-trial success from the independence-based estimator
`p**k`; label the estimator and trial count. A model with high Pass@1 but low
all-trial success is inconsistent on this benchmark. Neither score establishes
deployment readiness or better patient outcomes.

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
- **World state:** Native in-memory world seeded deterministically, with task
  injection and any opt-in profiles identified in run provenance.
- **Trials:** Minimum 3 for Pass^k. 5 recommended for Pass^5 comparison
  with tau2-Bench.
- **Judge:** Cross-vendor (never self-judge). Record exact judge identity,
  prompt version, rubric channel, grading errors, and unassessed coverage.
- **Task policy:** `system_prompt_override` replaces the inherited prompt;
  literal `system_prompt_append` is added once after the chosen prompt.

Comparative-value and publication requirements are tracked separately in the
[release evidence plan](RELEASE_EVIDENCE_PLAN.md). Engineering checks and local
diagnostics do not clear those gates.
