# 5. OpenRouter gateway and ReAct loop for HN collection

Date: 2026-07-02

## Status

Accepted

## Context

The HN agent was a one-shot Tavily wrapper with no reasoning, scoring, or stopping logic — it
called `search_articles()` once with a fixed query and returned whatever came back. There was no
LLM integration anywhere in `src/`, even though `docs/patterns.md` already named the ReAct pattern
and `docs/architecture/flows/langgraph-orchestrator.mmd` already sketched a reason→act→observe
graph as the target, with OpenRouter as the documented LLM gateway.

Making HN collection a genuine ReAct capability requires: an LLM gateway, structured LLM output
contracts, a loop with an explicit stop condition, and a graph runtime to express reason → act →
observe → decide.

## Decision

- Use **OpenRouter** as the LLM gateway, called through **litellm** (`litellm.completion`) with
  **Instructor** (`instructor.from_litellm`) layered on top so every LLM output is a validated
  Pydantic model (`ReasonDecision`, `SourceBatchScore`).
- Build the loop as a **custom `langgraph.graph.StateGraph`** (`reason_node → act_node →
  observe_node → conditional_edge`), not a prebuilt agent — the deprecated
  `langgraph.prebuilt.create_react_agent` import stays banned by ruff's `TID251`.
- Keep **two independent stop mechanisms**: `MAX_ITERATIONS` is product logic owned by
  `observe_node` (the real stop counter alongside `SCORE_THRESHOLD`); `recursion_limit` is only a
  safety guard passed via the graph's runtime `config`, not a `compile()` kwarg.
- Retry policy lives in `src/pulse/llm.py`: **retry** transient errors (rate limits, timeouts, 5xx)
  per model with `tenacity` exponential backoff; **fall back** to the next configured model only
  when the current one is unusable (not found / provider unavailable); **fail fast** — no retry, no
  fallback — on missing API key, auth errors, invalid requests, and Pydantic validation errors. The
  model list itself is not decided here — see
  [0007](0007-per-source-per-step-openrouter-model-chains.md) for where each source agent's model
  chains actually live.
- `get_api_key()` validates lazily (inside `complete_structured()`), never at import time, so
  importing `pulse.llm` and running the test suite never requires a real `.env`.

## Consequences

HN collection now reasons about what to search, scores results, and stops once they clear a
quality threshold instead of looping blindly or running exactly once. The `SourceItem` domain type
stays a plain dataclass; only LLM-output contracts became Pydantic models, keeping the
dataclass/Pydantic boundary from `AGENTS.md` intact. The OpenRouter/litellm/Instructor stack adds
new runtime dependencies (`langgraph`, `litellm`, `instructor`, `tenacity`, `pydantic`) but keeps
the heavier `langchain` provider packages out of the dependency tree. Multi-source routing
(ArXiv/YouTube/Newsletter fan-out via `route_by_source`), the full orchestrator graph,
checkpointer persistence, and Qdrant remain out of scope and stay `Planned`.

## Alternatives Considered

- `langgraph.prebuilt.create_react_agent`: fastest to wire up, but opaque control over the
  stop condition and scoring step, and it is the banned import (`TID251`) `AGENTS.md` forbids.
- Plain `while` loop with no graph: avoids the `langgraph` dependency, but the project's documented
  target architecture (`langgraph-orchestrator.mmd`) is already a `StateGraph`, and a hand-rolled
  loop would need to be rewritten when multi-source routing lands.
- Calling OpenAI/Anthropic SDKs directly instead of OpenRouter: fewer moving parts, but loses the
  documented single-gateway model fallback (Claude/GPT/Gemini) that `workspace.dsl` already models.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Model: [../workspace.dsl](../workspace.dsl)
- Flow: [../flows/hn-collect.mmd](../flows/hn-collect.mmd)
- Patterns: [../../patterns.md](../../patterns.md)
