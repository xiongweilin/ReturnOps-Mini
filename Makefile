.PHONY: test unit integration migrate seed up down lint typecheck format format-check verify mutation faultlab-up faultlab-run faultlab-perf faultlab-down

faultlab-up:
	docker compose -f faultlab/docker-compose.faultlab.yml up -d --build

faultlab-run:
	uv run python faultlab/scenarios.py

faultlab-perf:
	uv run python faultlab/run_perf.py

faultlab-down:
	docker compose -f faultlab/docker-compose.faultlab.yml down -v

mutation:
	mutmut run
	mutmut results

lint:
	ruff check .

typecheck:
	mypy

format:
	ruff format .

format-check:
	ruff format --check .

verify: lint typecheck format-check
	pytest -q -m "not integration"

unit:
	pytest -q -m "not integration"

test:
	pytest -q

integration:
	pytest -q -m integration

migrate:
	alembic upgrade head

seed:
	python -m returnops.seed

up:
	docker compose up --build

down:
	docker compose down
