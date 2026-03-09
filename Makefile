.PHONY: test lint smoke install format docker-up docker-down clean

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

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; true
