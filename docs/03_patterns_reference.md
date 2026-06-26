# PULSE — 12 Agentic Patterns Reference

## Architecture Overview

```
SCHEDULED RUN (every 12h)                   ON-DEMAND (via chat)
┌──────────────────────────┐              ┌────────────────────────────────────┐
│ 1. Planning Agent        │              │ Research & Report Agent             │
│    Plan-and-Execute      │              │ Plan→Search×5→Analyze→FactCheck    │
│    ExecutionPlan ────────┼──┐           │ →Synthesize→Format→[HITL]→Deliver  │
└──────────────────────────┘  │           └────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  2. Parallel Research — 5 Source Agents in MVP (6th = LinkedIn, Deep Track) │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐        │
│  │  HN  │ │ArXiv │ │  YT  │ │  TW  │ │  LI  │ │  NL  │        │
│  │React │ │React │ │React │ │React │ │React │ │React │ ← Tool  │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘        │
└──────────────────────────────────────────────────────────────────┘
           ↓ Orchestrator + Routing
┌──────────────────────────────────────────────────────────────────┐
│  3. Knowledge Layer                                              │
│  Qdrant(archive) ←── Router ──→ LightRAG+Neo4j(graph)           │
│                     Persistence: Mem0 + PostgresSaver            │
└──────────────────────────────────────────────────────────────────┘
           ↓
┌──────────────────────────────────────────────────────────────────┐
│  4. Content Generation                                           │
│  generate → [critique] ←── Self-correction loop (max 3)         │
│       ↓ score≥0.7                                               │
│  [verify claims] → CONTRADICTED removed → [final draft]         │
└──────────────────────────────────────────────────────────────────┘
           ↓
┌──────────────────────────────────────────────────────────────────┐
│  5. Human-in-the-Loop (Inngest)                                  │
│  [draft] → waitForEvent("approved", 24h) → [publish]            │
└──────────────────────────────────────────────────────────────────┘
           ↓ if approved
┌──────────────────────┐    ┌──────────────────────────┐
│  Deep Dive Agent     │    │  Weekly Reflection Agent  │
│  Composite pattern   │    │  @cron Sunday 10:00       │
│  momentum ≥5 → auto  │    │  → ReflectionReport       │
│  Search→Synth→Report │    │  → updates Mem0           │
└──────────────────────┘    └──────────────────────────┘
```

**MVP sources (Days 3–4b):** HN, ArXiv, YouTube, Twitter, Newsletter (5). LinkedIn agent = Deep Track extension on Day 3.

---

## Pattern Reference Table

