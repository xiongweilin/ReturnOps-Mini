.PHONY: test unit integration migrate seed up down

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
