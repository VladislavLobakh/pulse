# PULSE — AI Intelligence & Content Factory

A personal AI system that collects AI news from 5 sources (6th = Deep Track), filters through a personal profile, builds a knowledge graph, and generates a personalized digest + LinkedIn posts. Built over 21 days as an AI Engineering learning project.

**KPI:** 1 digest instead of 3h reading · 3 LinkedIn posts/week without stress

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env
# fill in TAVILY_API_KEY (required from Day 1)

# 3. Run Day 1 agent (once implemented)
uv run python -m pulse.agents.hn_agent

# Docker services are added incrementally (Qdrant D6, Langfuse D7, etc.)
# docker compose up -d
```

## Daily workflow

```bash
uv run pytest                              # test
uv run ruff check --fix && uv run ruff format   # lint + format
```

## Structure

```
pulse/
├── CLAUDE.md              # Claude Code context (always loaded)
├── .claude/
│   ├── agents/           # subagents (auto-load by description)
│   └── skills/           # skills (load on invocation)
├── docs/                 # specs — read before each day
├── src/pulse/            # source code
│   └── agents/           # source agents (D1: hn_agent)
├── tests/                # pytest
├── data/                 # test data + golden dataset
└── pyproject.toml        # single source of truth
```

## Documentation

| File | Purpose |
|---|---|
| `docs/00_AGENT_INSTRUCTIONS.md` | How to use all artifacts |
| `docs/01_business_requirements.md` | Persona, pains, KPI, user stories |
| `docs/02_21day_plan.md` | Day-by-day plan + concepts + questions + adaptability |
| `docs/03_patterns_reference.md` | 12 agentic patterns + Demo Script |
| `docs/04_tech_stack.md` | Versions, deps-by-day, Docker, deploy map |

## Stack (2026)

uv · Ruff · LangGraph 1.2 · LangChain 1.2 · FastMCP · Qdrant · Mem0 · Langfuse · Modal · Inngest · LightRAG + Neo4j · RAGAS · Next.js
