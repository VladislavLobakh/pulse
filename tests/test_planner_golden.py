"""Reviewed golden examples for the planner contract.

These are contract *plumbing* fixtures, not model-quality evaluations: the
accepted cases check that a reviewed structured payload passes through
plan_research unchanged and satisfies its scenario's PlanExpectation; the
rejected cases check that the two required-negative payloads never survive as
a plan. Judging planning quality against a live model belongs in
pulse/evals/plan_quality.py, which needs network access and is deliberately
out of scope for these deterministic tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from pulse.evals.plan_quality import PlanExpectation
from pulse.models import Source
from pulse.patterns.planner import ExecutionPlan, plan_research


@dataclass
class AcceptedGoldenCase:
    id: str
    query: str
    sources: frozenset[Source]
    payload: dict
    expectation: PlanExpectation
    notes: str


@dataclass
class RejectedGoldenCase:
    id: str
    query: str
    sources: frozenset[Source]
    payload: dict
    notes: str


ACCEPTED_CASES = [
    AcceptedGoldenCase(
        id="narrow_query_one_task",
        query="What did Anthropic announce about Claude this week?",
        sources=frozenset({Source.HACKER_NEWS, Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER}),
        payload={
            "tasks": [
                {
                    "topic": "Claude announcement",
                    "query": "Anthropic Claude announcement this week",
                    "source": "hacker_news",
                }
            ]
        },
        expectation=PlanExpectation(max_tasks=2),
        notes="A narrow, single-subject query needs only one focused task.",
    ),
    AcceptedGoldenCase(
        id="broad_query_multiple_source_types",
        query="What's happening across the AI industry right now?",
        sources=frozenset({Source.HACKER_NEWS, Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER}),
        payload={
            "tasks": [
                {
                    "topic": "AI industry news",
                    "query": "AI industry news this week",
                    "source": "hacker_news",
                },
                {
                    "topic": "AI research trends",
                    "query": "recent AI research papers",
                    "source": "arxiv",
                },
                {
                    "topic": "AI newsletter roundup",
                    "query": "AI newsletter roundup this week",
                    "source": "newsletter",
                },
            ]
        },
        expectation=PlanExpectation(min_tasks=3, min_unique_sources=3),
        notes="A broad query benefits from tasks spanning multiple source types.",
    ),
    AcceptedGoldenCase(
        id="research_heavy_query_uses_arxiv",
        query="What are the latest advances in transformer attention efficiency?",
        sources=frozenset({Source.HACKER_NEWS, Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER}),
        payload={
            "tasks": [
                {
                    "topic": "attention efficiency research",
                    "query": "transformer attention efficiency papers",
                    "source": "arxiv",
                }
            ]
        },
        expectation=PlanExpectation(required_sources=frozenset({Source.ARXIV})),
        notes="A research-heavy query should route to ArXiv.",
    ),
    AcceptedGoldenCase(
        id="practical_discussion_uses_hn_youtube_or_newsletter",
        query="How are developers actually using AI coding agents day to day?",
        sources=frozenset({Source.HACKER_NEWS, Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER}),
        payload={
            "tasks": [
                {
                    "topic": "AI coding agent usage",
                    "query": "developers using AI coding agents",
                    "source": "hacker_news",
                }
            ]
        },
        expectation=PlanExpectation(
            required_any_sources=frozenset({Source.HACKER_NEWS, Source.YOUTUBE, Source.NEWSLETTER})
        ),
        notes="A practical discussion query has several defensible sources; "
        "any one of HN/YouTube/Newsletter satisfies it.",
    ),
]

REJECTED_CASES = [
    RejectedGoldenCase(
        id="unavailable_source_never_accepted",
        query="anything about AI",
        sources=frozenset({Source.ARXIV}),
        payload={"tasks": [{"topic": "t", "query": "q", "source": "youtube"}]},
        notes="youtube has no runner offered in this run's registry (only arxiv "
        "was supplied) and must be rejected even though it is a real Source member.",
    ),
    RejectedGoldenCase(
        id="duplicate_query_source_pair_rejected",
        query="new AI model releases",
        sources=frozenset({Source.ARXIV, Source.HACKER_NEWS}),
        payload={
            "tasks": [
                {"topic": "t1", "query": "new AI model releases", "source": "arxiv"},
                {"topic": "t2", "query": "New AI Model Releases", "source": "arxiv"},
            ]
        },
        notes="Same query and source repeated (modulo case/whitespace) must be rejected.",
    ),
]


@pytest.mark.parametrize("case", ACCEPTED_CASES, ids=[c.id for c in ACCEPTED_CASES])
def test_accepted_golden_case_produces_a_plan_satisfying_its_expectation(
    case: AcceptedGoldenCase,
) -> None:
    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        return response_model.model_validate(case.payload)

    plan = asyncio.run(plan_research(case.query, case.sources, fake))

    assert case.expectation.check(plan) == []


@pytest.mark.parametrize("case", REJECTED_CASES, ids=[c.id for c in REJECTED_CASES])
def test_rejected_golden_case_never_survives_as_a_plan(case: RejectedGoldenCase) -> None:
    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        return response_model.model_validate(case.payload)

    with pytest.raises(ValidationError):
        asyncio.run(plan_research(case.query, case.sources, fake))


def test_golden_examples_cover_every_required_scenario() -> None:
    assert {case.id for case in ACCEPTED_CASES} == {
        "narrow_query_one_task",
        "broad_query_multiple_source_types",
        "research_heavy_query_uses_arxiv",
        "practical_discussion_uses_hn_youtube_or_newsletter",
    }
    assert {case.id for case in REJECTED_CASES} == {
        "unavailable_source_never_accepted",
        "duplicate_query_source_pair_rejected",
    }
