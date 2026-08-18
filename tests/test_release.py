"""When is a companion change safe to merge?

The two repositories reach users at different speeds: the backend explainer is
live the moment it merges, the Swift it describes waits on App Store review.
Merging both together produces the exact mismatch the companion exists to
prevent, inverted — the assistant describing a rule the installed app does not
implement yet.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from provenance.release import HOLD_MARKER, Release, held_since, hold_notice, is_released

MERGED = datetime(2026, 8, 18, 23, 28, 47, tzinfo=timezone.utc)


def _release(days_after: float, version: str = "3.90") -> Release:
    return Release(version=version, released_at=MERGED + timedelta(days=days_after))


class TestIsReleased:
    def test_a_build_after_the_merge_counts(self):
        assert is_released(MERGED, _release(3)) is True

    def test_the_build_users_already_had_does_not(self):
        """3.89 shipped a week before the change merged. It cannot contain it."""
        assert is_released(MERGED, _release(-7, "3.89")) is False

    def test_the_same_instant_does_not_count(self):
        """Strictly after. A release cut in the same second did not carry it,
        and being early here is the whole failure being avoided."""
        assert is_released(MERGED, _release(0)) is False

    def test_an_unreadable_app_store_holds_rather_than_releases(self):
        """A lookup failure must never be read as 'shipped'. Holding costs a
        delay; releasing early tells users something untrue."""
        assert is_released(MERGED, None) is False


class TestHoldMarker:
    def test_the_notice_round_trips(self):
        notice = hold_notice(MERGED, app="synqology", version_now="3.89")
        assert held_since(notice) == MERGED

    def test_a_body_without_a_marker_is_not_held(self):
        assert held_since("Just an ordinary pull request body.") is None
        assert held_since("") is None
        assert held_since(None) is None

    def test_the_marker_survives_a_body_edit(self):
        """Bodies get appended to. The marker must still parse."""
        notice = hold_notice(MERGED, app="synqology", version_now="3.89")
        assert held_since(notice + "\n\n---\n\nOriginal description here.") == MERGED

    def test_a_malformed_timestamp_is_not_held(self):
        assert held_since(f"<!-- {HOLD_MARKER}: not-a-date -->") is None


class TestTheNoticeExplainsItselfToAStranger:
    """Someone finds this draft months later with no memory of why it waits."""

    def test_it_says_do_not_merge(self):
        notice = hold_notice(MERGED, app="synqology", version_now="3.89")
        assert "Do not merge yet" in notice

    def test_it_names_the_version_users_are_actually_running(self):
        notice = hold_notice(MERGED, app="synqology", version_now="3.89")
        assert "3.89" in notice

    def test_it_says_what_will_release_the_hold(self):
        notice = hold_notice(MERGED, app="synqology", version_now="3.89")
        assert "App Store" in notice and "automatically" in notice

    def test_it_states_the_consequence_not_just_the_rule(self):
        notice = hold_notice(MERGED, app="synqology", version_now="3.89")
        assert "does not implement yet" in notice
