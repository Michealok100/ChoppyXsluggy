"""
utils/rate_limiter.py — In-memory per-user rate limiter.

Prevents a single user from hammering SerpAPI by enforcing:
  - Max N searches per rolling time window
  - Minimum cooldown between consecutive searches

All state is in-process (no Redis needed for single-instance deployments).
For multi-instance deployments, swap _store for a shared cache.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from utils.logger import log


@dataclass
class _UserBucket:
    """Sliding-window token bucket for one user."""
    timestamps: deque = field(default_factory=deque)   # recent search timestamps
    last_search: float = 0.0                            # epoch of last search


class RateLimiter:
    """
    Sliding-window rate limiter.

    Args:
        max_requests:  max searches allowed in `window_seconds`
        window_seconds: rolling window size
        cooldown_seconds: minimum gap between any two searches
    """

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 3600,      # 1 hour
        cooldown_seconds: float = 5.0,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._store: dict[int, _UserBucket] = defaultdict(_UserBucket)

    def _bucket(self, user_id: int) -> _UserBucket:
        return self._store[user_id]

    def check(self, user_id: int) -> tuple[bool, Optional[str]]:
        """
        Check whether *user_id* is allowed to search right now.

        Returns:
            (allowed: bool, reason: str | None)
        """
        now = time.monotonic()
        bucket = self._bucket(user_id)

        # ── Cooldown check ────────────────────────────────────────────────────
        elapsed = now - bucket.last_search
        if bucket.last_search > 0 and elapsed < self.cooldown_seconds:
            wait = round(self.cooldown_seconds - elapsed, 1)
            return False, f"Please wait {wait}s before searching again."

        # ── Sliding window check ──────────────────────────────────────────────
        cutoff = now - self.window_seconds
        while bucket.timestamps and bucket.timestamps[0] < cutoff:
            bucket.timestamps.popleft()

        if len(bucket.timestamps) >= self.max_requests:
            oldest = bucket.timestamps[0]
            reset_in = round(oldest + self.window_seconds - now)
            return False, (
                f"Search limit reached ({self.max_requests} per hour). "
                f"Resets in {reset_in}s."
            )

        return True, None

    def record(self, user_id: int) -> None:
        """Record that *user_id* performed a search right now."""
        now = time.monotonic()
        bucket = self._bucket(user_id)
        bucket.timestamps.append(now)
        bucket.last_search = now
        log.debug("Rate bucket for {uid}: {n} in window", uid=user_id, n=len(bucket.timestamps))

    def stats(self, user_id: int) -> dict:
        """Return current usage stats for a user (for /status command)."""
        now = time.monotonic()
        bucket = self._bucket(user_id)
        cutoff = now - self.window_seconds
        recent = sum(1 for t in bucket.timestamps if t >= cutoff)
        return {
            "searches_in_window": recent,
            "max_per_window": self.max_requests,
            "window_hours": self.window_seconds // 3600,
            "remaining": max(0, self.max_requests - recent),
        }


# Module-level singleton
rate_limiter = RateLimiter(
    max_requests=10,
    window_seconds=3600,
    cooldown_seconds=5.0,
)
