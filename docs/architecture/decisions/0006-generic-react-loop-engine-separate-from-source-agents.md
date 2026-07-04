# 6. Generic ReAct loop engine, separate from source agents

Date: 2026-07-04

## Status

Accepted

## Context

`hn_agent.py` originally bundled two concerns in one module: the ReAct graph mechanics
(retry/stop conditions, reasoning-context construction, trace events, `recursion_limit`) and
Hacker News' specific business logic (the Tavily-backed search call, the reasoning/scoring
prompts, the score threshold and iteration cap). Adding a second source agent — ArXiv, YouTube,
or Newsletter, all named `Planned` in `workspace.dsl` — would have meant copy-pasting the entire
graph (`build_graph`, `_reason_node`, `_act_node`, `_observe_node`, `_should_continue`, the
`ReActState` shape) and only changing a handful of source-specific lines inside it. Every future
bug fix or behavior change to the loop itself (e.g. the reasoning-context feedback added in this
same line of work) would then need to be repeated across every source agent file.

## Decision

Split the ReAct implementation into two layers:

- `src/pulse/agents/react_loop.py` — the generic engine. Owns `ReActState`, `NodeName`,
  `build_graph()`, `run_react()`, iteration counting, and stop-on-threshold /
  stop-on-max-iterations mechanics. It has no knowledge of Hacker News, Tavily, OpenRouter,
  litellm, or any specific topic — it does not import `pulse.llm` or any collector. Every
  source-specific concern is a field on `ReActConfig`, not an import.
- `src/pulse/agents/hn_agent.py` — the source agent. Supplies a `ReActConfig` with the Tavily
  search binding, `complete_structured` as the LLM call, the reason/observe system prompts, how to
  build reasoning context and scoring payloads, an action label for the trace, and the score
  threshold / iteration cap / recursion limit. Everything else delegates to `react_loop.run_react()`.

`ReActConfig` is a plain dataclass (not an LLM output contract) carrying:

- `search_fn: (query, max_results) -> SourceItemList` — the collector binding.
- `reason_llm` / `observe_llm: Callable[..., BaseModel]` — two separate callables, both mirroring
  `pulse.llm.complete_structured`'s signature, so the engine calls *some* structured-output function
  per step without importing any concrete gateway. Splitting them (rather than one shared
  `structured_llm`) lets each step be backed by its own model chain — see
  [0007](0007-per-source-per-step-openrouter-model-chains.md). Swapping LiteLLM for a different
  provider, or using a test fake, never touches `react_loop.py`.
- `reason_system_prompt` / `observe_system_prompt: str` — what "good" means for this source.
- `build_reason_context: (ReActState, ReActConfig) -> str` — the wording and feedback shape for the
  reasoning step (attempt count, previous score, previous titles) is source-specific: HN, ArXiv, and
  YouTube will each want to surface different signals here. It takes `config`, not just `state`, so
  it always reads the *live* `score_threshold`/`max_iterations` off the same config the engine runs
  with — a source agent can no longer bake its own copy of those numbers into the builder and have
  it silently drift from a `ReActConfig` built with different values.
- `build_score_payload: (SourceItemList) -> object` — how the current batch is formatted for the
  scoring call (HN: title/url/summary/source; a future ArXiv agent might send authors/abstract).
- `action_name: str` — the trace label for the act step (e.g. `tavily_hn`, `arxiv_search`), so the
  trace reads meaningfully per source instead of a generic `search(...)`.
- `score_threshold`, `max_iterations`, `recursion_limit` — per-source tunables; different sources
  may need different iteration budgets or safety limits.

The generic engine's public result type moved to `models.py` as `ReActResult` (renamed from
`HNReActResult`), since it carries no HN-specific fields and is returned by any source agent's run.

The graph also gained an explicit `no_results` node: reaching it now sets `done=True` and
`stop_reason=StopReason.NO_RESULTS` and appends its own trace event, instead of `run_react()`
inferring `NO_RESULTS` after the fact from an unset `stop_reason`. The post-invoke fallback
(`stop_reason or StopReason.ERROR`) exists only to catch a genuinely unreachable state, not as the
primary way `NO_RESULTS` gets set.

`hn_agent.py`'s public API (`run_hn_react`, `fetch_hn_articles`, `HN_QUERY`, `MIN_ARTICLES`) is
unchanged, so `main.py` and existing callers needed no changes.

## Consequences

Adding a second source agent (ArXiv/YouTube/Newsletter) now means writing a thin file with its own
collector binding, prompts, context/payload builders, and thresholds — not touching or duplicating
the graph. Bug fixes and behavior changes to the loop (stop conditions, trace shape, no-results
handling) apply to every source agent automatically. `react_loop.py` has no dependency on any LLM
gateway or collector, so its tests need no monkeypatching — every source-specific behavior is
passed in as a plain function, including the LLM call itself. Tests split along the same seam:
`tests/test_react_loop.py` proves the engine is source-agnostic using a synthetic config with no
Tavily/HN references; `tests/test_hn_agent.py` only checks that `hn_agent` builds the right
business logic and wires it into the engine. The cost is a wider `ReActConfig` surface (ten
fields) and one more level of indirection (`config.search_fn`/`config.reason_llm`/
`config.observe_llm` instead of direct calls) for what is, today, still a single source agent.

## Alternatives Considered

- Keep `hn_agent.py` as the only ReAct implementation and copy it per source: fastest for a single
  agent, but guarantees drift the moment loop behavior needs to change in more than one place —
  already true after two rounds of reasoning-context fixes in this same file.
- A single `SourceAgent` base class with template-method hooks (`reason()`, `act()`, `observe()`)
  instead of a config object: workable, but couples every source agent to inheriting from a
  specific class shape; a plain `ReActConfig` dataclass keeps the engine's dependency on a source
  agent to "supply this data," not "subclass this graph."
- Let `react_loop.py` import `pulse.llm.complete_structured` directly (the first version of this
  split did exactly that): simpler for a single source agent, but ties the generic engine to one
  concrete LLM gateway and forces every engine test to monkeypatch that import. Injecting
  `reason_llm`/`observe_llm` via config keeps the engine gateway-agnostic and makes tests pure
  function calls.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Patterns: [../../patterns.md](../../patterns.md)
- Flow: [../flows/hn-collect.mmd](../flows/hn-collect.mmd)
- Prior decision: [0005-openrouter-gateway-and-react-loop-for-hn-collection.md](0005-openrouter-gateway-and-react-loop-for-hn-collection.md)
