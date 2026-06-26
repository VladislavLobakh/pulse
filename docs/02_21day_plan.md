# PULSE — 21-Day Execution Plan

**KPI: "1 digest instead of 3 hours of reading · 3 LinkedIn posts/week without stress"**

## Legend
- 📖 Concept (10 min before coding) — understand WHY before HOW
- 🤔 Understanding question (5 min after deliverable) — can't answer without understanding
- ⚠️ Critical warning — will cause failure if ignored
- ⚡ Fast Track alternative — use if behind schedule

---

## Calendar Map (21 build days + 2 buffers)

| # | Segment | Phase | Pattern / focus | Notes |
|---|---|---|---|---|
| 1 | D1 | 1 | Tool use | Project init, HN agent, test fixtures |
| 2 | D2 | 1 | ReAct | **LangGraph installed here** (`create_agent`) |
| 3 | D3 | 1 | Parallel (asyncio) | 4 source agents |
| 4 | D4a | 1 | Orchestration | Same calendar day as 4b (morning) |
| 4 | D4b | 1 | Instructor + Pydantic | Same calendar day as 4a (afternoon) |
| 5 | D5 | 1 | Plan-and-Execute | |
| 6 | D6 | 1 | Persistence | Mem0 + Qdrant; PostgresSaver = concept only |
| 7 | D7 | 1 | Observability | Local digest + Telegram; **no Modal yet** |
| — | **B1** | — | Buffer | After D7 · not counted in 21 |
| 8 | D9 | 2 | Modal + FastAPI | Cloud deploy + `@cron` digest 8:00 UTC |
| 9 | D10 | 2 | Tool use (MCP) | FastMCP server |
| 10 | D11 | 2 | Self-correction | LinkedIn draft generator |
| 11 | D12 | 2 | Self-verification | Verify **before** human review |
| 12 | D13 | 2 | Human-in-the-loop | Inngest pause after verify |
| 13 | D14 | 2 | Routing advanced | LightRAG + Neo4j |
| 14 | D15 | 2 | Composite agent | Deep Dive |
| — | **B2** | — | Buffer | After D15 · not counted in 21 |
| — | **D16** | — | Slack | Optional catch-up · skip if on schedule |
| 15 | D17 | 3 | Research & Report p1 | RAGAS + PostgresSaver `/chat` |
| 16 | D18 | 3 | Research & Report p2 | On-demand full pipeline |
| 17 | D19 | 3 | Reflection | Weekly `@modal.cron` Sunday |
| 18 | D20 | 3 | Next.js UI | DraftInbox approve flow |
| 19 | D21 | 3 | Packaging | Demo Script + Loom |

**Phase boundaries:** Phase 1 = D1–D7 (+ B1) · Phase 2 = D9–D15 (+ B2) · Phase 3 = D17–D21 (+ D16 slack). Day 8 is B1, not a build day.

**Content pipeline order (Phase 2):** `generate → self-correct → verify → HITL pause → publish (stub until LinkedIn API)`.

**KPI cadence:** Digest automated @ D9 (`@cron` 8:00). Posts: `@modal.cron("0 9 * * 1,3,5")` draft generation on D13 — 3/week habit + HITL approve.

---

## Pre-start Diagnosis (Day 1, 15 min)

Answer honestly before starting:
- [ ] Know what async/await is in Python → if ❌: read asyncio basics (30 min)
- [ ] Have run Docker Compose with multiple services → if ❌: docker-compose up tutorial (20 min)
- [ ] Have made HTTP requests with httpx/requests in Python → if ❌: basic example (15 min)
- [ ] Have opened LangChain documentation → if ❌: Overview (15 min)

**Rule: if 2+ are ❌ → add Day 0 (optional, 3 hours) before Day 1.**

---

## Day 0 (Optional — only if diagnosis shows gaps)

**Time:** 3h | **Pattern:** — (prerequisites)

**Tasks:**
1. asyncio basics: async/await, gather (1h)
2. Docker Compose with two services (1h)
3. httpx requests (0.5h)
4. LangChain Overview (0.5h)

**Deliverable:** All checkboxes ✅ in diagnosis

---

## PHASE 1: INTELLIGENCE (Days 1–7, Day 4 = 4a + 4b)
### One agent grows, 6 patterns (+ Instructor on 4b)

