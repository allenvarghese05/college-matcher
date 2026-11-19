.PHONY: setup db-up db-down dev-api test lint fmt migrate data data-sample data-cip-download eval dev-web

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

# ---- Data ----
# DATABASE_URL (read by the backend) and DB_PORT (host port docker compose publishes)
# must agree. On the owner's Mac a native Postgres already holds 5432, so the
# convention is DB_PORT=5433 with
#   DATABASE_URL=postgresql+asyncpg://matcher:matcher@localhost:5433/matcher
# (set both in .env). The config default is 5432, which reaches the native server.
#
# make data          full load: Scorecard CSVs -> Postgres, CIP definitions, embeddings,
#                    and re-export data/fixtures/cip_embeddings.jsonl (commit it).
#                    Needs RAW_DIR/scorecard/*.csv; RAW_DIR/cip/CIPCode2020.csv is optional
#                    (`make data-cip-download`). First embed run downloads the model.
# make data-sample   committed ~200-school sample + CIP embeddings fixture (CI / dev).
RAW_DIR ?= data/raw
RAW_ABS := $(abspath $(RAW_DIR))
CIP_URL := https://nces.ed.gov/ipeds/cipcode/Files/CIPCode2020.csv

data: migrate
	cd $(BACKEND) && uv run python -m ingest.load --raw $(RAW_ABS)/scorecard
	cd $(BACKEND) && uv run python -m ingest.cip --csv $(RAW_ABS)/cip/CIPCode2020.csv
	cd $(BACKEND) && uv run python -m ingest.embed --export

data-sample: migrate
	cd $(BACKEND) && uv run python -m ingest.load --fixture

data-cip-download:
	mkdir -p $(RAW_ABS)/cip
	curl -fsSL -o $(RAW_ABS)/cip/CIPCode2020.csv $(CIP_URL)

# ---- Placeholders: owned by other phases ----

eval:  ## PLACEHOLDER (eval agent)
	@echo "make eval: not yet implemented"

dev-web:  ## PLACEHOLDER (web agent)
	@echo "make dev-web: not yet implemented"
