"""Tests for pulse.llm — no real network calls."""

from __future__ import annotations

from types import SimpleNamespace

import litellm
import pytest
from instructor.core.exceptions import InstructorRetryException
from pydantic import BaseModel, ValidationError

from pulse import llm as llm_module

MODELS = ["model-a", "model-b"]


class Dummy(BaseModel):
    value: str


def _error(cls, message="boom"):
    return cls(message=message, model="m", llm_provider="openrouter")


def _completion(finish_reason="stop", error=None):
    # A minimal stand-in for litellm's ModelResponse — only the attributes
    # _check_completion_error actually reads.
    message = SimpleNamespace(content=None)
    choice = SimpleNamespace(finish_reason=finish_reason, message=message, error=error)
    return SimpleNamespace(choices=[choice], error=None)


def _openrouter_error(code, error_type, message="boom"):
    # OpenRouter's documented structured error shape:
    # {code, message, metadata: {error_type}}.
    return {"code": code, "message": message, "metadata": {"error_type": error_type}}


def _api_error(status_code):
    return litellm.APIError(
        status_code=status_code, message="boom", llm_provider="openrouter", model="m"
    )


def _wrapped(cause: BaseException) -> InstructorRetryException:
    # Mirrors what Instructor's own retry loop actually raises in production:
    # any exception from the raw API call — even a non-retryable one like
    # NotFoundError — gets caught and re-raised as InstructorRetryException(...)
    # from <cause>, never the original type. See instructor/v2/core/retry.py.
    exc = InstructorRetryException(str(cause), n_attempts=1, total_usage=0)
    exc.__cause__ = cause
    return exc


class FakeCompletions:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = 0

    def create_with_completion(self, **kwargs):
        self.calls += 1
        item = next(self._responses)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, tuple):
            return item
        return item, _completion()


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

    result = llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert result.value == "ok"
    assert fake.completions.calls == 2


def test_fallback_chain_exhausted_propagates(monkeypatch) -> None:
    fake = FakeClient([_error(litellm.NotFoundError), _error(litellm.NotFoundError)])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with pytest.raises(RuntimeError, match="exhausted"):
        llm_module.complete_structured(
            messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
        )

    assert fake.completions.calls == 2


