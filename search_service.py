"""
scraper/search_service.py — High-level search service.
"""

from models import Person, SearchRequest, SearchResult
from linkedin_parser import parse_organic_results
from xray_scraper import SerpAPIClient, build_fallback_queries, build_xray_query
from logger import log
from rate_limiter import rate_limiter
from session import sessions
from storage import append_results
from config import settings


def get_client() -> SerpAPIClient:
    return SerpAPIClient(api_key=settings.SERPAPI_KEY)


async def execute_search(request: SearchRequest) -> SearchResult:
    result = SearchResult(request=request)

    if sessions.is_searching(request.user_id):
        result.error = "already_searching"
        return result

    allowed, reason = rate_limiter.check(request.user_id)
    if not allowed:
        result.error = f"rate_limited:{reason}"
        return result

    sessions.mark_searching(request.user_id)
    rate_limiter.record(request.user_id)
    client = get_client()

    try:
        log.info(
            "Search started — job: '{j}' | location: '{l}' | user: {u}",
            j=request.job_title,
            l=request.location,
            u=request.user_id,
        )

        raw_results = []
        query_used = ""
        fallback_level = 0

        for query, level in build_fallback_queries(request.job_title, request.location):
            log.info("Trying query level {l}: {q}", l=level, q=query)
            raw_results = await client.search(query, pages=1)
            log.info("Raw results count: {n}", n=len(raw_results))
            query_used = query
            fallback_level = level
            if raw_results:
                break

        result.query_used = query_used
        result.fallback_level = fallback_level

        if not raw_results:
            result.error = "no_results"
            log.warning("No results after all fallbacks for '{j}'", j=request.job_title)
            return result

        people: list[Person] = parse_organic_results(
            organic_results=raw_results,
            job_title=request.job_title,
            location=request.location,
        )

        if not people:
            result.error = "parse_failed"
            log.warning("Parsing returned 0 people from {n} raw results", n=len(raw_results))
            return result

        result.people = people
        log.info(
            "Search complete — {n} people found (fallback level {l})",
            n=len(people),
            l=fallback_level,
        )

        await append_results(request.user_id, people)

    except Exception as exc:
        result.error = str(exc)
        log.exception("Unexpected error during search: {e}", e=exc)

    finally:
        sessions.record_search(
            request.user_id,
            request.job_title,
            request.location,
            len(result.people),
        )

    return result


async def execute_person_search(request: SearchRequest) -> SearchResult:
    result = SearchResult(request=request)

    if sessions.is_searching(request.user_id):
        result.error = "already_searching"
        return result

    allowed, reason = rate_limiter.check(request.user_id)
    if not allowed:
        result.error = f"rate_limited:{reason}"
        return result

    sessions.mark_searching(request.user_id)
    rate_limiter.record(request.user_id)
    client = get_client()

    try:
        query = f'site:linkedin.com/in "{request.name}" "{request.job_title}"'
        log.info("Person search query: {q}", q=query)
        raw_results = await client.search(query, pages=1)
        log.info("Person search raw results count: {n}", n=len(raw_results))
        result.query_used = query

        if not raw_results:
            result.error = "no_results"
            return result

        people = parse_organic_results(
            organic_results=raw_results,
            job_title=request.job_title,
            location="",
        )

        if not people:
            result.error = "parse_failed"
            return result

        result.people = people
        await append_results(request.user_id, people)

    except Exception as exc:
        result.error = str(exc)
        log.exception("Error during person search: {e}", e=exc)

    finally:
        sessions.record_search(
            request.user_id,
            request.job_title,
            "",
            len(result.people),
        )

    return result