| Pattern | In PULSE | LangGraph Implementation | Trigger | Pydantic Model |
|---|---|---|---|---|
| Tool use | Source Agents use FastMCP tools on every call | `@tool` + `StructuredTool`. MCP client calls FastMCP server. | Agent decides which tool based on intent and available tools | `ToolCall(name, args, result, latency_ms)` |
| ReAct loop | Each Source Agent: search → read → evaluate → decide | `create_agent(llm, tools)`. Graph: `reason_node → act_node → observe_node → cond_edge` | While `relevance_score < 0.6` or `articles_found < 3` | `ReactStep(thought, action, observation, score)` |
| Plan-and-Execute | Morning Planning Agent before each scheduled run | `planning_node → ExecutionPlan in State → Source Agents read plan` | Every `@modal.cron` run starts with planning | `ExecutionPlan(topics: list[str], sources: list[str], depth: Literal["shallow","deep"], priority_queries: list[str])` |
| Routing | Adaptive RAG Router for "Ask Your Feed" + Source Orchestrator | `route_node` with `conditional_edges → [tavily│qdrant│lightrag]` | Intent: today→Tavily, archive→Qdrant, graph→LightRAG, report→Research | `RouteDecision(mode: Literal["live","archive","graph","research"], confidence: float)` |
| Self-correction | Content Revision Loop for LinkedIn posts and digest | `generate → critique(score) → cond_edge: score<0.7 → rewrite → critique`. Max 3 loops | After `generate_node`. Critic checks: point_of_view, specificity, engagement | `CritiqueResult(score: float, issues: list[str], suggestions: list[str], iteration: int)` |
| Parallel research | 5 Source Agents in MVP (6th = LinkedIn, Deep Track) via LangGraph Send API | Map-reduce: `orchestrator → Send(agent, config) × N → reduce_node` | Every scheduled run. Deep Dive for parallel sources on one topic. | `AgentResult(source: str, articles: list[Article], latency_ms: int, status: str)` |
| Self-verification | Fact-Check Node after digest generation | `generate → extract_claims → verify_node(Qdrant + Tavily) → filter_node` | After every digest or Research Report generation. Before human review. | `VerificationResult(claim: str, status: Literal["VERIFIED","UNVERIFIED","CONTRADICTED"], evidence: str, source_url: str)` |
| Reflection | Weekly Reflection Agent — past week analysis | `ReflectionGraph: gather_week_data → analyze_patterns → update_preferences → report_node` | `@modal.cron("0 10 * * 0")` — every Sunday. Also manual `/reflect` endpoint. | `ReflectionReport(period: str, approved_topics: list[str], rejected_topics: list[str], quality_trend: float, recommendations: list[str])` |
| Composite agent | Deep Dive Agent: chain of specialized subgraphs | `CompositeGraph: Search→Research→Synthesis→FactCheck→Report`. Each = separate `StateGraph`. | `momentum_detector`: 5+ articles on one topic in 2 days → auto. Or manual trigger. | `DeepDiveState(topic, search_results, research_notes, synthesis, verified_claims, final_report)` |
| Human-in-the-loop | Inngest Content Pipeline: pause before publishing | `Inngest: waitForEvent("content/approved", timeout="24h")`. `LangGraph: interrupt_before=["publish_node"]` | After generate + critique + verify. User sees draft in Dashboard → approve/reject/edit | `ContentReview(draft_id: str, content: str, quality_score: float, fact_check_status: str, approved: bool)` |
| Persistence | Three levels: Mem0 + PostgresSaver + Qdrant | `after_turn_node → extract_facts → m.add()`. PostgresSaver in each StateGraph. Qdrant upsert. | Mem0: after approvals, rejections. PostgresSaver: every chat message. Qdrant: every new article. | `UserPreference(topic: str, weight: float, last_updated: datetime, source: Literal["approve","reject","explicit"])` |
| Research & Report | On-Demand Research via "Ask Your Feed" chat | `research_orchestrator → [plan→search×5→analyze→factcheck→synthesize→format] → Inngest review` | Keywords in chat: "research", "report on", "deep dive into". Or `/research` endpoint. | `ResearchReport(topic, executive_summary, sections: list[Section], sources: list[str], linkedin_post: str, confidence: float)` |

---

## Each Pattern in Depth

---

### 1. Tool use — FastMCP

**Concept:** Agent doesn't call functions directly — it discovers and calls tools through the MCP protocol. Tools become replaceable and standardizable.

**Flow:**
```
Agent receives user request
  → decides which tool to call (by intent)
  → calls FastMCP server via MCP protocol
  → gets typed result
  → decides next action
```

**Implementation:**
```python
from fastmcp import FastMCP  # NOT from mcp.server.fastmcp

mcp = FastMCP("PULSE Tools")

@mcp.tool()
def search_articles(query: str, date_range: str = "24h") -> list[Article]:
    """Search collected articles by query"""
    return qdrant_search(query, date_range)

@mcp.tool()
def send_telegram(chat_id: str, text: str) -> bool:
    """Send message to Telegram"""
    return telegram_bot.send_message(chat_id, text)

@mcp.tool()
def approve_draft(draft_id: str) -> ContentReview:
    """Approve a content draft for publishing"""
    return inngest_client.send_event("content/approved", {"draft_id": draft_id})
```

**Integration with LangGraph:**
```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent

client = MultiServerMCPClient({
    "pulse": {"url": "https://pulse--mcp.modal.run/mcp", "transport": "http"}
})
tools = await client.get_tools()
agent = create_agent("claude-sonnet-4-6", tools)
```

**Interview phrase:** *"Every PULSE tool is a typed FastMCP endpoint. The agent discovers tools via the MCP protocol rather than calling functions directly — this makes the toolset replaceable and standardizable."*

---

### 2. ReAct loop

**Concept:** Agent reasons aloud before acting. Reason → Act → Observe → repeat. Stops when the goal is met, not after a fixed number of steps.