---

### Day 1 — Tool use (first tool)

**Time:** 3.5h | **Pattern:** Tool use | **Business:** First AI articles collected automatically

📖 **Concept:** Tool use is the foundation: the model calls an external capability and gets structured data back. Day 1 = Tavily SDK directly. Day 10 = FastMCP (same idea, standardized protocol). Without tools, an agent only knows training data.

**Install:**
```
uv add tavily-python python-dotenv faker ruff httpx
```

**Tasks:**
1. `uv init pulse` — create project; code in `src/pulse/`, tests in `tests/`
2. Create `.env` with API keys (Tavily required; others as needed later)
3. Add KPI to `CLAUDE.md`: "1 digest instead of 3h reading, 3 posts/week"
4. `generate_test_data.py` → `pulse_test_articles.json` (30 synthetic AI articles: title, content, source, date, topics[])
5. First HN Agent: `Tavily("AI LLM site:news.ycombinator.com")` → parse results to `ArticleList` (plain dataclass or dict — Pydantic models on D4b)

⚠️ Stuck: Tavily 401 → key starts with `tvly-`

**✅ Deliverable:**
```
uv run python -m pulse.agents.hn_agent → 8 AI articles from HN (title, url, score, summary)
pulse_test_articles.json → 30 synthetic articles created
```

**💼 Business:** First tool works. PULSE collects content without manual search.

🤔 **Question:** What's the difference between Day 1 direct Tavily calls and Day 10 FastMCP tool calls? Why introduce MCP later?

**CLAUDE.md:** Add KPI + Tool use pattern. Create `setup-checker` subagent.

---

### Day 2 — ReAct loop (reason→act→observe)

**Time:** 4h | **Pattern:** ReAct | **Business:** Agent decides what to search — not Ulad

**Install:**
```
uv add openai litellm tenacity langgraph>=1.2.0 langchain>=1.2.0 langchain-community>=0.3.0 langchain-openai langchain-anthropic
```

⚠️ **CRITICAL: `langgraph>=1.2.0` — NOT 1.0.x (breaking change in prebuilt Oct 2025)**

📖 **Concept:** ReAct = Reasoning + Acting. Before acting, the agent writes its reasoning ("Thought"), acts, observes, reasons again. ReAct agents can be debugged by reading their thoughts — unlike a blind tool loop.

**Tasks:**
1. Refactor HN Agent to use OpenRouter
2. ⚠️ `from langchain.agents import create_agent` — NOT `from langgraph.prebuilt import create_react_agent` (deprecated!)
3. ReAct graph: `reason_node → act_node(tavily) → observe_node(score sufficient?) → cond_edge`
4. `graph.compile(recursion_limit=10)` — protection against infinite loop
5. Add scoring: `ArticleScore(relevance, novelty, quality)` — use `@dataclass` until Pydantic on D4b
6. Fallback chain: Claude → GPT-4o → Gemini via litellm
7. `tenacity @retry` for 429/504 errors

⚠️ Stuck: OpenRouter 401 → key starts with `sk-or-v1-`

**✅ Deliverable:**
```
"Find articles about MCP" →
  Reason: "searching MCP"
  Act: tavily("MCP 2026")
  Observe: score=0.87 ✅
→ STOPPED (not looping)
```

🤔 **Question:** How does ReAct differ from a simple loop with tool calls? When can it get stuck and what does `recursion_limit=10` protect against?

**CLAUDE.md:** Add ReAct pattern. ⚠️ Note: `create_agent` from `langchain.agents`.

---

### Day 3 — Parallel research (asyncio)

**Time:** 3.5h | **Pattern:** Parallel (asyncio) | **Business:** 4 sources simultaneously

**Install:**
```
uv add llama-parse feedparser youtube-transcript-api
```

📖 **Concept:** `asyncio.gather()` runs multiple tasks simultaneously without waiting for each other. Error isolation is critical — one agent must not crash the others.

