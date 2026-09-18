.PHONY: test unit integration migrate seed up down lint typecheck format format-check verify

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
