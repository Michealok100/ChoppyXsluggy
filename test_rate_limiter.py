"""
tests/test_rate_limiter.py — Tests for rate limiter and session manager.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from utils.rate_limiter import RateLimiter
from utils.session import SessionManager


# ── RateLimiter ───────────────────────────────────────────────────────────────

class TestRateLimiter:
    def _limiter(self, max_req=5, window=60, cooldown=0.1):
        return RateLimiter(max_requests=max_req, window_seconds=window, cooldown_seconds=cooldown)

    def test_first_request_allowed(self):
        rl = self._limiter()
        allowed, reason = rl.check(user_id=1)
        assert allowed is True
        assert reason is None

    def test_record_and_check(self):
        # cooldown=0 so consecutive records do not block each other
        rl = RateLimiter(max_requests=3, window_seconds=60, cooldown_seconds=0)
        for _ in range(3):
            allowed, _ = rl.check(1)
            assert allowed
            rl.record(1)
        # 4th should be blocked by window limit
        allowed, reason = rl.check(1)
        assert allowed is False
        assert "limit" in reason.lower()

    def test_cooldown_enforced(self):
        rl = self._limiter(cooldown=60)
        rl.record(1)
        allowed, reason = rl.check(1)
        assert allowed is False
        assert "wait" in reason.lower()

    def test_cooldown_expires(self):
        rl = self._limiter(cooldown=0.05)
        rl.record(2)
        time.sleep(0.1)
        allowed, _ = rl.check(2)
        assert allowed is True

    def test_different_users_independent(self):
        rl = self._limiter(max_req=1)
        rl.record(10)
        rl.check(10)   # user 10 used their quota
        allowed, _ = rl.check(20)   # user 20 unaffected
        assert allowed is True

    def test_stats_returns_correct_counts(self):
        rl = self._limiter(max_req=10)
        rl.record(99)
        rl.record(99)
        stats = rl.stats(99)
        assert stats["searches_in_window"] == 2
        assert stats["remaining"] == 8
        assert stats["max_per_window"] == 10

    def test_window_slides(self):
        # Use a very short window so we can test expiry
        rl = RateLimiter(max_requests=2, window_seconds=1, cooldown_seconds=0)
        rl.record(5)
        rl.record(5)
        # Both slots used; window hasn't expired yet
        allowed, _ = rl.check(5)
        assert allowed is False
        time.sleep(1.1)
        # Window has slid past both timestamps
        allowed, _ = rl.check(5)
        assert allowed is True


# ── SessionManager ────────────────────────────────────────────────────────────

class TestSessionManager:
    def _sm(self):
        return SessionManager()

    def test_not_searching_initially(self):
        sm = self._sm()
        assert sm.is_searching(1) is False

    def test_mark_searching_and_done(self):
        sm = self._sm()
        sm.mark_searching(1)
        assert sm.is_searching(1) is True
        sm.mark_done(1)
        assert sm.is_searching(1) is False

    def test_record_search_clears_flag(self):
        sm = self._sm()
        sm.mark_searching(1)
        sm.record_search(1, "bookkeeper", "Alabama", 5)
        assert sm.is_searching(1) is False

    def test_get_last_search(self):
        sm = self._sm()
        sm.record_search(1, "nurse", "Texas", 3)
        result = sm.get_last_search(1)
        assert result == ("nurse", "Texas")

    def test_no_last_search_returns_none(self):
        sm = self._sm()
        assert sm.get_last_search(42) is None

    def test_history_newest_first(self):
        sm = self._sm()
        sm.record_search(1, "alpha", "CA", 1)
        sm.record_search(1, "beta", "NY", 2)
        history = sm.get_history(1)
        assert history[0]["job_title"] == "beta"
        assert history[1]["job_title"] == "alpha"

    def test_history_capped_at_10(self):
        sm = self._sm()
        for i in range(15):
            sm.record_search(1, f"role{i}", "USA", i)
        assert len(sm.get_history(1)) == 10

    def test_stats_increments(self):
        sm = self._sm()
        sm.record_search(1, "dev", "TX", 5)
        sm.record_search(1, "dev", "TX", 3)
        stats = sm.get_stats(1)
        assert stats["total_searches"] == 2

    def test_independent_users(self):
        sm = self._sm()
        sm.mark_searching(1)
        assert sm.is_searching(2) is False


# ── MockSerpAPIClient ─────────────────────────────────────────────────────────

class TestMockClient:
    @pytest.mark.asyncio
    async def test_returns_results_for_known_title(self):
        from scraper.mock_client import MockSerpAPIClient
        client = MockSerpAPIClient()
        results = await client.search('site:linkedin.com/in "bookkeeper" "Birmingham, Alabama"')
        assert len(results) > 0
        assert all("linkedin.com/in" in r["link"] for r in results)

    @pytest.mark.asyncio
    async def test_returns_generic_results_for_unknown_title(self):
        from scraper.mock_client import MockSerpAPIClient
        client = MockSerpAPIClient()
        results = await client.search('site:linkedin.com/in "xyzunknownrole123"')
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_pages_respected(self):
        from scraper.mock_client import MockSerpAPIClient
        client = MockSerpAPIClient()
        r1 = await client.search('site:linkedin.com/in "bookkeeper"', pages=1)
        r2 = await client.search('site:linkedin.com/in "bookkeeper"', pages=2)
        # With pages=2 we allow up to 20; pages=1 allows up to 10
        assert len(r1) <= 10
        assert len(r2) <= 20


# ── Full pipeline smoke test (mock mode) ─────────────────────────────────────

class TestFullPipelineMock:
    @pytest.mark.asyncio
    async def test_search_returns_people(self, tmp_path, monkeypatch):
        """End-to-end: mock client → parser → Person list."""
        import os
        # Point DATA_DIR at tmp so CSV doesn't pollute project
        monkeypatch.setenv("SERPAPI_KEY", "MOCK")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        # Reset module-level singletons
        import scraper.xray_scraper as xs
        xs._serpapi_client = None
        import config
        config.settings.SERPAPI_KEY = "MOCK"
        config.settings.DATA_DIR = tmp_path

        from models import SearchRequest
        from scraper.search_service import execute_search

        request = SearchRequest(
            job_title="bookkeeper",
            location="Birmingham, Alabama",
            user_id=999,
            chat_id=999,
        )
        result = await execute_search(request)

        assert result.error is None or result.error == ""
        assert result.found
        assert all(hasattr(p, "name") for p in result.people)
        assert all("linkedin.com/in" in p.linkedin_url for p in result.people)

        # CSV should have been written
        csv_file = tmp_path / "results_999.csv"
        assert csv_file.exists()
        content = csv_file.read_text()
        assert "name" in content   # header row


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
