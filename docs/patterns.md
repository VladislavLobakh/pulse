# PULSE — Agentic Patterns

Behavioral detail lives in [`docs/architecture/flows/*.mmd`](architecture/flows/). Pattern names and Pydantic contracts below.

| Pattern | Role in PULSE | Pydantic model | Flow |
|---|---|---|---|
| Tool use | Source agents call collectors / MCP tools | `ToolCall` | [`hn-collect.mmd`](architecture/flows/hn-collect.mmd) |
| ReAct loop | Source agent: search → read → evaluate → decide | `ReactStep` | [`langgraph-orchestrator.mmd`](architecture/flows/langgraph-orchestrator.mmd) |
| Plan-and-Execute | Planning agent before scheduled digest runs | `ExecutionPlan` | [`daily-digest.mmd`](architecture/flows/daily-digest.mmd) |
| Routing | RAG router: live / archive / graph / research modes | `RouteDecision` | [`langgraph-orchestrator.mmd`](architecture/flows/langgraph-orchestrator.mmd) |
| Self-correction | Critique loop on digest and LinkedIn drafts (max 3) | `CritiqueResult` | [`content-pipeline.mmd`](architecture/flows/content-pipeline.mmd) |
| Parallel research | Orchestrator runs multiple source agents in parallel | `AgentResult` | [`daily-digest.mmd`](architecture/flows/daily-digest.mmd) |
| Self-verification | Fact-check claims before human review | `VerificationResult` | [`content-pipeline.mmd`](architecture/flows/content-pipeline.mmd) |
| Reflection | Weekly analysis updates user preferences | `ReflectionReport` | [`daily-digest.mmd`](architecture/flows/daily-digest.mmd) |
| Composite agent | Deep Dive: chained specialized subgraphs | `DeepDiveState` | [`langgraph-orchestrator.mmd`](architecture/flows/langgraph-orchestrator.mmd) |
| Human-in-the-loop | Pause for approve/edit before publish | `ContentReview` | [`content-pipeline.mmd`](architecture/flows/content-pipeline.mmd) |
| Persistence | Mem0 + PostgresSaver + Qdrant memory layers | `UserPreference` | [`daily-digest.mmd`](architecture/flows/daily-digest.mmd) |
| Research & Report | On-demand full research pipeline via chat | `ResearchReport` | [`langgraph-orchestrator.mmd`](architecture/flows/langgraph-orchestrator.mmd) |
