# Phase 0: Setup and guardrails

**Time:** 3 to 4 hours. **AWS cost:** effectively $0 (a few thousandths of a cent for the Bedrock test).

**You finish with:**

- A working local stack: Python workspace, Postgres + pgvector, Ollama models, Langfuse.
- An AWS account that is safe to build in: no long-lived keys, budgets that alert on real usage, a least-privilege role for the app.
- Terraform managing all of it, with remote state.
- A green CI pipeline on GitHub.

No RAG yet. That is deliberate: Phase 0 is the part most tutorials skip and most production teams insist on.

---

## Part 1: The five ideas behind this phase

### 1. Guardrails before workloads

In a real company you do not get an AWS account and start launching things. A platform team first sets up budgets, tagging and access rules, then hands the account over. We do the same, in that order.

The reason is asymmetry. A budget alert takes ten minutes to set up. A runaway agent loop calling a large model can spend real money in an hour, and you only find out from the bill.

### 2. Local first, cloud second

Every RAG system needs dozens of experiments: chunk sizes, prompts, retrieval settings. If each experiment calls a paid API, you either spend a lot or experiment less.

So the code talks to a *provider interface*. Locally that is Ollama (free). In AWS it is Bedrock (paid). One setting, `KB_LLM_PROVIDER`, switches between them.

| | Ollama (local) | Bedrock |
|---|---|---|
| Cost per call | $0 | Per token |
| Quality | Good enough to test plumbing | Production quality |
| Speed on a Mac | Slower | Fast |
| Use it for | Iterating on chunking, wiring, tests | Evaluation runs, demos, production |

The catch: a small local model answers worse than Nova or Claude. So never judge *answer quality* on Ollama. Judge the *pipeline* there, and quality on Bedrock.

### 3. Short-lived credentials

The classic way to use the AWS CLI is `aws configure`, which writes a permanent access key to `~/.aws/credentials`. Leaked keys of that kind are behind a large share of cloud breaches: they end up in a git commit, a screenshot or a laptop backup, and they work until someone deletes them.

We use `aws login` instead (AWS CLI 2.32 and later). You sign in through the browser, exactly as you do for the console, and the CLI gets temporary credentials that rotate automatically. Nothing permanent is stored on disk.

**Why not IAM Identity Center (SSO)?** That is the standard answer in a company, and the one to give in an interview. But the account-access features of Identity Center need AWS Organizations, and on the Free plan, joining an Organization ends your free credits. `aws login` gives the same security property (no long-lived keys) without that cost.

### 4. Least privilege, tested locally

You log in as an administrator. The application must not run as one. Terraform creates a role, `kb-assistant-dev-app`, that can invoke three named Bedrock models and nothing else.

The smoke test *assumes that role* before calling Bedrock. If the policy is missing a permission, you find out today on your laptop, not in Phase 6 inside a container with no shell.

### 5. Infrastructure as code needs somewhere to keep its memory

Terraform records what it built in a *state file*. Lose it and Terraform no longer knows which resources are its own. Keep it only on your laptop and you cannot run Terraform from CI.

So state lives in an S3 bucket (versioned, encrypted, private). But that bucket has to exist before Terraform can use it. The answer is a tiny separate stack, `bootstrap/`, that creates the bucket and keeps its own state locally. You run it once.

Locking (so two runs cannot corrupt state at the same time) used to need a DynamoDB table. Current Terraform does it with a lock file in the same bucket (`use_lockfile = true`).

---

## Part 2: Step by step

### Step 1: Install the tools (20 min)

```bash
brew install uv fnm awscli gh pre-commit direnv jq tflint trivy gitleaks
brew tap hashicorp/tap && brew install hashicorp/tap/terraform
brew install --cask orbstack visual-studio-code ollama

fnm install 22 && fnm default 22
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc
echo 'eval "$(fnm env --use-on-cd)"' >> ~/.zshrc
exec zsh
```

Open OrbStack once so the Docker engine starts. If you already use Docker Desktop, skip OrbStack; everything works the same.

What each one is for:

