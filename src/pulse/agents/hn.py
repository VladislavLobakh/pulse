"""HN source agent — Hacker News business logic wired into the ReAct pattern.

The pattern mechanics (retry/stop/trace) live in `patterns.react`; this module
supplies everything specific to Hacker News: the collector call, the per-step
OpenRouter model chains (plain code constants — reviewable in git; only the
API key is a secret), the reasoning/scoring prompts, and the stop thresholds.

Live progress (`PULSE_VERBOSE=1`) prints each step to stderr as it happens.
It is independent of `PULSE_LOG_LEVEL`: DEBUG already prints per-node detail,
so tying the live printer to it would duplicate output for the same events.
"""

from __future__ import annotations

import functools
import os
import sys

from pulse.collectors.tavily import search_articles
from pulse.llm import complete_structured
from pulse.models import Source, SourceItemList
from pulse.patterns.react import (
    ReActConfig,
    ReActResult,
    ReActState,
    TraceEvent,
    run_react,
    step_suffix,
)

HN_DOMAINS = ["news.ycombinator.com"]

MAX_RESULTS = 10
MIN_ARTICLES = 8

SCORE_THRESHOLD = 0.75
MAX_ITERATIONS = 3
RECURSION_LIMIT = 10
PREVIEW_TITLE_COUNT = 5
ACTION_NAME = "tavily_hn"

# Reason/observe are short structured outputs: near-deterministic, and the
# token cap bounds cost if a model rambles inside a JSON string field.
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 500

REASON_MODELS = [
    "openrouter/qwen/qwen3.5-flash-02-23",
    "openrouter/google/gemini-2.5-flash-lite",
]
OBSERVE_MODELS = [
    "openrouter/qwen/qwen3.5-flash-02-23",
    "openrouter/google/gemini-2.5-flash-lite",
]

REASON_SYSTEM_PROMPT = """You rewrite Hacker News search queries.

The original user query is a contract: refine HOW to search, never change WHAT
is being searched for. You have no default topic — whatever subject the user
asked about, however broad or narrow, is the subject of every query you write.

Rules:
1. Copy into `must_keep_terms` every meaningful term of the original user
   query: named technologies and products, acronyms, quoted "exact phrases",
   negative terms starting with -, time constraints, and operators such as
   site: filters.
2. Every generated query must contain all must-keep terms (close spelling
   variants allowed); keep operators, quotation marks, negative terms, and
   time constraints verbatim.
3. You may add synonyms and closely related terms, expand an acronym while
   keeping the acronym itself, reorder words, and drop filler words.
4. If the query is already specific, change little or nothing.
5. If the query is broad or vague, sharpen it using only the user's own words —
   do not pick a topic for them.
6. If previous results scored poorly, broaden or vary the phrasing within the
   same subject. Never switch subjects and never inject topics, technologies,
   or domains absent from the original user query, no matter how many attempts
   have failed."""

OBSERVE_SYSTEM_PROMPT = """You score how well a batch of search results satisfies a user's request.

Input JSON has `original_query` (what the user actually asked for),
`generated_query` (what was searched), and `results`.

Score against `original_query`, NOT against `generated_query`:
- relevance: how well the results satisfy the original user query. Topic drift
  is the primary failure: if the results (or the generated query) shifted to a
  different subject than the original query, relevance must be near 0 — no
  matter how interesting or high-quality that other subject's results are.
  Results violating explicit constraints of the original query (negative
  terms, site: filters, time constraints, quoted phrases) also lower relevance.
- novelty and quality are secondary; never compensate poor relevance with
  high novelty or quality.

A high score means the user's actual request is satisfied and searching stops.
Score low to force another attempt whenever the original intent is not met."""


def _search(query: str, max_results: int) -> SourceItemList:
    return search_articles(
        query,
        Source.HACKER_NEWS,
        max_results=max_results,
        include_domains=HN_DOMAINS,
    )


def _build_reason_context(state: ReActState, config: ReActConfig) -> str:
    lines = [f"Original user query (the contract): {state['original_query']}"]
    if state["query"] != state["original_query"]:
        lines.append(f"Last generated query: {state['query']}")
    if state["iteration"] > 0:
        remaining = config.max_iterations - state["iteration"]
        lines.append(
            f"Search attempt {state['iteration']} of {config.max_iterations} scored "
            f"{state['last_score']:.2f} against a {config.score_threshold} threshold "
            f"({remaining} attempt{'s' if remaining != 1 else ''} remaining). "
            "Broaden or vary the phrasing within the same subject — "
            "do not switch subjects."
        )
        titles = [a.title for a in state["items"][:PREVIEW_TITLE_COUNT]]
        if titles:
            lines.append("Previous result titles: " + "; ".join(titles))
    return "\n".join(lines)


def _build_score_payload(items: SourceItemList) -> list[dict]:
    return [
        {
            "title": item.title,
            "url": item.url,
            "summary": item.summary,
            "source": str(item.source),
        }
        for item in items
    ]


def _live_progress_enabled() -> bool:
    return os.getenv("PULSE_VERBOSE") == "1"


def _print_step(event: TraceEvent) -> None:
    line = f"[live] {event.kind.capitalize()}: {event.message}{step_suffix(event)}"
    print(line, file=sys.stderr)


def _config() -> ReActConfig:
    return ReActConfig(
        search_fn=_search,
        reason_llm=functools.partial(
            complete_structured,
            models=REASON_MODELS,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        ),
        observe_llm=functools.partial(
            complete_structured,
            models=OBSERVE_MODELS,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        ),
        reason_system_prompt=REASON_SYSTEM_PROMPT,
        observe_system_prompt=OBSERVE_SYSTEM_PROMPT,
        build_reason_context=_build_reason_context,
        build_score_payload=_build_score_payload,
        action_name=ACTION_NAME,
        score_threshold=SCORE_THRESHOLD,
        max_iterations=MAX_ITERATIONS,
        recursion_limit=RECURSION_LIMIT,
        on_step=_print_step if _live_progress_enabled() else None,
    )


def run_hn_react(query: str, max_results: int = MAX_RESULTS) -> ReActResult:
    return run_react(_config(), query=query, max_results=max_results)


def fetch_hn_articles(query: str, max_results: int = MAX_RESULTS) -> SourceItemList:
    return run_hn_react(query=query, max_results=max_results).items
