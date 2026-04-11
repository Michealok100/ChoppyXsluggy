"""
parser/linkedin_parser.py — Extract structured Person records from raw
Google search result snippets returned by SerpAPI.

LinkedIn result titles typically follow one of these patterns:
    "John Doe - Bookkeeper - ABC Corp | LinkedIn"
    "Jane Smith | Senior Accountant at XYZ LLC | LinkedIn"
    "Bob Jones – Office Manager – Acme Inc."
    "Alice Brown · Project Manager · TechCo"

This module handles all common variants robustly.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from models import Person
from logger import log

# ── Regex helpers ────────────────────────────────────────────────────────────

# Separators used between name / title / company in LinkedIn titles
_SEP = re.compile(r"\s*[-–—|·•]\s*")

# Noise suffixes to strip from the raw title string
_NOISE = re.compile(
    r"\s*[\|\-–—·•]\s*(linkedin|profile|linkedin profile|view profile).*$",
    re.IGNORECASE,
)

# "at CompanyName" pattern used in newer LinkedIn titles
_AT_COMPANY = re.compile(r"\bat\s+(.+)$", re.IGNORECASE)

# Detect if a segment looks like a company (has Inc/LLC/Ltd/Corp etc.)
_COMPANY_HINT = re.compile(
    r"\b(inc|llc|ltd|corp|co|company|group|associates|partners|solutions|services|"
    r"consulting|systems|technologies|management|international)\b",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    """Strip surrounding whitespace and common punctuation artefacts."""
    return text.strip(" \t\n\r,.|–—-·•")


def parse_title_string(raw_title: str) -> tuple[str, str, str]:
    """
    Parse a LinkedIn result title into (name, job_title, company).

    Returns empty strings for fields that cannot be extracted.
    """
    # 1. Strip known noise suffixes
    title = _NOISE.sub("", raw_title).strip()

    # 2. Split on separators
    parts = [_clean(p) for p in _SEP.split(title) if _clean(p)]

    if not parts:
        return "", "", ""

    # 3. The first part is almost always the full name
    name = parts[0] if parts else ""

    # 4. Handle "Title at Company" pattern in second segment
    if len(parts) >= 2:
        at_match = _AT_COMPANY.search(parts[1])
        if at_match:
            job_title = _clean(parts[1][: at_match.start()])
            company = _clean(at_match.group(1))
            return name, job_title, company

    # 5. Standard 3-part: Name | Title | Company
    if len(parts) >= 3:
        return name, parts[1], parts[2]

    # 6. Two-part: Name | Title  (company unknown)
    if len(parts) == 2:
        return name, parts[1], "Unknown"

    return name, "", ""


def _score_relevance(person: Person, job_title: str, location: str) -> float:
    """
    Assign a 0-1 relevance score based on keyword overlap between the
    target job_title / location and the extracted record.
    """
    score = 0.0
    title_lower = person.title.lower()
    job_lower = job_title.lower()

    # Exact title match
    if job_lower == title_lower:
        score += 1.0
    # Title contains job keywords
    elif any(w in title_lower for w in job_lower.split()):
        score += 0.6
    # Partial word overlap
    elif any(w[:4] in title_lower for w in job_lower.split() if len(w) >= 4):
        score += 0.3

    return min(score, 1.0)


def parse_organic_results(
    organic_results: list[dict],
    job_title: str,
    location: str,
) -> list[Person]:
    """
    Convert a SerpAPI `organic_results` list into validated Person objects.

    Handles missing / malformed entries gracefully.
    """
    people: list[Person] = []
    seen_urls: set[str] = set()

    for result in organic_results:
        url: str = result.get("link", "")
        raw_title: str = result.get("title", "")
        snippet: str = result.get("snippet", "")

        # ── Guard: only LinkedIn profile URLs ───────────────────────────────
        if "linkedin.com/in/" not in url.lower():
            log.debug("Skipping non-profile URL: {u}", u=url)
            continue

        # ── Dedup on normalised URL ──────────────────────────────────────────
        parsed = urlparse(url)
        norm_url = f"https://www.linkedin.com{parsed.path}".rstrip("/")
        if norm_url in seen_urls:
            log.debug("Duplicate URL skipped: {u}", u=norm_url)
            continue
        seen_urls.add(norm_url)

        # ── Parse name / title / company ─────────────────────────────────────
        try:
            name, title, company = parse_title_string(raw_title)
        except Exception as exc:
            log.warning("Title parse error for '{t}': {e}", t=raw_title, e=exc)
            name, title, company = "", "", ""

        # Fallback: try to extract name from the URL slug
        if not name:
            slug = parsed.path.rstrip("/").split("/")[-1]
            name = slug.replace("-", " ").title() if slug else "Unknown"

        if not title:
            title = job_title  # best-effort: assume they match the query

        if not company:
            # Scan snippet for "at <Company>" pattern
            at_in_snippet = _AT_COMPANY.search(snippet)
            company = _clean(at_in_snippet.group(1)) if at_in_snippet else "Unknown"

        try:
            person = Person(
                name=name,
                title=title,
                company=company,
                linkedin_url=norm_url,
                snippet=snippet[:300],
            )
            person.relevance_score = _score_relevance(person, job_title, location)
            people.append(person)
            log.debug("Parsed: {n} | {t} | {c}", n=name, t=title, c=company)

        except Exception as exc:
            log.warning("Failed to create Person from result: {e}", e=exc)
            continue

    # Sort by descending relevance
    people.sort(key=lambda p: p.relevance_score, reverse=True)
    return people