**Flow:**
```
Reason: "User wants MCP articles. Search HN and ArXiv."
  Act: tavily_search("MCP site:news.ycombinator.com")
  Observe: 3 results, relevance_score=0.87 → sufficient
→ STOP

Reason: "Need more tech depth. Also check ArXiv."
  Act: tavily_search("MCP arxiv 2026")
  Observe: 1 paper found, score=0.61 → marginal
→ STOP (recursion_limit protection)
```

**Implementation:**
```python
from langchain.agents import create_agent  # NOT langgraph.prebuilt!

agent = create_agent(
    model="claude-sonnet-4-6",
    tools=[tavily_search, score_article, parse_pdf],
)

graph = StateGraph(PulseState)
graph.add_node("agent", agent)
graph.compile(recursion_limit=10)  # protection against infinite loop
```

**Interview phrase:** *"Each Source Agent uses a ReAct loop — it reasons about what to search, acts by calling Tavily, observes the relevance score, and decides whether to continue or stop. The agent thinks, not just queries."*

---

### 3. Plan-and-Execute

**Concept:** Planning is separated from execution. The planner decides WHAT to do at a high level; executors figure out HOW. This allows adapting the plan without restarting the whole pipeline.

**Flow:**
```
@modal.cron("0 8,20 * * *")
  ↓
planning_node(yesterday_digest, mem0_profile, trending_topics)
  ↓ ExecutionPlan(Pydantic)
  topics: ["LangGraph v2", "FastMCP growth"]
  depth: "deep" (new topic detected)
  priority_sources: ["arxiv", "hn"]
  ↓
Source Agents read ExecutionPlan from PulseState
  → adapt queries to plan, not hardcoded template
```

**Implementation:**
```python
def planning_node(state: PulseState) -> PulseState:
    if not state.get("history"):
        plan = ExecutionPlan(
            topics=DEFAULT_TOPICS,
            depth="shallow",
            priority_sources=["hn", "newsletter"]
        )
    else:
        plan = llm.with_structured_output(ExecutionPlan).invoke(
            f"Yesterday: {state['yesterday_digest']}\n"
            f"Profile: {mem0.search('interests')}\n"
            f"Trending: {get_trending()}\n"
            "Create today's collection plan."
        )
    return {**state, "execution_plan": plan}
```

**Interview phrase:** *"PULSE starts every run with a Planning Agent that analyzes yesterday's content and creates an ExecutionPlan — agents don't use hardcoded queries, they execute the plan."*

---

### 4. Routing (Adaptive RAG)

**Concept:** Different questions require different data sources. An intent classifier routes each query to the right source.

**Flow:**
```
"What's new about MCP today?"    → mode=live    → Tavily (real-time)
"Articles about FastMCP in May"  → mode=archive → Qdrant + FlashRank
"What's connected to LangGraph?" → mode=graph   → LightRAG (multi-hop)
"Research MCP ecosystem"         → mode=research → Research&Report Agent
```

**Implementation:**
```python
def route_node(state: PulseState) -> str:
    decision = llm.with_structured_output(RouteDecision).invoke(
        f"Query: {state['query']}\nChoose routing mode."
    )
    return decision.mode  # "live" | "archive" | "graph" | "research"

graph.add_conditional_edges("route", route_node, {
    "live": "tavily_search",
    "archive": "qdrant_search",
    "graph": "lightrag_search",
    "research": "research_orchestrator",
})
```

**Interview phrase:** *"PULSE uses an Adaptive RAG Router with 3 modes: live (Tavily), archive (Qdrant+FlashRank), and graph (LightRAG multi-hop). One query, the right source."*

---

### 5. Self-correction loop

**Concept:** Agent generates a draft, critiques it with a separate LLM call, and rewrites based on the critique. Loops until quality threshold or max iterations.

**Flow:**
```
generate_node() → LinkedInDraft
  ↓
critique_node() → CritiqueResult(score=0.51,
  issues=["no personal opinion", "generic phrases"])
  ↓
if score < 0.7 AND iteration < 3:
  → rewrite_node(draft + critique)  ← loop back
  ↓
critique_node() → CritiqueResult(score=0.79) ✅
  ↓
→ human_review_node (Inngest pause)
```

