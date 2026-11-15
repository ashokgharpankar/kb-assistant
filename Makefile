# One front door for every routine command. Run `make` to see the list.
TF_BOOT := infra/terraform/bootstrap
TF_DEV  := infra/terraform/envs/dev

.DEFAULT_GOAL := help
.PHONY: help doctor setup up down langfuse-up langfuse-down lint fmt test api \
        smoke-ollama smoke-bedrock tf-bootstrap tf-init tf-plan tf-apply tf-check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

doctor: ## Check that all required tools are installed
	@./scripts/doctor.sh

setup: ## Install Python deps and git hooks
	uv sync
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

test: ## Run unit tests
	uv run pytest

api: ## Run the API locally on :8000
	uv run uvicorn kb_api.main:app --reload --port 8000

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