**Tasks:**
1. ArXiv Agent: `Tavily("site:arxiv.org AI agents 2026")` + LlamaParse for PDFs
2. YouTube Agent: YouTube Transcript API (free, subtitles only)
3. Newsletter Agent: feedparser RSS (Latent Space, Simon Willison) + LlamaParse HTML
4. Run 3 agents via `asyncio.gather()`
5. Start `golden_digest.json`: format `{article_id, summary, quality: 1-5}` — add 2-3 daily from now

⚠️ YouTube: `YouTubeTranscriptApi` raises exception if no subtitles → skip the video

**✅ Deliverable:**
```
asyncio.gather(hn, arxiv, youtube, newsletter)
→ 4 sources in parallel
→ 15 articles in 52 sec (would be 180+ sec sequentially)
```

🤔 **Question:** What happens if one agent crashes without `try/except` inside `gather()`?

---

### Day 4a — Orchestration + LangGraph State

**Time:** 4h | **Pattern:** Orchestration + LangGraph State | **Business:** 4 agents as one system

**Install:**
```
uv add langchain-mcp-adapters>=0.3.0
```

⚠️ LangGraph installed on **D2** — do not reinstall. Only add MCP bridge adapter now (needed for D10).

📖 **Concept:** State = shared memory of the entire graph. TypedDict = type safety. Orchestrator coordinates — doesn't do the work itself.

**Tasks:**
1. `PulseState(TypedDict)` — define shared state
2. LangGraph StateGraph: Orchestrator launches 3 agents via Send API (NOT asyncio)
3. First router: `route_by_source()`
4. `MOMENTUM_THRESHOLD = 2` (dev mode, 5 in prod)

⚠️ Stuck: LangGraph Send API → check `langgraph>=1.2.0`

**✅ Deliverable:**
```
3 agents via Send API: 17 articles in 48 sec
PulseState passed between nodes ✅
```

🤔 **Question:** Why TypedDict for State? What do we lose without type safety in production?

---

### Day 4b — Instructor + Pydantic typing

**Time:** 3.5h | **Pattern:** (4a continued) | **Business:** System understands article meaning

📖 **Concept:** LLMs return text. Instructor wraps an LLM call with a Pydantic model, retrying on `ValidationError`. Unlike JSON mode, Instructor validates against a schema and retries — field names can't silently drift.

**Install:**
```
uv add pydantic>=2.11.0 instructor
```

**Tasks:**
1. Instructor: extract `TopicSignal` from each article
2. Pydantic models: `Article`, `ArticleScore`, `TopicSignal`
3. Twitter/X Agent: `Tavily("AI site:twitter.com top -lang:ru")`
4. `golden_digest.json` +2-3 entries

⚠️ `pydantic>=2.11.0` — full compatibility with qdrant-client 1.15.x

**✅ Deliverable:**
```
"FastMCP released" →
TopicSignal(topic="FastMCP", novelty=0.92, trend="rising")
```

🤔 **Question:** When is Instructor better than json mode in LLM? What problem does it solve?

---

### Day 5 — Plan-and-Execute

**Time:** 3.5h | **Pattern:** Plan-and-Execute | **Business:** PULSE thinks ahead

**Install:** (none new)

📖 **Concept:** Planning ≠ execution. Planner decides WHAT (high-level), executors do HOW. Separation allows adapting the plan without restarting the entire pipeline.

**Tasks:**
1. `planning_node` → `ExecutionPlan(topics, queries, depth, priority_sources)`
2. Fallback for first run: `if no_history → default_topics = ["LangGraph", "MCP", "AI agents", "Claude", "OpenAI"]`
3. Source Agents read plan from State and adapt queries
4. Test: two runs with different plans — compare results

⚠️ Stuck: planning_node too expensive → use `claude-haiku-4-5` for planning

**✅ Deliverable:**
```
Run without plan: → 17 articles (generic)
Run with plan: → 12 articles (focused)
→ PLAN IMPROVES FOCUS
```

🤔 **Question:** Why does Planning Agent need to be separate from Orchestrator? Why not hardcode topics?

---

### Day 6 — Persistence (3 memory levels)

**Time:** 3.5h | **Pattern:** Persistence | **Business:** PULSE learns preferences

**Install:**
```
uv add qdrant-client>=1.15.0 langchain-qdrant openai flashrank mem0ai>=0.1.100
```

