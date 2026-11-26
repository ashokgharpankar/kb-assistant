# Phase 6a: Containers and CI scanning

**Time:** 2 hours. **AWS cost:** $0 (the Cognito change is free).

**Goal:** the API and the web UI run as hardened containers, built and scanned by CI, so that
Kubernetes (6b) and AWS (6c) run exactly the images that were tested.

**You finish with:**

- `apps/api/Dockerfile` and `apps/web/Dockerfile`: multi-stage, non-root, health checks.
- The UI configured at runtime (`/config.json`), so one image works in every environment.
- `make app-up`: Postgres + API + UI as containers, UI on http://localhost:8080.
- CI jobs: **checkov** (Terraform, Dockerfiles), image build, **trivy** scan, **SBOM**, and a
  push to GitHub Container Registry from `main`.
- ADR 0022.

---

## Part 1: Concepts

### 1. What a good image looks like

| Practice | Why | Here |
|---|---|---|
| Multi-stage build | Build tools (uv, npm, compilers) never reach production | `build` → `runtime` stages |
| Dependencies before code | Docker caches layers; code edits shouldn't reinstall 150 packages | lockfile + `pyproject.toml` copied first |
| Locked, reproducible installs | Same versions in CI, on your Mac and in AWS | `uv sync --frozen`, `npm ci` |
| Non-root, fixed UID | A compromised process can't own the container | API uid 10001, nginx uid 101, port 8080 |
| Read-only filesystem, no capabilities | Attackers can't drop tools or escalate | `read_only`, `cap_drop: ALL`, `no-new-privileges` |
| Health check | The platform restarts what's broken and routes only to what's ready | `/health` (API), `/healthz` (UI) |
| Small context, no secrets | `.env`, `tfvars`, `.git` never enter an image layer | `.dockerignore` |

### 2. Build once, configure at runtime

Vite bakes `VITE_*` variables into the JavaScript at build time. That would mean one image
per environment, so the image you tested isn't the one you ship. Instead, nginx renders
`/config.json` from environment variables when the container starts, and the app reads it
before rendering. In local development (`make web-dev`) there's no `/config.json`, so the
app falls back to `.env.local` as before.

The Cognito IDs aren't secrets (the browser sees them anyway). Real secrets never go in
`/config.json` or in an image: they come from the platform at runtime (Kubernetes Secrets in
6b, Secrets Manager in 6c).

### 3. Scanning: two different questions

| Tool | Question | Fails the build when |
|---|---|---|
| **checkov** | Is the *configuration* risky? (Terraform, Dockerfiles) | A check fails without a written, inline skip reason |
| **trivy** | Does the *image* contain known vulnerabilities? | A HIGH or CRITICAL vulnerability **with a fix available** |
| SBOM (trivy, CycloneDX) | What exactly is inside? | Never: it's the inventory you search when the next big CVE lands |

"Unfixed" vulnerabilities are reported but don't block: nobody can act on them yet. Every
exception is written down: `#checkov:skip=ID:reason` in the Terraform, `.trivyignore` with a
reason and a recheck date.

### 4. The scanner is part of your supply chain too

In March 2026, attackers force-pushed 76 of the 77 version tags of the `trivy-action` GitHub
Action to credential-stealing code and published malicious trivy images (CVE-2026-33634).
Workflows that used `@v0.x` tags ran the attacker's code with their CI secrets.

