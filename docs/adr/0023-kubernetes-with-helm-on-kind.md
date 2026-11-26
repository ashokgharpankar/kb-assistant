# ADR 0023: Kubernetes with a Helm chart, run locally on kind

**Status:** Accepted, 2026-11-26 (Phase 6b)

## Context

The app runs as two hardened images (ADR 0022). Before deploying to AWS (6c), we want to run
it on Kubernetes: most GenAI platforms in industry run there, and the concepts (declarative
desired state, probes, resource requests, Secrets, NetworkPolicies, Pod Security) are what
interviews for platform-facing roles probe. It must cost nothing and run on a 16 GB laptop.

## Decision

1. **kind** (Kubernetes in Docker) for a local one-node cluster. The UI's NodePort is
   published on `localhost:8080`, the same URL as Compose, so Cognito needs no change.
2. **One Helm chart** (`infra/helm/kb-assistant`) for API, UI and an optional in-cluster
   pgvector Postgres (StatefulSet + PersistentVolumeClaim). `postgres.enabled=false` plus
   `externalDatabaseUrl` points the API at a managed database instead.
3. **Security by default, enforced by the cluster:**
   - The namespace is labelled `pod-security.kubernetes.io/enforce=restricted`: Kubernetes
     itself refuses pods that run as root, allow privilege escalation, keep capabilities or
     lack a seccomp profile.
   - Every pod: non-root fixed UID, `seccompProfile: RuntimeDefault`, all capabilities
     dropped, no service-account token (nothing here talks to the Kubernetes API).
   - API and UI: read-only root filesystems, `emptyDir` volumes for scratch space.
   - The Postgres password is mounted as a file (`POSTGRES_PASSWORD_FILE`), not an env var.
   - **NetworkPolicies:** UI ← anyone (port 8080 only), API ← UI only, Postgres ← API only.
4. **Probes:** a startup probe for the API (slow imports), then readiness and liveness;
   `pg_isready` for Postgres. Resource requests everywhere, memory limits, no CPU limits.
5. **Config:** non-secret settings in a ConfigMap; secrets in a Secret that the chart creates
   only for local use (`secrets.create=false` means "bring your own", e.g. External Secrets).
   A checksum annotation restarts pods when their settings change.
6. **Validated in CI** without a cluster: `helm lint`, `helm template`, Kubernetes schema
   validation, and checkov's Kubernetes rules on the rendered manifests. Accepted findings are
   annotations on the resources (`checkov.io/skipN`) with a reason, reviewed in diffs.

## Why (and what was rejected)

| Option | Rejected because |
|---|---|
| minikube / k3d / Docker Desktop Kubernetes | All fine; kind is what many CI systems use for Kubernetes tests, it's disposable, and it runs on OrbStack. |
| Plain manifests or Kustomize | No parameters for per-environment values without overlays; Helm gives install/upgrade/rollback and release history. Kustomize stays a good choice for config-only variation. |
| CPU limits | Limits throttle a bursty request handler even when the node is idle; requests reserve CPU, memory limits catch leaks. |
| Re-ingesting into the cluster | Minutes of embedding with Ollama; `pg_dump` from the local database copies chunks *and* embeddings in seconds. |
| Ingress controller | One more component to install and secure for one local UI; a NodePort is enough here. AWS uses an ALB (6c). |

## Consequences

- Local images are loaded into kind, not pulled, so they have no digest and use
  `IfNotPresent`; checkov findings for that are skipped with a reason. AWS deploys pull
  immutable digests from ECR (6c).
- NetworkPolicies need a network plugin that enforces them. `make k8s-netpol-test` checks it
  on your cluster rather than assuming.
- The in-cluster Postgres is for learning and tests; production uses a managed database
  (ADR for 6c).
- The API reads secrets from environment variables (pydantic settings). Reading them from
  files is a small backlog change.