📖 **Concept:** Three memory horizons: **PostgresSaver** (instant dialogue — wired D17), **Mem0** (medium-term preferences), **Qdrant** (long-term documents). One store for everything = slow or noisy retrieval.

**Tasks:**
1. Qdrant Docker: `docker run -p 6333:6333 qdrant/qdrant`
2. Upsert all collected articles (NOT delete+recreate!)
3. FlashRank reranking after search (local, no API key needed)
4. Mem0 init: `m.add("learning LangGraph, MCP, FastAPI", user_id="me")` — seed profile; then `m.add(...)` after each interaction
5. Test: same search with/without Mem0 profile — different ranking

⚠️ mem0ai Pydantic deprecation warning — WARNING only, not critical, works fine
⚠️ Stuck: Qdrant connection refused → `docker ps`, check port 6333

**✅ Deliverable:**
```
Search "MCP deployment" WITHOUT Mem0: → ArXiv article #1
Search "MCP deployment" WITH Mem0: → practical HN article #1
(you prefer practice over theory)
```

🤔 **Question:** Why three memory levels instead of one? What breaks if you store everything in Qdrant and use semantic search for session history?

---

### Day 7 — Daily Digest + Observability (infra)

**Time:** 4h | **Pattern:** (Observability — infra, not pattern) | **Business:** First automatic digest

📖 **Concept:** You can't improve what you can't see. Langfuse traces every LLM call: input, output, latency, cost, prompt version. D7 = local `run_digest.py`; cloud `@cron` on D9.

**Install:**
```
uv add langfuse
```

**Tasks:**
1. Langfuse Docker + `CallbackHandler` in Orchestrator
2. Prompt versioning: `system_prompt_v1` vs `v2` (v2 with CoT for scoring)
3. First Daily Digest: 5 insights + 1 hot take
4. `DigestItem(headline, insight, source_url, relevance_score, pattern_tag)`
5. `scripts/run_digest.py` — run locally: `uv run python -m pulse.scripts.run_digest` (optional: laptop `crontab` for 8:00)
6. Telegram Bot: `send_digest()` via httpx + `TELEGRAM_BOT_TOKEN`

⚠️ Modal `@cron` moves to **D9** — cloud automation requires Modal deploy first
⚠️ Stuck: Langfuse → `LANGFUSE_HOST=http://localhost:3000`

**✅ Deliverable:**
```
uv run python -m pulse.scripts.run_digest → Telegram:
"Today in AI:
1. FastMCP 1M downloads
2. LangGraph streaming
3. Claude Code vs Cursor
[hot take] MCP = new HTTP"

localhost:3000 → trace visible
Prompt v2: +18% accuracy
```

**💼 Business:** KPI step 1 — 1 message instead of 3h monitoring (manual trigger on D7; automated @ D9).

🤔 **Question:** Why add Langfuse on D7 before Modal deploy on D9? What would you lose if you skipped observability until production?

---

## Buffer Day 1 (B1) — Review & Consolidate Phase 1

**Time:** 3.5h | **Trigger:** After Day 7

### Structure:
- **1h — Audit:** `docker compose up -d && uv run python -m pulse.main`. Fix top-1 bug. `uv sync`.
- **1h — Rubber Duck:** Explain one pattern in plain English (no code). Goal: explain *why*, not just *how*.
- **1h — Extension (optional):** See Deep Track in Adaptability Rules.
- **0.5h — Documentation:** Update CLAUDE.md. Record 2-3 min Loom.

### Checkpoint questions (write answers):
1. Which pattern was hardest?
2. What are you building that already works?
3. Did you copy anything without understanding it? → That's the topic for Rubber Duck.

### 🏆 MVP Level 1: PULSE Alpha
- Daily Telegram digest works (manual `run_digest` on D7; `@cron` cloud on D9)
- Can demo it and talk about it in an interview
- Achieved: "1 digest instead of 3h reading" (content KPI; automation completes on D9)

---

## PHASE 2: CONTENT FACTORY (Days 9–15)
### Content machine, 5 advanced patterns

---

### Day 9 — Modal Deploy + FastAPI (production infra)

**Time:** 4h | **Pattern:** (infra) | **Business:** PULSE lives in cloud 24/7

**Install:**
```
uv add modal fastapi uvicorn sqlalchemy>=2.0.40 psycopg2-binary pytest httpx langgraph-checkpoint-postgres
```

