# ADR 0006: Quality gates with SonarQube Cloud, coverage and Dependabot

**Status:** Accepted, 2026-11-21. SonarQube Cloud deferred to the end of the project: coverage and Dependabot are active; the Sonar CI step is in place and runs once the `SONAR_TOKEN` secret is added.

## Context

CI already runs Ruff (including Bandit-style security rules), mypy, pytest with
integration tests, Terraform validation and gitleaks. Missing: a coverage
measurement, a view of maintainability (duplication, complexity), deeper
security analysis, and a single pass/fail signal per pull request. Dependencies
are also updated only when someone remembers.

## Decision

- **Coverage:** `pytest-cov` on every CI run, including integration tests; XML
  report with paths relative to the repo root.
- **SonarQube Cloud** (free for public repositories), CI-based analysis, using the
  default "Sonar way" quality gate. The scan waits for the gate result, so a
  failing gate fails the build.
- Analyse Python sources, scripts **and Terraform**.
- **Dependabot** weekly for uv, GitHub Actions and Terraform providers, with
  minor/patch updates grouped and a 5-day cooldown on Python releases.

## Why

- "Sonar way" gates **new code**: at least 80% coverage, no new bugs or
  vulnerabilities, all security hotspots reviewed, low duplication. Gating new
  code keeps standards high without demanding a rewrite of old code.
- CI-based analysis is required for coverage (automatic analysis can't read the
  report).
- SonarQube Cloud over a self-hosted SonarQube Community Build: no server or
  database to run for a public repository. Self-hosting is the answer when
  source code must not leave the network.
- Grouped Dependabot PRs keep the noise to a few PRs a week; each one must pass
  the same gates as human changes.

**Rejected:** CodeQL alongside Sonar (overlapping SAST for this size of project;
revisit if the repository becomes private); a hard overall coverage threshold
in pytest (punishes legacy code; Sonar's new-code gate is the better incentive).

## Consequences

- One more external service and a `SONAR_TOKEN` secret to manage.
- Contributors' PRs from forks don't have the secret, so the scan is skipped
  there (CI still runs everything else).
- Coverage below 80% on new code fails the gate. Pure glue code (CLI wiring)
  needs light tests with fakes, which also catches wiring bugs.
