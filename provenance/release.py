"""When is a companion change safe to merge?

The two repositories that describe synqology's scoring do not reach users at
the same speed. The Swift change waits on App Store review — days, sometimes
weeks. The backend explainer is live the moment it merges.

So merging both together, which is the obvious thing to do, produces the exact
failure the companion exists to prevent, only inverted: synqIQ starts telling
people about a rule the app they are running does not implement yet.

This module answers one question — has a build shipped since the code change
merged — so the companion can be held until then and released without anyone
having to remember why it was waiting.

It answers with a fact, not a guarantee. A release appearing after the merge
almost certainly carries it, but nothing here inspects the binary; the email
says which version and which dates, and a person confirms.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

LOOKUP_URL = "https://itunes.apple.com/lookup"

#: Written into a held companion's body. Parsed later to know what it waits on.
HOLD_MARKER = "hold-until-release-after"

_HOLD_PATTERN = re.compile(rf"<!--\s*{HOLD_MARKER}:\s*([0-9TZ:.\-+]+)\s*-->")


@dataclass(frozen=True)
class Release:
    version: str
    released_at: datetime
    name: str = ""


def live_release(bundle_id: str, *, country: str = "us") -> Release | None:
    """The version currently on the App Store, or ``None`` if unreadable.

    Deliberately the public lookup endpoint: no credentials, no App Store
    Connect key to rotate, and it reports what users can actually download
    rather than what has been approved or submitted.
    """
    try:
        response = httpx.get(
            LOOKUP_URL,
            params={"bundleId": bundle_id, "country": country},
            timeout=20.0,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
    except Exception as exc:
        log.warning("release: could not read the App Store: %s", exc)
        return None

    if not results:
        log.warning("release: no App Store entry for %s", bundle_id)
        return None

    entry = results[0]
    raw = entry.get("currentVersionReleaseDate")
    if not raw:
        return None
    try:
        released = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None

    return Release(
        version=str(entry.get("version", "")),
        released_at=released,
        name=str(entry.get("trackName", "")),
    )


def hold_notice(merged_at: datetime, *, app: str, version_now: str) -> str:
    """The block that goes in a held companion's body.

    Written for a human who finds this pull request months later with no
    memory of why it is a draft.
    """
    stamp = merged_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"<!-- {HOLD_MARKER}: {stamp} -->\n\n"
        f"## ⏸ Held until the app ships\n\n"
        f"**Do not merge yet.** This text is read aloud by synqIQ when a user "
        f"asks how their score works. The scoring change it describes merged "
        f"into the iOS trunk at `{stamp}`, but iOS changes reach users only "
        f"through App Store review — **{app} {version_now}** is what people are "
        f"running right now.\n\n"
        f"Merging this today would have the assistant describing a rule the "
        f"installed app does not implement yet. That is the same mismatch this "
        f"companion exists to prevent, pointing the other way.\n\n"
        f"Provenance watches the App Store nightly. When a build released after "
        f"`{stamp}` goes live, this is taken out of draft automatically and you "
        f"get one email saying it is safe to merge.\n"
    )


def held_since(body: str) -> datetime | None:
    """The merge timestamp a held companion is waiting past, if it is held."""
    match = _HOLD_PATTERN.search(body or "")
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    except ValueError:
        return None


def is_released(merged_at: datetime, release: Release | None) -> bool:
    """Has a build shipped since the code change merged?

    Strictly after. A release cut in the same second as the merge did not
    contain it, and being early here is the failure this whole module exists
    to avoid.
    """
    if release is None:
        return False
    return release.released_at > merged_at