def test_missing_api_key_fails_fast(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not construct a client without an API key")

    monkeypatch.setattr(llm_module.instructor, "from_litellm", _boom)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        llm_module.complete_structured(
            messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
        )

    assert called["n"] == 0


def test_transient_error_exhausted_propagates_without_fallback(monkeypatch) -> None:
    """A transient error is retried in place (same model) up to stop_after_attempt(3)
    times; if it never recovers, it propagates directly — it must NOT fall back to
    the next configured model, since RateLimitError is transient, not "unusable"."""
    fake = FakeClient([_error(litellm.RateLimitError) for _ in range(3)])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with pytest.raises(litellm.RateLimitError):
        llm_module.complete_structured(
            messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
        )

    assert fake.completions.calls == 3


def test_validation_error_falls_back_to_next_model(monkeypatch) -> None:
    """A ValidationError surviving Instructor's reask means "this model can't
    produce valid JSON for this schema" — a per-model defect, so fall back to
    the next configured model (without in-place retry) instead of failing the
    whole chain."""
    fake = FakeClient(
        [_wrapped(ValidationError.from_exception_data("Dummy", [])), Dummy(value="ok")]
    )
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    result = llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert result.value == "ok"
    assert fake.completions.calls == 2


def test_wrapped_fallback_error_still_falls_back_to_next_model(monkeypatch) -> None:
    """Regression: Instructor wraps every API error in InstructorRetryException
    before it reaches us, so without unwrapping, a real NotFoundError would never
    match FALLBACK_ERRORS and fallback would silently stop working in production."""
    fake = FakeClient([_wrapped(_error(litellm.NotFoundError)), Dummy(value="ok")])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    result = llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert result.value == "ok"
    assert fake.completions.calls == 2


def test_wrapped_fail_fast_error_propagates_without_fallback(monkeypatch) -> None:
    fake = FakeClient([_wrapped(_error(litellm.AuthenticationError))])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with pytest.raises(litellm.AuthenticationError):
        llm_module.complete_structured(
            messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
        )

    assert fake.completions.calls == 1


def test_wrapped_transient_error_retries_in_place(monkeypatch) -> None:
    fake = FakeClient([_wrapped(_error(litellm.RateLimitError)), Dummy(value="ok")])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    result = llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert result.value == "ok"
    assert fake.completions.calls == 2


def test_finish_reason_error_provider_unavailable_falls_back_to_next_model(monkeypatch) -> None:
    """Regression: OpenRouter can return finish_reason="error" while litellm/
    Instructor still parse a (garbage) response_model and raise nothing — that
    must NOT be treated as a successful call, and a provider_unavailable error
    must fall back to the next configured model."""
    error = _openrouter_error(502, "provider_unavailable", "upstream failed")
    fake = FakeClient(
        [
            (Dummy(value="garbage"), _completion(finish_reason="error", error=error)),
            (Dummy(value="ok"), _completion()),
        ]
    )
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    result = llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert result.value == "ok"
    assert fake.completions.calls == 2


def test_finish_reason_error_exhausted_raises_provider_completion_error(monkeypatch) -> None:
    error = _openrouter_error(502, "provider_unavailable", "upstream failed")
    fake = FakeClient(
        [
            (Dummy(value="garbage"), _completion(finish_reason="error", error=error)),
            (Dummy(value="garbage"), _completion(finish_reason="error", error=error)),
        ]
    )
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with pytest.raises(RuntimeError, match="exhausted"):
        llm_module.complete_structured(
            messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
        )

    assert fake.completions.calls == 2


def test_finish_reason_error_payment_required_fails_fast(monkeypatch) -> None:
    error = _openrouter_error(402, "payment_required", "insufficient credits")
    garbage_response = (Dummy(value="garbage"), _completion(finish_reason="error", error=error))
    fake = FakeClient([garbage_response])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with pytest.raises(llm_module.ProviderBillingError):
        llm_module.complete_structured(
            messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
        )

    assert fake.completions.calls == 1


def test_finish_reason_error_without_structured_fields_is_generic_completion_error(
    monkeypatch,
) -> None:
    """No code/error_type at all (just finish_reason: "error") must NOT be
    keyword-matched against the message — it's always a generic fallback case."""
    garbage_response = (
        Dummy(value="garbage"),
        _completion(finish_reason="error", error={"message": "insufficient credits, please pay"}),
    )
    fake = FakeClient([garbage_response, (Dummy(value="ok"), _completion())])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    result = llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert result.value == "ok"
    assert fake.completions.calls == 2


def test_api_error_status_402_reclassified_as_billing_fail_fast(monkeypatch) -> None:
    """litellm only maps OpenRouter status codes it recognizes to a specific
    exception type; 402 (insufficient credits) falls through to its generic
    APIError with status_code=402 — that must still fail fast, not propagate
    raw or get silently retried/fallback."""
    fake = FakeClient([_api_error(402)])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with pytest.raises(llm_module.ProviderBillingError):
        llm_module.complete_structured(
            messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
        )

    assert fake.completions.calls == 1


def test_api_error_status_502_reclassified_as_fallback(monkeypatch) -> None:
    fake = FakeClient([_api_error(502), Dummy(value="ok")])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    result = llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert result.value == "ok"
    assert fake.completions.calls == 2


def test_call_model_passes_request_timeout(monkeypatch) -> None:
    fake = FakeClient([Dummy(value="ok")])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)
    seen_kwargs = {}
    original = fake.completions.create_with_completion

    def _spy(**kwargs):
        seen_kwargs.update(kwargs)
        return original(**kwargs)

    fake.completions.create_with_completion = _spy

    llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert seen_kwargs["timeout"] == llm_module._REQUEST_TIMEOUT_SECONDS


def test_call_model_limits_instructor_internal_retries(monkeypatch) -> None:
    """Regression: Instructor's reask loop (client default max_retries=3,
    counting retries after the initial attempt) is separate from our tenacity
    retry. max_retries=1 caps it at one shot plus one reask — enough for a
    model to self-correct malformed JSON without multiplying requests across
    the model chain."""
    fake = FakeClient([Dummy(value="ok")])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)
    seen_kwargs = {}
    original = fake.completions.create_with_completion

    def _spy(**kwargs):
        seen_kwargs.update(kwargs)
        return original(**kwargs)

    fake.completions.create_with_completion = _spy

    llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert seen_kwargs["max_retries"] == 1


def test_complete_structured_configures_json_mode_and_global_timeout(monkeypatch) -> None:
    """Regression: Mode.TOOLS (instructor's default) makes some OpenRouter
    models/providers hang instead of erroring on a tool-call schema; Mode.JSON
    avoids that. litellm.request_timeout is set globally as a second cap in
    case a code path doesn't honor the per-call `timeout` kwarg."""
    fake = FakeClient([Dummy(value="ok")])
    seen = {}

    def _fake_from_litellm(*args, **kwargs):
        seen["mode"] = kwargs.get("mode")
        return fake

    monkeypatch.setattr(llm_module.instructor, "from_litellm", _fake_from_litellm)
    monkeypatch.setattr(llm_module.litellm, "request_timeout", None)

    llm_module.complete_structured(
        messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
    )

    assert seen["mode"] is llm_module.instructor.Mode.JSON
    assert llm_module.litellm.request_timeout == llm_module._REQUEST_TIMEOUT_SECONDS


def test_call_model_logs_elapsed_time(monkeypatch, caplog) -> None:
    fake = FakeClient([Dummy(value="ok")])
    monkeypatch.setattr(llm_module.instructor, "from_litellm", lambda *a, **k: fake)

    with caplog.at_level("DEBUG", logger=llm_module.logger.name):
        llm_module.complete_structured(
            messages=[], models=MODELS, response_model=Dummy, temperature=0.1, max_tokens=500
        )

    assert any("completed in" in record.getMessage() for record in caplog.records)
