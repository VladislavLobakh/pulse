# PULSE — Agentic Patterns

Behavioral detail lives in [`docs/architecture/flows/*.mmd`](architecture/flows/). Pattern names and contracts below.

| Pattern | Role in PULSE | Contract | Flow |
|---|---|---|---|
| Tool use | Source agents call collectors / MCP tools | `ToolCall` | [`hn-collect.mmd`](architecture/flows/hn-collect.mmd) |
| ReAct loop | Generic engine (`patterns/react.py`): reason → act → observe → decide, driven per-source by a `ReActConfig` (**Implemented**, HN is the first source wired in via `agents/hn.py`) | `ReasonDecision`, `SourceBatchScore` | [`hn-collect.mmd`](architecture/flows/hn-collect.mmd) |
| Plan-and-Execute | Planning agent before scheduled digest runs | `ExecutionPlan` | [`daily-digest.mmd`](architecture/flows/daily-digest.mmd) |
| Routing | RAG router: live / archive / graph / research modes | `RouteDecision` | [`langgraph-orchestrator.mmd`](architecture/flows/langgraph-orchestrator.mmd) |
| Self-correction | Critique loop on digest and LinkedIn drafts (max 3) | `CritiqueResult` | [`content-pipeline.mmd`](architecture/flows/content-pipeline.mmd) |
| Parallel research | Concurrent source runners with failure isolation and normalized-URL dedup (**Implemented** in `patterns/parallel.py`) | `SourceOutput`, `SourceRunResult`, `ParallelRunResult` | [`parallel-collect.mmd`](architecture/flows/parallel-collect.mmd) |
| Per-item signal extraction | Bounded-concurrency per-item analyzer (`patterns/topic_signal.py`) over the research workflow's collected items (**Implemented**, wired by `workflows/research.py`) | `TopicSignal`, `TopicSignalResult` | [`research-workflow.mmd`](architecture/flows/research-workflow.mmd) |
| Self-verification | Fact-check claims before human review | `VerificationResult` | [`content-pipeline.mmd`](architecture/flows/content-pipeline.mmd) |
| Reflection | Weekly analysis updates user preferences | `ReflectionReport` | [`daily-digest.mmd`](architecture/flows/daily-digest.mmd) |
| Composite agent | Deep Dive: chained specialized subgraphs | `DeepDiveState` | [`langgraph-orchestrator.mmd`](architecture/flows/langgraph-orchestrator.mmd) |
| Human-in-the-loop | Pause for approve/edit before publish | `ContentReview` | [`content-pipeline.mmd`](architecture/flows/content-pipeline.mmd) |
| Persistence | Mem0 + PostgresSaver + Qdrant memory layers | `UserPreference` | [`daily-digest.mmd`](architecture/flows/daily-digest.mmd) |
| Research & Report | On-demand full research pipeline via chat | `ResearchReport` | [`langgraph-orchestrator.mmd`](architecture/flows/langgraph-orchestrator.mmd) |
