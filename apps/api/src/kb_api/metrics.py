"""Prometheus metrics (Phase 7a).

Two layers:

- HTTP (RED: rate, errors, duration) for every endpoint, labelled by the route
  *template* ("/ask/stream"), never the raw path, so label values stay bounded.
- Answers: what a user and a budget owner care about. Time to first token, total
  time, outcome (answered, refused, below the similarity floor, error), tokens and
  cost by model, retrieval time and the best similarity score.

Traces (Langfuse) answer "why was this one answer bad?"; metrics answer "how are all
answers doing, and is it getting worse?". Neither replaces the other.

/metrics is served on the API port only. nginx forwards /api/ and nothing else, and in
AWS the load balancer reaches the web container only, so it isn't public.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from kb_core.models import Answer

# One registry for the app (not the global default), so tests can read it directly
# and nothing from imported libraries leaks in by accident.
REGISTRY = CollectorRegistry(auto_describe=True)

# Seconds. Local models are slow (several seconds to first token), hosted ones fast;
# the buckets cover both so the same dashboard works on Ollama and Bedrock.
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 60)
SIMILARITY_BUCKETS = (0.3, 0.4, 0.5, 0.55, 0.6, 0.62, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9)

HTTP_REQUESTS = Counter(
    "kb_http_requests",
    "HTTP requests by route template, method and status code.",
    ["method", "route", "status"],
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "kb_http_request_duration_seconds",
    "Time until the response starts. For /ask/stream that is the headers, not the whole "
    "answer: see kb_answer_duration_seconds.",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)

ANSWERS = Counter(
    "kb_answers",
    "Answers by endpoint, mode (pipeline or agent) and outcome.",
    ["endpoint", "mode", "outcome"],
    registry=REGISTRY,
)
TIME_TO_FIRST_TOKEN = Histogram(
    "kb_answer_time_to_first_token_seconds",
    "From question to the first generated token: what a user feels.",
    ["endpoint"],
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
ANSWER_DURATION = Histogram(
    "kb_answer_duration_seconds",
    "From question to the complete answer.",
    ["endpoint"],
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
RETRIEVAL_DURATION = Histogram(
    "kb_retrieval_duration_seconds",
    "Embedding the question plus the hybrid search.",
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
TOP_SIMILARITY = Histogram(
    "kb_retrieval_top_similarity",
    "Best cosine similarity among retrieved chunks. A falling median means questions "
    "are drifting away from the knowledge base.",
    buckets=SIMILARITY_BUCKETS,
    registry=REGISTRY,
)
SEARCHES = Histogram(
    "kb_answer_searches",
    "Searches per answer (1 for the pipeline; up to the agent's limit).",
    buckets=(1, 2, 3, 4, 5),
    registry=REGISTRY,
)
TOKENS = Counter(
    "kb_llm_tokens",
    "Model tokens by model and direction (input or output).",
    ["model", "direction"],
    registry=REGISTRY,
)
ESCALATIONS = Counter(
    "kb_escalations",
    "Questions routed to the larger model after the first refused with strong evidence "
    "(Phase 8b), by whether the larger model then answered.",
    ["from_model", "to_model", "result"],
    registry=REGISTRY,
)
DEGRADED = Counter(
    "kb_answers_degraded",
    "Answers under the daily spend cap: economy (routing off, at the soft limit) or "
    "over_budget (no model call).",
    ["level"],
    registry=REGISTRY,
)
CACHE = Counter(
    "kb_cache_requests",
    "Answer-cache lookups by result: exact, semantic or miss (blocked questions never reach it).",
    ["result"],
    registry=REGISTRY,
)
CACHE_SAVED = Counter(
    "kb_cache_saved_usd",
    "Model cost the cache avoided, in US dollars (what the cached answer cost to generate).",
    registry=REGISTRY,
)
CACHE_TOKENS_SAVED = Counter(
    "kb_cache_tokens_saved",
    "Model tokens the cache avoided.",
    registry=REGISTRY,
)
COST = Counter(
    "kb_llm_cost_usd",
    "Model cost in US dollars, by model (0 for local models).",
    ["model"],
    registry=REGISTRY,
)
GROUNDING = Histogram(
    "kb_answer_grounding_score",
    "Share of an answer's claims backed by the sources they cite (Phase 7b check).",
    buckets=(0.0, 0.25, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0),
    registry=REGISTRY,
)
UNKNOWN_TERMS = Counter(
    "kb_answer_unknown_terms",
    "Answers naming a product or term that appears in no retrieved source.",
    registry=REGISTRY,
)
BLOCKED = Counter(
    "kb_guardrail_blocked",
    "Questions blocked by the input screen before retrieval, by rule.",
    ["reason"],
    registry=REGISTRY,
)
BUILD_INFO = Gauge(
    "kb_build_info",
    "Always 1; the labels say what is running.",
    ["version", "env", "provider", "mode"],
    registry=REGISTRY,
)

OUTCOMES = ("answered", "refused", "below_floor", "blocked", "error")


def outcome_of(answer: Answer) -> str:
    """answered, refused (the model said "not found"), below_floor (no model call),
    blocked (the input screen stopped it before retrieval) or over_budget (the daily spend
    cap, Phase 8b). The other two outcomes, error and cancelled, have no answer: see
    record_error and record_cancelled."""
    if answer.blocked_by == "budget":
        return "over_budget"
    if answer.blocked_by:
        return "blocked"
    if answer.answered_from_context:
        return "answered"
    # Nothing cleared the similarity floor: "not found" without calling the model ($0).
    if not answer.retrieved:
        return "below_floor"
    return "refused"


def record_answer(answer: Answer, endpoint: str, mode: str, cache_on: bool = True) -> None:
    ANSWERS.labels(endpoint=endpoint, mode=mode, outcome=outcome_of(answer)).inc()
    if answer.degraded:
        DEGRADED.labels(level=answer.degraded).inc()
    if answer.blocked_by:
        if answer.blocked_by != "budget":
            BLOCKED.labels(reason=answer.blocked_by).inc()
        return  # nothing was retrieved or generated
    if answer.grounding is not None:
        if answer.grounding.score is not None:
            GROUNDING.observe(answer.grounding.score)
        if answer.grounding.unknown_terms:
            UNKNOWN_TERMS.inc()
    ANSWER_DURATION.labels(endpoint=endpoint).observe(answer.total_ms / 1000)
    if answer.time_to_first_token_ms is not None:
        TIME_TO_FIRST_TOKEN.labels(endpoint=endpoint).observe(answer.time_to_first_token_ms / 1000)
    RETRIEVAL_DURATION.observe(answer.retrieval_ms / 1000)
    if answer.retrieved:
        TOP_SIMILARITY.observe(max(r.similarity for r in answer.retrieved))
    SEARCHES.observe(answer.searches)
    if cache_on:  # with the cache off there was no lookup, so no miss to count
        CACHE.labels(result=answer.cache or "miss").inc()
    if answer.cache:
        # Latency above includes hits (users feel them); tokens and cost don't, because
        # they were counted when the answer was first generated.
        CACHE_SAVED.inc(float(answer.cost_saved_usd))
        CACHE_TOKENS_SAVED.inc(answer.tokens_saved)
        return
    if answer.model:
        TOKENS.labels(model=answer.model, direction="input").inc(answer.input_tokens)
        TOKENS.labels(model=answer.model, direction="output").inc(answer.output_tokens)
        COST.labels(model=answer.model).inc(float(answer.cost_usd))
    esc = answer.escalation
    if esc is not None:
        # The first model's call was paid for too: count it under its own model.
        TOKENS.labels(model=esc.model, direction="input").inc(esc.input_tokens)
        TOKENS.labels(model=esc.model, direction="output").inc(esc.output_tokens)
        COST.labels(model=esc.model).inc(float(esc.cost_usd))
        result = "answered" if answer.answered_from_context else "refused"
        ESCALATIONS.labels(from_model=esc.model, to_model=answer.model, result=result).inc()


def record_cancelled(endpoint: str, mode: str) -> None:
    """The browser left mid-stream (Stop button, closed tab). Not a fault: the SLO
    excludes it, so a user changing their mind doesn't spend the error budget."""
    ANSWERS.labels(endpoint=endpoint, mode=mode, outcome="cancelled").inc()


def record_error(endpoint: str, mode: str) -> None:
    ANSWERS.labels(endpoint=endpoint, mode=mode, outcome="error").inc()


def route_template(request: Request) -> str:
    """The matched route's path template, or "unmatched" (bounded label values)."""
    for route in request.app.router.routes:
        match, _ = route.matches(request.scope)
        if match is Match.FULL:
            return str(getattr(route, "path", "unmatched"))
    return "unmatched"


async def http_metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path == "/metrics":  # don't measure the scraper
        return await call_next(request)
    route = route_template(request)
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        HTTP_DURATION.labels(method=request.method, route=route).observe(
            time.perf_counter() - start
        )
        HTTP_REQUESTS.labels(method=request.method, route=route, status=str(status)).inc()
