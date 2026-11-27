# Phase 7a: Observability with Prometheus and Grafana

**Time:** 2 hours. **AWS cost:** $0 (everything runs locally).

**Goal:** know how the assistant is doing across all requests, not one trace at a time:
latency users feel, answer outcomes, cost, retrieval drift. Alert on symptoms tied to an
SLO, with the alert rules tested like code.

**You finish with:**

- `/metrics` on the API: HTTP (rate, errors, duration) and answer metrics (time to first token,
  outcome, tokens, cost, retrieval time, best similarity, searches; cancelled streams are outcome `cancelled` since 8a, incident 0016).
- Prometheus scraping the API container, with 10 recording rules and 6 alerts.
- `promtool` unit tests for the alerts, run in CI (`make obs-check`).
- A provisioned Grafana dashboard, "KB Assistant: overview", stored as JSON in the repo.
- ADR 0016.

---

## Part 1: Concepts

### 1. Metrics, traces, logs: different questions

| Signal | Answers | Here |
|---|---|---|
| **Metrics** | How are *all* requests doing? Is it getting worse? Should someone be woken up? | Prometheus (this phase) |
| **Traces** | Why was *this* request slow or wrong? | Langfuse (Phase 2a): chunks, prompt, answer, cost |
| **Logs** | What exactly happened, in order? | Container logs (`make app-logs`); CloudWatch in AWS |

Metrics are cheap because they're numbers aggregated at the source. A counter that has
seen a million answers is still one number. That's why they're what you alert on.

### 2. Which numbers: three frameworks, one for LLMs

| Framework | Measures | Use for |
|---|---|---|
| **RED** | Rate, Errors, Duration | Request-driven services (the API) |
| **USE** | Utilisation, Saturation, Errors | Resources (CPU, memory, DB connections) |
| **Golden signals** (Google SRE) | Latency, traffic, errors, saturation | Both; the usual dashboard top row |

An LLM app needs more, because "200 OK in 2 s" can still be a useless answer:

| LLM signal | Metric | Why |
|---|---|---|
| Time to first token | `kb_answer_time_to_first_token_seconds` | What users feel when streaming (Phase 2a) |
| Outcome | `kb_answers_total{outcome=answered\|refused\|below_floor\|error}` | A refusal is a 200; so is a stream that failed mid-way |
| Tokens and cost | `kb_llm_tokens_total`, `kb_llm_cost_usd_total` by model | Cost per answer is a product metric (FinOps, Phase 0) |
| Retrieval quality drift | `kb_retrieval_top_similarity` | Falling similarity = users asking what the KB doesn't cover |
| Agent behaviour | `kb_answer_searches` | Retries cost tokens (incident 0009) |

### 3. Metric types

| Type | Behaviour | Example | Query with |
|---|---|---|---|
| **Counter** | Only goes up (resets on restart) | answers, tokens, cost | `rate()`, `increase()` |
| **Gauge** | Up and down | build info, queue length | the value itself |
| **Histogram** | Counts observations into buckets | latency, similarity | `histogram_quantile()` |
| Summary | Percentiles computed in the app | — | Not used: can't be aggregated across instances |

Never graph a raw counter; graph its `rate()`. `rate()` also handles restarts (resets).

**Histogram percentiles are estimates.** Prometheus only knows how many observations fell in
each bucket and interpolates inside it. In the local test for this phase, every time to first
token was under 1.5 s, yet p95 came out as 1.89 s: the 1–2 s bucket was interpolated. Choose
bucket edges around the values you set alerts on.

### 4. Labels and cardinality

Every unique combination of label values is a separate time series. `route="/ask/stream"` is
fine; `path="/users/12345"` creates one series per user and can take Prometheus down.

Rules followed here:

- HTTP metrics use the **route template**; unknown paths become `route="unmatched"` (tested).
- No user ID, question text or session in any label. That's what traces are for.
- `model` is a label: there are a handful, and cost per model is the point.

### 5. SLI, SLO, error budget, burn rate

- **SLI** (indicator): share of answers that completed without an error.
- **SLO** (objective): 99% over 30 days. **Error budget**: the 1% you may fail.
- **Burn rate**: how fast the budget is going. 1× spends it in exactly 30 days; 14.4× spends
  it in about 2 days.

Alerting on "error ratio > 1% for 5 minutes" pages on every blip. The SRE-workbook pattern
uses two windows per alert: a long one (1 h) proves it's real, a short one (5 m) proves it's
still happening, so the alert also clears soon after a fix.

