# Phase 6b: Kubernetes with Helm on kind

**Time:** 2 hours. **AWS cost:** $0.

**Goal:** run the same images from 6a on Kubernetes, with security the cluster enforces,
and understand the core objects well enough to explain them in an interview.

**You finish with:**

- A local kind cluster with the UI on http://localhost:8080 (same as Compose).
- `infra/helm/kb-assistant`: API, UI and pgvector Postgres as one Helm release.
- Pod Security "restricted" enforced on the namespace; NetworkPolicies proven with a test.
- The local knowledge base copied into the cluster with `pg_dump`, no re-embedding.
- The chart linted, rendered, schema-validated and scanned in CI on every PR.
- ADR 0023.

---

## Part 1: Concepts

### 1. The objects, mapped to what we built

| Kubernetes object | What it does | Here |
|---|---|---|
| **Deployment** | Keeps N identical, stateless pods running; rolls out new versions | `kb-api`, `kb-web` |
| **StatefulSet** + **PVC** | Pods with a stable name and their own disk that survives restarts | `kb-postgres-0` with a 2 Gi volume |
| **Service** | A stable name and virtual IP in front of changing pods | `kb-api:8000`, `kb-postgres:5432`, `kb-web` (NodePort 30080) |
| **ConfigMap** | Non-secret settings, injected as env vars | `KB_*` settings, Cognito IDs |
| **Secret** | Sensitive values (base64, not encryption!) | DB password and URL, Langfuse keys |
| **NetworkPolicy** | Firewall rules between pods | UI ← anyone, API ← UI, Postgres ← API |
| **Namespace** + Pod Security | Isolation boundary; admission rules for pods | `kb-assistant`, `restricted` |

**Declarative:** you describe the desired state ("2 API pods, this image"), and controllers
keep reality matching it. Kill a pod and the Deployment replaces it.

### 2. Probes: three different questions

| Probe | Question | If it fails |
|---|---|---|
| **startup** | Has it finished starting? | Keep waiting (up to 60 s here); other probes wait too |
| **readiness** | Can it take traffic now? | Removed from the Service, not restarted |
| **liveness** | Is it stuck? | Restarted |

A common mistake is a liveness probe that checks dependencies (the database): one database
blip then restarts every API pod at once. Ours checks only the process (`/health`).

### 3. Requests and limits

- **Requests** reserve capacity: the scheduler only places a pod where they fit.
- **Memory limit:** exceed it and the container is killed (OOMKilled). Catches leaks.
- **CPU limit:** exceed it and the container is *throttled*, even when the node is idle.
  For a request-handling API that's added latency for nothing, so we set CPU requests and
  no CPU limit (checkov flags it; the skip says why).

### 4. Security the cluster enforces

The namespace has `pod-security.kubernetes.io/enforce=restricted`. Kubernetes refuses any
pod that could run as root, escalate privileges, keep Linux capabilities or run without a
seccomp profile. It's no longer just good practice in our YAML: a pod that breaks the rules
can't be created. Try it in Step 5.

Secrets in Kubernetes are only base64-encoded. They're protected by who can read them (RBAC)
and by encryption at rest in the cluster's datastore. In production they come from a secret
store (AWS Secrets Manager via External Secrets) rather than a values file; the chart's
`secrets.create=false` supports that.

### 5. Helm in one paragraph

A **chart** is templated YAML plus default `values.yaml`. `helm upgrade --install` renders it
with your values and applies the result as a **release** with a revision history, so
`helm rollback` returns to the previous revision. Values are how one chart serves kind, a
test cluster and production.

---

## Part 2: What changed in the repo

| Path | What |
|---|---|
| `infra/k8s/kind-config.yaml` | One-node cluster; NodePort 30080 published on 127.0.0.1:8080 |
| `infra/helm/kb-assistant/` | The chart: `values.yaml`, `_helpers.tpl` (labels, security), `api.yaml`, `web.yaml`, `postgres.yaml`, `secret.yaml`, `networkpolicy.yaml`, `NOTES.txt` |
| `Makefile` | `helm-check`, `k8s-up`, `k8s-load-data`, `k8s-status`, `k8s-logs`, `k8s-netpol-test`, `k8s-down`; `make help` now lists targets with digits |
| `.github/workflows/ci.yml` | `iac-scan` also runs `make helm-check` |
| `docs/adr/0023-...md` | The decisions |

Validated before delivery: the chart was rendered with Go's template engine (the one Helm
uses) and checked against the Kubernetes 1.35 schemas (11 objects, all valid) and checkov's
Kubernetes rules (259 passed, 0 failed, 13 skipped with reasons). `helm lint` and a real
install run for the first time on your Mac.

---

## Part 3: Step by step

### Step 1: Apply and check (10 min)

```bash
git checkout main && git pull && git checkout -b phase-6b
unzip -o ~/Downloads/kb-assistant-phase6b.zip -d .
make helm-check            # helm lint, render, schema validation, checkov: all green
```

### Step 2: Create the cluster and install (10 min)

Port 8080 is used by the Compose UI, so stop that first. Images from 6a must exist locally.

```bash
make app-down
docker images | grep kb-assistant     # kb-assistant-api:local and kb-assistant-web:local
make k8s-up                           # creates the cluster on first run (~1 min), installs the chart
make k8s-status
```

All pods should be `Running` and `1/1` ready. If one isn't:

```bash
kubectl --context kind-kb-assistant -n kb-assistant describe pod <name>   # Events at the bottom
kubectl --context kind-kb-assistant -n kb-assistant logs <name>
```

