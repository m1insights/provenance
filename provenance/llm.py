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
from functools import lru_cache

from google.adk.models.google_llm import Gemini

from . import auth
from .config import settings

log = logging.getLogger(__name__)


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
