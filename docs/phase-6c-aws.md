# Phase 6c: AWS foundations: state, ECR and GitHub OIDC

**Time:** 1.5 hours. **AWS cost:** under $1/month (ECR storage for a few images).

**Goal:** get the images into AWS with no long-lived keys anywhere, and fix the last piece
of hand-managed state, so the full deploy (6c-2) is only a `terraform apply` away once
Bedrock access arrives.

**You finish with:**

- The bootstrap stack's state moved from your laptop into S3 (Terraform `import` blocks).
- Two ECR repositories with immutable tags, scan on push and a lifecycle policy.
- A GitHub OIDC provider and a role that only `main` of this repository can assume.
- CI pushing each scanned image to ECR on merge to `main`, tagged with the commit SHA.
- ADRs 0014 (ECS Fargate), 0015 (no NAT Gateway) and 0024 (Aurora replaces S3 Vectors).

6c is split in two because Bedrock is still blocked (incident 0002):

| Part | What | When |
|---|---|---|
| **6c-1 (this guide)** | State, ECR, OIDC, CI push | Now; cheap and useful on its own |
| **6c-2** | VPC, ALB + CloudFront, ECS service, Aurora, Secrets Manager (Part 4) | Written; plan-only until Bedrock works |
| **6c-3** | Ingestion on Bedrock, deploy workflow, first apply | After Bedrock access |

---

## Part 1: Concepts

### 1. Why OIDC instead of access keys in GitHub secrets

| | Access keys in secrets | GitHub OIDC |
|---|---|---|
| What is stored in GitHub | A permanent key pair | Nothing. Only the role ARN, which is not a secret |
| Lifetime of credentials | Until someone rotates them | About 1 hour, per job |
| Who can use them | Any workflow, any branch, anyone who can edit a workflow | Only tokens whose `sub` claim matches the trust policy |
| If leaked | Works from anywhere until revoked | Expires within the hour |

How it works: the job asks GitHub for a signed JWT (`permissions: id-token: write`). The
token says who is asking, for example
`sub = repo:ashokgharpankar@15262181/kb-assistant@1459131240:ref:refs/heads/main` (GitHub's
immutable format with owner and repo IDs, the default for repositories created after mid-2026)
and `aud = sts.amazonaws.com`.
`configure-aws-credentials` sends it to STS `AssumeRoleWithWebIdentity`. STS checks the
signature against GitHub's OIDC provider registered in IAM, checks the trust policy
conditions, and returns temporary credentials.

**The trust policy is the security boundary.** A `sub` condition of `repo:owner/*` would
let any repository you own push images. Ours pins the repository *and* the branch, so a
pull request from a fork, or a feature branch, cannot assume the role.

The OIDC provider has no thumbprint: AWS has verified GitHub's certificate chain itself
since 2023, so thumbprints are ignored.

### 2. ECR settings that matter

| Setting | Our value | Why |
|---|---|---|
| Tag mutability | **IMMUTABLE** | `:abc123` always means the same bytes. Nobody can overwrite a deployed tag |
| Scan on push | On (basic) | A second scanner after trivy; findings visible in the console |
| Encryption | AES-256 (AWS-managed) | KMS CMK costs $1/month and adds nothing for public-source images (checkov skip documented) |
| Lifecycle policy | Untagged after 1 day, keep the last 10 | Storage is $0.10/GB-month; without a policy it only grows |
| `force_delete` | true | `terraform destroy` works in dev without emptying repos by hand |

Because tags are immutable, CI pushes only `:<sha>` to ECR, never `:main` or `:latest`.
GHCR still gets `:main` for local use.

**Tag vs digest:** a tag is a name, a digest (`sha256:…`) is the content. Deployments in
6c-2 pin the digest the CI step prints.

### 3. Moving state with `import` blocks

The bootstrap stack created the state bucket, but its own state was a local file, and
that file was lost in incident 0005. Terraform no longer "knows" the bucket exists, so a
careless apply would try to create it again. The fix:

1. Add `backend "s3" {}` to the bootstrap stack, with key `bootstrap/terraform.tfstate`.
2. Add `import` blocks (Terraform 1.5+) that map each existing resource to its address.
3. `plan` shows **6 to import, 1 to change** (the new multipart-abort lifecycle rule),
   **0 to add, 0 to destroy**. Anything else means stop and read the plan.

