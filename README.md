# PULSE — AI Intelligence & Content Factory

PULSE — personal AI intelligence & content factory: collects AI news from multiple sources, filters through a personal profile, builds a knowledge graph, and produces a digest + LinkedIn drafts.

**KPI:** 1 digest instead of 3h reading · 3 LinkedIn posts/week without stress

## Current capabilities

- Source runners for HN (via Tavily + a LangGraph ReAct reason/act/observe loop over
  OpenRouter), ArXiv papers, YouTube transcripts, and configured newsletter RSS/Atom feeds
- Source-neutral parallel coordinator; the CLI fans out to all four sources concurrently
  with a per-source status summary
- CLI entry point: `uv run python -m pulse.main "<search query>"`
- Digest generation, cross-source LangGraph orchestration, Qdrant — planned (see `docs/architecture.md`)

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env
# fill in TAVILY_API_KEY (HN + YouTube discovery) and OPENROUTER_API_KEY
# (HN reasoning); ArXiv and Newsletter need no keys.

# 3. Collect items from all sources
uv run python -m pulse.main "postgres vacuum tuning"
```

## Development

```bash
uv run pytest                              # test
uv run ruff check --fix && uv run ruff format   # lint + format
```

## Structure

```
pulse/
├── AGENTS.md              # canonical cross-agent project contract
├── CLAUDE.md              # Claude runtime bridge (imports AGENTS.md)
├── .agents/
│   └── skills/            # canonical shared agent skills
├── .claude/
│   └── skills/            # Claude skill bridges (load on invocation)
├── docs/                  # project documentation
├── src/pulse/             # source code
│   ├── patterns/          # agentic pattern engines (react, …)
│   ├── collectors/        # fetch + parse per source
│   ├── agents/            # per-source configs (hn, …)
│   ├── workflows/         # product workflows composing patterns (research.py)
│   └── evals/             # live-model regression evals
├── tests/                 # pytest
├── data/                  # test fixtures + golden eval examples
└── pyproject.toml         # Python deps (installed packages)
```

## Documentation

| File | Purpose |
|---|---|
| `AGENTS.md` | Canonical agent rules, conventions, commands |
| `CLAUDE.md` | Claude runtime bridge (imports `AGENTS.md`) |
| `.agents/skills/` | Canonical shared agent skills |
| `.claude/skills/` | Claude runtime skill bridges that `@` canonical skills |
| `docs/architecture.md` | C4 rules, container table, diagram policy |
| `docs/architecture/decisions/` | Structurizr-backed architecture decision log |
| `docs/patterns.md` | Agentic patterns + Pydantic contracts |
| `docs/architecture/` | Structurizr DSL + Mermaid flows |
| `.env.example` | Environment variable reference |

## Stack

**Installed** (in `pyproject.toml`): uv · Ruff · pytest · LangGraph · Instructor · LiteLLM · Pydantic · Tenacity · tavily-python · httpx · feedparser · youtube-transcript-api · python-dotenv · requests · faker

**Planned** (see `docs/architecture.md`): LangChain · FastMCP · Qdrant · Mem0 · Langfuse · Modal · Inngest · LightRAG + Neo4j · PostgreSQL · Redis · Next.js dashboard
