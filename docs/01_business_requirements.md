# PULSE — Business Requirements

## Persona: Ulad

**Who:** An intermediate-level developer actively learning to become an AI Engineer. Building PULSE as both a learning project and a real tool he uses daily.

**Context:**
- Follows the AI space closely: new tools, patterns, releases, expert discussions
- Wants to be at the cutting edge — but there's too much information coming from everywhere
- Building a personal brand on LinkedIn as an AI Engineer — wants to publish regularly
- Tech background: Python, TypeScript, some LLM API experience

**Core contradiction:**
> To be a good AI Engineer, you need to follow the field. But following the field takes time away from learning. PULSE breaks this cycle.

---

## Two Core Pains

### Pain 1: Information Overload

- Hacker News, ArXiv, Twitter/X, YouTube, Newsletters — all simultaneously, every day
- 3+ hours/day consumed by "absorption" — the return is disproportionate to the investment
- Important things get buried in noise. Missed LangGraph 2.0 release — learned from someone else's post a week later
- No personalization: LangGraph is critical for Ulad right now; GPT fine-tuning is not — the feeds don't know that
- **Result: either spend 3+ hours daily, or feel like you're falling behind. No middle ground.**

### Pain 2: Content Doesn't Ship

- Has things to say — but turning thoughts into a post takes 1+ hour with no quality guarantee
- Fear of publishing something inaccurate and damaging credibility
- LinkedIn algorithm rewards consistency — which doesn't exist with a manual approach
- Wants to position himself as an AI Engineer — but the profile goes silent for months
- **Result: 0–1 posts/month instead of the needed 3/week.**

---

## KPI — What "PULSE Works" Means

| KPI | Before PULSE | After PULSE | How PULSE does it |
|---|---|---|---|
| Time monitoring AI news | 3+ hours/day | **5 minutes morning** | Plan-Execute + Parallel + Mem0 + Digest @cron 8:00 |
| LinkedIn posts | 0–1/month | **3/week** | Self-correction + verify + HITL + Post Generator |
| Missing important releases | Often (learn a week late) | **Rarely** | Momentum detector + Deep Dive auto-trigger |
| Time to research a topic | 4+ hours manually | **8 minutes** | Research&Report: all 12 patterns in one request |
| Digest personalization | Zero — everything | **High** | Mem0 profile + FlashRank + weekly Reflection |
| Facts in posts | Sometimes inaccurate | **Verified** | Self-verification: VERIFIED/UNVERIFIED/CONTRADICTED |
| Understanding AI landscape | Linear (article by article) | **Knowledge graph** | LightRAG + Neo4j: multi-hop queries |

> **Primary KPI:** "1 digest instead of 3 hours of reading · 3 LinkedIn posts/week without stress"

Full KPI also in `CLAUDE.md`.

---

## User Stories

| When / Context | Ulad does | PULSE does | Result / Value |
|---|---|---|---|
| ☀️ Every morning 8:00 | Opens Telegram | Sends digest: 5 insights from last 24h, ranked by relevance to his stack | Reads 5 minutes instead of 3+ hours. Knows what matters. Nothing missed. |
| 📋 Sees interesting insight | Clicks "Deep Dive" in Dashboard | Launches Composite Agent: Search→Research→Synthesis→FactCheck→Report | Gets 800-word report in 8 minutes. Before: 4 hours of manual reading. |
| ✍️ Wants a LinkedIn post | Opens DraftInbox | Self-correction improved draft: 0.51→0.79. Facts verified. | Reads 30 sec, edits 1-2 sentences, hits Approve. Post goes live. |
| 🔍 Needs to understand a topic | Types: "Research MCP ecosystem" | Research&Report: Plan→Parallel Search×5→FactCheck→Synthesize→HITL | 8 minutes → 1200 words + LinkedIn draft. Before: 4 hours of manual research. |
| 📊 Sunday 10:00 | Reads Telegram | Reflection Agent: "You approved LangGraph(3), rejected finance(2). Quality: ↑0.74→0.81. Mem0 updated." | Understands his patterns. Next week automatically more precise. |
| 🔗 "What's related to X?" | Types: "What's connected to LangGraph?" | LightRAG multi-hop: LangGraph→MCP→Claude Code→FastMCP | Understands the landscape. Sees where the field is moving. |
| 📱 10 free minutes | Opens pulse.vercel.app | Dashboard: DigestFeed + DraftInbox (2 drafts waiting) | Approves from phone. Post goes live without a laptop. |

Per-day business scenarios live in `02_21day_plan.md` (💼 Business blocks).

---

## What Success Looks Like at Day 21

**Daily:** 8:00 Telegram digest · 2–3 verified drafts in Dashboard · 10 min approve → post live.

**Weekly:** 3 LinkedIn posts · Sunday Reflection in Telegram · Mem0 auto-updated.

**On demand:** "Research X" in 8 min · knowledge graph queries · Deep Dive on trending topics.

**In interviews:** Live demo · RAGAS 0.84 · "12 agentic patterns, each solves a real problem I had."
