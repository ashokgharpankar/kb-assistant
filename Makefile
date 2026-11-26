# One front door for every routine command. Run `make` to see the list.
TF_BOOT := infra/terraform/bootstrap
TF_DEV  := infra/terraform/envs/dev
# tflint left Homebrew (license change). Use a local install if there is one,
# otherwise the official image (Docker or OrbStack must be running).
TFLINT  := $(shell command -v tflint 2>/dev/null || echo docker run --rm -v "$(CURDIR)":/data -t ghcr.io/terraform-linters/tflint)

.DEFAULT_GOAL := help
.PHONY: eval eval-agent eval-judge eval-baseline help doctor setup up down langfuse-up langfuse-down lint fmt test test-integration coverage api mcp mcp-http mcp-smoke mcp-inspector \
        smoke-ollama smoke-bedrock fetch-sources init-db ingest ask ask-agent stats data-quality duplicates \
        web-setup web-dev web-demo web-lint web-test web-build \
        docker-build app-up app-down app-logs scan \
        tf-bootstrap tf-init tf-plan tf-apply tf-check tf-output cognito-env cognito-user

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

eval: ## Score the pipeline on eval/dataset.jsonl (Postgres + Ollama running)
	uv run kb eval

eval-agent: ## Score the LangGraph agent instead of the pipeline (compares with the baseline)
	uv run kb eval --mode agent

eval-judge: ## Same, plus an LLM judge for groundedness (slower)
	uv run kb eval --judge

eval-baseline: ## Run and save the result as eval/baseline.json (commit it)
	uv run kb eval --update-baseline

mcp: ## Run the MCP server over stdio (normally a client launches it, not you)
	uv run kb-mcp

mcp-http: ## Run the MCP server over streamable HTTP on 127.0.0.1:8765/mcp
	uv run kb-mcp --transport streamable-http --port 8765

mcp-smoke: ## Start the MCP server over stdio and call every tool: make mcp-smoke [Q="..."]
	uv run python scripts/mcp_smoke.py $(Q)

mcp-inspector: ## Open the MCP Inspector UI against the server (needs Node)
	npx -y @modelcontextprotocol/inspector uv run kb-mcp

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

COMPOSE_APP = docker compose -f infra/local/docker-compose.yml -f infra/local/docker-compose.app.yml

docker-build: ## Build the API and web images (same Dockerfiles CI uses)
	docker build -f apps/api/Dockerfile -t kb-assistant-api:local .
	docker build -f apps/web/Dockerfile -t kb-assistant-web:local .

app-up: ## Run postgres + api + web as containers: UI on http://localhost:8080
	$(COMPOSE_APP) up -d --build
	@echo "UI: http://localhost:8080   API: http://localhost:8000/health"

app-down: ## Stop the app containers (Postgres data is kept)
	$(COMPOSE_APP) down

app-logs: ## Follow the api and web container logs
	$(COMPOSE_APP) logs -f api web

scan: ## Scan the local images with trivy and the repo with checkov (needs both installed)
	trivy image --severity HIGH,CRITICAL --ignore-unfixed kb-assistant-api:local
	trivy image --severity HIGH,CRITICAL --ignore-unfixed kb-assistant-web:local
	checkov -d . --framework terraform dockerfile --compact --quiet --skip-path .venv --skip-path node_modules

fetch-sources: ## Download the knowledge-base PDFs into data/raw/
	uv run python scripts/fetch_sources.py

init-db: ## Create tables and indexes for the current embedding space
	uv run kb init-db

ingest: ## Load, chunk, embed and store everything in data/raw/ (skips unchanged)
	uv run kb ingest

ask: ## Ask a question: make ask Q="What is the Reliability pillar?"
	uv run kb ask "$(Q)"

ask-agent: ## Ask through the agent and show its steps: make ask-agent Q="..."
	uv run kb ask --mode agent "$(Q)"

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
	terraform -chdir=$(TF_DEV) init -reconfigure -backend-config=backend.hcl

tf-plan: ## Show what Terraform would change
	terraform -chdir=$(TF_DEV) plan

tf-apply: ## Apply the dev environment
	terraform -chdir=$(TF_DEV) apply

tf-output: ## Show Terraform outputs (app role ARN, Cognito IDs and URLs)
	terraform -chdir=$(TF_DEV) output

cognito-env: ## Print the Cognito settings for .env and apps/web/.env.local
	@echo "# ---- add to .env (repo root) ----"
	@terraform -chdir=$(TF_DEV) output -raw env_api
	@echo "# ---- add to apps/web/.env.local ----"
	@terraform -chdir=$(TF_DEV) output -raw env_web

cognito-user: ## Invite a user by email: make cognito-user EMAIL=you@example.com
	@test -n "$(EMAIL)" || { echo "usage: make cognito-user EMAIL=you@example.com"; exit 2; }
	@POOL=$$(terraform -chdir=$(TF_DEV) output -raw cognito_user_pool_id); REGION="$${POOL%%_*}"; \
	if aws cognito-idp admin-get-user --region "$$REGION" --user-pool-id "$$POOL" --username "$(EMAIL)" >/dev/null 2>&1; then \
	  echo "$(EMAIL) already exists. To email a new temporary password:"; \
	  echo "  aws cognito-idp admin-create-user --region $$REGION --user-pool-id $$POOL --username $(EMAIL) --message-action RESEND"; \
	else \
	  aws cognito-idp admin-create-user --region "$$REGION" --user-pool-id "$$POOL" \
	    --username "$(EMAIL)" \
	    --user-attributes Name=email,Value="$(EMAIL)" Name=email_verified,Value=true \
	    --desired-delivery-mediums EMAIL \
	    --query 'User.{username:Username,status:UserStatus}' --output table && \
	  echo "Cognito has emailed a temporary password to $(EMAIL) (from no-reply@verificationemail.com; check spam). It expires in 3 days."; \
	fi

tf-check: ## Format check, validate and lint Terraform (no AWS access needed)
	terraform fmt -check -recursive infra/terraform
	@# A separate data dir, so this never replaces the real backend set up by tf-init
	@# (validating with -backend=false in .terraform makes the next plan ask for init).
	TF_DATA_DIR=.terraform-validate terraform -chdir=$(TF_BOOT) init -backend=false -input=false >/dev/null
	TF_DATA_DIR=.terraform-validate terraform -chdir=$(TF_BOOT) validate
	TF_DATA_DIR=.terraform-validate terraform -chdir=$(TF_DEV) init -backend=false -input=false >/dev/null
	TF_DATA_DIR=.terraform-validate terraform -chdir=$(TF_DEV) validate
	$(TFLINT) --chdir=$(TF_BOOT)
	$(TFLINT) --chdir=$(TF_DEV)
