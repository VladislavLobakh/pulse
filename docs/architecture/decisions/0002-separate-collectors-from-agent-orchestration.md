# 2. Separate collectors from agent orchestration

Date: 2026-06-28

## Status

Accepted

## Context

PULSE source agents need to collect articles from multiple external sources while keeping the
agent layer thin enough to compose later inside LangGraph flows. The first implemented source,
Hacker News via Tavily, introduced both fetch/parse code and an agent entry point.

Mixing external API calls directly into agents would make source behavior harder to test, reuse,
and expose later through MCP or API surfaces.

## Decision

Collectors own external fetch and parse logic. Agents orchestrate collectors, apply source-level
defaults, and hand results to display or future pipeline steps.

Shared domain types stay in `src/pulse/models.py`. New sources add fetch/parse code under
`src/pulse/collectors/`, while `src/pulse/agents/` remains orchestration-only.

## Consequences

Collector parsing can be tested without network calls. The same collector behavior can later be
used by CLI, scheduled jobs, MCP tools, or API handlers without duplicating fetch logic.

Agents must not bypass collectors for convenience. If an agent needs new source data, the collector
contract should grow first.

## Alternatives Considered

- Put fetch logic in each agent: fastest for the first source, but couples orchestration to APIs.
- Build a generic collector abstraction immediately: premature while only one collector exists.

## Related

- Project contract: [../../../AGENTS.md](../../../AGENTS.md)
- HN flow: [../flows/hn-collect.mmd](../flows/hn-collect.mmd)
