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

from google.adk.models.google_llm import Gemini

from . import auth
from .config import settings

log = logging.getLogger(__name__)

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