`import` blocks are reviewable in a PR and run through the normal plan/apply, unlike the
old `terraform import` command that changed state with no plan. Once imported, the
blocks are harmless no-ops; we keep them as documentation.

### 4. Where the AWS design ended up (6c-2 preview)

```
Browser ──HTTPS──▶ CloudFront (*.cloudfront.net)
                       │  origin-facing prefix list only
                       ▼
                   ALB (public subnets, HTTP 80)
                       │  SG: from ALB SG only
                       ▼
            ECS Fargate task (public subnet, public IP, no inbound from internet)
            ┌──────────────┬──────────────┐
            │ web :8080    │ api :8000    │──▶ Bedrock, Cognito JWKS, Logs, ECR
            └──────────────┴──────────────┘
                              │ SG: 5432 from task SG only
                              ▼
            Aurora Serverless v2 + pgvector (private subnets, 0–2 ACU, auto-pause)
```

| Decision | ADR | One-line reason |
|---|---|---|
| ECS Fargate, not EKS or App Runner | 0014 | EKS control plane ≈ $73/month idle; App Runner closed to new customers |
| No NAT Gateway in dev | 0015 | NAT ≈ $33/month per AZ, more than everything else combined |
| Aurora Serverless v2, not S3 Vectors | 0024 | Hybrid search needs Postgres full-text; Aurora now pauses at 0 ACU |
| CloudFront in front of the ALB | 0015 | HTTPS without buying a domain; Cognito requires HTTPS callbacks |

### 5. Cost, dev, approximate us-east-1

| Item | Running 24×7 | Parked (desired count 0, DB paused) |
|---|---|---|
| ECR (2 repos, ≈ 10 images) | ≈ $0.50 | ≈ $0.50 |
| Fargate 0.5 vCPU / 1 GB (2 containers) | ≈ $18 | $0 |
| Public IPv4 for the task | ≈ $3.65 | $0 |
| ALB | ≈ $16 + LCUs | ≈ $16 (delete via Terraform to stop) |
| Aurora Serverless v2 | ≈ $0.12/ACU-hour while active | Storage only |
| CloudFront, Secrets Manager | < $2 | < $1 |
| Bedrock | Per token | $0 |

6c-1 alone costs well under $1/month. The ALB is the main fixed cost in 6c-2:
`app_desired_count = 0` parks the tasks, `enable_app = false` removes the whole stack.

---

## Part 2: Hands-on

```bash
git checkout main && git pull
git checkout -b phase-6c-aws
unzip -o ~/Downloads/kb-assistant-phase6c1.zip -d .
aws login                       # if the session has expired
cp infra/terraform/envs/dev/backend.hcl ~/kb-backup/        # backups first
cp infra/terraform/envs/dev/terraform.tfvars ~/kb-backup/
make tf-check                   # fmt, validate, checkov: expect 0 failed
```

### Step 1: move the bootstrap state into S3

```bash
make tf-bootstrap-plan
```

Read the plan. Expected summary:

```
Plan: 6 to import, 0 to add, 1 to change, 0 to destroy.
```

The one change is the lifecycle configuration gaining
`abort-incomplete-multipart-uploads`. If you see anything to **destroy** or **add**, stop
and paste the plan to me.

When `init` asks *"Do you want to copy existing state to the new backend?"*: answer
**yes** if a local `terraform.tfstate` exists in `infra/terraform/bootstrap/`; with no local
state there is nothing to copy and the import blocks do the work.

```bash
make tf-bootstrap-apply
aws s3 ls s3://<your-state-bucket>/bootstrap/    # terraform.tfstate is there
```

Keep the old local `terraform.tfstate` file (if any) in `~/kb-backup/` for a week, then delete it.

### Step 2: ECR and the OIDC role

```bash
make tf-plan        # expect 6 to add: 2 repos, 2 lifecycle policies, role, role policy
make tf-apply
terraform -chdir=infra/terraform/envs/dev output github_ecr_push_role_arn
```

The stack does not create the GitHub OIDC provider: an account has only one per URL and
other projects may share it, so it is looked up with a data source. If it does not exist
yet, create it once with the `aws iam create-open-id-connect-provider` command in
`github_oidc.tf`.

### Step 3: tell GitHub the role ARN

```bash
gh variable set AWS_ECR_PUSH_ROLE_ARN --body "$(terraform -chdir=infra/terraform/envs/dev output -raw github_ecr_push_role_arn)"
gh variable set AWS_REGION --body us-east-1     # or your region
gh variable list
```