Every `kubectl` here uses `--context kind-kb-assistant`: it can never touch another cluster
you might have configured. Worth making a habit.

### Step 3: Load the data (2 min)

The in-cluster database is empty. Copy the local one in (Compose Postgres must be running:
`make up`):

```bash
make k8s-load-data         # prints the chunk count at the end: expect 2711
```

`pg_dump` copies the schema, the chunks and their embeddings, so nothing is re-embedded.

### Step 4: Use it (5 min)

Open **http://localhost:8080**, sign in, ask a question. Same images, same UI, now on
Kubernetes. The API reaches Ollama on your Mac through `host.docker.internal`.

### Step 5: See Kubernetes doing its job (20 min)

**Self-healing:**

```bash
kubectl --context kind-kb-assistant -n kb-assistant delete pod -l app.kubernetes.io/component=api
kubectl --context kind-kb-assistant -n kb-assistant get pods -w     # a new pod appears; Ctrl+C
```

**NetworkPolicies:**

```bash
make k8s-netpol-test       # web → API: ok; a pod in another namespace → API: blocked
```

If the stray pod *can* reach the API, your cluster's network plugin isn't enforcing
policies. Note it: the policies are still correct, and EKS or a policy-enforcing plugin
would apply them.

**Pod Security admission:** try to start a root pod in our namespace:

```bash
kubectl --context kind-kb-assistant -n kb-assistant run rootpod --image=busybox:1.37 -- sleep 60
```

Kubernetes refuses it with a `violates PodSecurity "restricted"` message listing what's
missing. That's the cluster enforcing the rules, not our YAML.

**Persistence:** delete the database pod; the StatefulSet recreates `kb-postgres-0` with the
same volume, and the data is still there:

```bash
kubectl --context kind-kb-assistant -n kb-assistant delete pod kb-postgres-0
kubectl --context kind-kb-assistant -n kb-assistant wait --for=condition=Ready pod/kb-postgres-0 --timeout=90s
kubectl --context kind-kb-assistant -n kb-assistant exec kb-postgres-0 -- \
  psql -U kb -d kb -c "SELECT count(*) FROM kb_chunks_ollama_nomic_embed_text_768"   # still 2711
```

**Rollback:**

```bash
helm history kb --kube-context kind-kb-assistant -n kb-assistant
helm rollback kb 1 --kube-context kind-kb-assistant -n kb-assistant
```

### Step 6: Commit (10 min)

```bash
git add -A
git commit -m "Phase 6b: Helm chart on kind with Pod Security restricted, NetworkPolicies and CI validation"
git log --oneline origin/main..HEAD   # one commit
git push -u origin phase-6b
gh pr create --fill
gh pr checks --watch
```

When you're done for the day: `make k8s-down` deletes the cluster (the chart and your Compose
database are untouched; `make k8s-up` recreates everything).

---

## Part 4: Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Local cluster | kind | minikube, k3d | Disposable, used in CI, works on OrbStack |
| Packaging | Helm | Kustomize, raw YAML | Values per environment, releases, rollback |
| CPU | Requests, no limits | CPU limits | Limits throttle bursty APIs; memory limits still set |
| Postgres | StatefulSet (local), managed in AWS | Operator (CloudNativePG) | Enough to learn PVCs; production uses RDS/Aurora |
| Exposure | NodePort | Ingress controller | One UI, locally; ALB in AWS |
| Data | `pg_dump` from local | Re-ingest in the cluster | Seconds instead of minutes, no re-embedding |
| Secret delivery | Env vars (API), file (Postgres) | Files everywhere | API change is backlog; Postgres supports `_FILE` natively |

---

## Part 5: Interview hooks

1. *"Readiness vs liveness?"* Readiness takes a pod out of the Service while it can't serve;
   liveness restarts it when it's stuck. Never put dependency checks in liveness: a database
   blip would restart every pod at once. Add a startup probe for slow starters.
2. *"Should you set CPU limits?"* Usually not for latency-sensitive services: CPU limits
   throttle even on an idle node. Set requests for scheduling, memory limits to catch leaks.
3. *"How do you secure workloads on Kubernetes?"* Pod Security admission (`restricted`) so
   the cluster refuses unsafe pods; non-root, read-only filesystems, dropped capabilities,
   seccomp; NetworkPolicies between tiers; no service-account tokens unless needed; secrets
   from a secret store with RBAC and encryption at rest.
4. *"Deployment vs StatefulSet?"* Deployments for interchangeable stateless pods;
   StatefulSets for stable identity and per-pod storage (databases, brokers). In the cloud,
   prefer a managed database unless you need to run it yourself.
5. *"Helm or Kustomize?"* Helm: templating, per-environment values, releases with rollback,
   packaging for others. Kustomize: patch plain YAML per environment, no templates. Both are
   fine; I validate the rendered output in CI (schema + policy checks) either way.

---

## Part 6: Done checklist

- [ ] `make helm-check` green
- [ ] `make k8s-up`: all pods ready; `make k8s-load-data` shows 2711 chunks
- [ ] Signed in and asked a question on http://localhost:8080 (Kubernetes)
- [ ] Self-healing, NetworkPolicy test, Pod Security rejection, persistence, rollback tried
- [ ] PR merged with `iac-scan` (including the Helm chart) green

**Next:** Phase 6c, AWS: re-import the Terraform bootstrap state, then ECS Fargate (ADR:
Fargate vs EKS), ECR with digests, managed Postgres, and GitHub OIDC deploys, planned at $0
and applied only when you choose.
