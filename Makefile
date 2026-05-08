.PHONY: test lint smoke install format docker-up docker-down clean eval validate-tasks analyze preflight integrity v8-replay judge-tests v9-smoke v10-smoke v11-smoke ensemble-tests consensus hard release leaderboard release-tests agents-assemble-smoke

PYTHON := .venv/bin/python3
PYTEST := .venv/bin/pytest

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTEST) tests/ -q

lint:
	$(PYTHON) -m ruff check . && $(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format . && $(PYTHON) -m ruff check --fix .

smoke:
	$(PYTHON) scripts/smoke_test.py

docker-up:
	docker compose -f docker/docker-compose.yaml up -d --build

docker-down:
	docker compose -f docker/docker-compose.yaml down

eval:
	$(PYTHON) -m healthcraft.eval_runner --tasks all --model simulated --trials 1 --seed 42

validate-tasks:
	$(PYTHON) -c "from healthcraft.tasks.loader import load_tasks; from pathlib import Path; tasks = load_tasks(Path('configs/tasks')); print(f'{len(tasks)} tasks validated')"

analyze:
	$(PYTHON) scripts/analyze_results.py results/pilot-* -o docs/EVALUATION_FINDINGS.md

preflight:  ## Run before any evaluation launch
	$(PYTHON) scripts/preflight.py

integrity:  ## Evaluator-integrity test suite (Phase 1)
	$(PYTEST) tests/test_evaluator_integrity/ -q

v8-replay:  ## Golden-trajectory replay (V8 reproduction)
	$(PYTEST) tests/test_evaluator_integrity/test_golden_trajectory_replay.py -q

judge-tests:  ## Judge validation test suite (Phase 2)
	$(PYTEST) tests/test_judge/ -q

v9-smoke:  ## v9 rubric channel smoke test (no API calls)
	$(PYTEST) tests/test_evaluator_integrity/test_v9_smoke.py -q

v10-smoke:  ## v10 rubric channel smoke test (includes 11 banned-IDs regression lock)
	$(PYTEST) tests/test_evaluator_integrity/test_v10_smoke.py -q

v11-smoke:  ## v11 rubric channel smoke test (consensus overlay scaffolding)
	$(PYTEST) tests/test_evaluator_integrity/test_v11_smoke.py -q

ensemble-tests:  ## EnsembleJudge unit tests (stub clients, no API calls)
	$(PYTEST) tests/test_llm/ -q

release-tests:  ## HuggingFace release contract tests (no network)
	$(PYTEST) tests/test_release/ -q

consensus:  ## Build HealthCraft-Consensus subset (requires judge API keys + Ensemble execution $)
	$(PYTHON) scripts/build_consensus.py \
		--results results/pilot-v8-claude-opus results/pilot-v8-gpt54 results/pilot-v9-gemini-pro \
		--output data/consensus/healthcraft_consensus_v1.jsonl \
		--manifest data/consensus/consensus_criteria.yaml

hard:  ## Build HealthCraft-Hard subset (bottom 20% by frontier-agent mean reward, no API calls)
	$(PYTHON) scripts/build_hard.py \
		--results results/pilot-v8-claude-opus results/pilot-v8-gpt54 results/pilot-v9-gemini-pro \
		--output data/hard/healthcraft_hard_v1.jsonl \
		--manifest data/hard/hard_tasks.yaml

release:  ## Build HuggingFace release artifacts (Full/Consensus/Hard JSONLs + manifest + dataset card)
	$(PYTHON) scripts/build_huggingface_release.py \
		--output-dir data/huggingface_release \
		--version 1.0.0

leaderboard:  ## Regenerate docs/LEADERBOARD.md from docs/MODEL_CARDS/*.md
	$(PYTHON) scripts/regen_leaderboard.py

agents-assemble-smoke:  ## Smoke + E2E tests for the Agents Assemble hackathon submissions
	$(PYTEST) tests/test_agents_assemble/ -q

agents-assemble-validate:  ## End-to-end validation harness with metrics summary
	$(PYTHON) scripts/validate_agents_assemble.py

agents-assemble-fuzz:  ## Randomized breadth report (30 rules x 200 trials each)
	$(PYTHON) scripts/fuzz_agents_assemble.py

agents-assemble-cds-hooks:  ## Run the live CDS Hooks /cds-services HTTP service on :8080
	$(PYTHON) -m healthcraft.agents_assemble.cds_hooks_server --port 8080

agents-assemble-smart-demo:  ## Pull a synthetic patient from r4.smarthealthit.org and route them through the agent
	$(PYTHON) scripts/load_smart_sandbox.py

agents-assemble-baseline:  ## Empirical comparison: LLM-alone vs LLM+Superpower
	$(PYTHON) scripts/compare_baseline.py

agents-assemble-demo:  ## Run the triage agent against each labeled demo bundle
	@for sid in stemi pe_high pe_low sepsis; do \
		echo "=== $$sid ==="; \
		$(PYTHON) scripts/validate_agents_assemble.py --scenario $$sid; \
	done

agents-assemble-docker:  ## Build the ED Decision Rules Superpower image
	docker build \
		-f src/healthcraft/agents_assemble/docker/Dockerfile \
		-t agents-assemble/ed-decision-rules .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; true
