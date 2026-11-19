.PHONY: setup db-up db-down dev-api test lint fmt migrate data eval dev-web

BACKEND := backend

setup:
	cd $(BACKEND) && uv sync

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

dev-api:
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000

migrate:
	cd $(BACKEND) && uv run alembic upgrade head

test:
	cd $(BACKEND) && uv run pytest -q

lint:
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check . && uv run mypy app

fmt:
	cd $(BACKEND) && uv run ruff check --fix . && uv run ruff format .

# ---- Placeholders: owned by other phases ----
data:  ## PLACEHOLDER (data agent)
	@echo "make data: not yet implemented"

eval:  ## PLACEHOLDER (eval agent)
	@echo "make eval: not yet implemented"

dev-web:  ## PLACEHOLDER (web agent)
	@echo "make dev-web: not yet implemented"