**Implementation:**
```python
def should_rewrite(state: PulseState) -> str:
    critique = state["last_critique"]
    if critique.score < 0.7 and critique.iteration < 3:
        return "rewrite"
    return "human_review"

graph.add_conditional_edges("critique", should_rewrite, {
    "rewrite": "rewrite_node",
    "human_review": "hitl_node",
})
graph.compile(recursion_limit=5)  # safety for the inner loop
```

**Interview phrase:** *"The self-correction loop improved LinkedIn post quality from 0.51 to 0.79 in 2 iterations — the agent critiques and rewrites its own output before it reaches me."*

---

### 6. Parallel research

**Concept:** Multiple agents run simultaneously, each on its own source. Results are collected via map-reduce. Error isolation: one agent failing doesn't stop others.

**Flow:**
```
Orchestrator
  → Send(hn_agent, config)      ─┐
  → Send(arxiv_agent, config)   ─┤ parallel
  → Send(youtube_agent, config) ─┤ LangGraph Send API
  → Send(twitter_agent, config) ─┘
           ↓
reduce_node: aggregate all AgentResult[], deduplicate, rank
```

**Implementation:**
```python
from langgraph.types import Send

def orchestrator_node(state: PulseState) -> list[Send]:
    plan = state["execution_plan"]
    return [
        Send("source_agent", {"source": src, "plan": plan})
        for src in plan.priority_sources
    ]

# Each source_agent has error isolation:
async def source_agent_node(state: SourceState) -> SourceState:
    try:
        articles = await collect_from_source(state["source"])
        return {**state, "articles": articles, "status": "ok"}
    except Exception as e:
        return {**state, "articles": [], "status": f"error: {e}"}
```

**Interview phrase:** *"5 source agents run in parallel via LangGraph Send API (HN, ArXiv, YouTube, Twitter, Newsletter). If YouTube fails, HN and ArXiv continue. 17 articles in 48 seconds instead of 3+ minutes sequentially."*

---

### 7. Self-verification

**Concept:** Agent doesn't trust its own generated content. Verifies each factual claim against original sources before presenting to the user.

**Flow:**
```
digest_draft → extract_claims_node()
  claims: ["Anthropic released Claude 5", "LangGraph now supports streaming"]
  ↓
verify_node(claim, qdrant_sources, tavily_search)
  "Anthropic released Claude 5" → Qdrant: not found, Tavily: not confirmed
    → CONTRADICTED → remove from digest
  "LangGraph now supports streaming" → found in 3 sources
    → VERIFIED → keep
  ↓
filter_node: CONTRADICTED removed | UNVERIFIED tagged "[unverified]"
```

**Implementation:**
```python
def verify_claim(claim: str, sources: list[str]) -> VerificationResult:
    qdrant_evidence = qdrant_search(claim, top_k=3)
    tavily_evidence = tavily_search(claim + " confirmed 2026")

    result = llm.with_structured_output(VerificationResult).invoke(
        f"Claim: {claim}\n"
        f"Qdrant sources: {qdrant_evidence}\n"
        f"Tavily search: {tavily_evidence}\n"
        "Is this claim VERIFIED, UNVERIFIED, or CONTRADICTED?"
    )
    return result
```

**Interview phrase:** *"The VerifyNode checks every fact in the digest against Qdrant and Tavily. CONTRADICTED claims are automatically removed — PULSE doesn't spread rumors."*

---

### 8. Reflection

**Concept:** Agent analyzes its own behavior over a past period and updates its preferences model. Closed-loop self-improvement without manual reconfiguration.

**Flow:**
```
@modal.cron("0 10 * * 0")  ← every Sunday
  ↓
gather_week_data():
  7 digests + approved/rejected posts + Langfuse metrics + RAGAS trend
  ↓
analyze_patterns():
  approved_topics: ["LangGraph", "Claude Code", "FastMCP"]
  rejected_topics: ["finance", "crypto"]
  low_quality_days: [Wednesday: avg_score=0.61]
  ↓
update_preferences(): m.add(new_weights, user_id="me")
generate_report() → ReflectionReport → Telegram Sunday
```

**Implementation:**
```python
def analyze_patterns_node(state: ReflectionState) -> ReflectionState:
    report = llm.with_structured_output(ReflectionReport).invoke(
        f"7 digests: {state['digests']}\n"
        f"Approved: {state['approved_posts']}\n"
        f"Rejected: {state['rejected_posts']}\n"
        f"RAGAS trend: {state['ragas_metrics']}\n"
        "Analyze patterns and make recommendations."
    )
    # Update Mem0 with new weights
    for topic in report.approved_topics:
        mem0.add(f"user prefers content about {topic}", user_id="me")
    return {**state, "report": report}
```

