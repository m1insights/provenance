"""Model construction for ADK agents.

ADK builds its own ``google.genai.Client`` from environment variables, which
assumes Application Default Credentials are available. This project runs
against an organisation that forbids service-account keys, and its ADC consent
flow is not reliably available, so credentials are resolved by
``provenance.auth`` and injected through ``Gemini.client_kwargs``.

Also pins the serving location. Gemini 3.5+ models are *listed* under regional
endpoints but only answer on ``global``; pointing generation at ``us-central1``
returns 404 for a model that region reports as available.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Awaitable, Callable, TypeVar

from google.adk.models.google_llm import Gemini
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from . import auth
from .config import settings

log = logging.getLogger(__name__)

T = TypeVar("T")

_QUOTA_MESSAGE = re.compile(
    r"(?:"
    r"\bHTTP(?:\s+STATUS)?\s*[:=]?\s*429\b"
    r"|\bSTATUS(?:\s+CODE)?\s*[:=]?\s*429\b"
    r"|\b429\s+(?:TOO\s+MANY\s+REQUESTS|RESOURCE[_\s-]*EXHAUSTED|QUOTA\s+(?:EXCEEDED|EXHAUSTED))\b"
    r"|\bRESOURCE[_\s-]*EXHAUSTED\b"
    r"|\bQUOTA\s+(?:EXCEEDED|EXHAUSTED)\b"
    r")",
    re.IGNORECASE,
)


def _is_quota_status(value: object) -> bool:
    if callable(value):
        try:
            value = value()
        except Exception:
            return False
    if value is None:
        return False
    if isinstance(value, int) and not isinstance(value, bool):
        return value == 429

    normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    return normalized == "429" or normalized.endswith("RESOURCEEXHAUSTED")


def is_quota_error(exc: BaseException) -> bool:
    """Return whether a model-provider exception represents exhausted quota."""
    for attribute in ("status_code", "code", "status"):
        try:
            if _is_quota_status(getattr(exc, attribute, None)):
                return True
        except Exception:
            continue

    try:
        message = str(exc)
    except Exception:
        return False
    return bool(_QUOTA_MESSAGE.search(message))


async def call_with_quota_retry(fn: Callable[[], Awaitable[T]]) -> T:
    """Run ``fn`` once, retrying only 429 quota exhaustion, with backoff.

    A single busy night otherwise costs the whole stage: the model's per-minute
    quota is shared across every stage in the same run, so triage and appraisal
    can spend it before synthesis gets a turn. Waiting a few minutes and trying
    again is usually enough for the per-minute budget to refill -- no retry
    existed anywhere in this path before, so a transient 429 always fell
    straight through to the fail-soft "did not finish tonight" outcome. Any
    other exception is not retried; it is not a capacity problem.
    """

    @retry(
        retry=retry_if_exception(is_quota_error),
        wait=wait_exponential(multiplier=30, max=180),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _attempt() -> T:
        return await fn()

    return await _attempt()


@lru_cache(maxsize=8)
def model(name: str) -> Gemini:
    """An ADK model handle wired to this project's credentials.

    Cached per model name so a fleet of agents shares one client rather than
    minting a token per agent.
    """
    cfg = settings()

    if not cfg.use_vertex:
        if not cfg.google_api_key:
            raise RuntimeError(
                "No Gemini credentials. Either set GOOGLE_API_KEY, or set "
                "GOOGLE_GENAI_USE_VERTEXAI=true and run `gcloud auth login`."
            )
        return Gemini(model=name, client_kwargs={"api_key": cfg.google_api_key})

    return Gemini(
        model=name,
        client_kwargs={
            "vertexai": True,
            "project": cfg.gcp_project,
            "location": cfg.gemini_location,
            "credentials": auth.credentials(cfg.gcp_project),
        },
    )
