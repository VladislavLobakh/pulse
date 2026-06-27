# PULSE — Development Journal

Short log after each build day: what shipped, what was deferred, what we learned.  
Update at end of day before starting the next one.

**Template for new entries:**

```markdown
## D{n} — YYYY-MM-DD

**Pattern:** …  
**Deliverable:** …

### Done
- …

### Deferred
- …

### Learned
- …

### Understanding (🤔 from plan)
> …

### Next
- D{n+1}: …
```

---

## D1 — 2026-06-27

**Pattern:** Tool use  
**Deliverable:** `uv run python -m pulse.agents.hn_agent` → 8+ AI articles from HN; `data/pulse_test_articles.json` with 30 synthetic articles

### Done
- Project scaffold: `src/pulse/`, `tests/`, `uv` + `pyproject.toml`
- HN agent via Tavily SDK (`collectors/tavily.py`, `agents/hn_agent.py`)
- Shared domain models: `models.py` (`Article`, `Source`, `ArticleList`)
- CLI output: `display.py`; app entry: `main.py`
- Test fixture generator: `scripts/generate_test_data.py` → 30 articles, `random.seed(42)`
- 20 unit tests (models + Tavily parser, no network)
- Post-review hardening: `None` handling in parser, unified `MIN_ARTICLES` warning
- Architecture split: collectors / agents / models (not HN-centric)
- CI: GitHub Actions (pytest + ruff)

### Deferred
- `search_articles()` tests with mocked `TavilyClient`
- `pytest-cov` coverage gate
- Empty `url` filtering
- Reading `pulse_test_articles.json` in runtime pipeline (D4+)
- Pydantic models (D4b)

### Learned
- Tavily can return explicit `null` for fields — `.get("key", "")` is not enough; use `(r.get("key") or "")`
- Put shared types in `models.py` from day one, not inside the first agent
- Code review after deliverable catches real bugs before the next day builds on them

### Understanding (🤔 from plan)
> What's the difference between Day 1 direct Tavily calls and Day 10 FastMCP tool calls?

Day 1 = direct SDK call in Python code (simple, no protocol). Day 10 = same capability exposed via MCP (standardized tool schema, any MCP client/agent can call it). MCP adds interoperability and discovery; direct calls are fine for a single-script prototype.

### Next
- **D2:** ReAct loop — LangGraph `create_agent`, first reasoning→act→observe cycle on HN agent
