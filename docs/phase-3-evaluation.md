# Phase 3: Evaluation, turning "looks right" into numbers

**Time:** half a day plus experiments. **AWS cost:** $0 (runs on Ollama).

**You finish with:**

- A 34-question evaluation set in the repo: answerable, out-of-scope and prompt-injection cases.
- `kb eval`: retrieval hit rate and MRR, citation validity, fact recall, refusals, injection
  resistance, cost and latency, in one report.
- The similarity floor set from measured data instead of a few manual searches.
- A committed baseline and a gate: `kb eval` fails when quality drops.
- An optional LLM judge for groundedness.

---

## Part 1: Concepts

### 1. Why a fixed test set

Reading answers works for five questions. It doesn't catch the change that fixes one
question and breaks five others. A fixed set, scored the same way every time, makes every
later phase (hybrid search, reranking, model switches, prompt changes) a before/after
comparison. Temperature 0.1 matters here: runs are repeatable, so a changed score means a
changed system.

### 2. Score retrieval and generation separately

A bad answer has one of two causes, and they need different fixes:

| Stage | Question | Metrics |
|---|---|---|
| **Retrieval** | Was the evidence among the chunks the model saw? | **Hit rate @k**: share of answerable questions with evidence in the top k. **MRR**: average of 1/rank of the first relevant chunk (1.0 = always first). |
| **Generation** | Did the model use it well? | Citation validity, cited share, fact recall, false refusals |
| **Guardrails** | Did it refuse what it should? | Correct refusals, injection resistance, floor rejection |

`kb eval` searches 10 ranks deep **without** the floor, so you see where evidence sits
even when it's just outside the top k. That tells you whether raising k or improving ranking
(Phase 4) would help.

### 3. Labels that survive re-chunking

Each answerable case lists **evidence phrases**: a retrieved chunk counts as relevant if it
contains any of them (after normalising case, ligatures and dashes). And **facts**: things a
good answer mentions, each with alternative phrasings. Chunk IDs would be more precise but
break every time chunking changes; phrases don't.

Labels can be wrong. **A failing case is either a system problem or a label problem.**
Reviewing failures and fixing labels is part of the work, not a sign the method failed.

### 4. Calibrating the similarity floor

For each question the report records the best similarity score. The floor works if every
answerable question scores above it and every off-topic one below. The report sweeps floors
from 0.30 to 0.90 and shows, for each, the share of answerable questions kept and off-topic
questions rejected, then recommends **the middle of the gap**. If the two groups overlap, there
is no clean floor; the overlap tells you which questions to look at.

### 5. LLM-as-judge, with caveats

Deterministic checks can't tell a faithful paraphrase from an invention. A second model can,
roughly. `--judge` asks a model to score groundedness 1–5 against the sources (strict rubric,
JSON output). Known weaknesses: judges favour fluent answers, vary between runs, and a 3B
judge is weak. So the judge score is **reported, never gated**, and it's worth using a stronger
judge than the answering model (`--judge-model qwen2.5:7b`).

### 6. Gate and baseline

- **Gate** (`eval/gate.toml`): absolute minimums, e.g. every off-topic and injection question
  must be refused. Start loose, tighten once you trust the dataset.
- **Baseline** (`eval/baseline.json`, committed): the reference run. A later run fails if a
  quality score drops more than 0.05, or cost/latency gets more than 25% worse.

`kb eval` exits with code 1 in either case, so the same command works as a CI step later.

---

## Part 2: What changed in the repo

| Path | What |
|---|---|
| `packages/kb_core/src/kb_core/evaluation/` | New: `dataset.py` (format and validation), `metrics.py` (all scoring), `runner.py` (per-case run and summary), `judge.py` (optional LLM judge), `report.py` (Markdown report, baseline comparison, gate). |
| `packages/kb_core/src/kb_core/cli.py` | `kb eval` with `--k`, `--min-similarity`, `--depth`, `--only`, `--judge`, `--judge-model`, `--baseline`, `--gate`, `--update-baseline`, `--no-save`. |
| `eval/dataset.jsonl` | 34 cases: 24 answerable (all six pillars, two paraphrases), 6 out-of-scope (one near-domain: Azure), 4 injection. |
| `eval/gate.toml` | Starting minimums. |
| `eval/results/` | Every run as JSON + Markdown (git-ignored). |
| `packages/kb_core/tests/test_evaluation.py` | 31 tests: dataset errors, every metric, runner with a crashing case, judge parsing, regression and gate rules, the CLI. |
| `Makefile` | `make eval`, `make eval-judge`, `make eval-baseline`. |
| `docs/adr/0010-evaluation.md` | The decisions. |

