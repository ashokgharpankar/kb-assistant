# Phase 1.5: Quality gate

**Time:** about 2 hours. **Cost:** $0 (SonarQube Cloud is free for public repositories).

**You finish with:**

- Test coverage measured on every CI run (currently about 90% including integration tests).
- SonarQube Cloud analysing every push and pull request, with one pass/fail quality gate.
- Dependabot opening grouped, weekly dependency-update PRs that must pass the same gates.
- A quality-gate badge on the README.

---

## Part 1: Concepts

### What each gate catches

Every PR now passes through layers that catch different problems:

| Gate | Catches | Runs |
|---|---|---|
| Ruff | Style, bugs, unsafe patterns (Bandit rules) | pre-commit + CI |
| mypy | Type errors | pre-commit + CI |
| pytest + coverage | Broken behaviour; code no test exercises | CI |
| gitleaks | Committed secrets | pre-commit + CI |
| Terraform fmt/validate/tflint | Broken or sloppy infrastructure code | pre-commit + CI |
| **SonarQube Cloud** | Duplication, complexity, maintainability, deeper security issues (Python and Terraform), coverage on new code | CI |
| **Dependabot** | Outdated or vulnerable dependencies | Weekly PRs |

Later phases add `trivy` (container images), `checkov` (infrastructure policy) and an evaluation gate on *answer quality* (Phase 7).

### Coverage: a signal, not a target

Coverage says which lines ran during tests, not whether the tests check anything useful. A test that calls a function without asserting anything raises coverage and proves nothing. Use it to **find untested code**, then decide whether that code matters.

Adding coverage here immediately found something: `cli.py` had **0%** coverage. Five small tests with fakes (no database, no model) took it to 78% and check the CLI's wiring and output.

### The quality gate and "new code"

SonarQube's default gate, **Sonar way**, judges **new code**: what changed since the previous version or within a PR. Roughly: at least 80% coverage on new code, no new bugs or vulnerabilities, security hotspots reviewed, low duplication. (Check the exact conditions under Quality Gates in SonarQube Cloud.)

Gating new code is the practical choice for real teams: you can adopt it on a legacy codebase on day one without fixing everything first, and quality improves with every change.

### Why CI-based analysis

SonarQube Cloud can analyse a repository automatically, without CI. But automatic analysis cannot read a coverage report, so we run the scanner in GitHub Actions after the tests, and it uploads `coverage.xml` with the results.

`fetch-depth: 0` in the checkout step gives the scanner full git history, which it uses to tell new code from old and to attribute issues.

---

## Part 2: What changed in the repo

```
.github/workflows/ci.yml       Full-history checkout, tests with coverage, SonarQube scan + gate wait
.github/dependabot.yml         Weekly grouped updates: uv, GitHub Actions, Terraform providers
sonar-project.properties       Organisation, project key, sources (incl. Terraform), coverage path
pyproject.toml                 pytest-cov; coverage config (branch coverage, relative paths)
packages/kb_core/tests/test_cli.py   CLI tests with fakes
Makefile                       `make coverage` (terminal + HTML + XML report)
docs/adr/0006-quality-gates.md, docs/adr/README.md (planned ADRs renumbered from 0007)
```

---

## Part 3: Step by step

### Step 1: Apply and run locally (10 min)

```bash
unzip -o ~/Downloads/kb-assistant-phase1_5.zip -d ~/Projects/kb-assistant
uv sync
make lint test          # 55 passed, 4 skipped
make up
make coverage           # 59 passed, about 90% total
open htmlcov/index.html # red lines = never executed by any test
```

### Step 2: Set up SonarQube Cloud (15 min)

1. Go to **sonarcloud.io** and sign in with GitHub.
2. Create an organisation from your GitHub account. Choose the **free** plan.
3. **Analyze new project** → select `kb-assistant` → Set up.
4. Choose **With GitHub Actions** as the analysis method. This also turns off automatic analysis, which must be off for coverage to work. If it's still on: Administration → Analysis Method → switch Automatic Analysis **off**.
5. Copy the **SONAR_TOKEN** it shows.
6. Note the **Organization key** and **Project key**, and compare them with `sonar-project.properties`. Fix the file if they differ.
7. For "new code", choose **Previous version** (or "Number of days: 30" if you prefer).

