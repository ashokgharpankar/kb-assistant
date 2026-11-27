# One front door for every routine command. Run `make` to see the list.
TF_BOOT := infra/terraform/bootstrap
TF_DEV  := infra/terraform/envs/dev
# tflint left Homebrew (license change). Use a local install if there is one,
# otherwise the official image (Docker or OrbStack must be running).
TFLINT  := $(shell command -v tflint 2>/dev/null || echo docker run --rm -v "$(CURDIR)":/data -t ghcr.io/terraform-linters/tflint)

.DEFAULT_GOAL := help
.PHONY: eval-retrieval eval-index-publish obs-up obs-down obs-reload obs-check metrics ecr-digests tf-plan-app eval eval-agent eval-judge eval-baseline help doctor setup up down langfuse-up langfuse-down lint fmt test test-integration coverage api mcp mcp-http mcp-smoke mcp-inspector \
        smoke-ollama smoke-bedrock fetch-sources init-db ingest ask ask-agent stats data-quality duplicates \
        web-setup web-dev web-demo web-lint web-test web-build \
        docker-build app-up app-down app-logs scan \
        helm-check k8s-up k8s-load-data k8s-status k8s-logs k8s-netpol-test k8s-down \
        tf-bootstrap tf-bootstrap-plan tf-bootstrap-apply tf-backend-hcl tf-init tf-plan tf-apply tf-check tf-output cognito-env cognito-user

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

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

eval-retrieval: ## Retrieval-only evaluation: no model calls, deterministic (what CI runs on every PR)
	uv run kb eval --retrieval-only

eval-index-publish: ## Upload the local index (chunks + embeddings) to the private S3 bucket for CI; then commit eval/index.sha256
	scripts/eval-index.sh publish

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

app-down: ## Stop the api and web containers (local Postgres keeps running)
	$(COMPOSE_APP) rm --stop --force api web

app-logs: ## Follow the api and web container logs
	$(COMPOSE_APP) logs -f api web

# --- observability (Phase 7a) -------------------------------------------------
COMPOSE_OBS = $(COMPOSE_APP) -f infra/local/docker-compose.observability.yml
PROMETHEUS_IMAGE := prom/prometheus:v3.13.5
OBS_DIR := infra/observability

obs-up: ## Start Prometheus (localhost:9095) and Grafana (localhost:3001) for the app containers
	$(COMPOSE_OBS) up -d prometheus grafana
	@echo "Grafana: http://localhost:3001  (dashboard: KB Assistant: overview)"
	@echo "Prometheus: http://localhost:9095/targets  and  /alerts"

obs-down: ## Stop Prometheus and Grafana (their data volumes are kept)
	$(COMPOSE_OBS) rm --stop --force prometheus grafana

obs-reload: ## Reload Prometheus rules after editing them
	curl -fsS -X POST http://localhost:9095/-/reload && echo "reloaded"

obs-check: ## Validate the Prometheus config, rules, rule unit tests and the dashboard JSON
	docker run --rm --entrypoint promtool \
	  -v "$(CURDIR)/$(OBS_DIR)/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
	  -v "$(CURDIR)/$(OBS_DIR)/prometheus/rules:/etc/prometheus/rules:ro" \
	  $(PROMETHEUS_IMAGE) check config /etc/prometheus/prometheus.yml
	docker run --rm --entrypoint promtool -w /p/tests \
	  -v "$(CURDIR)/$(OBS_DIR)/prometheus:/p:ro" \
	  $(PROMETHEUS_IMAGE) test rules kb-assistant.test.yml
	python3 -m json.tool $(OBS_DIR)/grafana/dashboards/kb-assistant-overview.json > /dev/null && echo "dashboard JSON OK"

metrics: ## Show the API's own metrics (needs the API running on localhost:8000)
	@curl -fsS http://localhost:8000/metrics | grep -E "^kb_" | grep -v "_bucket" | head -40

scan: ## Scan the local images with trivy and the repo with checkov (needs both installed)
	trivy image --severity HIGH,CRITICAL --ignore-unfixed kb-assistant-api:local
	trivy image --severity HIGH,CRITICAL --ignore-unfixed kb-assistant-web:local
	checkov -d . --framework terraform dockerfile --compact --quiet --skip-path .venv --skip-path node_modules

# --- Kubernetes on kind (Phase 6b) -----------------------------------------------------
KIND_CLUSTER := kb-assistant
K8S_CTX      := kind-$(KIND_CLUSTER)
K8S_NS       := kb-assistant
HELM_CHART   := infra/helm/kb-assistant
KUBECTL      := kubectl --context $(K8S_CTX) -n $(K8S_NS)
HELM_TEST_SET := --set api.cognito.userPoolId=test --set api.cognito.clientId=test

helm-check: ## Lint and render the Helm chart, validate schemas and run checkov (no cluster needed)
	helm lint $(HELM_CHART) $(HELM_TEST_SET)
	helm template kb $(HELM_CHART) -n $(K8S_NS) $(HELM_TEST_SET) > .helm-rendered.yaml
	uvx kubernetes-validate==1.37.0 -k 1.35.0 --strict .helm-rendered.yaml
	uvx checkov==3.4.11 -f .helm-rendered.yaml --framework kubernetes --compact --quiet
	@rm -f .helm-rendered.yaml

