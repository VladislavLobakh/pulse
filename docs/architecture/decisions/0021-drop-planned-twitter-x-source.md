# 21. Drop planned Twitter/X source

Date: 2026-08-04

## Status

Accepted

## Context

`Source.TWITTER` and a corresponding `Twitter/X` external system existed as roadmap
placeholders since the project's initial scaffolding, with no collector, agent, or
runner ever built for it. The maintainer decided not to build a Twitter/X source
going forward, so the placeholder no longer represents planned work — carrying it
only tracks a roadmap item that will never land.

## Decision

Remove `Source.TWITTER` from `pulse.models.Source`, and remove the `twitter`
external system and its `agentRuntime -> twitter` relationship from
`workspace.dsl`. PULSE now has four sources: Hacker News, ArXiv, YouTube, and
Newsletter feeds.

## Consequences

- `Source` has 4 members, all backed by a real collector/agent/runner — there is
  no longer an enum member with no implementation behind it.
- Tests and fixtures that previously used `Source.TWITTER` as an example of "a
  real `Source` member excluded from a given run's registry" now use `Source.YOUTUBE`
  or `Source.ARXIV` for that role instead — any of the four current members serves
  equally well, since the planner's registry-based validation (ADR 20) narrows to
  whatever subset of `Source` a caller actually supplies, not to a fixed subset of
  the enum.
- Re-adding a Twitter/X source later means re-adding the enum member, a collector,
  an agent, and the external system/relationship in `workspace.dsl` from scratch —
  this ADR is not superseded by that; it would be a new decision.

## Alternatives Considered

- Leave `Source.TWITTER` as an inert placeholder: rejected — an unimplemented enum
  member with no owner and no plan to build it is dead roadmap noise, and it was
  the only `Source` member without a runner, which made it an outlier rather than
  a representative example in tests.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Model: [../workspace.dsl](../workspace.dsl)
- Code: `src/pulse/models.py`
- ADR 20: execution-plan contract and source-neutral planner (registry-based
  source validation, which is why dropping an enum member needs no contract change)
