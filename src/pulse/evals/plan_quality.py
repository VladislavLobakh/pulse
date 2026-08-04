"""Live planning-quality eval for `patterns.planner.plan_research`.

There is no production planner chain yet (task 3 wires one into `pulse.main`),
so model slugs are a required argument here rather than an import from the
composition root. Every case must declare a machine-checkable expectation —
`PlanExpectation` refuses to be constructed otherwise; successful JSON parsing
alone is never a pass. Needs OPENROUTER_API_KEY; network use is why this is a
script, not a pytest test.

Usage:
    uv run python -m pulse.evals.plan_quality <model-slug> [...]
"""

from __future__ import annotations

import asyncio
import functools
import sys
from dataclasses import dataclass

from pulse.llm import complete_structured
from pulse.models import Source
from pulse.patterns.planner import ExecutionPlan, plan_research

_LLM_TEMPERATURE = 0.2
_LLM_MAX_TOKENS = 700


@dataclass
class PlanExpectation:
    min_tasks: int | None = None
    max_tasks: int | None = None
    min_unique_sources: int | None = None  # distinct sources used, not task count
    allowed_sources: frozenset[Source] = frozenset()
    required_sources: frozenset[Source] = frozenset()  # every listed source must appear
    required_any_sources: frozenset[Source] = frozenset()  # at least one must appear

    def __post_init__(self) -> None:
        # `is None` rather than truthiness: 0 would be a legitimate bound.
        if (
            self.min_tasks is None
            and self.max_tasks is None
            and self.min_unique_sources is None
            and not self.allowed_sources
            and not self.required_sources
            and not self.required_any_sources
        ):
            raise ValueError("plan expectation declares no checkable expectation")

    def check(self, plan: ExecutionPlan) -> list[str]:
        failures = []
        count = len(plan.tasks)
        if self.min_tasks is not None and count < self.min_tasks:
            failures.append(f"task count={count} < {self.min_tasks}")
        if self.max_tasks is not None and count > self.max_tasks:
            failures.append(f"task count={count} > {self.max_tasks}")

        used = {task.source for task in plan.tasks}
        if self.min_unique_sources is not None and len(used) < self.min_unique_sources:
            failures.append(f"unique source count={len(used)} < {self.min_unique_sources}")
        if self.allowed_sources and not used <= self.allowed_sources:
            extra = [s.value for s in used - self.allowed_sources]
            failures.append(f"used disallowed sources: {extra}")
        if self.required_sources and not self.required_sources <= used:
            missing = [s.value for s in self.required_sources - used]
            failures.append(f"missing required sources: {missing}")
        if self.required_any_sources and not (used & self.required_any_sources):
            allowed = [s.value for s in self.required_any_sources]
            failures.append(f"none of the required-any sources used: {allowed}")

        seen: set[tuple[str, Source]] = set()
        for task in plan.tasks:
            key = (task.query.casefold(), task.source)
            if key in seen:
                failures.append(f"duplicate query/source assignment: {task.source.value!r}")
            seen.add(key)
        return failures


@dataclass
class Case:
    name: str
    query: str
    sources: frozenset[Source]
    expectation: PlanExpectation

    def run(self, model: str) -> tuple[ExecutionPlan | None, list[str]]:
        plan_llm = functools.partial(
            complete_structured,
            models=[model],
            temperature=_LLM_TEMPERATURE,
            max_tokens=_LLM_MAX_TOKENS,
        )
        try:
            plan = asyncio.run(plan_research(self.query, self.sources, plan_llm))
        except Exception as exc:  # provider/contract errors count as case failure
            return None, [f"error: {exc}"]
        return plan, self.expectation.check(plan)


_ALL_SOURCES = frozenset({Source.HACKER_NEWS, Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER})

CASES: list[Case] = [
    Case(
        name="1 narrow query, single obvious source",
        query="What did Anthropic announce about Claude this week?",
        sources=_ALL_SOURCES,
        expectation=PlanExpectation(max_tasks=2),
    ),
    Case(
        name="2 broad query, multiple source types",
        query="What's happening across the AI industry right now?",
        sources=_ALL_SOURCES,
        expectation=PlanExpectation(min_tasks=3, min_unique_sources=3),
    ),
    Case(
        name="3 research-heavy query, ArXiv appropriate",
        query="What are the latest advances in transformer attention efficiency?",
        sources=_ALL_SOURCES,
        expectation=PlanExpectation(required_sources=frozenset({Source.ARXIV})),
    ),
    Case(
        name="4 practical discussion, HN/YouTube/Newsletter appropriate",
        query="How are developers actually using AI coding agents day to day?",
        sources=_ALL_SOURCES,
        expectation=PlanExpectation(
            required_any_sources=frozenset({Source.HACKER_NEWS, Source.YOUTUBE, Source.NEWSLETTER})
        ),
    ),
]

# Unavailable-source rejection and duplicate-task rejection are contract
# guarantees, not model-quality signals: `plan_research` cannot return a plan
# violating either, for any model. Those cases live in
# `tests/test_planner_golden.py`, which proves the contract offline instead.


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: uv run python -m pulse.evals.plan_quality <model-slug> [...]\n"
            "This eval has no production chain to default to — pass at least one "
            "candidate model.",
            file=sys.stderr,
        )
        return 1
    models = [f"openrouter/{m.removeprefix('openrouter/')}" for m in args]

    exit_code = 0
    for model in models:
        print(f"\n=== {model} ===")
        passed = 0
        for case in CASES:
            plan, failures = case.run(model)
            passed += not failures
            status = "PASS" if not failures else "FAIL"
            print(f"[{status}] {case.name}")
            if plan is not None:
                for task in plan.tasks:
                    print(f"    {task.source.value}: topic={task.topic!r} query={task.query!r}")
            for failure in failures:
                print(f"    -> {failure}")
        print(f"--- {model}: {passed}/{len(CASES)} passed")
        if passed != len(CASES):
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
