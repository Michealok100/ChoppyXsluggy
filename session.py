"""
utils/session.py — Per-user session state.

Tracks:
  - Whether a user has an active (in-flight) search
  - Last search parameters (for /repeat command)
  - Running count of searches performed
  - Search history (last 10 queries) for /history command

All state lives in-process. Safe for asyncio (no thread locks needed
because Python's GIL protects dict mutations, and bot handlers run
in a single event loop).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class _UserSession:
    searching: bool = False
    total_searches: int = 0
    last_job_title: str = ""
    last_location: str = ""
    history: deque = field(default_factory=lambda: deque(maxlen=10))
    # deque items: {"job_title": str, "location": str, "found": int, "ts": datetime}


class SessionManager:
    def __init__(self):
        self._sessions: dict[int, _UserSession] = {}

    def _get(self, user_id: int) -> _UserSession:
        if user_id not in self._sessions:
            self._sessions[user_id] = _UserSession()
        return self._sessions[user_id]

    # ── Search lifecycle ──────────────────────────────────────────────────────

    def mark_searching(self, user_id: int) -> None:
        self._get(user_id).searching = True

    def mark_done(self, user_id: int) -> None:
        self._get(user_id).searching = False

    def is_searching(self, user_id: int) -> bool:
        return self._get(user_id).searching

    # ── History tracking ──────────────────────────────────────────────────────

    def record_search(
        self,
        user_id: int,
        job_title: str,
        location: str,
        results_found: int,
    ) -> None:
        s = self._get(user_id)
        s.searching = False
        s.total_searches += 1
        s.last_job_title = job_title
        s.last_location = location
        s.history.appendleft(
            {
                "job_title": job_title,
                "location": location,
                "found": results_found,
                "ts": datetime.now(timezone.utc),
            }
        )

    def get_last_search(self, user_id: int) -> Optional[tuple[str, str]]:
        """Return (job_title, location) of the most recent search, or None."""
        s = self._get(user_id)
        if s.last_job_title:
            return s.last_job_title, s.last_location
        return None

    def get_history(self, user_id: int) -> list[dict]:
        return list(self._get(user_id).history)

    def get_stats(self, user_id: int) -> dict:
        s = self._get(user_id)
        return {
            "total_searches": s.total_searches,
            "last_job_title": s.last_job_title,
            "last_location": s.last_location,
        }


# Module-level singleton
sessions = SessionManager()
