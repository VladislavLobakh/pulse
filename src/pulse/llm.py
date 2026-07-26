"""OpenRouter LLM gateway — structured completions via litellm + Instructor.

Shared gateway only: retry/fallback/fail-fast error handling and the actual
Instructor call. Callers always pass an explicit model list and sampling
params (temperature/max_tokens) — no model slug or sampling policy is
hardcoded here. Each source agent decides its own model chain per ReAct
step (e.g. reason vs observe) as plain code constants, since model slugs
aren't secrets; only the API key is a secret, so only that comes from env.

No import-time network calls: `get_api_key()` is only invoked lazily from
inside `complete_structured()`, so importing this module never requires
`.env`.
"""

from __future__ import annotations

import logging
import os
import time

import instructor
import litellm
from dotenv import load_dotenv
from instructor.core.exceptions import InstructorRetryException
from pydantic import BaseModel, ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pulse.logging_config import get_logger

logger = get_logger(__name__)

# Messages are logged at DEBUG for troubleshooting, but truncated — never log
# full prompts/responses (they can be large) and never log the API key.
_MESSAGE_LOG_CHARS = 200

# Fail fast on a hung provider rather than the ~2+ minute default HTTP timeout.
_REQUEST_TIMEOUT_SECONDS = 30


class ProviderTransientError(RuntimeError):
    """A structured OpenRouter error (or an unmapped API status code) that's
    transient — retried in place, same model, same policy as litellm's own
    RateLimitError/Timeout/ServiceUnavailableError."""


class ProviderCompletionError(RuntimeError):
    """Raised when OpenRouter reports a completion (no exception from litellm)
    that actually failed, e.g. `finish_reason == "error"` — a broken response
    Instructor would otherwise happily parse and report as a success. Also used
    for an unmapped API status code meaning "this model/provider is unusable
    right now" — fall back to the next configured model."""


class ProviderBillingError(RuntimeError):
    """A provider error tied to the OpenRouter account itself (auth, payment,
    permission) — fail fast, since retrying or falling back to another model
    won't fix an account issue."""


class ProviderConfigurationError(RuntimeError):
    """A local configuration problem (e.g. a missing API key) — not a
    provider response at all, so retrying or falling back to another model
    can't help."""


class ModelsExhaustedError(RuntimeError):
    """Every configured model failed this one request (validation or
    completion errors on all of them) — a per-request outcome, not an
    account-level problem, so it must not be treated as fail-fast."""


# OpenRouter documents structured completion errors as `finish_reason: "error"`
# with `choices[0].error = {code, message, metadata: {error_type}}`, and
# pre-stream failures as a plain HTTP status (`error.code` per the docs, or
# litellm's `status_code` on the exception). One table classifies both.
# See https://openrouter.ai/docs/api/reference/errors-and-debugging
_FAIL_FAST_STATUS_CODES = frozenset({401, 402, 403})
_FAIL_FAST_ERROR_TYPES = frozenset({"authentication", "payment_required", "permission_denied"})

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 503, 504})
_RETRYABLE_ERROR_TYPES = frozenset({"rate_limit_exceeded", "provider_overloaded", "timeout"})

_FALLBACK_STATUS_CODES = frozenset({404, 502})
_FALLBACK_ERROR_TYPES = frozenset({"provider_unavailable", "not_found"})

# Transient — retried in place (same model), exponential backoff.
TRANSIENT_ERRORS = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.InternalServerError,
    litellm.ServiceUnavailableError,
    ProviderTransientError,
)

# Current model unusable — skip retry, fall back to the next configured model.
# ValidationError: an exhausted Instructor reask means this model can't produce
# valid JSON for the schema — a per-model defect, so fall back, don't fail.
FALLBACK_ERRORS = (
    litellm.NotFoundError,
    litellm.BadGatewayError,
    ProviderCompletionError,
    ValidationError,
)

# Never retried, never fallen back — propagate immediately.
FAIL_FAST_ERRORS = (
    litellm.AuthenticationError,
    litellm.PermissionDeniedError,
    litellm.BadRequestError,
    ProviderBillingError,
    ProviderConfigurationError,
)


def get_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ProviderConfigurationError("OPENROUTER_API_KEY not set — check .env")
    return api_key


def _unwrap(exc: Exception) -> Exception:
    # Instructor wraps any error from the raw API call in
    # InstructorRetryException — without unwrapping `__cause__`, the error
    # tables above would never match a real litellm error.
    if isinstance(exc, InstructorRetryException) and isinstance(exc.__cause__, Exception):
        return exc.__cause__
    return exc


def _attr_or_key(obj: object, key: str) -> object | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _classify_error(code: int | None, error_type: str | None) -> type[RuntimeError] | None:
    """Map an OpenRouter status code / error_type to the exception class that
    encodes its retry policy — the same table drives both a litellm exception's
    `status_code` and a structured `finish_reason: "error"` completion. Returns
    None when neither is recognized (caller falls back to a generic class)."""
    if code in _FAIL_FAST_STATUS_CODES or error_type in _FAIL_FAST_ERROR_TYPES:
        return ProviderBillingError
    if code in _RETRYABLE_STATUS_CODES or error_type in _RETRYABLE_ERROR_TYPES:
        return ProviderTransientError
    if code in _FALLBACK_STATUS_CODES or error_type in _FALLBACK_ERROR_TYPES:
        return ProviderCompletionError
    return None