| Tool | Job |
|---|---|
| `uv` | Python versions, virtualenv and packages. Replaces pyenv + pip + poetry. |
| `fnm` | Node versions (for the frontend and the MCP Inspector later). |
| `direnv` | Sets `AWS_PROFILE` only inside this project folder. |
| `tflint`, `trivy`, `gitleaks` | Terraform lint, vulnerability scan, secret scan. |
| OrbStack | Runs Docker containers. Lighter than Docker Desktop on a Mac. |
| Ollama | Runs local models. |

### Step 2: Create the repository (15 min)

```bash
mkdir -p ~/code && cd ~/code
unzip ~/Downloads/kb-assistant-phase0.zip && cd kb-assistant

git init -b main
make setup          # uv sync, installs git hooks, creates .env and .envrc
direnv allow
make doctor         # every line should say "ok" except the AWS login (next step)
make lint test      # 22 tests should pass
```

Then publish it:

```bash
git add -A && git commit -m "Phase 0: project skeleton and guardrails"
gh repo create kb-assistant --public --source=. --push
```

The first commit runs the pre-commit hooks. If `ruff format` changes a file, the commit stops; run `git add -A` and commit again. That is the hook doing its job.

**Repository layout:**

```
apps/api/            FastAPI service (deployed to Fargate in Phase 6)
packages/kb_core/    Shared library: settings, pricing, later the RAG pipeline
scripts/             Smoke tests and helper scripts
infra/local/         docker-compose for local data stores
infra/terraform/
  bootstrap/         One-time: the S3 bucket for Terraform state
  envs/dev/          Budgets, tags, IAM. Grows every phase.
docs/                Phase guides, architecture decision records, build log
```

`apps/` versus `packages/` is the main idea. Later there will be three deployables (API, ingestion worker, MCP server) that all share one RAG library. A workspace lets them share code with a single lockfile.

### Step 3: Start the local stack (30 min, mostly downloads)

```bash
make up                                           # Postgres + pgvector on localhost:5433
ollama pull llama3.2 && ollama pull nomic-embed-text
make smoke-ollama
```

You should see a one-sentence answer and a 768-dimension vector. That vector is an *embedding*: the sentence turned into numbers so that similar meanings land close together. Phase 1 is built on that idea.

Now observability:

```bash
make langfuse-up     # six containers, first start takes a few minutes
```

Open http://localhost:3000, sign up (the account is local to your machine), create an organisation and a project called `kb-assistant`, then copy the public and secret keys into `.env`.

Langfuse needs roughly 4 GB of memory for its six containers. On a Mac with 8 GB of RAM, use the free Langfuse Cloud "Hobby" plan instead and set `KB_LANGFUSE_HOST` to the cloud URL. The code is identical either way.

### Step 4: Harden the AWS account (20 min, in the console)

These steps are manual on purpose. Terraform needs an identity to run as, so that identity cannot be created by Terraform.

1. **Root user:** sign in as root, turn on MFA (Security credentials > Assign MFA device). After today, do not use root again.
2. **Create your daily user:** IAM > Users > Create user.
   - Name: `ashok-dev`
   - Tick "Provide user access to the AWS Management Console".
   - Permissions: attach `AdministratorAccess` directly.
   - **Do not create access keys.**
3. Sign out, sign in as `ashok-dev`, and add MFA to this user too.
4. **Do not create an AWS Organization** and do not enable Control Tower. Either one ends your Free plan credits.

`AdministratorAccess` on a personal learning account is a reasonable trade-off: you are the only person, and the app itself never uses these permissions. In a company the equivalent would be a scoped permission set through Identity Center.

Now connect the CLI:

```bash
aws login --profile kb-dev      # choose us-east-1 when asked; a browser tab opens
aws sts get-caller-identity     # should show ...:user/ashok-dev
```

`AWS_PROFILE=kb-dev` is already set by direnv inside the project folder.

### Step 5: Meet Bedrock in the console (10 min)

1. Switch the console region to **US East (N. Virginia)**.
2. Open Amazon Bedrock > Playgrounds > Chat, pick **Amazon > Nova Micro**, and send a prompt.

