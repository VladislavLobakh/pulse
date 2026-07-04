"""HN source agent — Hacker News business logic wired into the generic ReAct loop.

The graph mechanics (retry/stop/trace) live in `react_loop`; this module supplies
everything specific to Hacker News: the collector call, the model chains bound to
the LLM gateway, the default query, the reasoning/scoring prompts, how reasoning
context and scoring payloads are built, and the thresholds that decide when to stop.

Reason and observe use separate OpenRouter model chains, defined here as plain
code constants (not env vars) — model slugs aren't secrets, and keeping them in
code makes changes reviewable/trackable in git, same as the prompts and
thresholds below. A future source agent (e.g. ArXiv) defines its own
REASON_MODELS/OBSERVE_MODELS constants without touching this file or
`react_loop.py`.

Live progress: when `PULSE_VERBOSE=1`, each ReAct step is printed to stderr as
it happens (via `ReActConfig.on_step`), not only once the whole run finishes
and the CLI prints the final trace. This is intentionally independent of
`PULSE_LOG_LEVEL` — DEBUG already prints its own per-node detail via
`logging`, so tying the live printer to DEBUG too would triple the output for
the same events (INFO log line + DEBUG detail + live line).
"""

from __future__ import annotations

import functools
import os
import sys

from pulse.agents.react_loop import ReActConfig, ReActState, _step_suffix, run_react
from pulse.collectors.tavily import search_articles
from pulse.llm import complete_structured
from pulse.models import ReActResult, Source, SourceItemList, TraceEvent

HN_QUERY = "AI LLM site:news.ycombinator.com"
MAX_RESULTS = 10
MIN_ARTICLES = 8

SCORE_THRESHOLD = 0.75
MAX_ITERATIONS = 3
RECURSION_LIMIT = 10
PREVIEW_TITLE_COUNT = 5
ACTION_NAME = "tavily_hn"

REASON_MODELS = [
    "openrouter/google/gemini-2.5-flash-lite",
    "openrouter/openai/gpt-4o-mini",
]
OBSERVE_MODELS = [
    "openrouter/google/gemini-2.5-flash-lite",
    "openrouter/openai/gpt-4o-mini",
]

REASON_SYSTEM_PROMPT = (
    "You are reasoning about what to search on Hacker News to find "
    "high-quality AI/LLM articles. Given the current query and any "
    "prior results, propose the next search query."
)
OBSERVE_SYSTEM_PROMPT = (
    "Score how well this batch of articles satisfies a search for "
    "high-quality, novel AI/LLM news. Rate relevance, novelty, and "
    "quality each from 0 to 1."
)


def _search(query: str, max_results: int) -> SourceItemList:
    return search_articles(query, Source.HACKER_NEWS, max_results=max_results)


def _build_reason_context(state: ReActState, config: ReActConfig) -> str:
    lines = [f"Current query: {state['query']}"]
    if state["iteration"] > 0:
        remaining = config.max_iterations - state["iteration"]
        lines.append(
            f"Search attempt {state['iteration']} of {config.max_iterations} scored "
            f"{state['last_score']:.2f} against a {config.score_threshold} threshold "
            f"({remaining} attempt{'s' if remaining != 1 else ''} remaining). "
            "Refine the query to find more relevant, novel, higher-quality results."
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
    line = f"[live] {event.kind.capitalize()}: {event.message}{_step_suffix(event)}"
    print(line, file=sys.stderr)


def _config() -> ReActConfig:
    return ReActConfig(
        search_fn=_search,
        reason_llm=functools.partial(complete_structured, models=REASON_MODELS),
        observe_llm=functools.partial(complete_structured, models=OBSERVE_MODELS),
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


def run_hn_react(
    query: str = HN_QUERY,
    max_results: int = MAX_RESULTS,
) -> ReActResult:
    return run_react(_config(), query=query, max_results=max_results)


def fetch_hn_articles(
    query: str = HN_QUERY,
    max_results: int = MAX_RESULTS,
) -> SourceItemList:
    return run_hn_react(query=query, max_results=max_results).items


if __name__ == "__main__":
    from pulse.display import print_articles, warn_if_below_minimum

    articles = fetch_hn_articles()
    warn_if_below_minimum(articles, MIN_ARTICLES)
    print_articles(articles)