**Tasks:**
1. `modal setup` + `modal secret create pulse-secrets`
2. `@modal.asgi_app()` → wraps FastAPI
3. FastAPI endpoints: `GET /digest`, `POST /feedback`, `GET /stats`, `GET /sources/status`
4. PostgreSQL schema: `articles`, `digests`, `feedback` tables
5. `@modal.cron("0 8 * * *")` — morning digest to Telegram (moved from D7)
6. `pytest` for each endpoint
7. GitHub Actions CI: run tests on push
8. ⚠️ Open `:8000/docs` — Swagger UI. **Show this to the interviewer first.**

⚠️ `sqlalchemy>=2.0.40` + `psycopg2-binary` + `langgraph-checkpoint-postgres` — PostgresSaver deps (wired on D17)
⚠️ Stuck: PostgreSQL → `docker ps`, check port 5432

**✅ Deliverable:**
```
curl https://pulse--api.modal.run/digest → DigestItem[] from cloud
8:00 UTC Telegram digest via Modal @cron ✅

:8000/docs → Swagger ✅
GitHub Actions: green ✅
```

---

### Day 10 — FastMCP (advanced Tool use)

**Time:** 3.5h | **Pattern:** Tool use (advanced) — MCP protocol | **Business:** Standard tool protocol

**Install:**
```
uv add fastmcp>=2.0.0 mcp>=1.9.0
```

📖 **Concept:** MCP = standardized tool protocol. Agent discovers tools via protocol instead of hardcoded functions. Discovery + standardization = replaceable tools (swap Telegram for Slack without touching agent code).

**Tasks:**
1. Read 20 min: MCP protocol architecture
2. ⚠️ `from fastmcp import FastMCP` — NOT `from mcp.server.fastmcp import FastMCP` (old path!)
3. ⚠️ `langchain-mcp-adapters` already installed in Day 4a — use `MultiServerMCPClient`
4. FastMCP server: 5 tools — `search_articles`, `save_draft`, `send_telegram`, `approve_draft`, `get_digest_stats`
5. Deploy as separate `@modal.web_endpoint`
6. Day 2 agent now calls tools through MCP instead of direct functions

⚠️ Stuck: agent doesn't see MCP → check `FastMCP_URL` in `.env`

**✅ Deliverable:**
```
"Send digest to Telegram"
→ agent → MCP send_telegram
→ delivered ✅

2 Modal URLs live: FastAPI + FastMCP
```

🤔 **Question:** Why is MCP better than direct function calls? When is it overkill?

---

### Day 11 — Self-correction loop

**Time:** 4h | **Pattern:** Self-correction | **Business:** Quality drafts, not first drafts

📖 **Concept:** Second LLM call as critic. Threshold 0.7 = "good enough for human review" (0.9 loops forever, 0.5 ships junk). Max 3 iterations — diminishing returns. Next: VerifyNode (D12) → HITL (D13).

**Tasks:**
1. LinkedIn Post Generator: point-of-view, not summary
2. `CritiqueAgent`: checks `point_of_view`, `specificity`, `hook`
3. LangGraph: `generate → critique → cond_edge(score<0.7 → rewrite) → critique`
4. Max 3 iterations, `recursion_limit=5` for the loop
5. Log each iteration in Langfuse

⚠️ Stuck: loop doesn't terminate → check `cond_edge` and `recursion_limit`

**✅ Deliverable:**
```
"FastMCP reached 1M downloads"
Draft #1: score=0.51
Critique: "no personal opinion"
Draft #2: score=0.79 ✅
→ "MCP became the new HTTP…"
```

🤔 **Question:** Why threshold 0.7, not 0.9? What happens at 0.5? At 0.95?

---

### Day 12 — Self-verification (fact-check node)

**Time:** 3h | **Pattern:** Self-verification | **Business:** No rumors in the digest or drafts

📖 **Concept:** Extract claims → verify against Qdrant + Tavily → VERIFIED / UNVERIFIED / CONTRADICTED. Prevents delivery of bad facts, not generation of them. Runs **before** HITL — human never sees CONTRADICTED claims.

