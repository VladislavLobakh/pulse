# 8. Intent contract for ReAct query generation and eval-driven model selection

Date: 2026-07-05

## Status

Accepted

## Context

The HN ReAct loop rewrote user queries into PULSE's default AI/LLM domain: a
run for `Kubernetes ingress nginx tuning site:news.ycombinator.com` generated
`LLM deployment Kubernetes site:news.ycombinator.com` on retry. Two causes:
the reason/observe prompts hardcoded "find AI/LLM articles" as the goal, and
the loop state carried only the current (already rewritten) query, so neither
step ever saw the user's original request again. Model choice for these steps
was also untested — there was no way to tell whether a cheaper model preserved
intent as well as a pricier one.

## Decision

- The ReAct state carries `original_query` (the user's query verbatim, never
  rewritten) alongside the working `query`. The reason context always leads
  with it; the observe scoring input pairs it with the generated query.
- Prompts encode a topic-agnostic intent contract: generated queries preserve
  named technologies, operators like `site:`/`-term`, quoted phrases, and
  time constraints; synonyms and same-topic broadening only. The agent has no
  default topic and no default query: the `HN_QUERY` constant from ADR 0006's
  public API is removed, the CLI requires a query argument, and a broad
  request is sharpened from the user's own words, never redirected to a
  product domain. `ReasonDecision` gained a `must_keep_terms` field to force
  the model to state the contract.
- Observe scores relevance against `original_query`, penalizing topic drift
  even when results are high-quality AI content.
- Source membership is enforced at the search-API level, not in query text:
  the HN agent passes its domain (`HN_DOMAINS`) to the Tavily collector's
  `include_domains` parameter, so neither users nor generated queries need a
  `site:` operator to stay on Hacker News (user-typed operators are still
  preserved by the contract). The collector stays a generic search client —
  which source lives on which domain is the source agent's knowledge.
- Model chains are selected by deterministic regression evals
  (`pulse.evals.intent_preservation`: 10 reason cases + 2 observe drift cases,
  keyword/regex checks, no LLM judge) — the cheapest passing model wins, the
  fallback must pass on a different provider. Current chain for both steps:
  `qwen/qwen3.5-flash-02-23` (12/12, $0.065/$0.26 per M) with
  `google/gemini-2.5-flash-lite` (12/12, $0.10/$0.40 per M) as fallback.
- Sampling params are the agent's decision, not the gateway's: `agents.hn`
  binds `temperature=0.1` / `max_tokens=500` into its step partials (short
  structured JSON — determinism and cost bounds matter more than variety);
  the gateway requires them per call and hardcodes no sampling policy.

## Consequences

- User intent survives retries; poor results broaden within the topic instead
  of resetting to the product's default domain.
- Model swaps are now a measurable decision: rerun `pulse.evals.intent_preservation` against a
  candidate and compare pass counts, instead of judging by vibes.
- Evals that assert real model behavior require network and an OpenRouter
  key; the offline pytest suite only pins prompt/state wiring.
- `max_tokens=500` would truncate models that emit visible reasoning tokens
  before the JSON (deepseek-v4-flash failed one case this way) — such models
  need either a higher cap or exclusion from the chain.

### Intentionally deferred

Reviewed against 2026 agentic-search practice and deferred deliberately, in
priority order:

1. **Novelty scoring has no memory.** `SourceBatchScore.novelty` asks the
   model to judge freshness "beyond content already seen", but the scorer is
   shown neither previous iterations nor previous runs. Fix when it matters:
   pass previously seen URLs into the scoring input, or drop the field.
2. **No per-item verification.** The batch is scored and returned as a whole;
   a mixed batch (half great, half junk) earns a middling score and the junk
   ships. Candidate fix: a cheap per-item relevance filter before returning.
3. **Single query per iteration.** No decomposition into sub-questions or
   parallel query fan-out. Revisit when PULSE goes multi-source (ArXiv +
   HN + newsletters) — not needed for single-source collection.
4. **Prompt-based policy, not RL-trained.** 2026 frontier trains search
   policies (when to search / what to read / when to stop) with RL; out of
   scope by explicit project decision (no fine-tuning), and the wrong cost
   profile at this scale.

## Alternatives Considered

- Keep intent rules in prompts only, no `original_query` in state: the model
  cannot preserve what it never sees; after one rewrite the original request
  is gone from context.
- A `mode` field (explicit_query vs broad_discovery) letting broad requests
  target PULSE's AI domain from inside the agent: rejected — it bakes product
  topics into a reusable agent; the default topic belongs in the default
  query, and mode classification is a drift vector of its own.
- Full structured intent contract (source_constraints, exact_phrases,
  time_constraints, ... as separate schema fields): more tokens and schema
  surface for small models to get wrong; `must_keep_terms` plus prompt rules
  passed all evals without it.
- gpt-4.1-nano as fallback: 11/12 (drops quote marks from exact phrases);
  gemini-2.5-flash-lite passed 12/12 at comparable cost.
- LLM-as-judge evals: non-deterministic and needs a second model; keyword and
  regex checks are reproducible and free.

## Related

- Architecture: [docs/architecture.md](../architecture.md)
- Model: [workspace.dsl](workspace.dsl)
- Builds on: [0007 per-source per-step model chains](0007-per-source-per-step-openrouter-model-chains.md)
