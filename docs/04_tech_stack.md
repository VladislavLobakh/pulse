# PULSE — Tech Stack Reference

Package list lives in **`pyproject.toml`** (single source of truth). This file: versions, install timeline, infra, debugging.

Import rules and code conventions: **`CLAUDE.md`**.

---

## Critical Compatibility Notes (June 2026)

### ⚠️ 1. LangGraph — use >=1.2.0, NOT 1.0.x

```python
# ✅ CORRECT:
from langchain.agents import create_agent

# ❌ DEPRECATED:
from langgraph.prebuilt import create_react_agent
```

### ⚠️ 2. FastMCP — standalone package

```python
# ✅ from fastmcp import FastMCP
# ❌ from mcp.server.fastmcp import FastMCP
```

### ⚠️ 3. langchain-mcp-adapters — required for MCP ↔ LangGraph

### ✅ 4. pydantic v2 + qdrant-client — conflict RESOLVED (2023 issue, safe now)

### ⚠️ 5. mem0ai — pydantic v1 deprecation warnings are non-critical

---

## Compatibility Matrix (key packages)

| Package | Version | Day | Notes |
|---|---|---|---|
| langgraph | >=1.2.6 | D2 | NOT 1.0.x |
| langchain | >=1.2.0 | D2 | `create_agent` from `langchain.agents` |
| langchain-mcp-adapters | >=0.3.0 | D4a | MCP ↔ LangGraph bridge |
| pydantic | >=2.11.0 | D4b | |
| instructor | >=1.0.0 | D4b | |
| qdrant-client | >=1.15.0 | D6 | upsert, never delete+recreate |
| mem0ai | >=0.1.100 | D6 | |
| langfuse | >=3.0.0 | D7 | |
| modal | >=0.73.0 | D9 | `@cron`, `@asgi_app` |
| langgraph-checkpoint-postgres | >=2.0.0 | D9 | PostgresSaver deps; wired D17 |
| fastmcp | >=2.0.0 | D10 | |
| inngest | >=0.3.0 | D13 | Fallback: Modal `@function` |
| lightrag-hku | >=1.0.0 | D14 | ~$0.10 indexing / 50 articles |
| ragas / deepeval | >=0.2 / >=1.0 | D17 | CI gate: avg_score < 0.75 |

---

## Dependencies by Day

| Day | `uv add` |
|---|---|
| D1 | `tavily-python python-dotenv faker ruff httpx` |
| D2 | `openai litellm tenacity langgraph>=1.2.0 langchain>=1.2.0 langchain-community>=0.3.0 langchain-openai langchain-anthropic` |
| D3 | `llama-parse feedparser youtube-transcript-api` |
| D4a | `langchain-mcp-adapters>=0.3.0` |
| D4b | `pydantic>=2.11.0 instructor` |
| D6 | `qdrant-client>=1.15.0 langchain-qdrant flashrank mem0ai>=0.1.100` |
| D7 | `langfuse` |
| D9 | `modal fastapi uvicorn sqlalchemy>=2.0.40 psycopg2-binary pytest httpx langgraph-checkpoint-postgres` |
| D10 | `fastmcp>=2.0.0 mcp>=1.9.0` |
| D13 | `inngest>=0.3.0 redis>=5.0.0` |
| D14 | `lightrag-hku>=1.0.0 neo4j` |
| D17 | `ragas>=0.2.0 deepeval>=1.0.0` |
| D20 | `npx create-next-app --typescript --tailwind` |

---

## Docker Compose (full local stack)

```yaml
version: "3.9"
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
    volumes: ["./data/qdrant:/qdrant/storage"]

  langfuse:
    image: langfuse/langfuse:latest
    ports: ["3000:3000"]
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/langfuse
      NEXTAUTH_SECRET: your-secret
      SALT: your-salt

  postgres:
    image: postgres:16
    ports: ["5432:5432"]
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: pulse

  neo4j:
    image: neo4j:5
    ports: ["7474:7474", "7687:7687"]
    environment:
      NEO4J_AUTH: neo4j/password
      NEO4J_dbms_memory_heap_max__size: 512m

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

Start: `docker compose up -d`

---

## Deploy Map

| Component | Where | URL / Port | Day |
|---|---|---|---|
| FastAPI core | Modal `@asgi_app` | `https://pulse--api.modal.run` | D9 |
| FastMCP server | Modal `@web_endpoint` | `https://pulse--mcp.modal.run` | D10 |
| Digest `@cron` 8:00 UTC | Modal Scheduler | daily 08:00 UTC | D9 (local script D7) |
| Reflection `@cron` Sunday | Modal Scheduler | Sun 10:00 UTC | D19 |
| Next.js Dashboard | Vercel | `https://pulse.vercel.app` | D20 |
| Qdrant | Docker | `localhost:6333` | D6 |
| Langfuse | Docker | `localhost:3000` | D7 |
| PostgreSQL | Docker | `localhost:5432` | D9 |
| Neo4j | Docker | `localhost:7474` / `7687` | D14 |
| Redis | Docker | `localhost:6379` | D13 |
| Mem0 | in-process | embedded | D6 |
| Inngest | Cloud + `inngest dev` | dashboard.inngest.com | D13 |

---

## Environment Variables

```bash
# LLM
OPENROUTER_API_KEY=sk-or-v1-...
OPENAI_API_KEY=sk-...

# Search & parsing
TAVILY_API_KEY=tvly-...
LLAMA_CLOUD_API_KEY=llx-...

# Memory & DB
QDRANT_URL=http://localhost:6333
POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/pulse
REDIS_URL=redis://localhost:6379

# Observability
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000

# Deploy & async
MODAL_TOKEN_ID=...
TELEGRAM_BOT_TOKEN=...
INNGEST_SIGNING_KEY=...
INNGEST_EVENT_KEY=...
MEM0_API_KEY=...             # optional cloud tier
```
