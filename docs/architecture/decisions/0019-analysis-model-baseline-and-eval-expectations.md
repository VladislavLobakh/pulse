# 19. Analysis model baseline and eval expectation policy

Date: 2026-08-03

## Status

Accepted

## Context

ADR 8 established eval-driven model selection: the cheapest passing model wins
and the fallback must pass on a different provider. Applying that to the
`topic_signal` analyzer exposed two problems.

First, the eval could not fail. Its sparse case — an item titled "update" with
the summary "minor fixes" — deliberately declared no assertions, "purely for
eyeballing", so it counted as `PASS` on every run regardless of what the model
returned. A case that cannot fail cannot detect drift, which is the entire
purpose of a regression eval.

Second, the analyzer had no production model chain at all, so the eval declared
its own. Importing that list back into production would have let a chain
validate itself, and the eval was additionally running at its own sampling
settings rather than the ones the app sends.

## Decision

- The production chain and sampling parameters live in the composition root
  (`pulse.main`): `ANALYSIS_MODELS`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`. The
  eval imports all three, so it cannot drift from what production sends.
- Candidate selection must pass model slugs explicitly on the command line.
  The imported chain is the script's default for regression runs only; using it
  to choose the chain would be circular.
- `Case.__post_init__` raises when a case declares no expectation at all
  (`max_relevance`, `min_relevance`, `max_confidence`, `expected_event_types`
  all unset). This makes the module unimportable with a defective case, so a
  network-free test catches it by import alone. The checks use `is None`
  rather than truthiness, since `0.0` is a legitimate bound.
- The sparse case asserts `event_type=UNKNOWN` and `confidence <= 0.50`; the
  deterministic golden fixture `sparse_low_confidence_item` was corrected from
  `TUTORIAL` to `UNKNOWN` to tell the same story.
- When models disagree with a defensible expectation, the prompt gets
  sharpened; the expectation does not get widened to match the model.
- Validated chain: **Qwen3.5 Flash primary, Gemini 2.5 Flash Lite fallback** —
  cheapest passing model first, fallback on a different provider, per ADR 8.

## Consequences

- On the first live run both candidates failed the corrected sparse case
  identically, classifying "update / minor fixes" as `release` with confidence
  0.60 (Qwen) and 1.00 (Gemini). That was prompt adherence, not a defensible
  disagreement, so `TopicSignal`'s `event_type` and `confidence` descriptions
  and the system prompt were sharpened to state that generic boilerplate with
  no named subject and no stated change is `UNKNOWN` with confidence below 0.5.
- After sharpening, both models scored **4/4**: Qwen3.5 Flash 4/4 and Gemini
  2.5 Flash Lite 4/4, each reporting the sparse item as `unknown` at
  confidence 0.30 — comfortable headroom under the 0.50 bound, which is
  therefore kept rather than tightened.
- The two-provider rule of ADR 8 is satisfied; no fallback decision is
  deferred.
- Eval runs are not perfectly repeatable: across three post-sharpening runs,
  one run reported 3/4 for each model, and both of those failures were
  `analysis failed: ModelsExhaustedError` — transient provider exhaustion, not
  a changed judgment. A single red case should be re-run before it is treated
  as drift.
- Sharpening the shared prompt to fix the sparse case changes extraction for
  every item, not just thin ones. The other three cases were re-checked and
  still pass on both models.

## Alternatives Considered

- Widen the sparse expectation to accept `RELEASE`/`OTHER` alongside `UNKNOWN`:
  rejected — it would encode the models' guess as the contract and leave PULSE
  unable to distinguish a real release from a content-free item.
- Validate the expectation guard in `main()` rather than `__post_init__`:
  rejected — it only fires when someone runs the eval with a provider key,
  whereas `__post_init__` makes a defective case fail an offline test.
- Keep the eval's own model list and sampling constants: rejected — it is the
  exact drift `evals/intent_preservation.py` was written to prevent.
- Ship Qwen alone and defer fallback selection: unnecessary — Gemini passed
  every expectation, so ADR 8's fallback requirement is met now rather than
  carried as debt.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Code: `src/pulse/main.py`, `src/pulse/patterns/topic_signal.py`
- Eval: `src/pulse/evals/topic_signal_extraction.py`
- Tests: `tests/test_topic_signal_extraction.py`, `tests/test_topic_signal_golden.py`
- ADR 8: intent contract and eval-driven model selection (extended here for the
  first cross-source LLM stage)
- ADR 17: topic-signal single-item extraction contract
- ADR 18: research workflow analyzes collected items
