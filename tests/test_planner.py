"""Deterministic, network-free tests for the planner engine.

These are plumbing tests: they prove plan_research wires inputs, outputs, and
errors correctly, and that the run-scoped response model used internally
never leaks past the public boundary. See test_planner_golden.py for reviewed
fixture cases.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from pulse import llm as llm_module
from pulse.models import Source
from pulse.patterns.planner import (
    ExecutionPlan,
    PlannedResearchTask,
    _canonical_sources,
    _plan_model_for,
    plan_research,
)


def _payload(*tasks: tuple[str, str, str]) -> dict:
    return {
        "tasks": [
            {"topic": topic, "query": query, "source": source} for topic, query, source in tasks
        ]
    }


# --- Contract acceptance ---


def test_valid_structured_response_creates_execution_plan() -> None:
    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        return response_model.model_validate(
            _payload(("t1", "q1", "arxiv"), ("t2", "q2", "hacker_news"))
        )

    plan = asyncio.run(plan_research("q", [Source.ARXIV, Source.HACKER_NEWS], fake))

    assert [t.source for t in plan.tasks] == [Source.ARXIV, Source.HACKER_NEWS]
    assert [t.topic for t in plan.tasks] == ["t1", "t2"]


def test_task_order_is_preserved_as_returned() -> None:
    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        return response_model.model_validate(
            _payload(("t3", "q3", "youtube"), ("t1", "q1", "arxiv"), ("t2", "q2", "newsletter"))
        )

    plan = asyncio.run(plan_research("q", [Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER], fake))

    assert [t.topic for t in plan.tasks] == ["t3", "t1", "t2"]


# --- Return-type stability: the narrowed model must not leak ---


def test_returned_plan_is_exactly_execution_plan() -> None:
    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        return response_model.model_validate(_payload(("t", "q", "arxiv")))

    plan = asyncio.run(plan_research("q", [Source.ARXIV], fake))

    assert type(plan) is ExecutionPlan
    assert type(plan.tasks[0]) is PlannedResearchTask


def test_returned_plan_survives_dump_and_revalidate_round_trip() -> None:
    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        return response_model.model_validate(_payload(("t", "q", "arxiv")))

    plan = asyncio.run(plan_research("q", [Source.ARXIV], fake))
    restored = ExecutionPlan.model_validate(plan.model_dump())

    assert restored == plan
    assert type(restored) is ExecutionPlan


def test_different_available_sources_return_the_same_public_type() -> None:
    def fake_arxiv(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        return response_model.model_validate(_payload(("t", "q", "arxiv")))

    def fake_youtube(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        return response_model.model_validate(_payload(("t", "q", "youtube")))

    plan_a = asyncio.run(plan_research("q", [Source.ARXIV], fake_arxiv))
    plan_b = asyncio.run(plan_research("q", [Source.YOUTUBE], fake_youtube))

    assert type(plan_a) is type(plan_b) is ExecutionPlan


# --- Internal narrowing still restricts source (asserted directly) ---


def test_plan_model_for_schema_source_enum_matches_supplied_sources() -> None:
    model = _plan_model_for((Source.ARXIV, Source.HACKER_NEWS))
    schema = model.model_json_schema()
    source_schema = schema["$defs"]["PlannedResearchTask"]["properties"]["source"]

    assert set(source_schema["enum"]) == {"arxiv", "hacker_news"}


def test_plan_model_for_rejects_unavailable_source_as_validation_error() -> None:
    model = _plan_model_for((Source.ARXIV,))

    # youtube is a real Source member, just not in the narrowed literal below.
    with pytest.raises(ValidationError):
        model.model_validate(_payload(("t", "q", "youtube")))


def test_validation_error_is_a_fallback_error() -> None:
    """Pins the reason invalid output reasks then falls back instead of
    failing hard: ValidationError is a member of the gateway's fallback set."""
    assert ValidationError in llm_module.FALLBACK_ERRORS


# --- Determinism of the canonical source order ---


@pytest.mark.parametrize(
    "sources",
    [
        [Source.YOUTUBE, Source.ARXIV],
        {Source.ARXIV, Source.YOUTUBE},
        (Source.YOUTUBE, Source.ARXIV),
        [Source.ARXIV, Source.YOUTUBE, Source.ARXIV],
    ],
)
def test_canonical_sources_is_project_declaration_order_regardless_of_input(sources) -> None:
    assert _canonical_sources(sources) == (Source.ARXIV, Source.YOUTUBE)


def test_equivalent_source_collections_share_the_same_cached_model() -> None:
    a = _plan_model_for(_canonical_sources([Source.YOUTUBE, Source.ARXIV]))
    b = _plan_model_for(_canonical_sources({Source.ARXIV, Source.YOUTUBE}))
    c = _plan_model_for(_canonical_sources([Source.ARXIV, Source.YOUTUBE, Source.ARXIV]))

    assert a is b is c