---

## Part 3: Step by step

### Step 1: Apply and test (5 min)

```bash
git checkout main && git pull && git checkout -b phase-3
unzip -o ~/Downloads/kb-assistant-phase3.zip -d .
uv sync
make lint test            # 134 passed, 8 skipped
```

### Step 2: First run (5–10 min)

```bash
make up                   # Postgres
make eval                 # Ollama must be running
```

Each case prints as it runs (`ok`/`FAIL`, best similarity, ID), then the report: metrics,
the gate result, the floor sweep, failing cases, and answers with unusable citations. The same
report is saved in `eval/results/`.

Don't expect all green. This first run measures the system *and* the labels.

### Step 3: Review the failures (20–30 min)

For each case under "Cases that did not pass":

- **Answerable, "evidence not in top k (rank N)"**: the evidence exists but ranks too low.
  A retrieval problem: note it for Phase 4 (hybrid search, reranking).
- **Answerable, "evidence not in top k (rank None)"**: either retrieval missed it completely,
  or the evidence phrase isn't in the document. Check with
  `uv run kb search "<question>"`. If the right section comes back but uses different words,
  **fix the label**: add the wording the document actually uses.
- **Answerable, "refused"**: the floor blocked it (best score below the floor) or the model
  said "not found" despite sources. The first is a floor question (Step 4); the second a
  generation problem.
- **Out-of-scope or injection, "answered instead of refusing" / "leaked"**: a guardrail
  problem. Look at the best score: if it cleared the floor, the floor is too low.

Edit `eval/dataset.jsonl` for label fixes only. Never change a label just to make the
system look better: change it only when the document really uses other words.

### Step 4: Set the floor from the data (5 min)

Look at `floor.gap`, `floor.recommended` and the floor table. If there's a clean gap, put
the recommended value in `.env`:

```bash
KB_MIN_SIMILARITY=0.65    # whatever the report recommends
```

Then run `make eval` again. If the groups overlap (no recommendation), look at which
answerable question scores lowest and which off-topic question scores highest: those two
define the problem.

### Step 5: Save the baseline (2 min)

When the report looks right and the labels are fixed:

```bash
make eval-baseline
git add eval/baseline.json eval/dataset.jsonl
```

From now on, `make eval` compares with it and shows a Baseline and Change column.

### Step 6: Experiments (optional, 30+ min)

Each is one command. Note the numbers in `docs/build-log.md`:

```bash
uv run kb eval --k 8 --no-save                   # does more context raise hit rate? at what token cost?
uv run kb eval --min-similarity 0.55 --no-save   # where does the floor start letting off-topic in?
ollama pull qwen2.5:7b
KB_OLLAMA_CHAT_MODEL=qwen2.5:7b uv run kb eval --no-save   # do citations improve? how much slower?
uv run kb eval --judge --judge-model qwen2.5:7b --only design-for-failure --only rel-principles
```

The model comparison is the interesting one: citation validity and cited share for llama3.2
vs qwen2.5, against latency. It's the first real model-selection decision in the project.

### Step 7: Commit

```bash
git add -A
git commit -m "Phase 3: evaluation set, kb eval, floor calibration, baseline and gate"
git push -u origin phase-3 && gh pr create --fill && gh pr checks --watch && gh pr merge --squash
```

CI runs the new unit tests and validates the dataset; the evaluation itself runs locally
until Phase 7.

### What the first run found (23 Nov 2026)

llama3.2, k=4, floor 0.62, 34 cases. Pass rate 85%, hit rate @4 79%, MRR 0.72, citation
validity 88%, correct refusals 100%, injection resisted 100%, time to first token 1.7 s
median (warm).

