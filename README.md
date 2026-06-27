# PULSE — AI Intelligence & Content Factory

PULSE — personal AI intelligence & content factory: collects AI news from multiple sources, filters through a personal profile, builds a knowledge graph, and produces a digest + LinkedIn drafts.

**KPI:** 1 digest instead of 3h reading · 3 LinkedIn posts/week without stress

## Current capabilities

- HN source agent collects AI articles from Hacker News via Tavily
- CLI entry points: `uv run python -m pulse.agents.hn_agent` or `uv run python -m pulse.main`
- Digest, LangGraph orchestration, Qdrant — planned (see `docs/architecture.md`)

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env
# fill in TAVILY_API_KEY (required)

# 3. Collect HN articles
uv run python -m pulse.agents.hn_agent
# or
uv run python -m pulse.main
```

## Development

```bash
uv run pytest                              # test
uv run ruff check --fix && uv run ruff format   # lint + format
```

## Structure

```
pulse/
├── CLAUDE.md              # AI agent context (always loaded in Cursor)
├── .claude/
│   └── skills/            # skills (load on invocation)
├── docs/                  # project documentation
├── src/pulse/             # source code
│   ├── collectors/        # fetch + parse per source
│   └── agents/            # orchestration (hn_agent, …)
├── tests/                 # pytest
├── data/                  # test fixtures
└── pyproject.toml         # Python deps (installed packages)
```

## Documentation

| File | Purpose |
|---|---|
| `CLAUDE.md` | Agent rules, conventions, commands |
| `docs/architecture.md` | C4 rules, container table, diagram policy |
| `docs/patterns.md` | Agentic patterns + Pydantic contracts |
| `docs/architecture/` | Structurizr DSL + Mermaid flows |
| `.env.example` | Environment variable reference |

## Stack

**Installed** (in `pyproject.toml`): uv · Ruff · pytest · tavily-python · httpx · python-dotenv · faker

**Planned** (see `docs/architecture.md`): LangGraph · LangChain · FastMCP · Qdrant · Mem0 · Langfuse · Modal · Inngest · LightRAG + Neo4j · PostgreSQL · Redis · Next.js dashboard
