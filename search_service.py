"""
scraper/search_service.py — High-level search service.

Glues together:
  1. xray_scraper    — builds queries + fires SerpAPI requests
  2. linkedin_parser — converts raw results into Person objects
  3. storage         — persists results to CSV
  4. rate_limiter    — enforces per-user request quotas
  5. session         — tracks in-flight searches and history

This is the single import needed by the bot layer.
"""

from __future__ import annotations

from models import Person, SearchRequest, SearchResult
from parser.linkedin_parser import parse_organic_results
from scraper.xray_scraper import get_client, run_xray_search
from utils.logger import log
from utils.rate_limiter import rate_limiter
from utils.session import sessions
from utils.storage import append_results


async def execute_search(request: SearchRequest) -> SearchResult:
    """
    Run a full talent search and return a SearchResult.

    Checks rate limits and concurrent-search guards before executing.
    Guarantees no unhandled exceptions escape to the bot layer.
    """
    result = SearchResult(request=request)

    # ── Guard: already searching ──────────────────────────────────────────────
    if sessions.is_searching(request.user_id):
        result.error = "already_searching"
        return result

    # ── Guard: rate limit ─────────────────────────────────────────────────────
    allowed, reason = rate_limiter.check(request.user_id)
    if not allowed:
        result.error = f"rate_limited:{reason}"
        return result

    # ── Mark in-flight ────────────────────────────────────────────────────────
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

        # ── 1. Run X-ray search with fallback ─────────────────────────────────
        raw_results, query_used, fallback_level = await run_xray_search(
            job_title=request.job_title,
            location=request.location,
            client=client,
        )

        result.query_used = query_used
        result.fallback_level = fallback_level

        if not raw_results:
            result.error = "no_results"
            log.warning("No results after all fallbacks for '{j}'", j=request.job_title)
            return result

        # ── 2. Parse into Person objects ──────────────────────────────────────
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

        # ── 3. Persist to CSV ─────────────────────────────────────────────────
        await append_results(request.user_id, people)

    except Exception as exc:
        result.error = str(exc)
        log.exception("Unexpected error during search: {e}", e=exc)

    finally:
        # Always clear the in-flight flag and record history
        sessions.record_search(
            request.user_id,
            request.job_title,
            request.location,
            len(result.people),
        )

    return result
