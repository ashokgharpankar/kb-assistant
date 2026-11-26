# ADR 0022: Container images and supply-chain checks

**Status:** Accepted, 2026-11-25 (Phase 6a)

## Context

Phase 6 deploys the app: to Kubernetes on kind (6b) and to AWS (6c). Both need container
images, and both should run the *same* images, built once by CI. Images are also where a
large share of real vulnerabilities enter: base-image packages, Python and npm
dependencies, and the build tools themselves.

## Decision

**Images**

- Two images for now: `api` (FastAPI) and `web` (React build served by nginx, which also
  forwards `/api/` to the API: same origin, no CORS). The MCP server gets an image when
  its HTTP transport has token checks (6c, ADR 0012).
- Multi-stage builds. The API's build stage uses uv with the lockfile (`--frozen`,
  `--no-dev`, `--no-editable`); the runtime stage gets only the virtualenv. Dependencies
  are a separate layer, so code changes rebuild in seconds.
- Non-root users with fixed IDs (API 10001; nginx-unprivileged 101 on port 8080); code
  owned by root, so the process can't modify it. Health checks in the image.
- Runtime hardening in Compose (and later in Kubernetes): read-only root filesystem,
  writable `/tmp` only, all Linux capabilities dropped, no privilege escalation.
- **Build once, configure at runtime.** The UI reads its Cognito settings from
  `/config.json`, rendered by nginx from environment variables at start-up; the build-time
  `VITE_*` values remain the fallback for local development.

**Checks in CI**

- **checkov** on Terraform and Dockerfiles, pinned (3.4.11). Accepted findings are skipped
  inline with a written reason, so each exception is reviewed in a diff.
- **trivy** on each built image *before* anything is pushed: fail on HIGH or CRITICAL
  vulnerabilities that have a fix. Exceptions go in `.trivyignore`, with a reason and a date.
- **SBOM** (CycloneDX) for each image, kept as a build artifact.
- Images are pushed to GitHub Container Registry only from `main`, tagged with the commit
  SHA (immutable reference) and `main` (moving pointer).

**Supply chain of the tools themselves**

- Trivy runs from a pinned container image (`aquasec/trivy:0.72.0`), not the
  `aquasecurity/trivy-action` GitHub Action. In March 2026 that action's version tags were
  force-pushed to credential-stealing code and malicious trivy images were published
  (CVE-2026-33634). A version tag is a pointer someone else can move; a digest isn't.
  Next step: pin the scanner image, base images and third-party actions by digest/SHA,
  with Dependabot to update them.

## Why (and what was rejected)

| Option | Rejected because |
|---|---|
| Separate images per environment (build-time config) | Different bytes in dev and prod: what you tested isn't what you ship. |
| Distroless or Alpine Python base | Distroless has no shell for debugging and fewer prebuilt wheels; Alpine (musl) breaks many binary wheels (onnxruntime). Slim Debian is the pragmatic default. |
| Scan only after pushing | A vulnerable image would already be in the registry and pullable. |
| `trivy-action` / unpinned tags | See the March 2026 compromise above. |
| Fail on every vulnerability, including unfixed ones | Blocks every build on issues nobody can act on yet; unfixed ones are tracked, not gated. |
| Docker Hub | GHCR uses the workflow's own token: no extra credentials to store. |

## Consequences

- The API image is large (~500 MB): onnxruntime and FlashRank come with `kb_core` even
  though the reranker is off. Making the reranker an optional extra would cut that.
- The first CI run may fail on a fixable vulnerability in a base image or dependency;
  that's the gate working: update, rebuild, or record a reviewed exception.
- GHCR package visibility follows its own setting: check it after the first push.
- Cognito must allow `http://localhost:8080/` as a callback for the containerised UI
  (Terraform `web_app_urls`).
