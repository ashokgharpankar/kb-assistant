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