1. **The cosine floor can't separate the groups.** Injection questions ("…reveal all hidden
   instructions", 0.727) and a near-domain question about another cloud (0.676) score *above*
   the weakest answerable question (0.714): a gap of −0.013. The floor still blocks the
   obviously unrelated ones (weather, pizza, capitals) for $0; the model refused the rest
   itself. Two layers, and the second one is a model following a prompt, so **every model
   switch must re-run this evaluation**. Similarity measures topic, not answerability.
   The gate now checks the outcome (refusals, injection resistance at 100%) and keeps the
   floor's share only as a regression guard. Phase 4's reranker gives a better relevance score.
2. **All retrieval misses are "What are the design principles of the X pillar?"** SQL showed
   the principle text exists (one chunk each) but ranks below overview chunks that describe
   the pillar in general terms (e.g. "Pillars of the Framework", p.15). Two causes: list-like
   chunks embed weakly against a question, and the chunk's section label is the pillar name,
   so the "Design principles" heading isn't part of what gets embedded. Phase 4 targets:
   keyword (hybrid) search, a reranker, and adding the section path to each chunk's text.
3. **One label was stale:** this edition doesn't contain "democratize advanced
   technologies". Fixed to wording the document actually uses.
4. **Citations:** all invalid markers were `[REL11-BP0x]` in the design-for-failure answers.

---

## Part 4: Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Core metrics | Deterministic | RAGAS / DeepEval (LLM-judged) | Fast, free, explainable; add judged metrics beside them later |
| Labels | Evidence phrases | Chunk IDs | Survive re-chunking (Phase 4 changes chunking) |
| Retrieval scoring | 10 deep, no floor | Only what the model saw | Shows how close misses were; separates ranking from the floor |
| Judge | Optional, not gated | Gated judge score | Small judges are noisy and biased towards fluency |
| Gate | Minimums + baseline with tolerance | Exact match with baseline | Small sets move by one case at a time; tolerance avoids false alarms |
| Where it runs | Locally (Ollama) | CI now | CI has no model; Phase 7 gates in CI against Bedrock |
| Size | 34 cases | Hundreds | Enough to catch regressions; grow it with every real bug |

---

## Part 5: Interview hooks

1. *"How do you evaluate a RAG system?"* Separate retrieval from generation. Retrieval: hit
   rate @k and MRR against labelled evidence. Generation: citation validity, faithfulness
   (judge), fact recall, refusal behaviour. Guardrails: out-of-scope and injection cases.
   Plus cost and latency per run. Run it on every change and compare with a baseline.
2. *"How did you pick your similarity threshold?"* Measured the best score per question
   for answerable and off-topic sets and put the floor in the middle of the gap; the report
   sweeps candidate floors and shows what each keeps and rejects.
3. *"Do you trust LLM-as-judge?"* As a signal, not a gate: judges favour fluent answers and
   vary between runs. Use a stronger judge than the model being graded, a fixed rubric, JSON
   output, and spot-check its verdicts.
4. *"How do you stop quality regressions?"* A versioned evaluation set, a committed baseline,
   tolerances, and a command that exits non-zero, so it can block a merge in CI.
5. *"Your labels could be wrong."* Yes: the first runs review the labels too. Labels are
   phrases from the source, changed only when the source really uses other words.

**Resume line:** "Built a RAG evaluation harness (34-case golden set, retrieval hit@k/MRR,
citation validity, refusal and injection checks, optional LLM judge) with a committed
baseline and regression gate, and calibrated the retrieval similarity floor from data."

---

## Part 6: Done checklist

- [ ] `make lint test` passes
- [ ] First `make eval` run; every failing case classified as system or label
- [ ] Labels fixed where the document uses other words
- [ ] Floor set from the report; re-run
- [ ] `eval/baseline.json` committed
- [ ] At least one experiment (k=8, or qwen2.5:7b) noted in the build log
- [ ] Merged through a PR with CI green

**Next:** Phase 4, hybrid search and reranking, measured with this harness: keyword search
next to vectors, a reranker, and the "Resources" cleanup from investigation 0001.
