# 4. Use Structurizr and Mermaid for architecture documentation

Date: 2026-06-28

## Status

Accepted

## Context

PULSE needs architecture documentation that can show both the stable system shape and the behavior
of source/digest/content flows. A single diagram style would either over-model runtime sequences or
hide structural boundaries between owned containers and external systems.

The project also needs clear current-vs-target status because most containers are planned while
the HN collector path is implemented.

## Decision

Use Structurizr DSL for C4 L1/L2 structure and Mermaid for behavioral flows.

Structurizr owns the software system, containers, external systems, relationships, and
Implemented/Planned tags. Mermaid owns sequence and flow diagrams for collector, orchestrator,
digest, and content-pipeline behavior.

## Consequences

Structure and behavior have separate sources of truth, reducing overlap and drift. The C4 model can
filter current and target container views, while Mermaid diagrams can stay focused on runtime
ordering.

Any code change that adds or changes a container, external integration, or top-level flow must
update the matching architecture docs in the same commit.

## Alternatives Considered

- Mermaid only: easy to edit, but weak for C4 model governance and current-vs-target filtering.
- Structurizr only: strong structural model, but too heavy for detailed runtime flows.
- Informal Markdown diagrams: quick to write, but hard to keep consistent as the system grows.

## Related

- Architecture docs: [../../architecture.md](../../architecture.md)
- Structurizr model: [../workspace.dsl](../workspace.dsl)
- Flows: [../flows/](../flows/)
