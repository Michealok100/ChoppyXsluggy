"""
scraper/mock_client.py — Deterministic mock SerpAPI client.

Used when SERPAPI_KEY is set to "MOCK" in .env, or when running
pytest without real credentials.  Returns realistic-looking fixtures
so the full pipeline (parser → formatter → bot) can be tested end-to-end.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from utils.logger import log

# ── Fixture data ─────────────────────────────────────────────────────────────
# Realistic snippets modelled on real SerpAPI responses.

_FIXTURE_PROFILES: list[dict] = [
    {
        "link": "https://www.linkedin.com/in/sarah-johnson-bookkeeper",
        "title": "Sarah Johnson - Bookkeeper - ABC Construction LLC | LinkedIn",
        "snippet": "Sarah Johnson is a Bookkeeper at ABC Construction LLC in Birmingham, AL with 8 years of experience in accounts payable/receivable.",
    },
    {
        "link": "https://www.linkedin.com/in/michael-chen-cpa",
        "title": "Michael Chen | Staff Accountant at Regional Healthcare Group | LinkedIn",
        "snippet": "CPA with 5+ years handling full-cycle bookkeeping and payroll for healthcare sector clients in Birmingham, Alabama.",
    },
    {
        "link": "https://www.linkedin.com/in/emily-rodriguez-finance",
        "title": "Emily Rodriguez - Accounts Payable Specialist - Vulcan Materials | LinkedIn",
        "snippet": "AP/AR specialist and bookkeeper. 12 years experience with QuickBooks, Sage, and NetSuite. Birmingham metro area.",
    },
    {
        "link": "https://www.linkedin.com/in/james-wilson-accounting",
        "title": "James Wilson - Senior Bookkeeper - Southern Bancorp | LinkedIn",
        "snippet": "Experienced bookkeeper managing monthly close, bank reconciliations, and financial reporting at Southern Bancorp.",
    },
    {
        "link": "https://www.linkedin.com/in/patricia-davis-bookkeeping",
        "title": "Patricia Davis | Bookkeeper | Davis & Associates CPA Firm | LinkedIn",
        "snippet": "Full-charge bookkeeper at a regional CPA firm. QuickBooks ProAdvisor certified. Serving Birmingham area clients.",
    },
    {
        "link": "https://www.linkedin.com/in/robert-thompson-finance",
        "title": "Robert Thompson - Bookkeeper - Thompson Construction | LinkedIn",
        "snippet": "Owner-operator and bookkeeper at Thompson Construction. Manages all AP, AR, payroll for 45-person crew.",
    },
    {
        "link": "https://www.linkedin.com/in/linda-martinez-acctg",
        "title": "Linda Martinez | Accounting Clerk at University of Alabama Birmingham | LinkedIn",
        "snippet": "Accounting clerk and bookkeeper supporting the finance department at UAB. AIPB member.",
    },
    {
        "link": "https://www.linkedin.com/in/david-nguyen-cfo",
        "title": "David Nguyen - Controller - Protective Life Corporation | LinkedIn",
        "snippet": "CPA and Controller. Previously bookkeeper and staff accountant. Birmingham, Alabama.",
    },
    {
        "link": "https://www.linkedin.com/in/karen-white-tax",
        "title": "Karen White | Bookkeeper & Tax Preparer | H&R Block | LinkedIn",
        "snippet": "Seasonal and year-round bookkeeping, payroll, and tax services for small businesses in the Birmingham area.",
    },
    {
        "link": "https://www.linkedin.com/in/charles-brown-ap",
        "title": "Charles Brown - Accounts Payable Manager - BBVA Compass | LinkedIn",
        "snippet": "AP manager with roots in bookkeeping. 15 years in financial services in Birmingham, AL.",
    },
    {
        "link": "https://www.linkedin.com/in/jessica-taylor-qb",
        "title": "Jessica Taylor | QuickBooks Bookkeeper | Self-Employed | LinkedIn",
        "snippet": "Freelance bookkeeper serving 20+ small businesses across the Birmingham, Alabama metro area.",
    },
    {
        "link": "https://www.linkedin.com/in/mark-anderson-acctg",
        "title": "Mark Anderson - Bookkeeper - Anderson & Sons HVAC | LinkedIn",
        "snippet": "In-house bookkeeper for a family-owned HVAC company in Homewood, Alabama.",
    },
]

# Generic profiles returned when no keyword match is found
_GENERIC_PROFILES: list[dict] = [
    {
        "link": "https://www.linkedin.com/in/generic-professional-1",
        "title": "Alex Turner - {title} - General Industries | LinkedIn",
        "snippet": "Experienced {title} in the {location} area.",
    },
    {
        "link": "https://www.linkedin.com/in/generic-professional-2",
        "title": "Morgan Lee | {title} at Acme Corp | LinkedIn",
        "snippet": "Dedicated {title} with 7 years of experience. Based in {location}.",
    },
    {
        "link": "https://www.linkedin.com/in/generic-professional-3",
        "title": "Casey Williams - Senior {title} - Metro Solutions LLC | LinkedIn",
        "snippet": "{title} specializing in process improvement. {location} metro.",
    },
]


def _apply_template(profile: dict, title: str, location: str) -> dict:
    """Fill {title} and {location} placeholders in generic fixture data."""
    return {
        k: v.format(title=title, location=location) if isinstance(v, str) else v
        for k, v in profile.items()
    }


class MockSerpAPIClient:
    """
    Drop-in replacement for SerpAPIClient that returns fixture data.

    Simulates realistic network latency (0.3s) and honours the same
    interface as the real client so the rest of the pipeline is unaffected.
    """

    async def search(self, query: str, pages: int = 1) -> list[dict]:
        log.info("[MOCK] Searching: {q}", q=query[:80])
        await asyncio.sleep(0.3)   # simulate network

        # Extract job title keyword from query for relevance filtering
        title_match = re.search(r'"([^"]+)"', query)
        keyword = title_match.group(1).lower() if title_match else ""

        # Return matching fixtures if keyword overlaps
        matching = [
            p for p in _FIXTURE_PROFILES
            if keyword and (keyword in p["title"].lower() or keyword in p["snippet"].lower())
        ]

        if matching:
            # Limit to pages * 10 results
            return matching[: pages * 10]

        # Fallback: return generic profiles templated with the query keyword
        job_title = keyword or "Professional"
        location_match = re.search(r'"([^"]+,\s*[^"]+)"', query)
        location = location_match.group(1) if location_match else "your area"

        return [
            _apply_template(p, job_title.title(), location)
            for p in _GENERIC_PROFILES
        ]

    async def close(self) -> None:
        pass   # nothing to close
