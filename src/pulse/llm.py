"""OpenRouter LLM gateway — structured completions via litellm + Instructor.

Shared gateway only: retry/fallback/fail-fast error handling and the actual
Instructor call. Callers always pass an explicit model list — no model slug
is hardcoded here. Each source agent decides its own model chain per ReAct
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
# ValidationError belongs here (not fail-fast): once Instructor's reask is
# exhausted it means "this model can't produce valid JSON for this schema" — a
# per-model defect, which is exactly what the fallback chain exists for.
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
)


def get_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set — check .env")
    return api_key


def _unwrap(exc: Exception) -> Exception:
    # Instructor's own retry loop catches *any* exception raised by the raw API
    # call (see instructor/v2/core/retry.py) and wraps it in
    # InstructorRetryException(...) from <original> before it ever reaches us —
    # so without this unwrap, TRANSIENT_ERRORS/FALLBACK_ERRORS/FAIL_FAST_ERRORS
    # above never match a real litellm error. `__cause__` holds the original
    # exception Instructor chained. Non-Instructor exceptions pass through.
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
) -> T:
    started = time.monotonic()
    try:
        result, completion = client.chat.completions.create_with_completion(
            model=model,
            messages=messages,
            response_model=response_model,
            api_key=api_key,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            # Instructor's internal retry loop (client default 3) re-asks the
            # model only on validation/parse errors — API errors pass through
            # to the tenacity retry wrapping this function. max_retries counts
            # retries *after* the initial attempt, so 1 = up to two attempts:
            # one shot plus one reask, enough for a model to self-correct
            # malformed JSON without multiplying across the model chain.
            max_retries=1,
        )
    except (InstructorRetryException, litellm.APIError) as exc:
        logger.debug("LLM call model=%s failed after %.2fs", model, time.monotonic() - started)
        raise _reclassify_api_error(_unwrap(exc)) from exc

    logger.debug("LLM call model=%s completed in %.2fs", model, time.monotonic() - started)
    _check_completion_error(model, completion)
    return result


def complete_structured[T: BaseModel](
    messages: list[dict], models: list[str], response_model: type[T]
) -> T:
    api_key = get_api_key()
    # litellm defaults to a 6000s request_timeout; the explicit `timeout=` kwarg
    # on create_with_completion should already cap each call, but this global
    # sets the same cap at the litellm layer in case a code path doesn't
    # forward the per-call kwarg (e.g. it silently doesn't apply the timeout
    # library-side depending on transport). Belt and suspenders, same value.
    litellm.request_timeout = _REQUEST_TIMEOUT_SECONDS
    # Mode.TOOLS (function-calling) is instructor's default but some OpenRouter
    # models/providers handle tool-call schemas poorly or hang instead of
    # erroring — Mode.JSON asks for plain JSON output instead, which is widely
    # supported and avoids that failure mode.
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
            result = _call_model(client, model, messages, response_model, api_key)
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
    raise RuntimeError(f"All configured models exhausted: {models}") from last_error