**Interview phrase:** *"Every Sunday, the Reflection Agent analyzes the week — which topics I approved, rejected, and where quality dropped — then updates Mem0. Next week is automatically more precise."*

---

### 9. Composite agent (Deep Dive)

**Concept:** A chain of specialized subgraphs, each doing one thing well. State flows between them. More controllable and debuggable than one large agent.

**Flow:**
```
momentum_detector: 5+ articles on same topic in 2 days
  ↓ trigger Deep Dive
SearchSubgraph(Tavily×3 + ArXiv)
  ↓ search_results[]
ResearchSubgraph(analyze each source)
  ↓ research_notes[]
SynthesisSubgraph(combine into narrative)
  ↓ synthesis
FactCheckSubgraph(verify key claims)
  ↓ verified_synthesis
ReportSubgraph(format: report + LinkedIn + quotes)
  ↓ DeepDiveReport
```

**Implementation:**
```python
# Each subgraph is a separate StateGraph
search_graph = StateGraph(SearchState)
research_graph = StateGraph(ResearchState)
synthesis_graph = StateGraph(SynthesisState)

# CompositeGraph chains them
composite = StateGraph(DeepDiveState)
composite.add_node("search", search_graph.compile())
composite.add_node("research", research_graph.compile())
composite.add_node("synthesis", synthesis_graph.compile())
composite.add_edge("search", "research")
composite.add_edge("research", "synthesis")
```

**Interview phrase:** *"The Deep Dive Composite Agent chains 5 specialized subgraphs. When a topic reaches momentum threshold, it automatically produces an 800-word analysis — each subgraph does one thing and passes clean state to the next."*

---

### 10. Human-in-the-loop

**Concept:** Not everything should be automated. Some decisions — especially public content — require human review and approval. System pauses and waits.

**Flow:**
```
generate + self-correct + verify → final draft
  ↓
Inngest: step.waitForEvent("content/approved", timeout="24h")
  ↓ PAUSED — waiting for human
  User opens Dashboard → reads draft → edits if needed → clicks Approve
  ↓ event fires
Inngest continues: step5 → publish to LinkedIn + Telegram
```

**Implementation:**
```python
@inngest_client.create_function(
    fn_id="content-pipeline",
    trigger=inngest.TriggerEvent(event="content/ready"),
)
async def content_pipeline(ctx, step):
    articles = await step.run("collect", collect_sources)
    draft = await step.run("generate", lambda: generate_post(articles))
    corrected = await step.run("self_correct", lambda: self_correction_loop(draft))
    verified = await step.run("verify", lambda: fact_check(corrected))

    # Human review pause
    approval = await step.wait_for_event(
        "content/approved",
        event="content/approved",
        timeout="24h",
    )
    await step.run("publish", lambda: publish(verified, approval))
```

**Interview phrase:** *"Inngest pauses the pipeline and waits up to 24 hours for my approval. Automation handles generation and quality; I control what gets published."*

---

### 11. Persistence (3 memory levels)

**Concept:** Different types of memory serve different time horizons. Using one store for everything creates either slow retrieval or data loss.

| Level | Store | What | Horizon |
|---|---|---|---|
| Instant | PostgresSaver | Dialogue history, session state | Current conversation |
| Medium-term | Mem0 | Preferences, approved topics, interests | Cross-session |
| Long-term | Qdrant | All articles, digests, reports | All time |

**Implementation:**
```python
# After each interaction — update Mem0
def after_turn_node(state: PulseState) -> PulseState:
    facts = extract_facts_llm(state["messages"])
    for fact in facts:
        mem0.add(fact, user_id="me")
    return state

# Before ranking — consult Mem0
def rank_articles(articles: list[Article]) -> list[Article]:
    preferences = mem0.search("content preferences", user_id="me")
    return flashrank_rerank(articles, context=preferences)

# Store everything in Qdrant with upsert
def ingest_article(article: Article):
    embedding = openai_embed(article.content)
    qdrant.upsert(  # NOT delete + recreate
        collection_name="pulse_articles",
        points=[PointStruct(id=article.id, vector=embedding, payload=article.dict())]
    )
```

