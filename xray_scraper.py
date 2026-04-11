"""
scraper/xray_scraper.py — Async Google X-ray search via SerpAPI.

Builds optimised LinkedIn X-ray queries, fires async HTTP requests,
applies progressive fallback on empty results, and returns raw
SerpAPI organic_results lists for the parser to process.
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
from utils.logger import log
from utils.synonyms import expand_location, get_synonyms

# ── Query builders ───────────────────────────────────────────────────────────


def build_xray_query(
    job_title: str,
    location: str,
    synonyms: Optional[list[str]] = None,
) -> str:
    """
    Construct a Google X-ray query targeting linkedin.com/in profiles.

    Format:
        site:linkedin.com/in ("primary title" OR "synonym1" OR ...) "location"
    """
    synonyms = synonyms or []

    # Build the title OR-group (max 5 terms to keep URL length sane)
    all_titles = [job_title] + synonyms[:4]
    title_group = " OR ".join(f'"{t}"' for t in all_titles)

    if len(all_titles) > 1:
        title_group = f"({title_group})"

    query = f'site:linkedin.com/in {title_group} "{location}"'
    log.debug("Built query: {q}", q=query)
    return query


def build_fallback_queries(job_title: str, location: str) -> list[tuple[str, int]]:
    """
    Return a list of (query_string, fallback_level) tuples in escalation order.

    Level 0: exact title + exact location
    Level 1: title + synonyms + exact location
    Level 2: title + synonyms + broader location
    Level 3: title + synonyms only (no location)
    """
    synonyms = get_synonyms(job_title)
    loc_variants = expand_location(location)

    queries: list[tuple[str, int]] = []

    # Level 0: exact
    queries.append((build_xray_query(job_title, location), 0))

    # Level 1: add synonyms, keep exact location
    if synonyms:
        queries.append((build_xray_query(job_title, location, synonyms), 1))

    # Level 2: synonyms + broader location variants
    for loc in loc_variants[1:]:  # skip index 0 (exact, already used)
        queries.append((build_xray_query(job_title, loc, synonyms), 2))

    # Level 3: no location at all
    queries.append((build_xray_query(job_title, "", synonyms).replace('""', "").strip(), 3))

    return queries


# ── SerpAPI client ───────────────────────────────────────────────────────────


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
        """Fetch one page of SerpAPI results. Retries on transient errors."""
        client = await self._get_client()
        params = {
            "engine": "google",
            "q": query,
            "api_key": self.api_key,
            "num": 10,          # results per page
            "start": start,
            "gl": "us",         # geo: US index
            "hl": "en",
        }
        log.debug("GET SerpAPI start={s} q={q}", s=start, q=query[:80])
        response = await client.get(settings.SERPAPI_URL, params=params)
        response.raise_for_status()
        return response.json()

    async def search(self, query: str, pages: int = 1) -> list[dict]:
        """
        Run a search across *pages* pages, returning merged organic_results.
        """
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
                log.debug("No organic results on page {p}", p=page + 1)
                break

            all_results.extend(organic)
            log.info("Page {p}: got {n} results", p=page + 1, n=len(organic))

            # Rate-limit courtesy delay
            if page < pages - 1:
                await asyncio.sleep(settings.REQUEST_DELAY)

        return all_results


# ── High-level search orchestrator ───────────────────────────────────────────


async def run_xray_search(
    job_title: str,
    location: str,
    client: SerpAPIClient,
    max_results: int = 15,
) -> tuple[list[dict], str, int]:
    """
    Execute X-ray search with progressive fallback.

    Returns:
        (raw_organic_results, query_used, fallback_level)
    """
    candidate_queries = build_fallback_queries(job_title, location)

    for query, level in candidate_queries:
        if not query.strip():
            continue

        log.info(
            "Trying fallback level {l}: {q}",
            l=level,
            q=query[:100],
        )

        raw_results = await client.search(query, pages=settings.SEARCH_PAGES)

        if raw_results:
            # Trim to max_results before returning
            return raw_results[:max_results], query, level

        log.info("No results at level {l}, escalating...", l=level)
        await asyncio.sleep(settings.REQUEST_DELAY)

    return [], "", 4  # level 4 = total failure


# ── Module-level convenience singleton ──────────────────────────────────────
# Instantiated once at import time; shared across all bot handlers.
# Set SERPAPI_KEY=MOCK in .env to use the deterministic mock client.
_serpapi_client = None


def get_client():
    """Return the appropriate SerpAPI client (real or mock)."""
    global _serpapi_client
    if _serpapi_client is None:
        if settings.SERPAPI_KEY.upper() == "MOCK":
            from scraper.mock_client import MockSerpAPIClient
            log.warning("Using MOCK SerpAPI client — no real searches will be made.")
            _serpapi_client = MockSerpAPIClient()
        else:
            _serpapi_client = SerpAPIClient(settings.SERPAPI_KEY)
    return _serpapi_client