This does two things: it confirms model access works on your account, and it completes one of the Free plan's credit-earning activities. Billing > Credits lists the others (creating a budget is one of them). Finish the ones you can before going further; each adds credit.

Stay with Amazon's own models (Nova, Titan) for now. Third-party models such as Claude are sold through AWS Marketplace, which the Free plan does not include. We add them when you upgrade.

### Step 6: Terraform the guardrails (30 min)

```bash
cp infra/terraform/envs/dev/terraform.tfvars.example infra/terraform/envs/dev/terraform.tfvars
# edit terraform.tfvars: set alert_email

make tf-bootstrap     # creates the state bucket; type "yes"
make tf-init          # connects envs/dev to that bucket
make tf-plan          # READ this before applying
make tf-apply
```

Read the plan line by line the first time. You should see five resources: two budgets, one IAM role, one IAM policy, one attachment. Nothing in that list costs money.

What you just built:

| Resource | Why |
|---|---|
| Account budget ($15/month) | Alerts at 50% and 100% of actual spend, and when the month is *forecast* to go over. |
| Bedrock budget ($5/month) | Tighter limit on the one service where a bug can spend quickly. |
| Default tags | Every resource gets `Project`, `Env`, `Owner`, `ManagedBy` automatically. |
| App role + policy | The identity the application runs as. |

**The detail worth remembering:** both budgets set `include_credit = false`. By default a budget tracks what you are *billed*, and with credits that is $0 until the credits run out. The alarm would stay silent while you spent them. Excluding credits makes the budget track real usage.

Copy the role into your settings:

```bash
terraform -chdir=infra/terraform/envs/dev output -raw app_role_arn
# paste into .env as KB_APP_ROLE_ARN=...
```

### Step 7: Prove it end to end (10 min)

```bash
make smoke-bedrock
```

Expected: your identity, the assumed role, a one-sentence answer from Nova Micro with token counts and latency, a 512-dimension Titan vector, and a total cost of a few thousandths of a cent.

Now test the guardrail by asking for a model that is *not* on the allow-list:

```bash
KB_BEDROCK_CHAT_MODEL=amazon.nova-pro-v1:0 make smoke-bedrock
```

Expected: `AccessDeniedException`. A security control you have not seen fail is one you only hope works.

### Step 8: Push and watch CI (10 min)

```bash
git add -A && git commit -m "Phase 0: guardrails applied" && git push
gh run watch
```

Three jobs run: Python (lint, types, tests), Terraform (format, validate, lint) and a secret scan. None needs AWS credentials. Deployment jobs arrive in Phase 6 using the same GitHub OIDC pattern as TaskFlow-lite.

### Day 2: per-project cost view (5 min)

A tag only appears in billing after it has been seen on a resource, which takes up to 24 hours. Tomorrow:

1. Billing > Cost allocation tags: confirm `Project` is listed.
2. In `terraform.tfvars` set `enable_project_tag_budget = true`, then `make tf-apply`.
3. Billing > Cost Anomaly Detection: if no "AWS services" monitor exists, also set `enable_anomaly_detection = true`. If one exists already, just add your email to it in the console (AWS allows only one monitor of that type).

---

## Part 3: Decisions and trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| CLI access | `aws login` | Access keys / Identity Center | No long-lived keys; Identity Center would cost the free credits. |
| Region | us-east-1 | ap-south-1 (Mumbai) | Widest Bedrock model list. Latency does not matter for a portfolio. |
| First models | Nova Micro + Titan Embed v2 | Claude | Work on the Free plan and are the cheapest option. |
| Embedding size | 512 dimensions | 1024 | Half the storage and faster search for a small quality loss. We measure that loss in Phase 3. |
| State locking | S3 lock file | DynamoDB table | One fewer resource. |
| State encryption | SSE-S3 | KMS key | Free. KMS adds about $1/month and matters when you need key-level audit. |
| Local vector DB | pgvector | Chroma, FAISS | Real SQL, metadata filters and full-text search in one place, and it carries over to RDS if needed. |
| Observability | Langfuse self-hosted | LangSmith | Open source, runs anywhere, no data leaves your machine. |
| Hooks | Local `uv run` hooks | Pinned remote hook repos | Same tool versions in the hook, `make lint` and CI. |

