workspace "PULSE" "AI Intelligence & Content Factory — C4 structural model (L1 Context + L2 Container)" {

    !identifiers hierarchical

    # ----------------------------------------------------------------------
    # MODEL
    #   Tag every element/relationship with exactly one of: Implemented | Planned
    #   "Implemented" = exists in the codebase today. Flip Planned -> Implemented
    #   when a container/integration actually lands (see docs/architecture.md).
    # ----------------------------------------------------------------------
    model {

        user = person "User" "Reads the morning digest, approves LinkedIn drafts." "Implemented"

        # --- External systems (L1 Context) ---
        tavily       = softwareSystem "Tavily"            "Web/search API for article discovery."          "External,Implemented"
        openrouter   = softwareSystem "OpenRouter"        "LLM gateway (Claude / GPT / Gemini fallback)."  "External,Planned"
        arxiv        = softwareSystem "ArXiv"             "Research paper source."                          "External,Planned"
        youtube      = softwareSystem "YouTube"           "Video transcripts source."                       "External,Planned"
        newsletters  = softwareSystem "RSS Newsletters"   "Latent Space, Simon Willison, etc."              "External,Planned"
        telegram     = softwareSystem "Telegram"          "Digest + reflection delivery (Bot API)."         "External,Planned"
        linkedin     = softwareSystem "LinkedIn"          "Publish target for generated posts."             "External,Planned"
        inngest      = softwareSystem "Inngest"           "Durable async + human-in-the-loop pauses."       "External,Planned"
        mem0cloud    = softwareSystem "Mem0 Cloud"        "Optional hosted profile-memory tier."            "External,Planned"
        twitter      = softwareSystem "Twitter/X"         "AI community discussions and announcements."     "External,Planned"

        # --- The system (L2 Container) ---
        pulse = softwareSystem "PULSE" "Personal AI intelligence & content factory." {

            !adrs decisions adrtools

            agentRuntime = container "Agent Runtime" "Collectors, source agents and the LangGraph orchestrator. Source agents (HN/ArXiv/YouTube/Newsletter/Twitter) are in-process components here — not separate containers." "Python / LangGraph" "Implemented"

            fastapiCore  = container "FastAPI Core"        "REST entrypoint that invokes agent pipelines on demand." "Modal @asgi_app"       "Planned"
            fastmcpSrv   = container "FastMCP Server"       "Exposes PULSE collectors as standardized MCP tools."    "Modal @web_endpoint"   "Planned"
            digestCron   = container "Digest Scheduler"     "Daily 08:00 UTC digest job."                            "Modal @cron"           "Planned"
            reflectCron  = container "Reflection Scheduler" "Weekly Sunday reflection job."                          "Modal @cron"           "Planned"
            dashboard    = container "Dashboard"            "DigestFeed + DraftInbox approve flow."                  "Next.js / Vercel"      "Planned"

            qdrant       = container "Qdrant"               "Vector store for article embeddings."                   "Vector DB"             "Planned,Database"
            postgres     = container "PostgreSQL"           "Drafts, app state, LangGraph checkpoints."              "PostgreSQL 16"         "Planned,Database"
            neo4j        = container "Neo4j + LightRAG"      "Knowledge graph for multi-hop queries."                 "Neo4j 5 / LightRAG"    "Planned,Database"
            redis        = container "Redis"                "Queue/cache backing async + HITL."                      "Redis"                 "Planned,Database"
            langfuse     = container "Langfuse"             "LLM tracing & observability."                           "Langfuse"              "Planned"
        }

        # --- Relationships ---
        user -> pulse.agentRuntime "Runs collectors from the CLI"        "uv run"          "Implemented"
        user -> pulse.dashboard    "Reads digest, approves drafts"            "HTTPS"           "Planned"

        pulse.agentRuntime -> tavily       "Searches articles via"            "HTTPS / SDK"     "Implemented"
        pulse.agentRuntime -> openrouter   "Calls LLM via"                    "HTTPS"           "Planned"
        pulse.agentRuntime -> arxiv        "Fetches papers from"              "HTTPS"           "Planned"
        pulse.agentRuntime -> youtube      "Fetches transcripts from"         "HTTPS"           "Planned"
        pulse.agentRuntime -> newsletters  "Fetches feeds from"               "RSS"             "Planned"
        pulse.agentRuntime -> linkedin     "Publishes posts to (stub)"        "HTTPS"           "Planned"
        pulse.agentRuntime -> mem0cloud    "Reads/writes profile (optional)"  "HTTPS"           "Planned"
        pulse.agentRuntime -> twitter      "Fetches AI discussions from"      "HTTPS"           "Planned"

        pulse.agentRuntime -> pulse.qdrant    "Upserts embeddings"            "gRPC"            "Planned"
        pulse.agentRuntime -> pulse.neo4j     "Indexes knowledge graph"       "Bolt"            "Planned"
        pulse.agentRuntime -> pulse.langfuse  "Sends traces"                  "HTTPS"           "Planned"

        pulse.dashboard   -> pulse.fastapiCore "Calls REST API"               "HTTPS / JSON"    "Planned"
        pulse.fastapiCore -> pulse.agentRuntime "Invokes agent pipelines"     "in-process"      "Planned"
        pulse.fastapiCore -> pulse.postgres     "Persists drafts & state"     "SQL"             "Planned"
        pulse.fastapiCore -> inngest            "Enqueues HITL pause"          "HTTPS"           "Planned"
        pulse.fastmcpSrv  -> pulse.agentRuntime "Wraps collectors as tools"   "in-process"      "Planned"
        inngest           -> pulse.redis        "Backs durable steps"          "Redis"           "Planned"

        pulse.digestCron  -> pulse.agentRuntime "Triggers daily digest"       "in-process"      "Planned"
        pulse.digestCron  -> telegram           "Sends digest"                 "Bot API"         "Planned"
        pulse.reflectCron -> pulse.agentRuntime "Triggers weekly reflection"  "in-process"      "Planned"
        pulse.reflectCron -> telegram           "Sends reflection"             "Bot API"         "Planned"
    }

    # ----------------------------------------------------------------------
    # VIEWS
    #   Context        — L1, who/what touches PULSE.
    #   Container_Now  — L2, only Implemented elements (today's reality).
    #   Container_Target — L2, the full target design.
    # ----------------------------------------------------------------------
    views {

        systemContext pulse "Context" {
            description "L1 — PULSE in its environment."
            include *
            autolayout lr
        }

        container pulse "Container_Now" {
            description "L2 — what exists today. Planned elements excluded."
            include *
            exclude "element.tag==Planned"
            exclude "relationship.tag==Planned"
            autolayout lr
        }

        container pulse "Container_Target" {
            description "L2 — full target design (Implemented + Planned)."
            include *
            autolayout lr
        }

        styles {
            element "Person" {
                shape Person
                background #08427b
                color #ffffff
            }
            element "Software System" {
                background #1168bd
                color #ffffff
            }
            element "External" {
                background #6b6b6b
                color #ffffff
            }
            element "Container" {
                background #438dd5
                color #ffffff
            }
            element "Database" {
                shape Cylinder
            }
            element "Implemented" {
                background #1f8a4c
                color #ffffff
            }
            element "Planned" {
                background #c7c7c7
                color #303030
                border dashed
                opacity 70
            }
            relationship "Planned" {
                style dashed
                color #9a9a9a
            }
        }
    }
}
