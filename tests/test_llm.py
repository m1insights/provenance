"""``call_with_quota_retry`` had zero direct tests before this: the only
coverage was indirect, through a nightly test that mocked the wrapped
function entirely. Test the wrapper itself, with the real backoff sleep
neutralized so a retry-exhaustion case doesn't cost real wall-clock time.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from provenance.llm import call_with_quota_retry, is_quota_error


class _QuotaError(RuntimeError):
    status_code = 429


class TestIsQuotaError:
    def test_status_code_429_is_a_quota_error(self):
        assert is_quota_error(_QuotaError("boom"))

    def test_resource_exhausted_message_is_a_quota_error(self):
        assert is_quota_error(RuntimeError("429 RESOURCE_EXHAUSTED: quota"))

    def test_unrelated_error_is_not_a_quota_error(self):
        assert not is_quota_error(RuntimeError("bad response"))


def _run_without_sleeping(fn):
    """Run call_with_quota_retry(fn) with tenacity's backoff sleep neutralized."""
    with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
        return asyncio.run(call_with_quota_retry(fn))


class TestCallWithQuotaRetry:
    def test_succeeds_immediately_when_the_call_does_not_raise(self):
        fn = AsyncMock(return_value="ok")
        assert _run_without_sleeping(fn) == "ok"
        assert fn.await_count == 1

    def test_retries_a_quota_error_then_returns_the_eventual_success(self):
        fn = AsyncMock(side_effect=[_QuotaError("429"), _QuotaError("429"), "ok"])
        assert _run_without_sleeping(fn) == "ok"
        assert fn.await_count == 3

    def test_reraises_the_original_error_once_attempts_are_exhausted(self):
        fn = AsyncMock(side_effect=_QuotaError("429 RESOURCE_EXHAUSTED"))
        with pytest.raises(_QuotaError):
            _run_without_sleeping(fn)
        assert fn.await_count == 4  # stop_after_attempt(4)

    def test_does_not_retry_a_non_quota_error(self):
        fn = AsyncMock(side_effect=RuntimeError("bad response"))
        with pytest.raises(RuntimeError, match="bad response"):
            _run_without_sleeping(fn)
        assert fn.await_count == 1
