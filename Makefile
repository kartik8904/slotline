.PHONY: dev worker test lint migrate seed

dev:
	uv run uvicorn slotline.main:create_app --factory --reload --port 8000 --no-access-log

worker:
	uv run python -m slotline.worker.main

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

migrate:
	uv run alembic upgrade head

seed:
	@echo "seed is not implemented until session 12" >&2; exit 1