def _reclassify_api_error(exc: Exception) -> Exception:
    # litellm raises its own APIError only for status codes it doesn't map to a
    # specific type (for OpenRouter: notably 402 and 403, and 502) — reclassify
    # those via the same table as structured completion errors so they get the
    # right retry/fallback/fail-fast treatment instead of propagating raw.
    if not isinstance(exc, litellm.APIError):
        return exc
    exception_cls = _classify_error(getattr(exc, "status_code", None), None)
    return exception_cls(str(exc)) if exception_cls else exc


def _check_completion_error(model: str, completion: object) -> None:
    """Detect OpenRouter's structured completion error — `finish_reason:
    "error"` with `choices[0].error = {code, message, metadata: {error_type}}`
    (or `error` on the completion itself, in case a provider puts it there).
    Works with either dicts or attribute objects, since litellm may hand back
    either depending on the call path."""
    choices = _attr_or_key(completion, "choices")
    choice = choices[0] if choices else None
    if choice is None or _attr_or_key(choice, "finish_reason") != "error":
        return

    error = _attr_or_key(choice, "error") or _attr_or_key(completion, "error")
    metadata = _attr_or_key(error, "metadata")
    code = _attr_or_key(error, "code")
    error_type = _attr_or_key(metadata, "error_type")
    exception_cls = _classify_error(code, error_type) or ProviderCompletionError

    summary = f"model={model} finish_reason=error code={code} error_type={error_type}"
    if exception_cls is ProviderBillingError:
        logger.error("Provider billing/auth error: %s", summary)
    else:
        logger.warning("Provider completion error (no exception raised by litellm): %s", summary)
    message = _attr_or_key(error, "message")
    if message:
        logger.debug("Provider completion error detail: %s", message)
    raise exception_cls(summary)


def _summarize_messages(messages: list[dict]) -> str:
    parts = []
    for message in messages:
        content = str(message.get("content", ""))
        if len(content) > _MESSAGE_LOG_CHARS:
            content = content[:_MESSAGE_LOG_CHARS] + "...(truncated)"
        parts.append(f"{message.get('role')}={content!r}")
    return "; ".join(parts)


@retry(
    retry=retry_if_exception_type(TRANSIENT_ERRORS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _call_model[T: BaseModel](
    client: instructor.Instructor,
    model: str,
    messages: list[dict],
    response_model: type[T],
    api_key: str,
    temperature: float,
    max_tokens: int,
) -> T:
    started = time.monotonic()
    try:
        result, completion = client.chat.completions.create_with_completion(
            model=model,
            messages=messages,
            response_model=response_model,
            api_key=api_key,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            temperature=temperature,
            max_tokens=max_tokens,
            # One Instructor reask on invalid JSON only — API errors pass
            # through to the tenacity retry wrapping this function.
            max_retries=1,
        )
    except (InstructorRetryException, litellm.APIError) as exc:
        logger.debug("LLM call model=%s failed after %.2fs", model, time.monotonic() - started)
        raise _reclassify_api_error(_unwrap(exc)) from exc

    logger.debug("LLM call model=%s completed in %.2fs", model, time.monotonic() - started)
    _check_completion_error(model, completion)
    return result


def complete_structured[T: BaseModel](
    messages: list[dict],
    models: list[str],
    response_model: type[T],
    *,
    temperature: float,
    max_tokens: int,
) -> T:
    if not models:
        raise ProviderConfigurationError("complete_structured called with an empty model list")
    api_key = get_api_key()
    # Same cap at the litellm layer in case a call path drops the per-call
    # timeout kwarg (litellm's own default is 6000s).
    litellm.request_timeout = _REQUEST_TIMEOUT_SECONDS
    # Mode.JSON over instructor's default Mode.TOOLS: some OpenRouter
    # models/providers hang or mishandle tool-call schemas.
    client = instructor.from_litellm(litellm.completion, mode=instructor.Mode.JSON)

    last_error: Exception | None = None
    for model in models:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "LLM call model=%s response_model=%s messages=[%s]",
                model,
                response_model.__name__,
                _summarize_messages(messages),
            )
        try:
            result = _call_model(
                client, model, messages, response_model, api_key, temperature, max_tokens
            )
        except FAIL_FAST_ERRORS as exc:
            logger.warning("LLM call model=%s failed fast (%s), no retry/fallback", model, exc)
            raise
        except FALLBACK_ERRORS as exc:
            logger.warning("Model %s unusable (%s) — falling back to next model", model, exc)
            last_error = exc
            continue
        else:
            logger.debug("LLM call model=%s succeeded", model)
            return result

    logger.error("All configured models exhausted: %s", models)
    raise ModelsExhaustedError(f"All configured models exhausted: {models}") from last_error
