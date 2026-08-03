# PULSE — AI Intelligence & Content Factory

[![CI](https://github.com/VladislavLobakh/pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/VladislavLobakh/pulse/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

PULSE — personal AI intelligence & content factory: collects AI news from multiple sources, filters through a personal profile, builds a knowledge graph, and produces a digest + LinkedIn drafts.

**KPI:** 1 digest instead of 3h reading · 3 LinkedIn posts/week without stress

## Current capabilities

- Source runners for HN (via Tavily + a LangGraph ReAct reason/act/observe loop over
  OpenRouter), ArXiv papers, YouTube transcripts, and configured newsletter RSS/Atom feeds
- Cross-source LangGraph research workflow (`workflows/research.py`) that validates the query,
  then fans out to all four sources concurrently via the parallel coordinator with a
  per-source status summary
- Per-item topic-signal extraction (`patterns/topic_signal.py`) over the collected items, shown
  in the CLI listing with a separate analysis status
- CLI entry point: `uv run python -m pulse.main "<search query>"`

Full implemented/planned status and roadmap: [`docs/architecture.md`](docs/architecture.md).

## Setup

**Prerequisites:** Python 3.13 · [uv](https://docs.astral.sh/uv/)

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

## Contributing

Read [`AGENTS.md`](AGENTS.md) before opening a PR — it's the canonical contract for repo
layout, engineering rules, and forbidden actions (applies to human and AI contributors alike).
Run the test/lint commands above before submitting; CI (`.github/workflows/ci.yml`) enforces
the same checks on every push and PR to `main`.

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

Planned additions are tracked in [`docs/architecture.md`](docs/architecture.md).