So CI here runs trivy from a pinned image released after the fix, not the Action. The
complete fix is pinning by **digest** (an image's content hash) and third-party actions by
**commit SHA**, with Dependabot proposing updates. A tag is a pointer someone else can move.

---

## Part 2: What changed in the repo

| Path | What |
|---|---|
| `apps/api/Dockerfile` | uv-based multi-stage build; runtime: slim Python, uid 10001, health check |
| `apps/web/Dockerfile` | Node build → nginx-unprivileged; uid 101, port 8080, health check |
| `apps/web/nginx/*.conf*` | SPA routing, `/api/` proxy (SSE unbuffered), `/config.json`, `/healthz`, security headers and CSP, asset caching |
| `apps/web/src/lib/auth.ts`, `main.tsx` | `loadRuntimeEnv()`: runtime config with build-time fallback; 3 tests |
| `infra/local/docker-compose.app.yml` | API + UI containers next to Postgres; read-only, no capabilities |
| `.dockerignore`, `.trivyignore` | Keep secrets out of images; reviewed vulnerability exceptions |
| `.github/workflows/ci.yml` | `iac-scan` (checkov) and `images` (build, trivy, SBOM, push on main) |
| `infra/terraform/bootstrap/main.tf` | checkov exceptions with reasons (no resource changes) |
| `infra/terraform/envs/dev/variables.tf` | Cognito also allows `http://localhost:8080/` |
| `Makefile` | `docker-build`, `app-up`, `app-down`, `app-logs`, `scan` |
| `docs/adr/0022-...md` | The decisions |

---

## Part 3: Step by step

### Step 1: Apply (10 min)

```bash
git checkout main && git pull && git checkout -b phase-6a
unzip -o ~/Downloads/kb-assistant-phase6a.zip -d .
make lint test                     # 182 passed, 13 skipped
make web-lint web-test             # 44 web tests
```

### Step 2: Let Cognito redirect to the container (5 min, free)

```bash
make tf-plan                       # expect: 1 to change (the app client's callback URLs)
make tf-apply
```

Read the plan before applying: the only change should be `callback_urls` and `logout_urls`
gaining `http://localhost:8080/`. Anything else means stop and check.

### Step 3: Build and run the containers (15 min)

Docker Desktop running, Ollama running, `make up` already done:

```bash
make docker-build                  # first build: a few minutes; later builds: seconds
docker images | grep kb-assistant  # note the sizes
make app-up
curl -s localhost:8000/health
curl -s localhost:8080/config.json
```

Open **http://localhost:8080**, sign in, ask a question. The answer should stream exactly like
the dev server, because nginx passes server-sent events through unbuffered.

Check the hardening for yourself:

```bash
docker exec kb-assistant-api-1 id                  # uid=10001(app)
docker exec kb-assistant-api-1 touch /app/x        # fails: read-only filesystem
docker inspect kb-assistant-api-1 --format '{{.State.Health.Status}}'   # healthy
```

### Step 4: Scan locally (10 min, optional)

```bash
brew install trivy checkov
make scan
```

Compare with what CI reports. If trivy finds a fixable HIGH/CRITICAL, the usual fix is
rebuilding (newer base image) or updating the dependency.

### Step 5: Commit and watch CI (10 min)

```bash
make app-down
git add -A
git commit -m "Phase 6a: hardened container images, runtime UI config, checkov + trivy + SBOM in CI"
git push -u origin phase-6a
gh pr create --fill
gh pr checks --watch
```

New checks on the PR: `iac-scan`, `images (api)`, `images (web)`. Open a run and look at the
trivy table and the SBOM artifacts. After merging, the push to GHCR runs on `main`:

```bash
gh pr merge --squash && gh pr view --json state
gh run watch                       # the main-branch run that pushes the images
```

Then on GitHub: your profile → **Packages**. Check that each package's visibility is what you
want (private is the safe default for this project).

### Problem found on the first run (26 Nov 2026)

**The UI container was "Up" but every request got an empty reply.**

- *Logs:* `20-envsubst-on-templates.sh: ERROR: /etc/nginx/templates exists, but
  /etc/nginx/conf.d is not writable`, then nginx started anyway.
- *Cause:* the container's filesystem is read-only, with a tmpfs mounted at
  `/etc/nginx/conf.d` for the rendered config. tmpfs mounts are owned by root; nginx runs
  as uid 101, so it couldn't write there. The entrypoint logged an error and carried on,
  nginx started with **no site configured**, and connections on 8080 were closed.
- *Caught by:* the image's health check: Docker marked the container `unhealthy`.
- *Fix:* `tmpfs: /etc/nginx/conf.d:mode=1777` (and `/tmp:mode=1777`) in the Compose file.
  Kubernetes (6b) will use an `emptyDir` volume, which the pod's user can write to.
- *Lesson:* hardening changes runtime behaviour; test the hardened container, not just the
  image. And a start-up script that logs an error and continues is a silent failure:
  health checks are what turn it into a visible one.

---

## Part 4: Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Base image | `python:3.12-slim` | Distroless, Alpine | Debuggable, wheels work (onnxruntime); distroless later if size or CVE count demands |
| UI config | Runtime `/config.json` | Build-time `VITE_*` | One image for every environment |
| Scan gate | Fixable HIGH/CRITICAL | Everything / nothing | Actionable failures only; unfixed tracked |
| Scanner install | Pinned trivy image | `trivy-action` | The action's tags were hijacked in 2026 |
| Registry | GHCR | Docker Hub, ECR | Free, uses the workflow token; ECR in 6c for AWS |
| MCP image | Later (6c) | Now | Its HTTP transport needs token checks before it may listen beyond localhost |

---

## Part 5: Interview hooks

1. *"How do you build a secure container image?"* Multi-stage, locked dependencies, non-root
   with a fixed UID, read-only filesystem, no capabilities, health checks, a `.dockerignore`
   that keeps secrets out, and a scan before push that fails on fixable HIGH/CRITICAL.
2. *"What's an SBOM and why keep one?"* A list of every package and version in an image. When
   the next widespread CVE appears, you search SBOMs instead of rebuilding to find out
   whether you're affected.
3. *"How do you configure a SPA per environment?"* Build once, load config at runtime: the web
   server renders a small config file from environment variables. Never put secrets in it.
4. *"Tell me about a supply-chain risk in CI."* The 2026 trivy-action compromise: version tags
   moved to malicious commits, stealing secrets from every workflow that used them. Pin by
   digest or commit SHA, keep workflow permissions minimal, update through reviewed PRs.
5. *"checkov or trivy?"* Different questions: checkov checks configuration (IaC, Dockerfiles);
   trivy finds known vulnerabilities in what you built. Use both, and record every exception
   with a reason.

---

## Part 6: Done checklist

- [ ] `make lint test`, `make web-lint web-test` pass
- [ ] `make tf-plan` showed only the callback URL change; applied
- [ ] `make app-up`: sign-in and a streamed answer on http://localhost:8080
- [ ] Hardening checked: uid, read-only, healthy
- [ ] CI green with `iac-scan` and both `images` jobs; SBOMs downloaded once
- [ ] Merged; images in GHCR, visibility checked

**Next:** Phase 6b, the same images on Kubernetes (kind) with a Helm chart.
