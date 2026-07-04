# 7. Per-source, per-step OpenRouter model chains

Date: 2026-07-04

## Status

Accepted

## Context

Before this change, every structured LLM call in PULSE went through one env var
(`OPENROUTER_MODELS`) and one `ReActConfig.structured_llm` callable. The reason step (deciding the
next search query) and the observe step (scoring a batch of results) always used the same model
fallback chain, and `llm.py` itself decided which chain to use by reading `OPENROUTER_MODELS`
directly. Reason and observe are different tasks with different quality/cost/latency tradeoffs —
reasoning about a query is cheap and latency-sensitive, scoring a batch may benefit from a stronger
model — so sharing one chain forced the same tradeoff on both. Adding a second source agent
(ArXiv, per `workspace.dsl`) would have meant sharing that same single chain across every source
and every step, or `llm.py` growing source-specific env var names, which would break the layering
established in [0006](0006-generic-react-loop-engine-separate-from-source-agents.md): `react_loop.py`
must not know about any concrete source or gateway detail.

## Decision

- `src/pulse/llm.py` no longer reads any model list from env or code itself. `complete_structured()`
  takes an explicit `models: list[str]` parameter — the caller decides which chain to use, `llm.py`
  only knows how to retry/fall back/fail-fast across whatever list it's given. `get_api_key()` is
  the only env read left in `llm.py`, because the API key — unlike a model slug — is a secret.
- `src/pulse/agents/react_loop.py` gained a second callable on `ReActConfig`: `reason_llm` and
  `observe_llm` (both `Callable[..., BaseModel]`), replacing the single `structured_llm` field. The
  engine calls `config.reason_llm(...)` in the reason node and `config.observe_llm(...)` in the
  observe node — it still does not import `pulse.llm` or read any env var.
- `src/pulse/agents/hn_agent.py` defines `REASON_MODELS`/`OBSERVE_MODELS` as plain Python list
  constants (not env vars) and binds each into a `functools.partial(complete_structured,
  models=...)` passed as `reason_llm`/`observe_llm`. Model slugs are not secrets — they are a
  business-logic choice like the reason/observe prompts or `SCORE_THRESHOLD` right next to them —
  so keeping them in code makes changes to which model backs a step reviewable in a PR diff and
  traceable in `git blame`, rather than living in an untracked `.env` file that can silently drift
  between environments with no record of what changed or why.
- The naming convention for a future source agent is `REASON_MODELS`/`OBSERVE_MODELS` constants in
  its own module (e.g. `arxiv_agent.py`), mirroring HN's. No shared/global model-list constant or
  env var exists; only `OPENROUTER_API_KEY` (the actual secret) comes from env.

## Consequences

Reason and observe can now use different models (e.g. a fast/cheap one for query refinement, a
stronger one for scoring) without either agent code or `react_loop.py` needing to change. A future
ArXiv or YouTube agent defines its own `REASON_MODELS`/`OBSERVE_MODELS` constants and passes its own
bound callables — no shared constant to collide with HN's chains, and no change to `llm.py` or
`react_loop.py`. Changing which model backs a step is now a normal code change (PR, review, git
history) rather than an untracked `.env` edit — the tradeoff is that changing models per deployment
(e.g. a cheaper model in a dev environment) requires a code change instead of an env override; if
that need arises later, a source agent can still read `os.environ.get(...)` inside its own module
without touching `llm.py` or `react_loop.py`. Tests reflect the same split — `tests/test_llm.py`
passes `models` explicitly, and `tests/test_react_loop.py` has a dedicated test proving `reason_llm`
and `observe_llm` are called independently for their respective steps.

## Alternatives Considered

- Keep one shared `OPENROUTER_MODELS` env var and one `structured_llm` callable, differentiating
  reason vs observe (or source vs source) only by request content: simplest, but forces every step
  and every source onto the same model chain — the exact problem this decision fixes.
- Per-source, per-step env vars (`OPENROUTER_MODELS_HN_REASON`/`_OBSERVE`, parsed via a shared
  `models_from_env(var_name)` helper in `llm.py`): this was the first version of this decision. It
  achieved the same separation but stored model slugs — which are not secrets — in the same
  mechanism as the API key, making changes to model choice untracked and invisible in code review.
  Moved to plain code constants instead, keeping env reserved for actual secrets.
- Let `llm.py` itself own a mapping of `(source, step) -> models` (e.g. a lookup table keyed by
  string identifiers): centralizes the convention, but requires `llm.py` to know about "sources" and
  "steps" as concepts, reintroducing exactly the kind of source-specific knowledge `react_loop.py`/
  `llm.py` are supposed to stay free of.
- Bind the model list inside `react_loop.py` by adding `reason_models`/`observe_models: list[str]`
  fields to `ReActConfig` and calling `pulse.llm.complete_structured` directly from the engine:
  would still require `react_loop.py` to import `pulse.llm`, violating the layering from
  [0006](0006-generic-react-loop-engine-separate-from-source-agents.md) that the engine must not
  know about any concrete LLM gateway.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Prior decision: [0006-generic-react-loop-engine-separate-from-source-agents.md](0006-generic-react-loop-engine-separate-from-source-agents.md)
- Flow: [../flows/hn-collect.mmd](../flows/hn-collect.mmd)
- Env vars: [`.env.example`](../../../.env.example)