It is a **variable**, not a secret: a role ARN gives nothing without a valid OIDC token
from this repository's `main` branch.

### Step 4: commit, PR, merge, watch the push

```bash
git add -A
git status            # no backend.hcl, terraform.tfvars, .env, *.tfplan
git commit -m "Phase 6c-1: bootstrap state in S3, ECR, GitHub OIDC push"
git push -u origin phase-6c-aws
gh pr create --fill
```

On the PR, the three ECR steps show as **skipped** (they run only on `main`). After the
merge, open the `images` job on `main`: the step summary shows
`Pushed <account>.dkr.ecr.<region>.amazonaws.com/kb-assistant-dev/api@sha256:…`.

```bash
aws ecr describe-images --repository-name kb-assistant-dev/api \
  --query 'imageDetails[].{tag:imageTags[0],pushed:imagePushedAt,scan:imageScanStatus.status}'
aws ecr describe-image-scan-findings --repository-name kb-assistant-dev/api \
  --image-id imageTag=<sha> --query 'imageScanFindings.findingSeverityCounts'
```

### Step 5: prove the trust policy holds (optional, 2 minutes)

Push a throwaway branch with `on: push` temporarily allowing that branch in the ECR
steps' `if:` and watch `AssumeRoleWithWebIdentity` fail with
`Not authorized to perform sts:AssumeRoleWithWebIdentity`. That failure is the feature.
Revert the change.

---

## Part 3: Interview framing

**"How does your CI authenticate to AWS?"**
GitHub OIDC. No keys are stored. Each job gets a short-lived token, STS exchanges it for
1-hour credentials, and the trust policy pins `aud` to STS and `sub` to this repository's
`main` branch. The role can push to two ECR repositories and nothing else.

**"Why immutable tags?"**
So a tag is a promise. With mutable tags, `:prod` can change under a running service, and
a rollback to "the previous tag" might not give the previous bytes. We tag by commit SHA
and deploy by digest.

**"Why not EKS? You already have a Helm chart."**
The chart proves I can run Kubernetes. For one team and one service, EKS adds a $73/month
control plane and an upgrade cycle for no feature we need. ECS task definitions take the
same security settings. I would choose EKS when there is a platform team or many services.

**"You dropped S3 Vectors. Why?"**
Measured, not taste: hybrid search improved retrieval in Phase 4, and it needs full-text
search next to vectors. Aurora Serverless v2 now scales to zero, which removed the cost
argument for S3 Vectors.

**"No NAT Gateway, so your tasks are in public subnets? Isn't that insecure?"**
Reachability is decided by security groups. The task SG allows inbound only from the ALB
SG; the ALB allows only CloudFront. It is a dev cost trade-off, about $33–66/month saved,
and production would use private subnets with endpoints or a NAT. I say that up front.

---

## Part 4: 6c-2, the app stack as code (plan-only)

Everything the app needs in AWS is written and checked, but **off**: `enable_app = false`,
so `make tf-plan` and `make tf-apply` don't touch it and it costs nothing. `make tf-plan-app`
previews it against the real account without creating anything.

### What's in `infra/terraform/modules/aws-app`

| File | Resources | Notes |
|---|---|---|
| `network.tf` | VPC, 2 public + 2 private subnets, internet gateway, route tables, S3 gateway endpoint | No NAT (ADR 0015); default security group emptied |
| `security.tf` | 3 security groups: ALB, task, database | CloudFront prefix list → ALB:80 → task:8080 → Aurora:5432 |
| `alb.tf` | ALB, target group (`/healthz`), listener, header rule | Requests without the secret `X-Origin-Verify` header get 403 |
| `cloudfront.tf` | Distribution | HTTPS on `*.cloudfront.net`, caching off, all viewer headers except Host |
| `database.tf` | Aurora PostgreSQL Serverless v2 cluster + instance | 0–2 ACU, pauses after 10 min, password managed by RDS in Secrets Manager |
| `ecs.tf` | Cluster, log groups, execution + task roles, task definition, service | web + api in one task, read-only root filesystems, circuit-breaker rollback |

Wiring in `envs/dev/app.tf`: the module gets the Cognito IDs and the Phase 0 Bedrock policy;
Cognito's callback URLs gain the CloudFront address automatically.

### Two roles, two jobs

| Role | Used by | Can do |
|---|---|---|
| Execution role | ECS itself, before the app starts | Pull from ECR, write logs, read **only** the database secret |
| Task role | The application code | Invoke the approved Bedrock models. Nothing else |

