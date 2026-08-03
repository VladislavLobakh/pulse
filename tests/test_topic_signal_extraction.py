"""Network-free tests for the live extraction eval's own expectations.

The eval itself needs a provider, but whether its cases can fail at all is a
structural property — checkable by import alone.
"""

from __future__ import annotations

import pytest

from pulse.evals.topic_signal_extraction import CASES, Case
from pulse.models import Source, SourceItem
from pulse.patterns.topic_signal import EventType


def _has_expectation(case: Case) -> bool:
    return (
        case.max_relevance is not None
        or case.min_relevance is not None
        or case.max_confidence is not None
        or bool(case.expected_event_types)
    )


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_every_case_declares_a_checkable_expectation(case: Case) -> None:
    """A case with no expectation reports PASS unconditionally and can never
    detect drift, which is what made the sparse case useless before."""
    assert _has_expectation(case)


def test_case_without_any_expectation_cannot_be_constructed() -> None:
    with pytest.raises(ValueError):
        Case(
            name="no expectations",
            query="q",
            item=SourceItem(
                title="t", url="https://a.example/1", score=0.3, summary="s", source=Source.YOUTUBE
            ),
        )


def test_zero_valued_bound_counts_as_an_expectation() -> None:
    case = Case(
        name="strictly off-topic",
        query="q",
        item=SourceItem(
            title="t", url="https://a.example/1", score=0.3, summary="s", source=Source.YOUTUBE
        ),
        max_relevance=0.0,
    )

    assert _has_expectation(case)


def test_sparse_case_expects_unknown_with_low_confidence() -> None:
    sparse = next(case for case in CASES if "sparse" in case.name)

    assert sparse.expected_event_types == [EventType.UNKNOWN]
    assert sparse.max_confidence == 0.50
