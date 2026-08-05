"""
scraper/xray_scraper.py — Async Google X-ray search via SerpAPI.

Builds optimised LinkedIn X-ray queries with optional industry filter,
fires async HTTP requests, applies progressive fallback on empty results.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional
from urllib.parse import urlparse

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


# ── Query builders ────────────────────────────────────────────────────────────

def build_xray_query(
    job_title: str,
    location: str,
    synonyms: Optional[list[str]] = None,
    industry: Optional[str] = None,
) -> str:
    synonyms = synonyms or []

    all_titles = [job_title] + synonyms[:4]
    title_group = " OR ".join(f'"{t}"' for t in all_titles)
    if len(all_titles) > 1:
        title_group = f"({title_group})"

    location_term = f'"{location}"' if location else ""
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
    synonyms = get_synonyms(job_title)
    loc_variants = expand_location(location)

    queries: list[tuple[str, int]] = []

    queries.append((build_xray_query(job_title, location, industry=industry), 0))

    if synonyms:
        queries.append((build_xray_query(job_title, location, synonyms, industry=industry), 1))

    for loc in loc_variants[1:]:
        queries.append((build_xray_query(job_title, loc, synonyms, industry=industry), 2))

    if industry:
        queries.append((build_xray_query(job_title, "", synonyms, industry=industry), 3))

    queries.append((build_xray_query(job_title, "", synonyms, industry=None), 4))

    return queries


def _extract_company_slug(company_url: str) -> str | None:
    """
    Extract company slug from LinkedIn company URL.
    
    Example: "https://www.linkedin.com/company/google/" → "google"
    """
    if not company_url or "linkedin.com/company/" not in company_url.lower():
        return None
    
    try:
        parsed = urlparse(company_url)
        path = parsed.path.rstrip("/")
        
        # Extract slug between /company/ and trailing /
        match = re.search(r"/company/([^/]+)", path)
        if match:
            return match.group(1)
    except Exception as exc:
        log.warning("Error extracting company slug from {u}: {e}", u=company_url, e=exc)
    
    return None


def build_company_xray_queries(
    company_slug: str,
    company_name: Optional[str] = None,
) -> list[tuple[str, int]]:
    """Build progressive company X-ray queries using company slug/LinkedIn URL.
    
    ✅ Level 0: site:linkedin.com/company/google (only employees at that company)
    ✅ Level 1: site:linkedin.com/company/google with "employee" keyword
    ✅ Level 2: site:linkedin.com/company/google with seniority keywords
    ✅ Level 3: Fallback to name-based search if slug fails
    
    Args:
        company_slug: LinkedIn company slug (e.g., "google", "apple-inc")
        company_name: Human-readable company name (used as fallback)
    
    Returns:
        List of (query, fallback_level) tuples
    """
    if not company_slug or not company_slug.strip():
        log.warning("Empty company slug provided")
        return []
    
    company_slug = company_slug.strip().lower()
    queries: list[tuple[str, int]] = []
    
    # ✅ Level 0: Base company page query (most specific)
    # This ONLY matches people who explicitly list this company on their profile
    base_query = f'site:linkedin.com/company/{company_slug}/'
    queries.append((base_query, 0))
    
    # ✅ Level 1: Company page + "employee" keyword
    # Filters for people who mention they work there
    employee_query = f'site:linkedin.com/company/{company_slug}/ "employee"'
    queries.append((employee_query, 1))
    
    # ✅ Level 2: Company page + seniority/current keywords
    # Targets managers, directors, leads, etc.
    seniority_query = (
        f'site:linkedin.com/company/{company_slug}/ '
        f'("manager" OR "director" OR "engineer" OR "senior" OR "lead")'
    )
    queries.append((seniority_query, 2))
    
    # ✅ Level 3: Fallback to company name search if slug-based search fails
    # Only if company_name provided
    if company_name and company_name.strip():
        name_query = f'site:linkedin.com/in "{company_name.strip()}"'
        queries.append((name_query, 3))
    
    log.debug(
        "Built {n} company queries for slug '{s}'",
        n=len(queries),
        s=company_slug,
    )
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
            data = None
            try:
                data = await self._fetch_page(query, start)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    log.warning("SerpAPI rate limit hit — waiting 30s")
                    await asyncio.sleep(30)
                    try:
                        data = await self._fetch_page(query, start)
                    except Exception as retry_exc:
                        log.error("SerpAPI retry failed: {e}", e=retry_exc)
                        break
                else:
                    log.error("SerpAPI HTTP error: {e}", e=exc)
                    break
            except Exception as exc:
                log.error("SerpAPI request failed: {e}", e=exc)
                break

            if data is None:
                break

            organic = data.get("organic_results", [])
            if not organic:
                log.info("No organic results on page {p}", p=page + 1)
                break

            all_results.extend(organic)
            log.info("Page {p}: got {n} results", p=page + 1, n=len(organic))

            if page < pages - 1:
                await asyncio.sleep(settings.REQUEST_DELAY)

        return all_results


# ── High-level search orchestrators ──────────────────────────────────────────

async def run_xray_search(
    job_title: str,
    location: str,
    client,
    max_results: int = 15,
    industry: Optional[str] = None,
) -> tuple[list[dict], str, int]:
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

    return [], "", 5


async def run_company_search(
    company_slug: str,
    company_name: Optional[str] = None,
    client=None,
    max_results: int = 15,
) -> tuple[list[dict], str, int]:
    """
    High-level orchestrator for company employee search.
    
    Tries progressive query levels:
    Level 0: Direct company slug search (most accurate)
    Level 1: Company slug + "employee" keyword
    Level 2: Company slug + seniority keywords
    Level 3: Fallback to company name search
    
    Args:
        company_slug: LinkedIn company slug (e.g., "google", "apple-inc")
        company_name: Human-readable company name (used as fallback)
        client: SerpAPIClient instance
        max_results: Max results to return
    
    Returns:
        (raw_results, query_used, fallback_level)
    """
    if client is None:
        client = get_client()
    
    if not company_slug or not company_slug.strip():
        log.error("Company slug is required for company search")
        return [], "", -1
    
    candidate_queries = build_company_xray_queries(company_slug, company_name)
    
    if not candidate_queries:
        log.error("No company queries generated for slug: {s}", s=company_slug)
        return [], "", -1
    
    for query, level in candidate_queries:
        if not query.strip():
            continue
        
        log.info("Company search level {l}: {q}", l=level, q=query[:100])
        raw_results = await client.search(query, pages=settings.SEARCH_PAGES)
        log.info("Level {l} returned {n} results", l=level, n=len(raw_results))
        
        if raw_results:
            return raw_results[:max_results], query, level
        
        log.info("No results at level {l}, escalating...", l=level)
        await asyncio.sleep(settings.REQUEST_DELAY)
    
    log.warning("No results found at any level for company: {s}", s=company_slug)
    return [], "", len(candidate_queries)


# ── Module-level singleton ────────────────────────────────────────────────────

_serpapi_client = None


def get_client():
    global _serpapi_client
    if _serpapi_client is None:
        if settings.SERPAPI_KEY.upper() == "MOCK":
            from mock_client import MockSerpAPIClient
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
    raw_results = await client.search(query)
    return raw_results, query


async def run_domain_search(
    domain: str,
    client,
) -> tuple[list[dict], str]:
    """X-ray search for all employees at a company by domain."""
    company = domain.replace("www.", "").split(".")[0]
    query = f'site:linkedin.com/in "{domain}" OR "{company}"'
    log.info("Domain search query: {q}", q=query)
    raw_results = await client.search(query)
    return raw_results, query
