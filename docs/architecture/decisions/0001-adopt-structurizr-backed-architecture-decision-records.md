# 1. Adopt Structurizr-backed architecture decision records

Date: 2026-06-28

## Status

Accepted

## Context

PULSE already uses Structurizr DSL for the C4 architecture model and Mermaid for behavioral
flows. The project needs a durable way to capture why architecture and tooling choices were made,
without creating a separate documentation island that can drift from the model.

Structurizr can import ADRs from Markdown into its decision log. Keeping ADRs under
`docs/architecture/decisions/` makes them part of the same documentation bundle as the C4 model.

## Decision

Use Structurizr-backed ADRs for architecture and major tooling decisions.

ADRs live in `docs/architecture/decisions/`, use the adr-tools compatible Markdown shape, and are
imported from `docs/architecture/workspace.dsl` with `!adrs decisions adrtools`. The template lives
outside the imported directory at `docs/architecture/decision-template.md` so Structurizr does not
treat it as a real decision.

## Consequences

Architecture decisions are visible from Structurizr's decision log and live beside the C4 model.
Accepted ADRs become project memory, so later changes should supersede or deprecate them instead
of silently rewriting history.

This does not add adr-tools, markdown linting, or CI validation yet. The process stays lightweight
until missing ADR coverage becomes a real review problem.

## Alternatives Considered

- Standalone `docs/adr/`: simpler to browse on GitHub, but disconnected from the Structurizr model.
- Add adr-tools now: useful for generation, but unnecessary until manual numbering becomes painful.
- Add CI validation now: stronger governance, but too much process for the first ADR pass.

## Related

- Architecture docs: [../../architecture.md](../../architecture.md)
- Structurizr model: [../workspace.dsl](../workspace.dsl)
