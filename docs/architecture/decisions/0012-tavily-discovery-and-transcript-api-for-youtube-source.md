# 12. Use Tavily discovery and youtube-transcript-api for the YouTube source

Date: 2026-07-19

## Status

Accepted

## Context

PULSE needs a YouTube source that finds relevant videos for a user query and turns their
transcripts into `SourceItem`s through the source-neutral parallel contract. The
`youtube-transcript-api` library fetches captions for a known video id but is not a search
API, so discovery needs its own mechanism. Discovered URLs arrive in many variants
(`watch`, `youtu.be`, `shorts`, `embed`) mixed with non-video pages, and many videos have
disabled or missing captions — a per-video condition that must not fail the whole run.
The library talks to an unofficial endpoint, so infrastructure failures such as request
blocking must stay distinguishable from genuinely missing captions.

## Decision

Discover videos with the existing Tavily collector restricted to `youtube.com`, reusing the
HN precedent and requiring no new API key. Normalize every discovered URL to a canonical
11-character video id with a strict allowlist of hosts and path shapes; non-video URLs are
dropped silently as discovery noise. Deduplicate ids preserving Tavily relevance order and
request transcripts for at most `MAX_TRANSCRIPTS` candidates per run — a deterministic
truncation, not a recorded failure. There is no ReAct loop and no LLM summarization: an
available transcript becomes a whitespace-normalized excerpt bounded to 1,500 characters,
and emitted items carry the canonical `watch` URL so the coordinator's URL dedup collapses
variant forms.

A transcript is required for an item; a video without one is never emitted from the Tavily
snippet alone. Failures follow an explicit taxonomy. Per-video caption problems —
`TranscriptsDisabled`, `NoTranscriptFound`, `VideoUnavailable`, `VideoUnplayable`,
`AgeRestricted`, `PoTokenRequired` — skip only that video and are recorded as the video id
plus exception class name. Infrastructure failures — `RequestBlocked`/`IpBlocked`,
`YouTubeRequestFailed`, `YouTubeDataUnparsable`, network timeouts, and any unknown
`CouldNotRetrieveTranscript` subclass — propagate immediately, stopping further transcript
requests, so the coordinator records `FAILED` with the class name. Runner statuses map to
stable short codes only: items without skips are `SUCCESS`; recorded skips yield
`PARTIAL(skipped_videos)` or `PARTIAL(no_transcripts)`; an empty discovery yields
`PARTIAL(no_results)`.

All transcript HTTP traffic goes through one `requests.Session` per run that enforces a
finite default timeout (including when a caller passes `timeout=None`) and is closed when
the run ends. `requests` becomes a direct dependency because the collector imports it.
`max_results` and `max_transcripts` are validated as integers within their bounds before
discovery; out-of-range values are configuration errors, not clamped.

## Consequences

- No new API credentials: discovery reuses the Tavily key already required by other sources.
- Request blocking and endpoint drift surface as `FAILED` runs instead of silently empty
  `PARTIAL` results, at the cost of failing the source when YouTube blocks the caller's IP.
- Skipped videos are explainable from the video id and exception class name without ever
  logging provider payloads or exception messages.
- The transcript library is unofficial; YouTube-side changes can break it independently of
  PULSE releases.
- English captions only for now; broadening is a one-constant change.
- The parallel coordinator and the HN-only CLI remain unchanged.

## Alternatives Considered

- YouTube Data API v3 for discovery: official metadata, but adds a Google API key, quota
  management, and still cannot fetch transcripts.
- yt-dlp subtitle download: heavyweight dependency and file handling for what one HTTP
  library call provides.
- Emitting Tavily snippets when transcripts fail: produces a mixed-quality summary corpus
  and removes the source's value over plain Tavily search.
- LLM summarization of transcripts: nondeterministic output and per-run cost where a
  bounded excerpt suffices.
- Catching the library's base exception for all failures: simpler, but hides request
  blocking and future unknown failures inside skipped-video lists.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Model: [../workspace.dsl](../workspace.dsl)
- Parallel flow: [../flows/parallel-collect.mmd](../flows/parallel-collect.mmd)
- Parallel contract: [0010-source-neutral-parallel-fanout-contract.md](0010-source-neutral-parallel-fanout-contract.md)
- ArXiv precedent: [0011-use-arxiv-api-for-metadata-and-tavily-for-bounded-pdf-enrichment.md](0011-use-arxiv-api-for-metadata-and-tavily-for-bounded-pdf-enrichment.md)
