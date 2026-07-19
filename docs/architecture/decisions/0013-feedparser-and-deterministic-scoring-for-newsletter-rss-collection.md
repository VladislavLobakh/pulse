# 13. Use feedparser and deterministic scoring for newsletter RSS collection

Date: 2026-07-19

## Status

Accepted

## Context

PULSE needs a newsletter source that reads a small curated set of RSS/Atom feeds (initially
Latent Space and Simon Willison), selects entries relevant to the user query, and joins the
source-neutral parallel contract. The feeds are explicitly configured, so the workflow is
deterministic and needs neither feed discovery nor an LLM loop. Feed formats differ (RSS 2.0
with `content:encoded` vs Atom), entries may be malformed, and any single feed can be down
without the whole source being worthless. `SourceItem` has no per-feed metadata field, but the
digest should still show which newsletter an item came from.

## Decision

Configure feeds as code data in `collectors/newsletter.py`, never in the generic coordinator.
Fetch each feed with `httpx` (bounded 10-second timeout, explicit User-Agent) and hand the
bytes to `feedparser`, which normalizes RSS 2.0 and Atom uniformly; do not let `feedparser`
fetch URLs itself, keeping one HTTP stack and testability via mocked `httpx.get`.

Isolate failures at two levels: a failing or unusable feed is logged (exception class name
only) and recorded in `failed_feeds` while other feeds proceed, and a single malformed entry
is skipped without failing its feed. Only when every configured feed fails does the collector
raise `NewsletterFeedError`, so the coordinator records `FAILED`. The runner maps surviving
items with failed feeds to `PARTIAL(partial_feed_failure)` and a clean empty result to
`PARTIAL(no_results)`.

Score relevance deterministically: the fraction of non-stopword query tokens (fixed 20-word
stopword set) found in the entry title plus the full cleaned entry text, preferring
`content[*].value` over the summary; tokens of four or more characters also match as
prefixes. Zero-score entries are dropped; results sort stably by score. There is no LLM
scoring, no ReAct loop, and no full-page HTML enrichment. Accept only absolute HTTP(S) entry
links, strip URL fragments, and dedup by the coordinator's `normalize_url`. Record the source
newsletter by prefixing the summary with the feed name, truncated together to the summary
bound, instead of extending the shared `SourceItem` model.

## Consequences

- Feed collection needs no API keys or LLM calls; a run makes exactly one bounded GET per
  configured feed.
- Relevance is reviewable and fully testable, but token overlap is cruder than semantic
  scoring; refining relevance later means revisiting the scoring step, not the contract.
- Adding a newsletter is a one-line config change; automatic discovery stays out of scope.
- The feed name lives inside the summary text, so consumers needing structured per-feed
  metadata would require extending `SourceItem` later.
- The generic parallel coordinator remains source-neutral, and the HN-only CLI is unchanged.

## Alternatives Considered

- LLM batch scoring via the existing `SourceBatchScore` contract: better semantic relevance,
  but nondeterministic, adds API cost, and is unnecessary for two curated feeds.
- Hand-rolled per-format XML parsing (as the ArXiv collector does for Atom): avoids a
  dependency, but duplicates RSS/Atom quirk handling that `feedparser` already normalizes.
- Extending `SourceItem` with a feed-metadata field: cleaner provenance, but touches the
  shared model used by every source for a display-grade need.
- Full-page HTML enrichment for thin entries: both initial feeds ship substantial entry
  content, so the added fetch surface is not worth it yet.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Model: [../workspace.dsl](../workspace.dsl)
- Parallel flow: [../flows/parallel-collect.mmd](../flows/parallel-collect.mmd)
- Parallel contract: [0010-source-neutral-parallel-fanout-contract.md](0010-source-neutral-parallel-fanout-contract.md)
