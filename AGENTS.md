# AGENTS.md — PULSE project contract

Canonical cross-agent instructions for this repo. Use this as the first repo-level instruction file for any AI coding agent.

## Project overview

PULSE — personal AI intelligence & content factory: collects AI news from multiple sources, filters through a personal profile, builds a knowledge graph, and produces a digest + LinkedIn drafts.

## Repo map

```
src/pulse/
  models.py       — shared domain types (Article, Source, ArticleList, enums)
  collectors/     — one file per data source; own the fetch + parse logic
  agents/         — thin orchestration wrappers; import from collectors + models, no fetch logic
  display.py      — terminal/CLI output only
  scripts/        — runnable utilities (e.g. generate_test_data)
tests/            — mirrors src/pulse/ structure
```

New shared types → `models.py`. New data source → `collectors/<name>.py`.

## Setup

```bash
uv sync                          # install from lockfile
```

## Test / lint / run commands

```bash
uv run pytest                    # run tests
uv run ruff check --fix && uv run ruff format   # lint + format
uv run python -m pulse.main      # run the app
```

Run everything with `uv run`; never activate the venv manually.

## Core engineering rules

- **Imports:** `from langchain.agents import create_agent` (NOT `langgraph.prebuilt.create_react_agent`); `from fastmcp import FastMCP` (NOT `mcp.server.fastmcp`).
- **Version pins (do not change):** `langgraph>=1.2.0` (NOT 1.0.x), `langchain-mcp-adapters>=0.3.0`, `qdrant-client>=1.15.0`, `pydantic>=2.11.0`. Pins apply when adding those packages; installed deps live in `pyproject.toml`.
- Every LLM output → a Pydantic model (via Instructor). Plain domain data structures may remain dataclasses; do not convert existing domain dataclasses to Pydantic unless they become LLM output contracts.
- Every agent graph → `graph.compile(recursion_limit=10)`.
- Qdrant: always `upsert`, never `delete`+`recreate`.
- Agents never fetch directly — fetch/parse logic lives in `collectors/`.

## Forbidden actions

- Do not change the version pins above.
- Do not use the deprecated imports listed above.
- Do not put fetch logic in `agents/`.
- Do not `delete`+`recreate` Qdrant collections.
- Do not read or commit `.env`.

## Architecture update expectation

When code changes a container, external system, or top-level flow, update the architecture docs in the **same commit**: flip `Planned → Implemented` on the element **and every relationship tag** on its edges. This means both `docs/architecture.md` (the canonical C4 rules and container table) and the supporting files in `docs/architecture/` (Structurizr DSL + Mermaid flows).

## Docs map

- `docs/architecture.md` — C4 rules, container table, status-flip/grep/parity governance (canonical).
- `docs/patterns.md` — agentic pattern table; read when implementing ReAct, HITL, MCP, etc.
- `pyproject.toml` — Python deps + ruff/pytest config.
- `.env.example` — env vars.
- `README.md` — human onboarding.

## Instruction precedence

1. System, tool, and safety constraints.
2. Explicit user instructions in the current task.
3. This `AGENTS.md`.
4. Tool-specific bridge files such as `CLAUDE.md` for runtime-only notes — these must not contradict `AGENTS.md`.
5. Canonical docs (`docs/*`) for the domains they own.

If anything conflicts with `AGENTS.md`, `AGENTS.md` wins unless a higher-priority instruction says otherwise. If `AGENTS.md` looks stale, flag it rather than silently diverging.
