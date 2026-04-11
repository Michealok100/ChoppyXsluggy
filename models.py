"""
models.py — Shared data models (Pydantic v2)

All layers (scraper, parser, bot) import from here so the shape
of a "person" record is defined in one place.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, field_validator, HttpUrl


class Person(BaseModel):
    """A professional discovered through X-ray search."""

    name: str
    title: str
    company: str
    linkedin_url: str
    snippet: Optional[str] = None          # raw Google snippet kept for debug
    relevance_score: float = 0.0           # 0-1 ranking score
    timestamp: datetime = None             # set on creation

    def __init__(self, **data):
        if "timestamp" not in data or data["timestamp"] is None:
            data["timestamp"] = datetime.now(timezone.utc)
        super().__init__(**data)

    @field_validator("linkedin_url")
    @classmethod
    def normalise_url(cls, v: str) -> str:
        """Strip query params / tracking suffixes from LinkedIn URLs."""
        if "?" in v:
            v = v.split("?")[0]
        v = v.rstrip("/")
        return v

    def as_telegram_block(self, index: int) -> str:
        """Format one person as a Telegram message block."""
        return (
            f"*{index}.* 👤 *{self.name}*\n"
            f"   💼 {self.title}\n"
            f"   🏢 {self.company}\n"
            f"   🔗 {self.linkedin_url}\n"
        )

    def as_csv_row(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "company": self.company,
            "linkedin_url": self.linkedin_url,
            "timestamp": self.timestamp.isoformat(),
        }


class SearchRequest(BaseModel):
    """Validated user search request."""

    job_title: str
    location: str
    user_id: int
    chat_id: int

    @field_validator("job_title", "location")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Field must not be empty.")
        return v


class SearchResult(BaseModel):
    """Aggregated output of a full search cycle."""

    request: SearchRequest
    people: list[Person] = []
    query_used: str = ""
    fallback_level: int = 0        # 0 = exact, 1-4 = progressive fallback
    error: Optional[str] = None

    @property
    def found(self) -> bool:
        return len(self.people) > 0
