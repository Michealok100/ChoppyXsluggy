"""
models.py — Shared data models (Pydantic v2)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, field_validator


class Person(BaseModel):
    """A professional discovered through X-ray search."""

    name: str
    title: str
    company: str
    linkedin_url: str
    snippet: Optional[str] = None
    relevance_score: float = 0.0
    confidence: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    timestamp: datetime = None

    def __init__(self, **data):
        if "timestamp" not in data or data["timestamp"] is None:
            data["timestamp"] = datetime.now(timezone.utc)
        super().__init__(**data)

    @field_validator("linkedin_url")
    @classmethod
    def normalise_url(cls, v: str) -> str:
        if "?" in v:
            v = v.split("?")[0]
        v = v.rstrip("/")
        return v

    def as_telegram_block(self, index: int) -> str:
        confidence_emoji = {
            "HIGH": "✅",
            "MEDIUM": "🔵",
            "LOW": "⚠️",
        }.get(self.confidence, "❓")
        
        return (
            f"*{index}.* 👤 *{self.name}* {confidence_emoji}\n"
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
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }


class CompanyInfo(BaseModel):
    """Extracted company information from URL or domain."""
    company_name: str
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    domain: Optional[str] = None
    source: str = "unknown"  # "linkedin", "domain", "manual"


class SearchRequest(BaseModel):
    """Validated user search request."""
    name: str | None = None 
    job_title: str
    location: str
    industry: Optional[str] = None          # ← optional industry filter
    company_url: Optional[str] = None       # ← NEW: for company search
    user_id: int
    chat_id: int

    @field_validator("job_title", "location")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Field must not be empty.")
        return v

    @field_validator("industry")
    @classmethod
    def clean_industry(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v if v else None
    
    @field_validator("company_url")
    @classmethod
    def clean_company_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v if v else None


class SearchResult(BaseModel):
    """Aggregated output of a full search cycle."""

    request: SearchRequest
    people: list[Person] = []
    query_used: str = ""
    fallback_level: int = 0
    error: Optional[str] = None

    @property
    def found(self) -> bool:
        return len(self.people) > 0
