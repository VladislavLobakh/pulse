# 3. Use Tavily for initial Hacker News collection

Date: 2026-06-28

## Status

Accepted

## Context

PULSE needs an initial working source agent that can collect AI-related Hacker News articles before
the full digest, memory, and orchestration stack exists. Direct Hacker News API integration would
provide raw item data, but ranking, search relevance, and broad web lookup would need additional
implementation.

The first milestone prioritized a small working collector and stable article model over complete
source fidelity.

## Decision

Use Tavily as the initial Hacker News article discovery integration.

The HN agent queries Tavily with a Hacker News scoped AI query, maps Tavily results into shared
`Article` domain objects, and treats Tavily score as search relevance rather than Hacker News vote
count.

## Consequences

The project gets a working source quickly, with parsing covered by tests and a single external
integration represented in the C4 model.

The tradeoff is that source completeness depends on Tavily search results. If later requirements
need exact Hacker News ranking, comments, authors, or vote counts, a direct Hacker News collector
can be added and this ADR can be superseded.

## Alternatives Considered

- Direct Hacker News API: better source fidelity, but more implementation before proving the flow.
- RSS or static fixtures only: easier testing, but not a realistic live collection path.

## Related

- C4 model: [../workspace.dsl](../workspace.dsl)
- HN flow: [../flows/hn-collect.mmd](../flows/hn-collect.mmd)
