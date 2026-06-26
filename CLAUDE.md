# PULSE — AI Intelligence & Content Factory

Building PULSE to become an AI Engineer: a system that collects AI news from 5 sources, filters through a personal profile, builds a knowledge graph, and generates a personalized digest + LinkedIn posts.

**KPI:** "1 digest instead of 3h reading · 3 LinkedIn posts/week without stress"

## Critical import rules
```python
from langchain.agents import create_agent      # NOT langgraph.prebuilt.create_react_agent
from fastmcp import FastMCP                     # NOT mcp.server.fastmcp
```

## Version pins (do not change)
- `langgraph>=1.2.0` — NOT 1.0.x (breaking change in prebuilt)
- `langchain-mcp-adapters>=0.3.0` — required for MCP↔LangGraph
- `qdrant-client>=1.15.0`, `pydantic>=2.11.0`

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

## Project status
- **Day:** D1 (not started) · **Phase:** 1 — Intelligence · **MVP:** 0

## Where things live
- Specs: `docs/` — read the relevant file before each day (see `docs/00_AGENT_INSTRUCTIONS.md`)
- Daily plan: `docs/02_21day_plan.md`
- Tech stack & compatibility: `docs/04_tech_stack.md`

## Compaction policy
When compacting, always preserve: the current Day number, the list of modified files, the active deliverable, and any unresolved bug.