.PHONY: test lint smoke install format docker-up docker-down clean eval validate-tasks analyze preflight

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

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; true
