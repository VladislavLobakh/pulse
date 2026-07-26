# 17. Topic-signal single-item extraction contract

Date: 2026-07-24

## Status

Accepted

## Context

PULSE needs a reusable engine that extracts a structured signal from a single
collected `SourceItem` via the existing OpenRouter/Instructor gateway
(`pulse.llm.complete_structured`), to later feed digest/reflection workflows
that need per-item judgments. The engine analyzes each item strictly in
isolation — no other item and no history of prior runs is available to it —
and must run many items concurrently without overwhelming the provider or
blocking the event loop.

An initial contract draft included `novelty` and `trend` fields. Both require
comparing an item against other items or against prior history to answer
honestly; a single-item analyzer has no such context, so any answer would be
a guess dressed as a judgment. Separately, the gateway
(`pulse.llm.complete_structured`) originally raised one unclassified
`RuntimeError` for two operationally different situations — a missing API key
(shared/config) and an exhausted per-request model chain (per-item) — making
it impossible to reliably tell "abort the whole batch" apart from "isolate
this one item" from exception type alone.

## Decision

- Drop `novelty`/`trend`. The contract (`TopicSignal`) instead extracts
  `topic`, `event_type` (`RELEASE`/`RESEARCH`/`TUTORIAL`/`DISCUSSION`/
  `RECAP`/`OTHER`/`UNKNOWN`), `key_change`, `relevance`, `confidence`, and
  `evidence` — all judged from the item's own content only. `RECAP` is
  judged from the item's own wording (e.g. "as previously announced...")
  rather than by comparing against other items, since none are available;
  `UNKNOWN` covers content with too little evidence to categorize.
- Add two named exception classes to `pulse.llm`: `ProviderConfigurationError`
  (missing/invalid local config, e.g. no API key — added to
  `FAIL_FAST_ERRORS`) and `ModelsExhaustedError` (every configured model
  failed this one request — deliberately excluded from `FAIL_FAST_ERRORS`).
- In the analyzer's per-item worker (`_analyze_one`), isolate only
  `ModelsExhaustedError` as a per-item failure; every other exception
  (`FAIL_FAST_ERRORS`, an unclassified bug, cancellation) sets a shared
  `_AbortSignal` and propagates, aborting the whole batch. Items still
  queued behind the concurrency limit check that flag before making their
  own request, so a shared failure stops further billable calls instead of
  letting queued work run to completion after the caller already saw it.
- Bound concurrency with `asyncio.Semaphore`, run the blocking gateway call
  via `asyncio.to_thread`, and gather with `asyncio.gather` — the same shape
  as `patterns.parallel` (ADR 10).
- The engine takes the gateway call (`analyze_llm`) as an injected callable,
  never importing `complete_structured` directly — the same DI shape as
  `ReActConfig` (ADR 6), so a caller binds it via `functools.partial` exactly
  as `agents/hn.py` already does for `reason_llm`/`observe_llm`.

## Consequences

- The analyzer cannot express "this topic is new" or "trending" on its own;
  any such judgment must come from a layer with cross-item or historical
  context (a future workflow), not from this engine.
- Callers get a strict, auditable failure contract: exactly one exception
  class isolates per item, everything else aborts the batch — there is no
  silent "guess and continue" path for an unclassified error.
- `pulse.llm`'s exception surface grew by two classes; `complete_structured`'s
  retry/fallback control flow itself did not change, and existing tests
  (`pytest.raises(RuntimeError, match=...)`) keep passing since both new
  classes still subclass `RuntimeError`.
- The engine has no wired-in caller yet — no agent binds `analyze_llm`, no
  workflow calls `analyze_items`. `docs/patterns.md` gets a row only when
  that wiring lands, per the existing status-flip convention.
- Extraction quality (does `event_type` classify real content correctly, is
  `key_change`/`evidence` actually well grounded) is unverified against a
  live model — deterministic tests only prove the engine's plumbing, not the
  prompt's quality. A live eval (`pulse/evals/topic_signal_extraction.py`)
  exists for that but has not yet been run to completion.

## Alternatives Considered

- Keep `novelty`/`trend` and accept the model guessing without cross-item
  context: rejected — an unfounded guess dressed as a structured signal is
  worse than not offering the field at all.
- Isolate every `RuntimeError` per item (first implementation): rejected —
  it silently swallowed real bugs and shared account errors as if they were
  per-item content problems; caught only during code review.
- Classify shared-vs-per-item by matching on exception message text (e.g. an
  "OPENROUTER_API_KEY" substring): rejected — fragile, and couples the
  analyzer to another module's internal wording instead of its exception
  taxonomy.
- Hardcode `complete_structured` as a direct import (no DI): rejected —
  breaks unit-testing with deterministic, network-free fakes, and departs
  from the DI shape already established by `patterns.react`/`patterns.parallel`.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Pattern table: [../../patterns.md](../../patterns.md)
- Code: `src/pulse/patterns/topic_signal.py`, `src/pulse/llm.py`
- Eval: `src/pulse/evals/topic_signal_extraction.py`
- ADR 6: generic ReAct loop engine separate from source agents
- ADR 9: package-by-pattern module structure
- ADR 10: source-neutral parallel fan-out contract
