# Phase 7c: The evaluation as a CI gate

**Time:** 1–1.5 hours. **Cost:** $0 (GitHub-hosted runners, local models).

**Goal:** a change that makes retrieval worse can't merge, and a change that makes answers
worse is caught within a day. The same evaluation and gate you run locally, in CI.

**You finish with:**

- `kb eval --retrieval-only`: retrieval, the similarity floor and the input screen, with no
  model calls. Deterministic.
- `.github/workflows/eval.yml` with two tiers: retrieval on every relevant pull request; the
  full evaluation nightly, on demand, or with the label `eval:full`.
- The index (chunks and embeddings) as a checksum-verified fixture: a GitHub release asset
  plus `eval/index.sha256` in the repo.
- ADR 0025.

---

## Part 1: Concepts

### 1. Why evaluation belongs in CI

Unit tests check code paths. They didn't catch any of the quality changes in this project:
retrieval went from 79% to 96% hit rate in Phase 4 through configuration (heading paths,
hybrid search), and a reranker made it worse (88%) with every unit test green. An LLM app's
behaviour lives in data, prompts and settings, so the gate has to measure behaviour.

### 2. Two tiers: fast and deterministic, slow and complete

| | Tier 1: retrieval | Tier 2: full |
|---|---|---|
| When | Every PR touching `packages/kb_core`, `eval/`, `uv.lock` | Nightly, "Run workflow", or label `eval:full` |
| Model calls | Embeddings only | Embeddings + the chat model |
| Measures | Hit rate, MRR, floor, input screen | Everything: answers, refusals, citations, grounding, cost |
| Deterministic | Yes | No (generation varies) |
| Time on a hosted runner | ~3 min | ~20–30 min on CPU; minutes on Bedrock |

Most regressions in this project's history were retrieval regressions, and those are cheap and
deterministic to catch. Generation is slow and noisy on CPU, so it runs where the wait doesn't
block anyone.

### 3. Reproducibility: the index is a fixture

CI must evaluate the same chunks and embeddings as the baseline, or a "regression" might just
be a different index. Re-ingesting the PDFs in CI would take minutes and could differ. Instead:

1. `make eval-index-publish` dumps the three tables (plain SQL, gzip), uploads the file to a
   GitHub release named `eval-index`, and writes its sha256 to `eval/index.sha256`.
2. You commit `eval/index.sha256`.
3. CI downloads the dump and refuses it unless the checksum matches the committed one.

That's the same idea as pinning an image by digest: the bytes the test uses are reviewed.

### 4. Gates, baselines and noise

- **Gate** (`eval/gate.toml`): absolute minimums. In a retrieval-only run, answer metrics
  aren't measured, so they're skipped rather than failed (tested).
- **Baseline** (`eval/baseline.json`): relative comparison, 0.05 tolerance on quality.
- **Latency** isn't gated on shared CPU runners: they vary too much. It is in the report.
- Generation on CPU differs slightly from the laptop's GPU, so the nightly run may show small
  answer-metric drift against a laptop baseline until runs move to Bedrock.

### 5. What this costs, and what it will cost

$0 now: public GitHub-hosted runners and local models. After the Bedrock switch, a full run is
37 questions × ~1,000 input and ~100 output tokens. With a small model like Nova Micro that's
well under a cent per run, and the nightly job becomes a few minutes. The OIDC role from 6c is
how CI would call Bedrock, with a separate role allowed only `bedrock:InvokeModel` on the
approved models.

---

## Part 2: What was built

| File | What |
|---|---|
| `packages/kb_core/src/kb_core/evaluation/runner.py` | `answer_fn=None` → retrieval-only: screen checked, answer metrics `None` |
| `packages/kb_core/src/kb_core/evaluation/report.py` | `check_gate(..., skip_unmeasured=True)`; a "Retrieval misses" report |
| `packages/kb_core/src/kb_core/cli.py` | `kb eval --retrieval-only` (refuses `--update-baseline` and `--judge`) |
| `scripts/eval-index.sh` | `publish` (dump → release asset + checksum) and `restore` (download → verify → load) |
| `scripts/ollama-pull.sh`, `scripts/eval-summary.sh` | Pull models over Ollama's API; put the report on the run page |
| `.github/workflows/eval.yml` | Tier 1 and tier 2 jobs |
| `Makefile` | `eval-retrieval`, `eval-index-publish` |