k8s-up: ## Create the kind cluster if needed, load the images, install the chart (UI: localhost:8080)
	@kind get clusters 2>/dev/null | grep -qx $(KIND_CLUSTER) || kind create cluster --config infra/k8s/kind-config.yaml
	kind load docker-image kb-assistant-api:local kb-assistant-web:local --name $(KIND_CLUSTER)
	kubectl --context $(K8S_CTX) create namespace $(K8S_NS) --dry-run=client -o yaml | kubectl --context $(K8S_CTX) apply -f -
	kubectl --context $(K8S_CTX) label namespace $(K8S_NS) pod-security.kubernetes.io/enforce=restricted --overwrite
	@set -a; . ./.env; if [ -f apps/web/.env.local ]; then . apps/web/.env.local; fi; set +a; \
	helm upgrade --install kb $(HELM_CHART) --kube-context $(K8S_CTX) -n $(K8S_NS) --wait --timeout 5m \
	  --set api.cognito.userPoolId="$$KB_COGNITO_USER_POOL_ID" \
	  --set api.cognito.clientId="$$KB_COGNITO_CLIENT_ID" \
	  --set web.cognito.authority="$$VITE_COGNITO_AUTHORITY" \
	  --set web.cognito.clientId="$$VITE_COGNITO_CLIENT_ID" \
	  --set web.cognito.domain="$$VITE_COGNITO_DOMAIN"

k8s-load-data: ## Copy the local Postgres data (chunks and embeddings) into the cluster's database
	@docker compose -f infra/local/docker-compose.yml ps --status running --services | grep -qx postgres \
	  || { echo "Local Postgres isn't running: run 'make up' first."; exit 1; }
	@# pipefail: without it a failed pg_dump would feed psql nothing and still "succeed".
	bash -o pipefail -c 'docker compose -f infra/local/docker-compose.yml exec -T postgres \
	  pg_dump -U kb -d kb --no-owner --no-privileges --clean --if-exists \
	| $(KUBECTL) exec -i kb-postgres-0 -- psql -U kb -d kb -q -v ON_ERROR_STOP=1'
	$(KUBECTL) exec kb-postgres-0 -- psql -U kb -d kb -c "SELECT count(*) AS chunks FROM kb_chunks_ollama_nomic_embed_text_768"

k8s-status: ## Pods, services and the chart's status in the cluster
	$(KUBECTL) get pods,svc,pvc,networkpolicy
	helm status kb --kube-context $(K8S_CTX) -n $(K8S_NS) | head -8

k8s-logs: ## Follow the API logs in the cluster
	$(KUBECTL) logs deploy/kb-api -f

k8s-netpol-test: ## Prove the NetworkPolicies work: web can reach the API, a stray pod can't
	@echo "From the web pod (allowed):"
	@$(KUBECTL) exec deploy/kb-web -- wget -qO- -T 3 http://kb-api:8000/health && echo
	@echo "From a pod in another namespace (should be blocked):"
	@kubectl --context $(K8S_CTX) run netpol-probe -n default --rm -i --restart=Never --image=busybox:1.37 -- \
	  wget -qO- -T 3 http://kb-api.$(K8S_NS):8000/health && echo "REACHABLE: policies are NOT enforced" || echo "blocked, as expected"

k8s-down: ## Delete the kind cluster (and everything in it)
	kind delete cluster --name $(KIND_CLUSTER)

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

tf-bootstrap: ## Brand-new account only: see infra/terraform/bootstrap/versions.tf
	@echo "The bootstrap stack keeps its state in S3 since Phase 6c."
	@echo "Existing account: make tf-bootstrap-plan, then make tf-bootstrap-apply."
	@echo "Brand-new account: follow the comment in $(TF_BOOT)/versions.tf."

# The bootstrap stack's state lives in the bucket it manages (key bootstrap/terraform.tfstate).
# It reuses the dev backend.hcl for the bucket name and region, with its own key.
tf-bootstrap-plan: ## Plan the state-bucket stack (6c: should show 6 imports and 1 change)
	terraform -chdir=$(TF_BOOT) init -reconfigure \
	  -backend-config=../envs/dev/backend.hcl -backend-config=key=bootstrap/terraform.tfstate
	terraform -chdir=$(TF_BOOT) plan -out=bootstrap.tfplan

tf-bootstrap-apply: ## Apply exactly the plan reviewed with tf-bootstrap-plan
	terraform -chdir=$(TF_BOOT) apply bootstrap.tfplan
	@rm -f $(TF_BOOT)/bootstrap.tfplan

tf-backend-hcl: ## Rebuild envs/dev/backend.hcl from the bootstrap stack's outputs (if it's lost again)
	terraform -chdir=$(TF_BOOT) output -raw backend_hcl > $(TF_DEV)/backend.hcl
	@echo "Wrote $(TF_DEV)/backend.hcl"

tf-init: ## Initialise the dev environment against the remote state bucket
	terraform -chdir=$(TF_DEV) init -reconfigure -backend-config=backend.hcl

tf-plan: ## Show what Terraform would change
	terraform -chdir=$(TF_DEV) plan

tf-apply: ## Apply the dev environment
	terraform -chdir=$(TF_DEV) apply

ecr-digests: ## Print the newest api and web images in ECR, pinned by digest
	@scripts/ecr-digests.sh $(TF_DEV)

tf-plan-app: ## Preview the AWS app stack (6c-2) without enabling it; nothing is created
	@scripts/ecr-digests.sh $(TF_DEV) | sed 's/ = /=/' > .app-images.env
	@. ./.app-images.env && rm -f .app-images.env && \
	terraform -chdir=$(TF_DEV) plan -input=false -lock=false \
	  -var enable_app=true -var app_api_image="$$app_api_image" -var app_web_image="$$app_web_image"

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