# --- Rejected by contract ---


def _fake_returning(payload: dict):
    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        return response_model.model_validate(payload)

    return fake


def test_zero_tasks_rejected() -> None:
    with pytest.raises(ValidationError):
        asyncio.run(plan_research("q", [Source.ARXIV], _fake_returning({"tasks": []})))


def test_more_than_five_tasks_rejected() -> None:
    payload = _payload(*[(f"t{i}", f"q{i}", "arxiv") for i in range(6)])
    with pytest.raises(ValidationError):
        asyncio.run(plan_research("q", [Source.ARXIV], _fake_returning(payload)))


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_topic_rejected(blank: str) -> None:
    payload = _payload((blank, "q", "arxiv"))
    with pytest.raises(ValidationError):
        asyncio.run(plan_research("q", [Source.ARXIV], _fake_returning(payload)))


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_query_rejected(blank: str) -> None:
    payload = _payload(("t", blank, "arxiv"))
    with pytest.raises(ValidationError):
        asyncio.run(plan_research("q", [Source.ARXIV], _fake_returning(payload)))


def test_unknown_source_value_rejected() -> None:
    # Not a Source member at all — distinct from a real member excluded this run.
    payload = _payload(("t", "q", "bluesky"))
    with pytest.raises(ValidationError):
        asyncio.run(plan_research("q", [Source.ARXIV], _fake_returning(payload)))


def test_source_not_offered_this_run_rejected_even_if_globally_valid() -> None:
    # youtube is a real Source member but wasn't in the supplied registry.
    payload = _payload(("t", "q", "youtube"))
    with pytest.raises(ValidationError):
        asyncio.run(plan_research("q", [Source.ARXIV], _fake_returning(payload)))


@pytest.mark.parametrize("second_query", ["q", "Q", "q  ", " Q "])
def test_duplicate_query_source_pair_rejected_after_strip_and_casefold(second_query: str) -> None:
    payload = _payload(("t1", "q", "arxiv"), ("t2", second_query, "arxiv"))
    with pytest.raises(ValidationError):
        asyncio.run(plan_research("q", [Source.ARXIV], _fake_returning(payload)))


# --- Inputs reach the planner ---


def test_original_query_reaches_the_prompt_verbatim() -> None:
    captured: dict = {}

    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        captured["messages"] = messages
        return response_model.model_validate(_payload(("t", "q", "arxiv")))

    asyncio.run(plan_research("some distinctive query", [Source.ARXIV], fake))

    assert any("some distinctive query" in m["content"] for m in captured["messages"])


def test_every_available_source_named_and_no_unavailable_source_mentioned() -> None:
    captured: dict = {}

    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        captured["messages"] = messages
        return response_model.model_validate(_payload(("t", "q", "arxiv")))

    asyncio.run(plan_research("q", [Source.ARXIV, Source.HACKER_NEWS], fake))

    content = "\n".join(m["content"] for m in captured["messages"])
    assert "arxiv" in content
    assert "hacker_news" in content
    assert "youtube" not in content
    assert "newsletter" not in content


# --- At-most-once ---


def test_plan_llm_called_exactly_once() -> None:
    calls = {"count": 0}

    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        calls["count"] += 1
        return response_model.model_validate(_payload(("t", "q", "arxiv")))

    asyncio.run(plan_research("q", [Source.ARXIV], fake))

    assert calls["count"] == 1


# --- No source or network work ---


def test_no_sources_available_raises_before_calling_plan_llm() -> None:
    calls = {"count": 0}

    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        calls["count"] += 1
        return response_model.model_validate(_payload(("t", "q", "arxiv")))

    with pytest.raises(ValueError):
        asyncio.run(plan_research("q", [], fake))

    assert calls["count"] == 0


# --- Shared provider errors and unexpected errors propagate with their type ---


@pytest.mark.parametrize(
    "exc",
    [
        llm_module.ProviderBillingError("billing"),
        llm_module.ProviderConfigurationError("config"),
        llm_module.ModelsExhaustedError("exhausted"),
        RuntimeError("unclassified bug"),
    ],
)
def test_errors_from_plan_llm_propagate_with_their_exact_type(exc: BaseException) -> None:
    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        raise exc

    with pytest.raises(type(exc)):
        asyncio.run(plan_research("q", [Source.ARXIV], fake))


def test_cancellation_propagates() -> None:
    def fake(*, messages: list[dict], response_model: type[ExecutionPlan]) -> ExecutionPlan:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(plan_research("q", [Source.ARXIV], fake))
