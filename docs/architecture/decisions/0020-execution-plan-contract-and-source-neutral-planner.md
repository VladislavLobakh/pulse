# 20. Execution-plan contract and source-neutral planner

Date: 2026-08-03

## Status

Accepted

## Context

`docs/patterns.md` reserved a Plan-and-Execute row and the `ExecutionPlan`
name for a planning stage before PULSE fans out to sources, but nothing
implements it: today every query is sent to all four runners unconditionally
(`main.build_runners` → `patterns.parallel.run_sources`). A reusable planner
needs a query-to-source assignment contract that a later dispatcher (task 3,
out of scope here) can execute deterministically, and that contract must
reject an unavailable source without the caller writing its own check —
`Source` is a fixed enum with a `TWITTER` member that has no runner, so
validating against the enum itself would accept a source nothing can run.

## Decision

- `ExecutionPlan` is one ordered list of `PlannedResearchTask` (`topic`,
  `query`, `source`), not parallel `topics`/`queries`/`priority_sources`
  arrays — a list can't drift into an inconsistent length across arrays, and
  list order is the deterministic reduction key a later dispatcher needs.
  One to five tasks, non-blank topic/query, and no duplicate
  `(query.casefold(), source)` pair are enforced by Pydantic validators, not
  caller discipline.
- Source membership in the run's registry is enforced by narrowing the
  `source` field to a `Literal` of the supplied sources on a run-scoped
  subclass built with `pydantic.create_model`, used **only** as the
  structured call's `response_model`. An unavailable source becomes a
  Pydantic `ValidationError`, already a member of `pulse.llm.FALLBACK_ERRORS`
  — Instructor reasks, then the gateway falls back to the next model, for
  free. The narrowed subclass is never returned: `plan_research` always
  converts the validated result back to the stable base `ExecutionPlan`
  before returning, so callers and any persisted graph state see one
  consistent type, never a per-run anonymous class.
- The caller's source collection is canonicalized once, into `Source`
  declaration order, before it touches either the prompt or the response
  model. Set iteration and caller-supplied ordering must not change what the
  model is asked or what schema constrains it.
- `patterns.planner.plan_research(query, sources, plan_llm)` takes the
  gateway call as an injected callable (`StructuredLLMFn`, the same alias
  shape as `patterns.react`/`patterns.topic_signal`), never importing
  `complete_structured` directly, and calls it at most once per invocation.
  Every exception propagates with its exact type — no error is caught,
  reformatted, or turned into a fallback plan; `ModelsExhaustedError` is the
  planner-stage failure a future caller classifies, per the same split ADR
  17 established for `topic_signal`.
- No `depth`, priority, scheduling, previous-run, preference, or trend field:
  none of them change execution in this task, and a field a dispatcher can't
  yet act on is misleading dead state.

## Consequences

- **The guarantee this contract makes is scoped, not absolute.** Only a plan
  *returned by `plan_research` for a given source collection* is guaranteed
  to name sources from that collection — `ExecutionPlan(...)` can still be
  hand-constructed with any `Source` member, including one with no runner. A
  plan is a value that can be stored, replayed, or edited between planning
  and dispatch, so its provenance is not a substitute for a check at the
  point of use: the future dispatcher (task 3) must still validate a plan
  against its actual runner registry before executing it, especially a plan
  it did not just receive from this function.
- The planner has no wired-in caller yet — nothing in `main.py` or
  `workflows/research.py` calls `plan_research`, and no model slug is
  hardcoded here. `docs/patterns.md` gets an implemented note now, matching
  its existing "wired in" convention only once a caller lands.
- Planning quality (does the model pick the right sources, the right number
  of tasks) is unverified against a live model — deterministic tests only
  prove the contract's plumbing, not prompt quality. A live eval
  (`pulse/evals/plan_quality.py`) exists for that but has not been run to
  completion, and it takes model slugs explicitly rather than defaulting to
  a production chain, since none exists yet.

## Alternatives Considered

- Parallel `topics`/`queries`/`priority_sources` arrays: rejected — nothing
  ties a query to the source it should run against, and the arrays can grow
  inconsistent lengths silently.
- Post-hoc `if task.source not in available: raise` after the structured
  call returns: rejected — it skips Instructor's reask and the gateway's
  model fallback entirely, leaving the model free to keep emitting an
  unavailable source on every retry instead of being constrained at
  generation time.
- Validate `source` against the full `Source` enum instead of the supplied
  registry: rejected — `Source.TWITTER` has no collector, agent, or runner,
  so this would accept a source nothing can execute.
- Return the run-scoped narrowed subclass to callers: rejected — its type
  identity changes per call (per available-source combination), which is
  unsound to serialize, checkpoint into LangGraph state, or compare against
  in later tests.
- Take `Sequence[SourceRunner]` (the literal runner objects) instead of
  `Collection[Source]`: rejected for this task — it would import
  `patterns.parallel` into the planner for no benefit here, since only
  source identity, not the runner callable, is needed to plan. The
  composition root derives the source set from the real runners
  (`{r.source for r in build_runners()}`) when it wires the planner in.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Pattern table: [../../patterns.md](../../patterns.md)
- Code: `src/pulse/patterns/planner.py`
- Eval: `src/pulse/evals/plan_quality.py`
- ADR 9: package-by-pattern module structure
- ADR 10: source-neutral parallel fan-out contract
- ADR 17: topic-signal single-item extraction contract (per-item error split
  this ADR reuses for the planner-stage failure)
