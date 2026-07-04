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

import os

import instructor
import litellm
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Transient — retried in place (same model), exponential backoff.
TRANSIENT_ERRORS = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.InternalServerError,
    litellm.ServiceUnavailableError,
)

# Current model unusable — skip retry, fall back to the next configured model.
FALLBACK_ERRORS = (
    litellm.NotFoundError,
    litellm.BadGatewayError,
)

# Never retried, never fallen back — propagate immediately.
FAIL_FAST_ERRORS = (
    litellm.AuthenticationError,
    litellm.PermissionDeniedError,
    litellm.BadRequestError,
    ValidationError,
)


def get_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set — check .env")
    return api_key


@retry(
    retry=retry_if_exception_type(TRANSIENT_ERRORS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _call_model[T: BaseModel](
    client: instructor.Instructor,
    model: str,
    messages: list[dict],
    response_model: type[T],
    api_key: str,
) -> T:
    return client.chat.completions.create(
        model=model,
        messages=messages,
        response_model=response_model,
        api_key=api_key,
    )


def complete_structured[T: BaseModel](
    messages: list[dict], models: list[str], response_model: type[T]
) -> T:
    api_key = get_api_key()
    client = instructor.from_litellm(litellm.completion)

    last_error: Exception | None = None
    for model in models:
        try:
            return _call_model(client, model, messages, response_model, api_key)
        except FAIL_FAST_ERRORS:
            raise
        except FALLBACK_ERRORS as exc:
            last_error = exc
            continue

    raise RuntimeError(f"All configured models exhausted: {models}") from last_error
