"""
scraper/xray_scraper.py — Async Google X-ray search via SerpAPI.

Builds optimised LinkedIn X-ray queries with optional industry filter,
fires async HTTP requests, applies progressive fallback on empty results.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings
from industries import build_industry_query_fragment
from logger import log
from synonyms import expand_location, get_synonyms
from search_service import run_person_search  # only if needed cross-file

# ── Query builders ────────────────────────────────────────────────────────────

def build_xray_query(
    job_title: str,
    location: str,
    synonyms: Optional[list[str]] = None,
    industry: Optional[str] = None,
) -> str:
    """
    Construct a Google X-ray query targeting linkedin.com/in profiles.

    Format (no industry):
        site:linkedin.com/in ("bookkeeper" OR "accounts payable") "Birmingham, Alabama"

    Format (with industry):
        site:linkedin.com/in ("bookkeeper" OR "accounts payable") "Birmingham, Alabama" ("healthcare" OR "hospital")
    """
    synonyms = synonyms or []

    # Title OR-group (max 5 terms)
    all_titles = [job_title] + synonyms[:4]
    title_group = " OR ".join(f'"{t}"' for t in all_titles)
    if len(all_titles) > 1:
        title_group = f"({title_group})"

    # Location term
    location_term = f'"{location}"' if location else ""

    # Industry fragment (optional)
    industry_fragment = build_industry_query_fragment(industry) if industry else ""

    parts = ["site:linkedin.com/in", title_group]
    if location_term:
        parts.append(location_term)
    if industry_fragment:
        parts.append(industry_fragment)

    query = " ".join(parts)
    log.debug("Built query: {q}", q=query)
    return query


def build_fallback_queries(
    job_title: str,
    location: str,
    industry: Optional[str] = None,
) -> list[tuple[str, int]]:
    """
    Return (query_string, fallback_level) tuples in escalation order.

    Level 0: exact title + exact location + industry
    Level 1: title + synonyms + exact location + industry
    Level 2: title + synonyms + broader location + industry
    Level 3: title + synonyms + industry (no location)
    Level 4: title + synonyms only (no location, no industry)
    """
    synonyms = get_synonyms(job_title)
    loc_variants = expand_location(location)

    queries: list[tuple[str, int]] = []

    # Level 0: exact
    queries.append((build_xray_query(job_title, location, industry=industry), 0))

    # Level 1: add synonyms, keep exact location + industry
    if synonyms:
        queries.append((build_xray_query(job_title, location, synonyms, industry=industry), 1))

    # Level 2: synonyms + broader location + industry
    for loc in loc_variants[1:]:
        queries.append((build_xray_query(job_title, loc, synonyms, industry=industry), 2))

    # Level 3: no location but keep industry
    if industry:
        queries.append((build_xray_query(job_title, "", synonyms, industry=industry), 3))

    # Level 4: no location, no industry (widest net)
    queries.append((build_xray_query(job_title, "", synonyms, industry=None), 4))

    return queries


# ── SerpAPI client ────────────────────────────────────────────────────────────

class SerpAPIClient:
    """Async wrapper around SerpAPI's /search endpoint."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _fetch_page(self, query: str, start: int = 0) -> dict:
        client = await self._get_client()
        params = {
            "engine": "google",
            "q": query,
            "api_key": self.api_key,
            "num": 10,
            "start": start,
            "gl": "us",
            "hl": "en",
        }
        log.debug("GET SerpAPI start={s} q={q}", s=start, q=query[:80])
        response = await client.get(settings.SERPAPI_URL, params=params)
        response.raise_for_status()
        return response.json()

    async def search(self, query: str, pages: int = 1) -> list[dict]:
        all_results: list[dict] = []

        for page in range(pages):
            start = page * 10
            try:
                data = await self._fetch_page(query, start)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    log.warning("SerpAPI rate limit hit — waiting 30s")
                    await asyncio.sleep(30)
                    data = await self._fetch_page(query, start)
                else:
                    log.error("SerpAPI HTTP error: {e}", e=exc)
                    break
            except Exception as exc:
                log.error("SerpAPI request failed: {e}", e=exc)
                break

            organic = data.get("organic_results", [])
            if not organic:
                break

            all_results.extend(organic)
            log.info("Page {p}: got {n} results", p=page + 1, n=len(organic))

            if page < pages - 1:
                await asyncio.sleep(settings.REQUEST_DELAY)

        return all_results


# ── High-level search orchestrator ────────────────────────────────────────────

async def run_xray_search(
    job_title: str,
    location: str,
    client,
    max_results: int = 15,
    industry: Optional[str] = None,
) -> tuple[list[dict], str, int]:
    """
    Execute X-ray search with progressive fallback.

    Returns:
        (raw_organic_results, query_used, fallback_level)
    """
    candidate_queries = build_fallback_queries(job_title, location, industry=industry)

    for query, level in candidate_queries:
        if not query.strip():
            continue

        log.info("Trying fallback level {l}: {q}", l=level, q=query[:100])
        raw_results = await client.search(query, pages=settings.SEARCH_PAGES)

        if raw_results:
            return raw_results[:max_results], query, level

        log.info("No results at level {l}, escalating...", l=level)
        await asyncio.sleep(settings.REQUEST_DELAY)

    return [], "", 5   # level 5 = total failure


# ── Module-level singleton ────────────────────────────────────────────────────

_serpapi_client = None


def get_client():
    global _serpapi_client
    if _serpapi_client is None:
        if settings.SERPAPI_KEY.upper() == "MOCK":
            from scraper.mock_client import MockSerpAPIClient
            log.warning("Using MOCK SerpAPI client.")
            _serpapi_client = MockSerpAPIClient()
        else:
            _serpapi_client = SerpAPIClient(settings.SERPAPI_KEY)
    return _serpapi_client

async def run_person_search(
    name: str,
    job_title: str,
    client,
) -> tuple[list[dict], str]:
    """X-ray search for a specific person by name + job title."""
    query = f'site:linkedin.com/in "{name}" "{job_title}"'
    log.info("Person search query: {q}", q=query)
    raw = await asyncio.to_thread(client.search, query)
    organic = raw.get("organic_results", [])
    return organic, query
