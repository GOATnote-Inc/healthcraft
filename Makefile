.PHONY: test lint smoke install format docker-up docker-down clean eval validate-tasks analyze preflight integrity v8-replay judge-tests v9-smoke

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -q

lint:
	ruff check . && ruff format --check .

format:
	ruff format . && ruff check --fix .

smoke:
	python scripts/smoke_test.py

docker-up:
	docker compose -f docker/docker-compose.yaml up -d --build

docker-down:
	docker compose -f docker/docker-compose.yaml down

eval:
	python -m healthcraft.eval_runner --tasks all --model simulated --trials 1 --seed 42

validate-tasks:
	python -c "from healthcraft.tasks.loader import load_tasks; from pathlib import Path; tasks = load_tasks(Path('configs/tasks')); print(f'{len(tasks)} tasks validated')"

analyze:
	python scripts/analyze_results.py results/pilot-* -o docs/EVALUATION_FINDINGS.md

preflight:  ## Run before any evaluation launch
	python scripts/preflight.py

integrity:  ## Evaluator-integrity test suite (Phase 1)
	pytest tests/test_evaluator_integrity/ -q

v8-replay:  ## Golden-trajectory replay (V8 reproduction)
	pytest tests/test_evaluator_integrity/test_golden_trajectory_replay.py -q

judge-tests:  ## Judge validation test suite (Phase 2)
	pytest tests/test_judge/ -q

v9-smoke:  ## v9 rubric channel smoke test (no API calls)
	pytest tests/test_evaluator_integrity/test_v9_smoke.py -q

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; true