### Step 3: Add the token to GitHub (2 min)

```bash
gh secret set SONAR_TOKEN        # paste the token when prompted
gh secret list                   # SONAR_TOKEN should be listed
```

The token is stored encrypted by GitHub and never appears in logs. Don't put it in `.env` or any file.

### Step 4: Push and watch (10 min)

```bash
git add -A
git commit -m "Phase 1.5: coverage, SonarQube Cloud quality gate, Dependabot"
git push
gh run watch
```

The Python job now ends with **SonarQube Cloud scan and quality gate**. Open your project in SonarQube Cloud to see the dashboard: issues, security hotspots, coverage, duplication.

### Step 5: Work through the first findings (30 to 60 min)

The first analysis usually reports a handful of issues. For each:

- **Bug or vulnerability:** fix it.
- **Security hotspot:** review it. A hotspot is code that *might* be sensitive (for example `subprocess` or a hard-coded local password in docker-compose). Mark it **Safe** with a one-line reason, or fix it.
- **Code smell:** fix it if it improves the code; otherwise mark it **Accepted** with a reason. Not every rule fits every project.

Keep a note of anything interesting for your build log; "what did Sonar find that Ruff didn't?" is a good interview story.

### Step 6: Branch protection (5 min)

So the gates actually block merges: GitHub repo → **Settings → Branches → Add rule** for `main`:

- Require a pull request before merging
- Require status checks to pass: `python`, `terraform`, `secrets`

From now on, work on a branch and merge through a PR. That's also how Dependabot's PRs will arrive.

### Step 7: Dependabot

Nothing to do: the file is enough. On Monday you'll see grouped PRs (for example "Bump the python-minor-and-patch group"). Each one runs the full CI and Sonar gate. Merge them when green.

---

## Part 4: Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Static analysis service | SonarQube Cloud | Self-hosted SonarQube; Codacy; CodeQL | Free for public repos, no server to run, PR decoration, analyses Terraform too |
| Analysis mode | CI-based | Automatic analysis | Automatic analysis can't read coverage |
| Gate scope | New code ("Sonar way") | Overall thresholds | Raises the bar on every change without a big-bang cleanup |
| Coverage threshold in pytest | None | `--cov-fail-under=80` | One gate in one place (Sonar), on new code |
| Dependency updates | Dependabot, grouped, 5-day cooldown | Renovate; manual | Native to GitHub; grouping limits noise; cooldown avoids broken fresh releases |

---

## Part 5: Interview hooks

1. *"How do you enforce code quality across a team?"* Layered gates: fast local checks in pre-commit, the same checks in CI, a quality gate on new code that blocks merges via branch protection, and dependency updates that must pass the same gates.
2. *"What's your view on code coverage targets?"* Coverage finds untested code; it doesn't prove tests are good. Gate it on new code, not overall, and pair it with review of what the tests assert.
3. *"SonarQube Cloud or self-hosted?"* Cloud for public or low-sensitivity code (no infrastructure to run); self-hosted when source code must stay inside the network, or for compliance.

**Resume line:** "Introduced quality gates (SonarQube Cloud on new code, branch coverage, Dependabot) with branch protection, so every change, including automated dependency updates, passes the same checks."

---

## Part 6: Done checklist

- [ ] `make coverage` runs locally; HTML report opened
- [ ] SonarQube Cloud project created, automatic analysis off
- [ ] `SONAR_TOKEN` secret added; keys in `sonar-project.properties` match
- [ ] CI green including the Sonar step; quality gate passed
- [ ] First findings triaged (fixed, or marked Safe/Accepted with reasons)
- [ ] Branch protection on `main`
- [ ] README badge shows the gate status

**Next: Phase 2.** Bedrock provider, streaming answers, a React UI with Cognito sign-in, and Langfuse tracing.