**Tasks:**
1. `VerifyNode`: `digest → extract_claims_llm() → for each claim: verify_against_qdrant + tavily_verify → VerificationResult`
2. `VerificationResult(claim, status: VERIFIED|UNVERIFIED|CONTRADICTED, evidence, source_url)`
3. `CONTRADICTED` → remove. `UNVERIFIED` → mark "[unverified]"
4. Wire into content pipeline: runs after self-correction (D11), before HITL (D13)
5. Log all verifications in Langfuse
6. `golden_digest.json` +2-3 entries

⚠️ Verification too slow → add `async parallel verify`

**✅ Deliverable:**
```
"Anthropic released Claude 5"
→ VerifyNode checks
→ Qdrant: not found
→ Tavily: not confirmed
→ CONTRADICTED → removed
Digest: 1 cleaner fact
```

🤔 **Question:** Why does self-verification ≠ full hallucination prevention? Give 3 claims that would pass unverified.

---

### Day 13 — Human-in-the-loop (Inngest pause)

**Time:** 3.5h | **Pattern:** Human-in-the-loop | **Business:** You control what gets published

**Install:**
```
uv add inngest>=0.3.0 redis>=5.0.0
```

📖 **Concept:** Inngest `waitForEvent` pauses the **entire** multi-step pipeline until approval — not polling. Correct order: generate → self-correct → verify → HITL → publish (stub). LinkedIn API not in stack — copy-paste from approved draft.

**Tasks:**
1. Inngest Content Pipeline: `step1: collect → step2: analyze → step3: generate+self-correct → step4: verify → step5: PAUSE(waitForEvent "approved", 24h timeout) → step6: publish_stub`
2. Redis: job status tracking
3. `GET /drafts`, `POST /approve/{id}` endpoints
4. `@modal.cron("0 9 * * 1,3,5")` — generate 3 draft slots/week (Mon/Wed/Fri)
5. ⚠️ LinkedIn publish = **stub** (`publish_stub` logs + saves `published_at` in DB) — no LinkedIn API in stack; copy-paste or add API in Deep Track
6. ⚠️ Fallback if Inngest is complex: `Modal @function(retries=3)` — same HITL pattern, simpler

⚠️ Stuck: Inngest dev → run `inngest dev` in a separate terminal

**✅ Deliverable:**
```
Draft created (verified ✅) →
Inngest PAUSE ⏸
GET /drafts → see draft
POST /approve/123 → ✅
Inngest continues → publish_stub (logged, ready to copy to LinkedIn)
```

🤔 **Question:** When is HITL mandatory vs when is self-correction + verification enough?

---

## Buffer Day 2 (B2) — Review & Consolidate Phases 1+2

**Time:** 3.5h | **Trigger:** After Day 15

Same structure as B1, but focus on Days 9–15 patterns.

**Checkpoint question:** "Which patterns from Phases 1+2 will you use in your next project?"

### 🏆 MVP Level 2: PULSE Beta
- LinkedIn posts with approval flow (verified before review)
- Verified digest
- Full content factory working

---

## PHASE 3: KNOWLEDGE & QUALITY (Days 17–21, D16 = slack)

---

### Day 14 — Advanced Routing (LightRAG + Neo4j)

**Time:** 4h | **Pattern:** Routing advanced | **Business:** Different questions, different sources

**Install:**
```
uv add lightrag-hku>=1.0.0 neo4j
```

📖 **Concept:** Intent classifier routes to live (Tavily) / archive (Qdrant+FlashRank) / graph (LightRAG). Multi-hop queries need graph traversal — vector search alone can't answer "what's connected to X through 2 hops?"

**Tasks:**
1. Neo4j Docker: `neo4j:5` image
2. LightRAG indexing of all collected articles (~$0.10 cost)
3. Upgrade Adaptive RAG Router: `today→Tavily | archive→Qdrant+FlashRank | relationships→LightRAG`
4. `test_router.py`: 3 queries × assert correct mode
5. `MOMENTUM_THRESHOLD=2` in dev (5 in prod)

⚠️ Neo4j OOM → add `-e NEO4J_dbms.memory.heap.max_size=512m`

