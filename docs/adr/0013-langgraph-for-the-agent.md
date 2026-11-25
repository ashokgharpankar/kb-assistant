# ADR 0013: LangGraph for the agent, not CrewAI

**Status:** Accepted, 2026-11-25 (Phase 5; the agent is built in 5b)

## Context

The pipeline answers in one pass: retrieve once, generate once. Phase 4's results show
where that falls short. The Security principles question retrieved the right passage and
the small model still refused; other questions need two searches (compare two pillars) or
a reworded query. Phase 5b adds an agent that can decide to search again, read around a
hit, or refuse, using the Phase 5a tools.

The two common Python choices are LangGraph and CrewAI.

## The comparison

| | LangGraph | CrewAI |
|---|---|---|
| Model | An explicit state graph: typed state, nodes, conditional edges, loops | Role-based agents ("researcher", "writer") with tasks, in a crew; Flows for event-driven steps |
| Control | You define every step and transition | The framework plans and delegates between agents |
| Best for | One agent with a clear, auditable loop; production workflows | Several cooperating roles; quick multi-agent prototypes |
| Determinism and testing | Each node is a plain function; the graph can be tested node by node | Behaviour depends more on prompts and delegation; harder to unit-test |
| State, retries, limits | Built in: checkpointing, recursion limits, human-in-the-loop interrupts | Available, less granular |
| Fit with this repo | Already on LangChain for providers; LangGraph uses the same messages and models | A second abstraction over the same models |
| MCP tools | Via `langchain-mcp-adapters` or our own small adapter | Supported through its tool integrations |

## Decision

**LangGraph**, for a single retrieval agent with an explicit loop:

```
question → plan query → search (MCP tool) → enough evidence?
              ↑                                  │ no, and attempts left: rewrite query
              └──────────────────────────────────┘
                                                 │ yes → answer with citations
                                                 │ no, attempts used up → "not found"
```

- At most 3 searches per question (a hard limit, plus LangGraph's recursion limit), so
  cost per question is bounded.
- Each node is a plain function with typed state, tested without a model.
- Measured with the Phase 3 evaluation against the one-pass pipeline: the agent must
  match or beat it on pass rate without breaking the refusal and injection checks, and
  its extra latency and tokens are reported.

## Why not CrewAI

Our problem is one agent with a loop we want to see and bound, not a team of roles.
CrewAI's strength, delegation between role-playing agents, adds model calls and makes
cost and behaviour harder to predict and test. If a later feature genuinely needs
several roles (for example a reviewer that checks answers against a policy), revisit:
LangGraph can also express multi-agent graphs, so that alone isn't a reason to switch.

## Consequences

- New dependencies in 5b: `langgraph` (and possibly `langchain-mcp-adapters`).
- The agent becomes a second answer path next to `RagPipeline`; the API chooses by
  setting, so the two can be compared on the same evaluation.
- A small local model may be poor at tool calling; the graph keeps the decisions
  (when to search, when to stop) in code where it can, and uses the model only for
  rewriting queries and writing the answer.

## Implementation notes (Phase 5b, 2026-11-25)

The built graph keeps every decision it can in code, so a 3B model can run it:

```
START → retrieve → nothing above the floor? → refuse → END   (no model call, as before)
           ↑          │ found something
           │          ↓
           │       generate → answered? → END
           │          │ "not found", searches left
           │          ↓
           └────── rewrite (model writes a new keyword query)
```

- The loop triggers on the measured failure: relevant text retrieved, answer "not found".
  It never runs for off-topic questions, so they stay free.
- On a retry, the chunk *after* each of the top two hits is added. "Design principles"
  sections can start with a heading-only chunk; the list is in the next one.
- Evidence accumulates across searches (deduplicated, at most 8 chunks).
- A rewrite that repeats an earlier query falls back to "best hit's heading + question".
- The agent calls the retriever in-process, not over MCP: same code as the MCP tools,
  without a subprocess and a JSON round trip inside one service.
- `KB_ANSWER_MODE=pipeline|agent` picks the answer path for the CLI, API and evaluation.
  The default stays `pipeline` until the evaluation says otherwise.

## Result (2026-11-25)

Measured with `make eval-agent`: the agent improved no answer, retried mostly questions that
should be refused (+60% input tokens, 2× time to first token), and its one apparent win was a
disguised refusal. **The pipeline stays the default; the agent stays behind
`KB_ANSWER_MODE=agent`.** LangGraph remains the right framework; the retry *signal* was wrong.
See incident 0009 for the follow-ups.