The three decisions with longer write-ups are in `docs/adr/`. An ADR (architecture decision record) is a short note on what you decided and why. Interviewers ask "why did you choose X?" constantly, and ADRs are how you answer without improvising.

---

## Part 4: What Phase 0 costs

| Item | Cost |
|---|---|
| S3 state bucket | A few kilobytes. Fractions of a cent per month. |
| IAM role, policy, tags | Free. |
| Budgets, anomaly detection | No charge for this kind of use (check the AWS Budgets pricing page if you add budget *actions*). |
| Bedrock smoke test | About $0.00002 per run. |
| Local stack | $0. |

Nothing here runs by the hour. That stays true until Phase 6.

---

## Part 5: Troubleshooting

| Symptom | Fix |
|---|---|
| `aws: 'login' is not a valid command` | `brew upgrade awscli` (needs 2.32 or later). |
| `aws login` fails or uses the wrong account | Remove any `AWS_PROFILE` export from `~/.zshrc`, and move old keys aside: `mv ~/.aws/credentials ~/.aws/_credentials`. |
| Terraform: "No valid credential sources found" | `terraform version` must be 1.15 or later; run `aws login --profile kb-dev` again; check `echo $AWS_PROFILE`. |
| Python: credentials expire after about 15 minutes | `uv sync` (the lockfile pins a new enough `boto3` and `awscrt`). |
| `smoke-bedrock`: AccessDenied on `sts:AssumeRole` | Compare `aws sts get-caller-identity` with the `developer_arn` Terraform output. If you log in through a role instead of an IAM user, set `developer_principal_arn` in `terraform.tfvars`. |
| `smoke-bedrock`: model not available | Confirm the region is us-east-1 and that the model works in the console playground. |
| Port 5432 or 3000 already in use | Another Postgres or dev server is running. Stop it, or change the port in the compose file. |
| Cost allocation tag fails to activate | The tag is not in billing data yet. Wait a day. |

---

## Part 6: Interview hooks

**Questions this phase prepares you for**

1. *"How do you control cost on a GenAI workload?"* Three layers: prevention (model allow-list in IAM, cheap default model, local models for development), detection (budgets on gross usage, a separate Bedrock budget, anomaly detection) and attribution (default tags, cost per call computed in code).
2. *"How do your developers authenticate to AWS?"* Short-lived credentials only. Identity Center in an organisation; the app runs as a separate least-privilege role that developers can assume to reproduce production permissions.
3. *"How do you manage Terraform state?"* S3 with versioning, encryption and native locking, bootstrapped by a separate stack; one state file per environment.

**The trade-off you can speak to from experience**

"Budgets on an account funded by credits are silent by default, because they track billed cost. I excluded credits so the alerts track actual consumption."

**Resume line**

"Established FinOps and security guardrails as code (Terraform) for a GenAI platform: usage-based budgets, cost-allocation tagging, model allow-listing through least-privilege IAM, and keyless developer access."

---

## Part 7: Done checklist

- [ ] `make doctor` shows no missing tools
- [ ] `make lint test` passes
- [ ] `make smoke-ollama` returns an answer and a vector
- [ ] Langfuse opens on localhost:3000 and its keys are in `.env`
- [ ] Root and `ashok-dev` both have MFA; no access keys exist
- [ ] `make tf-apply` completed; the budget confirmation email arrived
- [ ] `make smoke-bedrock` works *through the app role*
- [ ] The non-allowed model is denied
- [ ] CI is green on GitHub
- [ ] First entry written in `docs/build-log.md`

---

## Part 8: Hashnode post 1 (outline)

**Title:** "Before the first prompt: guardrails for a GenAI project on AWS"

1. Why I set up budgets before writing any AI code
2. The credit trap: why my first budget would never have fired
3. No access keys: `aws login` in practice
4. An IAM role that can call three models and nothing else, and how I tested the denial
5. What it cost (nothing) and what comes next (naive RAG, locally)

---

**Next: Phase 1.** Load the AWS Well-Architected documents, chunk them, embed them into pgvector and answer the first question with LangChain, all on local models.