**✅ Deliverable:**
```
"What's new about MCP today?" → Router: mode=live → Tavily
"Articles about FastMCP last month" → Router: mode=archive → Qdrant
"What's connected to LangGraph?" → Router: mode=graph → LightRAG → 4 articles
```

🤔 **Question:** How does the router decide a query is "multi-hop"? What if it's wrong?

---

### Day 15 — Composite Agent (Deep Dive)

**Time:** 4h | **Pattern:** Composite agent | **Business:** Automatic deep analysis

📖 **Concept:** Specialized subgraphs (Search → Research → Synthesis → FactCheck → Report), each with own State type. Better than one mega-agent: debuggable stages, different models per stage. Tradeoff: 5 LLM contexts = orchestration overhead.

**Tasks:**
1. `CompositeGraph`: `SearchSubgraph(Tavily×3+ArXiv) → ResearchSubgraph → SynthesisSubgraph → FactCheckSubgraph → ReportSubgraph`
2. Each = separate `StateGraph`
3. Mock trigger: `MOMENTUM_THRESHOLD=2` → run manually for testing
4. Output: `DeepDiveReport(topic, summary, sections[], sources[], linkedin_post, word_count)`

⚡ **Fast Track:** Replace with `Tavily×3 → Synthesis` without LightRAG

**✅ Deliverable:**
```
MOMENTUM=2 reached: "LangGraph 2.0 release"
→ Deep Dive launched
→ SearchSubgraph: 12 sources
→ SynthesisSubgraph: narrative
→ FactCheck: 2 claims verified
→ Report: 820 words ✅
```

🤔 **Question:** When is Composite better than one large agent? What's the overhead of a 5-subgraph chain?

---

### Day 16 — Slack (optional catch-up)

**Time:** 0–3.5h | **Pattern:** — | **Business:** Recover if behind schedule

Not a build day. Use if a prior day spilled over (especially D7, D9, D14, D17). Options:
- Finish unfinished deliverable from previous day
- Run B2 early if Phase 2 is complete
- Rest — D16 is intentionally unscheduled in the 21-day budget

---

### Day 17 — Research & Report p1 (eval infrastructure)

**Time:** 4h | **Pattern:** Research & Report (part 1) | **Business:** Measurable quality

📖 **Concept:** RAGAS measures faithfulness (no hallucinations), answer relevancy (on-topic), context recall (nothing missed). Requires `golden_digest.json` built since D3. CI gate = quality enforced, not vibes.

**Install:**
```
uv add ragas>=0.2.0 deepeval>=1.0.0
```

**Tasks:**
1. `golden_digest.json` ready (30+ evaluated digests, Days 3–15)
2. RAGAS: `faithfulness`, `answer_relevancy`, `context_recall` for digests
3. DeepEval: LinkedIn post quality (originality, value, opinion)
4. GitHub Actions: block merge if `avg_score < 0.75`
5. `/chat` endpoint with PostgresSaver + `session_id` (deps from D9: sqlalchemy + langgraph-checkpoint-postgres)
6. CORS stub for Next.js (full origins on D20)

⚠️ Stuck: RAGAS timeout → `max_concurrency=2`

**✅ Deliverable:**
```
python run_evals.py
→ faithfulness: 0.84 ✅
→ relevancy: 0.81 ✅
→ recall: 0.68 ⚠️ (GraphRAG needed!)

GET /chat "articles about LangGraph this week"
→ 5 found from archive
```

🤔 **Question:** What does faithfulness 0.84 actually mean? Can you fully trust RAGAS?

---

### Day 18 — Research & Report p2 (on-demand full)

**Time:** 3.5h | **Pattern:** Research & Report (full) | **Business:** 4-hour research in 8 minutes

📖 **Concept:** Research & Report activates ALL patterns in one request: Plan-Execute + Parallel + ReAct + FactCheck + Synthesis + HITL.

**Tasks:**
1. Research Orchestrator: `intent → Plan(5 queries) → Parallel Search → Analyze → FactCheck → Synthesize → Format(report+linkedin+quotes) → Inngest HITL pause`
2. Trigger keywords in chat: "research X", "write a report on Y", "deep dive into Z"

⚠️ Stuck: too slow → add streaming updates via SSE