**Interview phrase:** *"Three memory levels: Mem0 for preferences and interests, PostgresSaver for dialogue history, Qdrant for all documents. Each optimized for its time horizon."*

---

### 12. Research & Report

**Concept:** The final form — combines all 11 previous patterns in one on-demand request. User asks a question, system does full research and delivers a report.

**Flow:**
```
User: "Research MCP ecosystem state June 2026"
  ↓
intent_classifier → mode="research"   ← Routing
  ↓
Research Planning:
  queries: ["MCP adoption 2026", "FastMCP vs alternatives", "MCP in production"]
  ← Plan-and-Execute
  ↓
Parallel Search × 5   ← Parallel research
Each query → ReAct loop per result   ← ReAct
  ↓
Synthesis → FactCheck   ← Self-verification
  ↓
Self-correction on report draft   ← Self-correction
  ↓
Inngest: waitForEvent("report/approved")   ← Human-in-the-loop
  ↓
Deliver: Markdown report + LinkedIn summary + key quotes
Saved to Qdrant + Mem0 updated   ← Persistence
```

**Trigger keywords:** "research", "report on", "deep dive", "what is X", `/research` endpoint

**Interview phrase:** *"Research & Report combines all 12 patterns in one request: Plan-Execute routes the queries, Parallel Search runs 5 simultaneous searches, FactCheck verifies claims, Self-correction improves the draft, and HITL gives me final control before delivery. 8 minutes instead of 4 hours."*

---

## Pattern Introduction Order (pedagogical sequence)

```
Day 1  → Tool use          (foundation: without tools, nothing else works)
Day 2  → ReAct             (builds on Tool use: tools + reasoning)
Day 3  → Parallel (asyncio)(natural next step: multiple agents)
Day 4a → Orchestration     (scale parallel to LangGraph State)
Day 5  → Plan-and-Execute  (makes sense once there's something to plan)
Day 6  → Persistence       (memory needs history to remember)
Day 10 → Tool use advanced (MCP upgrade of Day 1 Tool use)
Day 11 → Self-correction   (content to correct appears only after LinkedIn gen)
Day 12 → Self-verification (verify before human review — matches architecture diagram)
Day 13 → HITL              (logical after verify: human approves clean draft)
Day 14 → Routing advanced  (GraphRAG routing after basic routing on Day 4a)
Day 15 → Composite agent   (uses all previous patterns inside)
Day 17 → Research & Report (final form: all patterns in one request)
Day 19 → Reflection        (needs data from all previous days to analyze)
```

---

## Demo Script (Interview — 7 steps, 5 minutes)

| Step | Action | Pattern + What to say |
|---|---|---|
| 1 | Show Telegram 8:00 digest | [Persistence + Plan-Execute] "Every morning PULSE analyzes yesterday's content, creates an execution plan, and runs 5 source agents in parallel. Here's the result — 5 insights in 52 seconds instead of 3 hours." |
| 2 | Show ReAct loop in terminal logs | [ReAct] "Here are the agent logs: Reason → Act(tavily) → Observe(score=0.87) → stop. The agent decided when enough was enough — not just a query." |
| 3 | Show self-correction 2 iterations | [Self-correction] "Draft #1 scored 0.51. CritiqueAgent found: no personal opinion. Draft #2 scored 0.79 ✅. The pattern improved quality in 2 iterations." |
| 4 | Show fact-check removing a claim | [Self-verification] "VerifyNode checked every fact against Qdrant + Tavily. One claim was CONTRADICTED and automatically removed — before I ever saw the draft." |
| 5 | Show Inngest approve flow | [HITL] "Inngest waits up to 24 hours for my approval. I see the verified draft, edit if needed, hit Approve — then publish_stub runs." |
| 6 | Show LightRAG multi-hop | [Routing advanced] "Three different question types — three different sources. Today's news → Tavily. Archive → Qdrant. Connections → LightRAG. Here's the graph: MCP → FastMCP → LangGraph → Claude Code." |
| 7 | Show RAGAS + Reflection | [Research&Report + Reflection] "RAGAS faithfulness 0.84. Every Sunday, Reflection Agent analyzes the week and updates Mem0 — next week is automatically more precise. Closed learning loop." |
