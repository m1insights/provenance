"""Credential resolution.

Three environments, one function:

* **Cloud Run** -- the attached service account supplies Application Default
  Credentials from the metadata server. Nothing else is needed.
* **Local with ADC** -- ``gcloud auth application-default login`` has been run.
* **Local without ADC** -- this project's org enforces
  ``constraints/iam.disableServiceAccountKeyCreation``, so there is no key file
  to fall back to. We borrow the ``gcloud auth login`` user credential instead
  by shelling out for an access token.

The third case is a development convenience and never runs in production, where
the metadata server answers first.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import google.auth
from google.auth import credentials as ga_credentials
from google.auth.exceptions import DefaultCredentialsError

log = logging.getLogger(__name__)

_GCLOUD_CANDIDATES = (
    Path.home() / "google-cloud-sdk" / "bin" / "gcloud",
    Path("/opt/homebrew/bin/gcloud"),
    Path("/usr/local/bin/gcloud"),
)

#: gcloud access tokens last an hour; refresh early so a long sweep never
#: expires mid-flight.
_TOKEN_LIFETIME = timedelta(minutes=45)


def _gcloud_path() -> str | None:
    for candidate in _GCLOUD_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("gcloud")


class GcloudUserCredentials(ga_credentials.Credentials):
    """Access tokens borrowed from the local ``gcloud`` user login.

    Implements ``refresh`` by re-invoking gcloud, so a sweep that outlives one
    token keeps working rather than failing at an arbitrary point.
    """

    def __init__(self, gcloud: str, quota_project_id: str | None = None) -> None:
        super().__init__()
        self._gcloud = gcloud
        self._quota_project_id = quota_project_id

    def refresh(self, request) -> None:  # noqa: ARG002 - signature fixed by base class
        result = subprocess.run(
            [self._gcloud, "auth", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise DefaultCredentialsError(
                "gcloud could not mint an access token. Run "
                "`gcloud auth login`, or `gcloud auth application-default login` "
                f"and tick every consent checkbox. stderr: {result.stderr.strip()}"
            )
        self.token = result.stdout.strip()
        self.expiry = (datetime.now(timezone.utc) + _TOKEN_LIFETIME).replace(tzinfo=None)

    @property
    def quota_project_id(self) -> str | None:
        return self._quota_project_id

    def with_quota_project(self, quota_project_id: str) -> "GcloudUserCredentials":
        return GcloudUserCredentials(self._gcloud, quota_project_id)


def credentials(project: str | None = None):
    """Return usable credentials, or raise with an actionable message."""
    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        log.debug("auth: using application default credentials")
        return creds
    except DefaultCredentialsError:
        pass

    gcloud = _gcloud_path()
    if gcloud is None:
        raise DefaultCredentialsError(
            "No application default credentials and no gcloud on PATH. "
            "Install the Cloud SDK, then run `gcloud auth login`."
        )

    log.info("auth: no ADC; borrowing the gcloud user credential")
    creds = GcloudUserCredentials(gcloud, quota_project_id=project)
    creds.refresh(None)
    return creds