| Alert | Condition | Severity |
|---|---|---|
| `KbErrorBudgetFastBurn` | error ratio > 14.4% over 1 h **and** 5 m | page |
| `KbErrorBudgetSlowBurn` | error ratio > 6% over 6 h **and** 30 m | ticket |
| `KbApiDown` | scrape failing for 2 min | page |
| `KbSlowFirstToken` | p95 > 10 s for 15 min (local model; ~3 s on Bedrock) | ticket |
| `KbRefusalRatioHigh` | > 50% refusals over 30 min, **with at least 10 answers** | ticket |
| `KbModelCostHigh` | > $0.50/hour for 15 min | ticket |

Alert on **symptoms** users feel (errors, latency), not causes (CPU). The refusal alert
needs a minimum volume: 2 refusals out of 2 answers is 100% and means nothing (tested).

### 6. Why stream errors don't show up as 5xx

Once an SSE response starts, the status (200) is already sent, so a failure mid-stream
travels as an `error` event (Phase 2a). A dashboard built on HTTP status codes would show
100% success. The error SLI here counts **answer outcomes**, and a test proves a failed
stream is counted even though HTTP says 200.

---

## Part 2: What was built

| File | What |
|---|---|
| `apps/api/src/kb_api/metrics.py` | Metric definitions, `record_answer`, route-template HTTP middleware |
| `apps/api/src/kb_api/main.py` | `/metrics`, recording in `/ask` and `/ask/stream`, disconnects, build info |
| `apps/api/tests/test_metrics.py` | Outcomes, tokens and cost, stream errors behind a 200, bounded route labels |
| `infra/observability/prometheus/prometheus.yml` | Scrape config (`api:8000`) |
| `infra/observability/prometheus/rules/kb-assistant.yml` | 10 recording rules, 6 alerts |
| `infra/observability/prometheus/tests/kb-assistant.test.yml` | 6 promtool unit tests |
| `infra/observability/grafana/` | Data source and dashboard provisioning, dashboard JSON |
| `infra/local/docker-compose.observability.yml` | Prometheus v3.13.5 (LTS), Grafana 13.1.0, localhost-only ports |

Verified before delivery: unit tests pass; `promtool check` and `test rules` pass; a real
Prometheus scraped the API under synthetic traffic and every recording rule and dashboard
query returned data (error ratio 3.3%, refusals 31%, cost per answer $0.00004).

---

## Part 3: Hands-on

```bash
git checkout main && git pull && git checkout -b phase-7a-observability
unzip -o ~/Downloads/kb-assistant-phase7a.zip -d .
uv sync                       # adds prometheus-client; commit uv.lock
make test
make obs-check                # promtool + rule tests + dashboard JSON (Docker)
```

### Step 1: see the raw metrics

```bash
make app-up                   # rebuilds the API image with /metrics
curl -s localhost:8000/metrics | grep -E "^kb_" | head -20
```

`localhost:8000` is the API container's port, published on 127.0.0.1 only. Through the UI
port (`localhost:8080/metrics`) you get the React app, not metrics: nginx doesn't route it.

### Step 2: start Prometheus and Grafana

```bash
make obs-up
```

- http://localhost:9095/targets: `kb-api` should be **UP**.
- http://localhost:9095/alerts: six alerts, all **inactive**.
- http://localhost:3001: Grafana opens on "KB Assistant: overview" (admin login: `admin` /
  `admin` unless `GRAFANA_ADMIN_PASSWORD` is set).

### Step 3: make some traffic

Ask 10–15 questions in the UI at http://localhost:8080: a few real ones, two off-topic ("best
pizza in Rome?"), one injection ("ignore your rules…"), and press Stop once mid-answer. Then
watch the dashboard (30 s refresh):

- **Answers by outcome:** answered, refused, below_floor all appear.
- **Time to first token:** several seconds on llama3.2; compare with the retrieval panel.
- **Cost per answer:** $0 on Ollama. This panel matters after the Bedrock switch.
- **Streams stopped by the user:** your Stop press.

### Step 4: watch an alert fire

```bash
docker compose -f infra/local/docker-compose.yml -f infra/local/docker-compose.app.yml stop api
```

At http://localhost:9095/alerts, `KbApiDown` goes **pending**, then **firing** after 2 minutes.
The dashboard's "API up" turns red. Then `make app-up` and watch it resolve.

### Step 5: commit

