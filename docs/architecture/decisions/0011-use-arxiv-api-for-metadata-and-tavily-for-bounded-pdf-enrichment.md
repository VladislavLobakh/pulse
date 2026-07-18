# 11. Use the ArXiv API for metadata and Tavily for bounded PDF enrichment

Date: 2026-07-18

## Status

Accepted

## Context

PULSE needs an ArXiv source that preserves user intent, returns authoritative publication
metadata, and joins the source-neutral parallel contract without duplicating the ReAct engine.
ArXiv's Atom API supplies titles, abstract-page and PDF links, abstracts, and publication dates,
but its search endpoint expects fielded query syntax. Full-text PDF processing can improve a small
number of results, but must not make metadata collection depend on PDF extraction.

## Decision

Use one direct ArXiv Atom API request as the source of truth for search and metadata. Convert the
immutable user query with a deterministic grammar: unqualified terms use `all`, supported ArXiv
field prefixes remain fielded, positive clauses use `AND`, and leading-minus exclusions use
`ANDNOT`. Quoted phrases remain single clauses. Invalid local syntax is rejected before the
request; there is no LLM query refinement or ArXiv ReAct runner. Serialize requests with a
process-wide gate held through the HTTP call, and keep at least three seconds between request
starts to comply with the legacy API terms. Bound each request with a 30-second timeout because
observed API response latency can exceed 15 seconds.

HTTP errors, timeouts, invalid XML, non-Atom responses, and ArXiv Atom error entries raise so the
parallel coordinator records `FAILED`. A valid feed with no valid papers maps to
`PARTIAL(no_results)`. Malformed individual papers are skipped.

For optional PDF enrichment, select at most the first two valid papers with PDF links and make one
Tavily Extract batch call using the original query. Request three query-focused text chunks per
paper with a finite 20-second timeout, and append no more than 1,500 characters of highlights.
Missing credentials and batch or per-PDF failures retain the normalized ArXiv abstract and do not
change source status.

## Consequences

- ArXiv metadata collection works without Tavily credentials; only optional PDF highlights need
  Tavily.
- Query conversion is deterministic, reviewable, and testable, but intentionally supports only a
  small documented grammar rather than arbitrary ArXiv Boolean expressions.
- One source run makes one bounded ArXiv request and at most one bounded Tavily extraction call.
- The current single-process runtime enforces ArXiv pacing locally; a multi-process deployment
  would need shared rate-limit coordination.
- The generic parallel coordinator remains source-neutral, and the HN-only CLI is unchanged.

## Alternatives Considered

- Tavily-only search: simpler integration, but less authoritative abstracts, dates, and canonical
  paper links.
- Local PDF downloads and parsing: avoids Tavily extraction, but adds a PDF dependency, more
  bandwidth, and a larger failure surface.
- A dedicated ArXiv ReAct loop: unnecessary for the parallel-source contract and would add LLM
  cost without improving authoritative metadata normalization.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Model: [../workspace.dsl](../workspace.dsl)
- Parallel flow: [../flows/parallel-collect.mmd](../flows/parallel-collect.mmd)
- Parallel contract: [0010-source-neutral-parallel-fanout-contract.md](0010-source-neutral-parallel-fanout-contract.md)