The database password never reaches Terraform state, tfvars or the task definition. RDS
creates it in Secrets Manager; ECS injects `KB_DB_USERNAME` and `KB_DB_PASSWORD` at start-up;
the API builds its URL from `KB_DB_HOST` and those values (new settings, with tests).

### Two small changes that came out of writing it

- **Dockerfiles declare `VOLUME`s.** Fargate mounts scratch volumes root-owned 0755 unless
  the image declares the same path with `VOLUME`; then it copies the directory, owner and mode
  included. Without it, nginx (uid 101) couldn't write `/etc/nginx/conf.d` on a read-only root:
  the Phase 6a nginx bug, in a new place. Compose and Kubernetes mount over these paths as before.
- **Images are pinned by digest.** The module refuses a tag (`validation` on `api_image`
  and `web_image`). `make ecr-digests` prints the newest pushed digests.

### Try it

```bash
git checkout main && git pull && git checkout -b phase-6c2-app-stack
unzip -o ~/Downloads/kb-assistant-phase6c2.zip -d .
make tf-init                 # installs the new module and the random provider
make tf-check                # fmt, validate, tflint, checkov
make tf-plan                 # expect: No changes (the app is off)
make ecr-digests             # the two image digests CI pushed
make tf-plan-app             # preview only; -lock=false, nothing is created
```

`tf-plan-app` should show **43 to add** and **1 to change** (the Cognito client gains
the CloudFront URL), **0 to destroy**. Read it like a design review: every security group
rule, the two IAM policies, the task definition's environment (no passwords in it).

### Cost when enabled (dev, us-east-1, approximate)

| Item | Per month, running | Parked (`app_desired_count = 0`) |
|---|---|---|
| Fargate 0.5 vCPU / 1 GB | ≈ $18 | $0 |
| Public IPv4 (task) | ≈ $3.65 | $0 |
| ALB | ≈ $16 + LCUs | ≈ $16 |
| Aurora Serverless v2 | ≈ $0.12 per ACU-hour while active; paused after 10 min idle | storage ≈ $0.10/GB |
| CloudFront, Secrets Manager, logs | < $3 | < $1 |

To stop all fixed cost, set `enable_app = false` and apply: Terraform destroys the stack.

### Still to do before applying (6c-3, after Bedrock)

1. Bedrock quotas approved; `make smoke-bedrock` passes.
2. Ingestion into Aurora with Titan embeddings (512-d): a one-off ECS task or a run from the
   laptop through a temporary tunnel. The local 768-d Ollama vectors can't be copied.
3. A deploy workflow: CI registers a new task definition with the new digests and updates
   the service, using a second OIDC role limited to that service.
4. First apply, smoke test through CloudFront, then incidents and numbers.

---

## Problems found in this phase

- Incident 0011: 6c was branched before 6b merged, so the chart was missing on the 6c branch.
- Incident 0012: trivy blocked the web image on new nginx and Alpine CVEs, with no patched base image yet.
- Incident 0013: the GitHub OIDC provider already existed in the account; now looked up, not owned.
- Incident 0014: GitHub's immutable OIDC subject (`owner@id/repo@id`) didn't match the trust policy.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Error: Backend initialization required` | Old `.terraform` dir from local state | `make tf-bootstrap-plan` already uses `-reconfigure`; rerun |
| Plan shows the bucket to **add** | Import block id does not match the bucket name | Check `local.bucket_name` vs `aws s3 ls`; do not apply |
| `EntityAlreadyExists` for the OIDC provider | Provider created earlier for another project (happened here) | The stack now looks the provider up with a data source instead of owning it, so destroying this stack can't break other projects. Check it lists `sts.amazonaws.com` as a client ID |
| CI: `Not authorized to perform sts:AssumeRoleWithWebIdentity` on main | The token's `sub` doesn't match the trust policy. Repos created after mid-2026 use `repo:owner@ID/name@ID:...` | `gh api repos/OWNER/NAME/actions/oidc/customization/sub`; set `github_repository` to that form (incident 0014) |
| CI: `ImageTagAlreadyExistsException` | Re-run of a commit whose tag already points at different bytes (a rebuild is not byte-identical) | Expected on re-runs; the first image for that SHA stays. Push a new commit instead |
| ECR scan status `UNSUPPORTED_IMAGE` | Basic scanning does not support some base OS versions | trivy in CI is the gate; ECR scan is a second opinion |