```bash
git add -A && git status      # includes uv.lock; no .env or tfvars
git commit -m "Phase 7a: Prometheus metrics, alert rules with tests, Grafana dashboard"
git push -u origin phase-7a-observability && gh pr create --fill
```

CI's `iac-scan` job now also runs `make obs-check`.

`make obs-down` stops both; their data volumes are kept.

---

## What the first real run found

The dashboard paid for itself in the first half hour:

| Seen | Cause | Fix |
|---|---|---|
| Target DOWN: `server returned HTTP status 404` | The API container still ran a pre-7a image | `make app-up` rebuilt it. `KbApiDown` fired and resolved: the alert drill, by accident |
| `make app-up`: `Bind for 127.0.0.1:8080 failed` | The 6b kind cluster also maps the UI to 8080 | `make k8s-down` |
| Web container `Exited (1)`: `host not found in upstream "api"` | nginx resolved `api` once at start-up and exited when it couldn't; the UI and its health check went down with it | Incident 0015: resolve at request time (`resolver` + variable) |
| "Error ratio (1h)": No data, with zero errors | No error series exists yet, so the ratio is empty, not 0 | `or vector(0)` in the recording rules, plus a rule test |
| Refusals 100% at first, 33% later | The first questions asked were the off-topic and injection ones; refusing them is correct | None: read ratios together with volume (why the refusal alert needs 10+ answers) |
| Retrieval ~2 s, not tens of ms | Embedding the question through Ollama from the container; to investigate in 7b | Compare `make api` on the host vs the container |

## Part 4: Interview framing

**"How do you monitor an LLM application?"**
Three layers. Service signals (rate, errors, latency) like any API. LLM signals: time to first
token, answer outcomes including refusals, tokens and cost per answer by model, and retrieval
similarity to catch drift. Traces per request for debugging. I alert on an SLO with burn rates,
not on raw thresholds.

**"Your dashboards show 100% success but users complain. Why?"**
Streaming. The 200 is sent before the answer is generated, so mid-stream failures never become
5xx. I count answer outcomes as the SLI, and I have a test that proves a failed stream increments
the error counter while HTTP says 200. Refusals are another "successful" failure, so they're
tracked separately.

**"What's a burn-rate alert?"**
It alerts on how fast the error budget is being spent. With a 99% SLO, 14.4× burn means the
monthly budget is gone in about two days: page. 6× over six hours: ticket. Two windows each, so
it doesn't fire on a blip and clears soon after recovery.

**"How do you avoid cardinality problems?"**
Bounded label values only: route templates, not paths; model names, not users. Per-user and
per-question detail goes to traces and logs. I have a test that two unknown URLs share one
label value.

**"How do you know your alerts work?"**
They're code with unit tests: promtool feeds synthetic series and checks the alert fires (or
doesn't) at a given time. Mine test, for example, that two refusals out of two answers *don't*
page, because there's a minimum volume.

---

## Cost

$0 locally. In AWS later: Amazon Managed Service for Prometheus bills per sample ingested and
stored; at this app's volume, a few dollars a month. CloudWatch custom metrics are ~$0.30
per metric per month, and label combinations count as separate metrics, so the cardinality
rules above matter for the bill too.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Bind for 127.0.0.1:8080 failed` on `make app-up` | The kind cluster from 6b maps the UI to 8080 too | `make k8s-down` (recreate later with `make k8s-up`) |
| `make app-up` warns about orphan containers (grafana, prometheus) | `app-up` only knows the app's compose files | Ignore it. Never add `--remove-orphans`: it would delete them |
| `/metrics` returns 404 | The API container runs an image from before 7a | `make app-up` rebuilds it; `build --no-cache api` if the cache is stale |
| `Bind for 0.0.0.0:9090 failed: port is already allocated` | Something else holds 9090 (Langfuse's MinIO) | Prometheus now uses 9095; or `PROMETHEUS_PORT=9096 make obs-up` |
| Target `kb-api` DOWN, "no such host" | App containers not running, or started without the shared Compose project | `make app-up`, then `make obs-up` |
| Grafana panels "No data" | No traffic yet, or less than two scrapes since it started | Ask a few questions; `rate()` needs two samples |
| p95 looks higher than any real request | Histogram interpolation within a bucket | Expected; see Concepts 3 |
| Alert stays pending | It has a `for:` duration | Wait it out; check the expression in the Graph tab |
| Edited a rule, nothing changed | Prometheus reads rules at start-up | `make obs-reload` |
| Grafana dashboard edits lost | The dashboard is provisioned from the repo | Export JSON, save over `kb-assistant-overview.json`, commit |
