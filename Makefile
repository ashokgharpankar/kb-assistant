# One front door for every routine command. Run `make` to see the list.
TF_BOOT := infra/terraform/bootstrap
TF_DEV  := infra/terraform/envs/dev

.DEFAULT_GOAL := help
.PHONY: help doctor setup up down langfuse-up langfuse-down lint fmt test test-integration coverage api \
        smoke-ollama smoke-bedrock fetch-sources init-db ingest ask stats data-quality duplicates \
        web-setup web-dev web-demo web-lint web-test web-build \
        tf-bootstrap tf-init tf-plan tf-apply tf-check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

doctor: ## Check that all required tools are installed
	@./scripts/doctor.sh

setup: ## Install Python and web deps, and git hooks
	uv sync
	npm --prefix apps/web ci
	pre-commit install
	@test -f .env || cp .env.example .env
	@test -f .envrc || cp .envrc.example .envrc
	@echo "Done. If you use direnv, run: direnv allow"

up: ## Start local Postgres + pgvector
	docker compose -f infra/local/docker-compose.yml up -d --wait

down: ## Stop local Postgres (data is kept)
	docker compose -f infra/local/docker-compose.yml down

langfuse-up: ## Start local Langfuse (LLM tracing UI on :3000)
	@./scripts/langfuse.sh up

langfuse-down: ## Stop local Langfuse
	@./scripts/langfuse.sh down

lint: ## Ruff + mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

fmt: ## Auto-format and auto-fix
	uv run ruff check --fix .
	uv run ruff format .
	terraform fmt -recursive infra/terraform

test: ## Run unit tests (integration tests skip without a database)
	uv run pytest

test-integration: ## Run all tests, including those that need local Postgres (make up)
	@docker compose -f infra/local/docker-compose.yml exec -T postgres \
		psql -U kb -d kb -tc "SELECT 1 FROM pg_database WHERE datname = 'kb_test'" | grep -q 1 || \
		docker compose -f infra/local/docker-compose.yml exec -T postgres createdb -U kb kb_test
	KB_TEST_DATABASE_URL=postgresql://kb:kb_local_only@localhost:5433/kb_test uv run pytest

coverage: ## Tests with coverage (incl. integration); HTML report in htmlcov/
	KB_TEST_DATABASE_URL=postgresql://kb:kb_local_only@localhost:5433/kb_test \
		uv run pytest --cov --cov-report=term --cov-report=html --cov-report=xml
	@echo "Open htmlcov/index.html for line-by-line coverage"

api: ## Run the API locally on :8000
	uv run uvicorn kb_api.main:app --reload --port 8000

web-setup: ## Install the web UI's dependencies (exact versions from package-lock.json)
	npm --prefix apps/web ci

web-dev: ## Run the web UI on :5173 (needs `make api` or `make web-demo` running)
	npm --prefix apps/web run dev

web-demo: ## Run the API with a scripted answer on :8000 (no Ollama or database needed)
	uv run python scripts/demo_api.py

web-lint: ## Prettier, oxlint and TypeScript checks for the web UI
	npm --prefix apps/web run format:check
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck

web-test: ## Web UI tests with coverage
	npm --prefix apps/web run coverage

web-build: ## Production build of the web UI into apps/web/dist
	npm --prefix apps/web run build

fetch-sources: ## Download the knowledge-base PDFs into data/raw/
	uv run python scripts/fetch_sources.py

init-db: ## Create tables and indexes for the current embedding space
	uv run kb init-db

ingest: ## Load, chunk, embed and store everything in data/raw/ (skips unchanged)
	uv run kb ingest

ask: ## Ask a question: make ask Q="What is the Reliability pillar?"
	uv run kb ask "$(Q)"

stats: ## Show documents and chunks stored
	uv run kb stats

PSQL := docker compose -f infra/local/docker-compose.yml exec -T postgres psql -U kb -d kb -q

data-quality: ## Data-quality report on the ingested chunks (ligatures, headers, ToC, references)
	@$(PSQL) < scripts/sql/data_quality.sql

duplicates: ## Overlap between two documents: make duplicates A=<doc_id> B=<doc_id>
	@$(PSQL) -v a=$(A) -v b=$(B) < scripts/sql/duplicates.sql

smoke-ollama: ## Check local models respond (free)
	uv run python scripts/smoke_ollama.py

smoke-bedrock: ## Check Bedrock models respond (costs a tiny fraction of a cent)
	uv run python scripts/smoke_bedrock.py

tf-bootstrap: ## One-time: create the S3 bucket that stores Terraform state
	terraform -chdir=$(TF_BOOT) init
	terraform -chdir=$(TF_BOOT) apply
	@terraform -chdir=$(TF_BOOT) output -raw backend_hcl > $(TF_DEV)/backend.hcl
	@echo "Wrote $(TF_DEV)/backend.hcl"

tf-init: ## Initialise the dev environment against the remote state bucket
	terraform -chdir=$(TF_DEV) init -backend-config=backend.hcl

tf-plan: ## Show what Terraform would change
	terraform -chdir=$(TF_DEV) plan

tf-apply: ## Apply the dev environment
	terraform -chdir=$(TF_DEV) apply

tf-check: ## Format check, validate and lint Terraform (no AWS access needed)
	terraform fmt -check -recursive infra/terraform
	terraform -chdir=$(TF_BOOT) init -backend=false -input=false >/dev/null && terraform -chdir=$(TF_BOOT) validate
	terraform -chdir=$(TF_DEV) init -backend=false -input=false >/dev/null && terraform -chdir=$(TF_DEV) validate
	tflint --chdir=$(TF_BOOT) && tflint --chdir=$(TF_DEV)