Verified before delivery: unit tests for retrieval-only metrics and the gate's skip mode; the
restore script against a real Postgres with pgvector (checksum mismatch refused; tables,
vectors, generated tsvector column and HNSW index loaded; safe to run twice); checkov on the
workflows (0 failed); mypy as the pre-commit hook runs it.

---

## Part 3: Hands-on

```bash
git checkout main && git pull && git checkout -b phase-7c-eval-in-ci
unzip -o ~/Downloads/kb-assistant-phase7c.zip -d .
uv run mypy && make test
```

### Step 1: try the retrieval-only run locally

```bash
make up              # Postgres
make eval-retrieval
```

Answerable cases show `ok` or `FAIL` (evidence in the top k or not); the others show `-`,
because there's nothing to judge without an answer. The report has no answer metrics, and the
gate passes on what was measured. It finishes in seconds.

### Step 2: publish the index CI will use

```bash
gh auth status                 # needs to be able to create releases in the repo
make eval-index-publish
cat eval/index.sha256
gh release view eval-index     # a pre-release with kb-index.sql.gz
```

The release is marked "pre-release" and titled "Evaluation index (not a release)". If the
repository is public, so is this file: it holds chunks of the public AWS documents and their
embeddings, nothing private.

### Step 3: open the PR and watch tier 1

```bash
git add -A && git status        # includes eval/index.sha256 and the new scripts
git commit -m "Phase 7c: evaluation in CI (retrieval on PRs, full nightly)"
git push -u origin phase-7c-eval-in-ci && gh pr create --fill
gh pr checks --watch
```

The `eval / retrieval` job should load the index (`… chunks loaded`), pull `nomic-embed-text`,
and pass. The report appears on the run's summary page.

### Step 4: run tier 2 once

Add the label `eval:full` to the PR (create it if it doesn't exist:
`gh label create eval:full --description "Run the full evaluation with the model"`), or after
merging: Actions → eval → Run workflow. Expect 20–30 minutes. Compare its numbers with your
laptop baseline.

### Step 5: make it required (optional)

Settings → Branches → `main` → require `eval / retrieval`. The workflow only runs when relevant
paths change, so if you make it required, also run it on every PR (remove `paths:`) or GitHub
will wait for a check that never starts.

---

## Part 4: Interview framing

**"How do you stop quality regressions in an LLM app?"**
The evaluation is a CI gate in two tiers. On every pull request that touches retrieval,
prompts or the dataset, a deterministic retrieval run against a real index and the real
embedding model checks hit rate, ranking, the similarity floor and the injection screen in
about three minutes. Nightly, or on a label, the full evaluation runs with the model. Same
gate file and baseline as locally.

**"Why not run the full evaluation on every PR?"**
Time and noise. On CPU runners it's 20+ minutes per run, and generation varies between runs.
Most of my historical regressions were retrieval, which is cheap and deterministic to test.
Generation is checked daily or on request; after the Bedrock switch it gets fast and cheap
enough to run more often.

**"How do you make evaluation reproducible in CI?"**
Treat the index as a fixture: a dump published as a release asset, its checksum committed, and
CI refuses anything that doesn't match. Pin the database and model server images. Don't gate
latency on shared runners.

**"What does it cost?"**
Nothing now. After the Bedrock switch, under a cent per full run with a small model; the
bigger cost is runner minutes, which is why the slow tier doesn't run on every push.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `release not found` in "Load the evaluation index" | Index never published | `make eval-index-publish`, commit `eval/index.sha256` |
| `doesn't match eval/index.sha256: refusing to use it` | The release asset was replaced, or the checksum wasn't committed | Re-run `make eval-index-publish` and commit the new checksum |
| Retrieval metrics far below the laptop | CI loaded a different index than the baseline used | Publish the index from the same database the baseline ran on |
| `Pull of nomic-embed-text failed` | Registry hiccup | Re-run the job |
| Full job times out | CPU generation is slow | Keep it nightly; raise `timeout-minutes`, or wait for Bedrock |
| The eval job never starts on a PR | No file under its `paths:` changed | Expected; or "Run workflow" by hand |
