"""Tests for pulse.llm — no real network calls."""

from __future__ import annotations

import litellm
import pytest
from pydantic import BaseModel, ValidationError

from pulse import llm as llm_module

MODELS = ["model-a", "model-b"]


class Dummy(BaseModel):
    value: str


def _error(cls, message="boom"):
    return cls(message=message, model="m", llm_provider="openrouter")


class FakeCompletions:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        item = next(self._responses)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)
        self.chat = FakeChat(self.completions)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    # Stub out load_dotenv so these tests are hermetic regardless of a real
    # local .env file (which may itself set OPENROUTER_API_KEY).
    monkeypatch.setattr(llm_module, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")


def test_transient_error_then_success_retries(monkeypatch) -> None:
    fake = FakeClient([_error(litellm.RateLimitError), Dummy(value="ok")])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    result = llm_module.complete_structured(messages=[], models=MODELS, response_model=Dummy)

    assert result.value == "ok"
    assert fake.completions.calls == 2


def test_fallback_chain_exhausted_propagates(monkeypatch) -> None:
    fake = FakeClient([_error(litellm.NotFoundError), _error(litellm.NotFoundError)])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with pytest.raises(RuntimeError, match="exhausted"):
        llm_module.complete_structured(messages=[], models=MODELS, response_model=Dummy)

    assert fake.completions.calls == 2


def test_missing_api_key_fails_fast(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not construct a client without an API key")

    monkeypatch.setattr(llm_module.instructor, "from_litellm", _boom)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        llm_module.complete_structured(messages=[], models=MODELS, response_model=Dummy)

    assert called["n"] == 0


def test_transient_error_exhausted_propagates_without_fallback(monkeypatch) -> None:
    """A transient error is retried in place (same model) up to stop_after_attempt(3)
    times; if it never recovers, it propagates directly — it must NOT fall back to
    the next configured model, since RateLimitError is transient, not "unusable"."""
    fake = FakeClient([_error(litellm.RateLimitError) for _ in range(3)])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with pytest.raises(litellm.RateLimitError):
        llm_module.complete_structured(messages=[], models=MODELS, response_model=Dummy)

    assert fake.completions.calls == 3


def test_non_transient_exception_propagates_without_retry(monkeypatch) -> None:
    fake = FakeClient([ValidationError.from_exception_data("Dummy", [])])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with pytest.raises(ValidationError):
        llm_module.complete_structured(messages=[], models=MODELS, response_model=Dummy)

    assert fake.completions.calls == 1
