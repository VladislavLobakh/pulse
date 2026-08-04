"""Network-free tests for the live planning eval's own expectations.

The eval itself needs a provider, but whether its cases and grader can fail
at all is a structural property — checkable by import alone.
"""

from __future__ import annotations

import pytest

from pulse.evals.plan_quality import CASES, Case, PlanExpectation
from pulse.models import Source
from pulse.patterns.planner import ExecutionPlan


def _has_expectation(expectation: PlanExpectation) -> bool:
    return (
        expectation.min_tasks is not None
        or expectation.max_tasks is not None
        or expectation.min_unique_sources is not None
        or bool(expectation.allowed_sources)
        or bool(expectation.required_sources)
        or bool(expectation.required_any_sources)
    )


def _plan(*sources: Source) -> ExecutionPlan:
    return ExecutionPlan.model_validate(
        {
            "tasks": [
                {"topic": "t", "query": f"q{i}", "source": source.value}
                for i, source in enumerate(sources)
            ]
        }
    )


# --- Every declared case has a checkable expectation ---


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_every_case_declares_a_checkable_expectation(case: Case) -> None:
    assert _has_expectation(case.expectation)


def test_expectation_without_any_bound_cannot_be_constructed() -> None:
    with pytest.raises(ValueError):
        PlanExpectation()


def test_zero_valued_bound_counts_as_an_expectation() -> None:
    expectation = PlanExpectation(min_tasks=0)

    assert _has_expectation(expectation)


def test_required_any_sources_alone_counts_as_an_expectation() -> None:
    expectation = PlanExpectation(required_any_sources=frozenset({Source.ARXIV}))

    assert _has_expectation(expectation)


def test_min_unique_sources_alone_counts_as_an_expectation() -> None:
    expectation = PlanExpectation(min_unique_sources=2)

    assert _has_expectation(expectation)


# --- The grader actually fails bad plans (successful parsing alone is not a pass) ---


def test_check_fails_a_plan_with_too_few_tasks() -> None:
    expectation = PlanExpectation(min_tasks=2)
    plan = _plan(Source.ARXIV)

    assert expectation.check(plan) != []


def test_check_fails_a_plan_with_too_many_tasks() -> None:
    expectation = PlanExpectation(max_tasks=1)
    plan = _plan(Source.ARXIV, Source.HACKER_NEWS)

    assert expectation.check(plan) != []


def test_check_fails_a_plan_missing_a_required_source() -> None:
    expectation = PlanExpectation(required_sources=frozenset({Source.ARXIV}))
    plan = _plan(Source.HACKER_NEWS)

    assert expectation.check(plan) != []


def test_check_fails_a_plan_using_a_disallowed_source() -> None:
    expectation = PlanExpectation(allowed_sources=frozenset({Source.ARXIV}))
    plan = _plan(Source.HACKER_NEWS)

    assert expectation.check(plan) != []


def test_check_fails_a_plan_with_too_few_unique_sources() -> None:
    """min_tasks alone would let three same-source tasks pass; a diversity
    requirement must count distinct sources, not task count."""
    expectation = PlanExpectation(min_unique_sources=3)
    plan = _plan(Source.ARXIV, Source.ARXIV, Source.ARXIV)

    assert expectation.check(plan) != []


def test_check_passes_a_plan_that_meets_min_unique_sources() -> None:
    expectation = PlanExpectation(min_unique_sources=3)
    plan = _plan(Source.ARXIV, Source.HACKER_NEWS, Source.NEWSLETTER)

    assert expectation.check(plan) == []


def test_check_passes_a_plan_that_meets_every_bound() -> None:
    expectation = PlanExpectation(
        min_tasks=1, max_tasks=2, allowed_sources=frozenset({Source.ARXIV})
    )
    plan = _plan(Source.ARXIV)

    assert expectation.check(plan) == []


# --- required_any_sources: at-least-one, not all, not none ---


def test_required_any_sources_passes_with_exactly_one_present() -> None:
    expectation = PlanExpectation(
        required_any_sources=frozenset({Source.HACKER_NEWS, Source.YOUTUBE, Source.NEWSLETTER})
    )
    plan = _plan(Source.HACKER_NEWS, Source.ARXIV)

    assert expectation.check(plan) == []


def test_required_any_sources_passes_with_more_than_one_present() -> None:
    expectation = PlanExpectation(
        required_any_sources=frozenset({Source.HACKER_NEWS, Source.YOUTUBE, Source.NEWSLETTER})
    )
    plan = _plan(Source.HACKER_NEWS, Source.YOUTUBE)

    assert expectation.check(plan) == []


def test_required_any_sources_fails_when_none_present() -> None:
    expectation = PlanExpectation(
        required_any_sources=frozenset({Source.HACKER_NEWS, Source.YOUTUBE, Source.NEWSLETTER})
    )
    plan = _plan(Source.ARXIV)

    assert expectation.check(plan) != []


# --- Regression: "broad query" case must reject source-homogeneous plans ---


def test_broad_query_case_rejects_three_tasks_against_one_source() -> None:
    broad_case = next(c for c in CASES if "broad query" in c.name)
    same_source_plan = _plan(Source.HACKER_NEWS, Source.HACKER_NEWS, Source.HACKER_NEWS)

    assert broad_case.expectation.check(same_source_plan) != []
