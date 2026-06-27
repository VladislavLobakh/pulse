# PULSE — Architecture (C4)

C4 governance: diagram tools, depth policy, containers, flows, and update rules. Agent coding
rules (imports, conventions, module layout) → [`CLAUDE.md`](../CLAUDE.md).

Diagrams live in [`docs/architecture/`](architecture/). Pattern names and Pydantic contracts →
[`patterns.md`](patterns.md).

## Current vs target

**Implemented today:** Agent Runtime (HN collector via Tavily), Tavily external integration.

**Target (Planned):** remaining containers and flows in `Container_Target` view — see table below.

## Tool responsibility — no overlap, no drift

| Tool | Owns | Files |
|---|---|---|
| **Structurizr DSL** | *Structure* — C4 **L1 Context** + **L2 Container** | [`architecture/workspace.dsl`](architecture/workspace.dsl) |
| **Mermaid** | *Behavior* — sequence & flowchart (pipelines, LangGraph graphs) | [`architecture/flows/*.mmd`](architecture/flows/) |

The two **never describe the same thing**. Structurizr answers *"what are the parts and how
are they wired"*; Mermaid answers *"what happens, in what order"*. A box never appears in
both as the same fact, so they cannot drift apart.

## Depth policy

- **L1 Context** and **L2 Container** — always, in Structurizr.
- **L3 Component / L4 Code — not used yet.** The five source agents
  (HN / ArXiv / YouTube / Newsletter / Twitter) run **in-process** inside the *Agent Runtime*
  container, so they are *components*, not containers — they appear only in Mermaid flows.
- **Trigger to introduce L3 later:** when a single container's behavioral flow exceeds
  ~20 nodes, or that container gains independently meaningful sub-modules worth their own
  view. Until then, adding L3 is over-engineering for a solo project.

## C4 model for PULSE

**Person** — a human actor (`User`).

**Software System (external)** — something PULSE talks to but does not own:
Tavily, OpenRouter, ArXiv, YouTube, RSS Newsletters, Twitter/X, Telegram, LinkedIn, Inngest, Mem0 Cloud.

**Container** — a **separately runnable / deployable process or data store** that PULSE owns.

> **Boundary rule:** a new *container* = a new separately runnable process or data store.
> A new *source agent, graph node, or pipeline step* inside the Agent Runtime is **not** a
> container — it is a (deferred) component and changes only a Mermaid flow.

### Containers (L2)

| Container | Tech | Local / Deploy | Status |
|---|---|---|---|
| Agent Runtime (collectors + agents + orchestrator) | Python / LangGraph | `uv run` (CLI) | **Implemented** (HN collector only) |
| FastAPI Core | Modal `@asgi_app` | `https://pulse--api.modal.run` | Planned |
| FastMCP Server | Modal `@web_endpoint` | `https://pulse--mcp.modal.run` | Planned |
| Digest Scheduler | Modal `@cron` 08:00 | daily 08:00 UTC | Planned |
| Reflection Scheduler | Modal `@cron` Sun | Sun 10:00 UTC | Planned |
| Dashboard | Next.js / Vercel | `https://pulse.vercel.app` | Planned |
| Qdrant | Vector DB | `localhost:6333` | Planned |
| PostgreSQL | Postgres 16 | `localhost:5432` | Planned |
| Neo4j + LightRAG | Neo4j 5 / LightRAG | `localhost:7474` / `7687` | Planned |
| Redis | Redis | `localhost:6379` | Planned |
| Langfuse | Langfuse | `localhost:3000` | Planned |

This table **must** match the containers in `workspace.dsl`.

## Behavioral flows (Mermaid)

### Implemented

**HN collect** — [`architecture/flows/hn-collect.mmd`](architecture/flows/hn-collect.mmd)

```bash
uv run python -m pulse.agents.hn_agent
# or
uv run python -m pulse.main
```

Preview locally:

```bash
npx @mermaid-js/mermaid-cli -i docs/architecture/flows/hn-collect.mmd -o /tmp/hn-collect.svg
```

### Target (Planned)

[`daily-digest.mmd`](architecture/flows/daily-digest.mmd) ·
[`langgraph-orchestrator.mmd`](architecture/flows/langgraph-orchestrator.mmd) ·
[`content-pipeline.mmd`](architecture/flows/content-pipeline.mmd)

## Creation rules

**Structurizr (`workspace.dsl`):**
- One workspace, `!identifiers hierarchical`.
- Identifiers `camelCase`; human-readable names in the element title.
- Every element carries exactly one of `Implemented` / `Planned`. Data stores also carry `Database`.
- Every relationship is `source -> dest "verb phrase" "technology" "Implemented|Planned"`.
- Three views only: `Context`, `Container_Now` (Planned excluded), `Container_Target` (all).
- Max ~20 elements per view — past that, see the L3 trigger above.

**Mermaid (`flows/*.mmd`):**
- One flow per file, `kebab-case.mmd`, with a `--- title: … ---` header.
- Each file states `(current / Implemented)` or `(target / Planned)` in its title.
- ≤ ~20 nodes per diagram.

## Update rules

Diagrams are updated **in the same commit as the code** that adds or changes the feature.

1. **New external integration** (new API/SaaS) → add a `softwareSystem` to the model
   (shows in `Context`) + update the relevant Mermaid flow.
2. **New container** (new runnable process or data store — see the table) → add to the model;
   it appears in `Container_Target`. When it actually lands, flip its tag
   `Planned → Implemented` so it enters `Container_Now` automatically.
3. **New in-process agent / node / pipeline step** → **no L2 change**; update or add the
   matching Mermaid flow only.
4. **Status flip** when a container lands: flip the container's element tag **and every
   relationship tag on its edges** from `Planned → Implemented`. Both must change or
   `Container_Now` shows the container as a disconnected island with no edges.
5. **Removed / renamed** element → update the DSL and every Mermaid flow referencing it.
   Run two greps before committing: one for the DSL identifier (`grep -r "<camelCaseId>" docs/architecture/*.dsl`)
   and one for the human-readable name used in `.mmd` participant labels
   (`grep -r "<Element Title>" docs/architecture/flows/`).
6. **Quality gate:** if a Container view passes ~20 elements, revisit the depth policy
   (introduce L3) instead of cramming the view.

## Rendering

**Structurizr** (parses + validates on load):

```bash
docker run --rm -p 8081:8080 \
  -v "$PWD/docs/architecture:/usr/local/structurizr" structurizr/lite
# open http://localhost:8081 → Context · Container_Now · Container_Target
```

**Mermaid** — GitHub renders fenced ` ```mermaid ``` ` blocks inside `.md` files natively.
Standalone `.mmd` files are displayed as plain text on GitHub — use the CLI or VS Code
extension to preview them locally:

```bash
npx @mermaid-js/mermaid-cli -i docs/architecture/flows/daily-digest.mmd -o /tmp/out.svg
```
