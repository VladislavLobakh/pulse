# PULSE — AI Intelligence & Content Factory

PULSE — personal AI intelligence & content factory: collects AI news from multiple sources, filters through a personal profile, builds a knowledge graph, and produces a digest + LinkedIn drafts.

## Critical import rules
```python
from langchain.agents import create_agent      # NOT langgraph.prebuilt.create_react_agent
from fastmcp import FastMCP                     # NOT mcp.server.fastmcp
```

## Version pins (do not change)
- `langgraph>=1.2.0` — NOT 1.0.x (breaking change in prebuilt)
- `langchain-mcp-adapters>=0.3.0` — required for MCP↔LangGraph
- `qdrant-client>=1.15.0`, `pydantic>=2.11.0`

Installed deps → `pyproject.toml`. Pins above apply when adding those packages.

## Code conventions
- Every LLM output → Pydantic model (via Instructor)
- Every agent graph → `graph.compile(recursion_limit=10)`
- Qdrant: always `upsert`, never `delete`+`recreate`
- Source layout: code lives in `src/pulse/`, tests in `tests/`
- Run commands with `uv run`, never activate venv manually

## Build & test commands
```bash
uv sync                          # install from lockfile
uv run python -m pulse.main      # run the app
uv run pytest                    # run tests
uv run ruff check --fix && uv run ruff format
```

## Current capabilities
- HN source agent collects AI articles via Tavily (`collectors/tavily.py`)
- CLI: `uv run python -m pulse.agents.hn_agent` or `uv run python -m pulse.main`
- LangGraph, Qdrant, digest pipeline — **not implemented yet** (see `docs/architecture.md`)

## Module layout
```
src/pulse/
  models.py       — shared domain types (Article, Source, ArticleList, enums)
  collectors/     — one file per data source; own the fetch + parse logic
  agents/         — thin orchestration wrappers; import from collectors + models, no fetch logic
  display.py      — terminal/CLI output only
  scripts/        — runnable utilities (e.g. generate_test_data)
tests/            — mirrors src/pulse/ structure
```
New shared types → `models.py`. New data source → `collectors/<name>.py`. Agents never fetch directly.

## Architecture
- Full C4 rules, container table, Structurizr/Mermaid flows → `docs/architecture.md`
- When code changes a container, external system, or top-level flow → update `docs/architecture/*` in the same commit; flip `Planned → Implemented` on the element **and every relationship tag** on its edges

## Where things live
- `docs/patterns.md` — agentic pattern table; read when implementing ReAct, HITL, MCP, etc.
- Python deps → `pyproject.toml` · env vars → `.env.example` · import gotchas → this file

## Compaction policy
When compacting, preserve the list of modified files and any unresolved bugs.