**✅ Deliverable:**
```
"Research MCP ecosystem state in June 2026"
→ Planning: 5 queries
→ Parallel Search: 18 sources
→ FactCheck: 3 verifications
→ Inngest pause ⏸
→ approve
→ 1200 words + LinkedIn draft
```

🤔 **Question:** List all patterns from previous days that live inside this Research & Report request.

---

### Day 19 — Reflection (weekly meta-analysis)

**Time:** 3h | **Pattern:** Reflection | **Business:** PULSE self-improves

📖 **Concept:** Meta-learning from implicit signals (approved/rejected/ignored) — not explicit config. Closes the loop: gather → analyze → update Mem0 → next week automatically different. A dashboard shows data; Reflection *acts* on it.

**Tasks:**
1. `@modal.cron("0 10 * * 0")` — Sunday 10:00
2. `gather_week_data()`: 7 digests + approved/rejected posts + Langfuse metrics + RAGAS trend
3. `analyze_patterns()`: which topics ignored, which formats approved, where score dropped
4. `update_preferences()`: `m.add(new_weights)`
5. `generate_report()`: `ReflectionReport` → Telegram

⚡ **Fast Track:** Skip entirely

**✅ Deliverable:**
```
Sunday 10:00 Telegram:
"Week 1 report:
✅ Approved: LangGraph(3), MCP(4)
❌ Rejected: finance(2), crypto(1)
📈 Quality: 0.74 → 0.81
💡 Recommendation: ↑ priority MCP"

Mem0 updated automatically
```

🤔 **Question:** How does Reflection Agent differ from a regular analytics dashboard?

---

### Day 20 — Next.js UI (infra)

**Time:** 3.5h | **Pattern:** (infra) | **Business:** Approve from any device

**Install:**
```
npx create-next-app --typescript --tailwind
```

**Tasks:**
1. FastAPI: `CORSMiddleware(origins=["https://pulse.vercel.app"])`
2. Next.js: `DigestFeed`, `DraftInbox` (approve flow), `StatsPanel`
3. `session_id` in localStorage → passed to each request → backend reads from PostgresSaver
4. Vercel deploy

⚡ **Alternative:** Streamlit — 2h instead of 4h

⚠️ Stuck: CORS error → add Modal URL to origins list

**✅ Deliverable:**
```
pulse.vercel.app:
→ DigestFeed works
→ Approve draft ✅
→ fetch without CORS errors
```

---

### Day 21 — Final (packaging)

**Time:** 3h | **Pattern:** — | **Business:** Product ready for interview

**Tasks:**
1. README: ASCII architecture + Deploy Map
2. CLAUDE.md final revision: all 12+ subagents documented
3. Demo Script: 7 steps, 5 minutes (see `03_patterns_reference.md`)
4. Loom 4 min following Demo Script

**🤔 Final questions (write before Loom):**
> 1. Which 3 patterns will you use in your next project and why?
> 2. Explain Self-correction to a non-technical colleague — no jargon.
> 3. Starting over, what would you architect differently?

**✅ Deliverable:**
```
pulse.vercel.app ✅
GitHub README ✅
Demo Script passed ✅
Loom 4 min ✅
```

### 🏆 MVP Level 3: PULSE Production
- All 12 patterns
- Demo Script ready
- KPI achieved: 1 digest + 3 posts/week

---

## Adaptability Rules

| Situation | Action | Details |
|---|---|---|
| Day took 5+ hours | Carry over to buffer | If unfinished after 4.5h → note what's left, move to B1/B2/D16 |
| Behind by 2+ days | Fast Track | Skip D14, D15 full, D19. Replace D15 → Tavily×3→Synthesis. **Stop at D19** (skip D20–D21). Keeps 9/12 patterns. |
| Moving fast | Deep Track | D3: 5th source · D5: novelty-based depth · D11: 4th critique dimension · D14: LightRAG modes · D15: 6th subgraph |
| Stuck on Docker | Skip the service | In-memory alternative; return on buffer day |
| LightRAG too complex | Fast Track | Qdrant + multi-query instead |
| Next.js unfamiliar | Streamlit | 2h instead of 4h — functionally equivalent for demo |
| Inngest unclear | Modal fallback | `@function(retries=3)` — same HITL pattern |
| Neo4j OOM | AuraDB free tier | Or Qdrant multi-query |
