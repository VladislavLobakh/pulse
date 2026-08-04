"""Plan-and-Execute planner — turns a query and the sources available for this
run into a bounded, validated `ExecutionPlan`. Executes nothing: no fetching,
no dispatch, no analysis.

Source membership is enforced by narrowing `PlannedResearchTask.source` to a
`Literal` of the available sources on a run-scoped response model passed only
to the structured call; an unavailable source becomes a Pydantic
`ValidationError`, which `pulse.llm` already reasks and falls back on. The
narrowed model is an internal generation/validation device — `plan_research`
always returns the stable base `ExecutionPlan`, never a per-run subclass, so
callers and any persisted graph state see one consistent type. This narrows
membership only for plans this function returns; a hand-built `ExecutionPlan`
can still name any `Source`, so a dispatcher must validate against its actual
runner registry before executing a plan it did not just receive.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable, Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from pulse.models import Source

MAX_TASKS = 5

_SOURCE_CAPABILITIES: dict[Source, str] = {
    Source.HACKER_NEWS: "Hacker News: developer/practitioner discussion and opinion on "
    "recent tech and AI news.",
    Source.ARXIV: "ArXiv: peer-reviewed and preprint research papers — use for "
    "research-heavy, technical, or methods questions.",
    Source.YOUTUBE: "YouTube: talks, demos, and tutorials — use for practical, "
    "hands-on, or walkthrough-style questions.",
    Source.NEWSLETTER: "Newsletter feeds: curated AI news summaries and announcements.",
}


# --- LLM output contract (Pydantic — Instructor requires Pydantic) ---

_TOPIC_DESCRIPTION = "The specific subject this task investigates."
_QUERY_DESCRIPTION = (
    "A focused search query for the assigned source — not a restatement of "
    "the original user query, but a concrete sub-question it implies."
)
_SOURCE_DESCRIPTION = "The single source this task's query runs against."
_TASKS_DESCRIPTION = "One to five focused research tasks, ordered by priority."


class PlannedResearchTask(BaseModel):
    # See TopicSignal for why: min_length alone accepts whitespace-only strings.
    model_config = ConfigDict(str_strip_whitespace=True)

    topic: str = Field(min_length=1, description=_TOPIC_DESCRIPTION)
    query: str = Field(min_length=1, description=_QUERY_DESCRIPTION)
    source: Source = Field(description=_SOURCE_DESCRIPTION)


class ExecutionPlan(BaseModel):
    tasks: list[PlannedResearchTask] = Field(
        min_length=1, max_length=MAX_TASKS, description=_TASKS_DESCRIPTION
    )

    @model_validator(mode="after")
    def _reject_duplicate_assignments(self) -> ExecutionPlan:
        seen: set[tuple[str, Source]] = set()
        for task in self.tasks:
            key = (task.query.casefold(), task.source)
            if key in seen:
                raise ValueError(f"duplicate query/source assignment: {task.source.value!r}")
            seen.add(key)
        return self


def _canonical_sources(sources: Collection[Source]) -> tuple[Source, ...]:
    """Deterministic `Source` declaration order — caller iteration order must
    not change the prompt or the generated schema."""
    supplied = set(sources)
    return tuple(source for source in Source if source in supplied)


@functools.cache
def _plan_model_for(sources: tuple[Source, ...]) -> type[ExecutionPlan]:
    """Run-scoped response model, used only as `response_model` for the
    structured call — never returned (see module docstring)."""
    task_model = create_model(
        "PlannedResearchTask",
        __base__=PlannedResearchTask,
        source=(Literal[sources], Field(description=_SOURCE_DESCRIPTION)),
    )
    return create_model(
        "ExecutionPlan",
        __base__=ExecutionPlan,
        tasks=(
            list[task_model],
            Field(min_length=1, max_length=MAX_TASKS, description=_TASKS_DESCRIPTION),
        ),
    )


def _build_messages(query: str, sources: tuple[Source, ...]) -> list[dict]:
    capabilities = "\n".join(f"- {_SOURCE_CAPABILITIES[source]}" for source in sources)
    allowed = ", ".join(source.value for source in sources)
    system = (
        "You plan focused research tasks for a research assistant. Given a "
        "query and the sources available this run, break it into one to five "
        "tasks, each pairing a focused query with exactly one source. Only "
        "the sources listed below are available — never assign a task to any "
        "other source, however well it might otherwise fit:\n"
        f"{capabilities}\n\n"
        "Use as many or as few tasks as the query actually needs: a narrow "
        "query may need only one task, a broad one may need several across "
        "different sources. Do not create two tasks with the same query "
        "against the same source."
    )
    user = f"Original query: {query!r}\nAvailable sources: {allowed}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# (messages=..., response_model=...) -> BaseModel; normally `complete_structured`
# bound via `functools.partial`, as in `agents/hn.py`.
StructuredLLMFn = Callable[..., BaseModel]


async def plan_research(
    query: str,
    sources: Collection[Source],
    plan_llm: StructuredLLMFn,
) -> ExecutionPlan:
    """Plan focused research tasks for `query` over `sources`. Calls `plan_llm`
    exactly once (excluding the gateway's own retry/reask/fallback) and raises
    whatever it raises — including `ModelsExhaustedError`, which this function
    does not turn into a fallback plan; the caller classifies it.
    """
    available = _canonical_sources(sources)
    if not available:
        raise ValueError("no sources available for planning")
    plan = await asyncio.to_thread(
        plan_llm,
        messages=_build_messages(query, available),
        response_model=_plan_model_for(available),
    )
    # Convert back to the stable base type — the narrowed model above is an
    # internal device and must not reach callers or persisted graph state.
    return ExecutionPlan.model_validate(plan.model_dump())
