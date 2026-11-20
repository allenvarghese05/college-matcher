.PHONY: setup db-up db-down dev-api test lint fmt migrate data data-sample data-cip-download eval dev-web \
	eval-db eval-replay eval-record-smoke eval-live pool label

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

# Tests always run against a dedicated *_test database (the session fixture commits
# sample data and FakeEmbedder vectors). tests/conftest.py creates it if missing and
# refuses to write to any database whose name doesn't end in _test.
DB_PORT ?= 5433
TEST_DATABASE_URL ?= postgresql+asyncpg://matcher:matcher@localhost:$(DB_PORT)/matcher_test

test:
	cd $(BACKEND) && DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest -q

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

# ---- Evals (evals/; SPEC §10) ----
# make eval-replay        CI-safe: 3 personas, scripted simulator, committed cassettes
#                         (backend/tests/cassettes/evals), fixture DB, no API key, $0.
# make eval-record-smoke  rebuild those cassettes offline (fake Anthropic transport).
# make eval-live          real Claude run of all personas (Ollama simulator by default),
#                         recorded to evals/recordings so it can be replayed; prints a
#                         cost estimate and needs CONFIRM=1. Writes docs/results.md.
# make pool / make label  labeling workflow (evals/labels/criteria.md).
EVAL_DATABASE_URL ?= postgresql+asyncpg://matcher:matcher@localhost:$(DB_PORT)/matcher_evalsmoke_test
EVAL_SMOKE_PERSONAS ?= aaliyah-ga,maya-oh,zoe-co
EVAL_SMOKE_CASSETTES := tests/cassettes/evals
EVAL_SMOKE_RUN ?= replay-smoke
EVAL_SMOKE_REPORT ?= ../evals/results/$(EVAL_SMOKE_RUN)/results.md
EVAL_SIM ?= ollama
EVAL_PERSONAS ?= ../evals/personas/*.yaml
EVAL_MAX_COST ?= 8
EVAL_CONCURRENCY ?= 2
EVAL_LIVE_RUN ?= live-$(shell date +%Y%m%d-%H%M%S)
RUNS ?= latest

eval: eval-replay

eval-db:
	cd $(BACKEND) && DATABASE_URL=$(EVAL_DATABASE_URL) uv run python ../evals/db_setup.py

eval-replay: eval-db
	cd $(BACKEND) && DATABASE_URL=$(EVAL_DATABASE_URL) EMBEDDER=fake LLM_MODE=replay \
		uv run python ../evals/run.py --mode replay --sim scripted \
		--personas $(EVAL_SMOKE_PERSONAS) --cassette-dir $(EVAL_SMOKE_CASSETTES) \
		--run-id $(EVAL_SMOKE_RUN)
	cd $(BACKEND) && uv run python ../evals/report.py --run $(EVAL_SMOKE_RUN) \
		--out $(EVAL_SMOKE_REPORT) --min-groundedness 0.95 --require-complete

eval-record-smoke: eval-db
	cd $(BACKEND) && rm -f $(EVAL_SMOKE_CASSETTES)/parse-*.json $(EVAL_SMOKE_CASSETTES)/stream-*.json \
		$(EVAL_SMOKE_CASSETTES)/ollama-*.json
	cd $(BACKEND) && DATABASE_URL=$(EVAL_DATABASE_URL) EMBEDDER=fake \
		uv run python ../evals/run.py --mode record --transport fake --sim scripted \
		--personas $(EVAL_SMOKE_PERSONAS) --cassette-dir $(EVAL_SMOKE_CASSETTES) \
		--run-id record-smoke

eval-live:
	cd $(BACKEND) && uv run python ../evals/run.py --mode record --sim $(EVAL_SIM) \
		--personas '$(EVAL_PERSONAS)' --max-cost-usd $(EVAL_MAX_COST) --estimate-only
	@if [ "$(CONFIRM)" != "1" ]; then \
		echo "eval-live calls the Anthropic API. Re-run with: CONFIRM=1 make eval-live"; exit 1; fi
	cd $(BACKEND) && uv run python ../evals/run.py --mode record --sim $(EVAL_SIM) \
		--personas '$(EVAL_PERSONAS)' --max-cost-usd $(EVAL_MAX_COST) \
		--concurrency $(EVAL_CONCURRENCY) --run-id $(EVAL_LIVE_RUN) --confirm --allow-dev-db
	cd $(BACKEND) && uv run python ../evals/report.py --run $(EVAL_LIVE_RUN) --out ../docs/results.md

pool:
	cd $(BACKEND) && uv run python ../evals/labels/pool.py --runs $(RUNS)

label:
	cd $(BACKEND) && uv run python ../evals/labels/label.py $(ARGS)

# ---- Placeholders: owned by other phases ----

dev-web:  ## PLACEHOLDER (web agent)
	@echo "make dev-web: not yet implemented"
