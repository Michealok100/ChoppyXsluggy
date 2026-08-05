"""
scraper/search_service.py — High-level search service.
"""

import re
from urllib.parse import urlparse

from models import Person, SearchRequest, SearchResult, CompanyInfo
from linkedin_parser import parse_organic_results
from xray_scraper import (
    SerpAPIClient,
    build_fallback_queries,
    build_xray_query,
    build_company_xray_queries,
    run_company_search,
    _extract_company_slug,
    get_client,
)
from logger import log
from rate_limiter import rate_limiter
from session import sessions
from storage import append_results
from config import settings
from company_resolver import extract_company_from_url, resolve_company_name_to_linkedin


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


async def execute_company_search(request: SearchRequest) -> SearchResult:
    """
    Search for employees at a company by name/URL.
    
    Process:
    1. Resolve company from URL or company name
    2. Extract LinkedIn company slug
    3. Run progressive company search with URL-based queries
    4. Validate results match target company
    5. Score confidence based on query level
    """
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
        # Step 1: Resolve company information
        company_name = request.job_title  # Fallback
        company_url = request.company_url
        company_slug = None
        
        # If company URL provided, extract info and slug
        if request.company_url:
            log.info("Resolving company from URL: {u}", u=request.company_url)
            company_info = extract_company_from_url(request.company_url)
            
            if not company_info:
                result.error = "invalid_company_url"
                log.warning("Could not parse company URL: {u}", u=request.company_url)
                return result
            
            company_name = company_info.company_name
            company_url = company_info.linkedin_url or request.company_url
            
            # Extract slug from LinkedIn URL
            if company_info.linkedin_url:
                company_slug = _extract_company_slug(company_info.linkedin_url)
        
        # Step 2: If no slug yet, try to resolve company name to LinkedIn URL
        if not company_slug and company_name:
            log.info("Resolving company name to LinkedIn URL: {c}", c=company_name)
            resolved_url = await resolve_company_name_to_linkedin(company_name)
            
            if resolved_url:
                log.info("Resolved '{c}' to: {u}", c=company_name, u=resolved_url)
                company_url = resolved_url
                company_slug = _extract_company_slug(resolved_url)
            else:
                log.warning("Could not resolve company name to LinkedIn URL: {c}", c=company_name)
                # Fall back to name-based queries (less accurate)
        
        # Step 3: Validate we have either a slug or a name
        if not company_slug and not company_name:
            result.error = "no_company_info"
            log.error("No company name or URL provided")
            return result
        
        # Step 4: Run company search
        if company_slug:
            log.info(
                "Starting company search with slug: {s} (name: {n})",
                s=company_slug,
                n=company_name,
            )
            raw_results, query_used, fallback_level = await run_company_search(
                company_slug=company_slug,
                company_name=company_name,
                client=client,
            )
        else:
            # Fallback: use name-based queries (less accurate, marked as low confidence)
            log.warning(
                "No company slug available, falling back to name-based search: {n}",
                n=company_name,
            )
            # This will use Level 3 fallback in build_company_xray_queries
            raw_results, query_used, fallback_level = await run_company_search(
                company_slug="__FALLBACK__",  # Signal that this is name-based
                company_name=company_name,
                client=client,
            )
        
        result.query_used = query_used
        result.fallback_level = fallback_level
        
        if not raw_results:
            result.error = "no_results"
            log.warning("No results for company '{c}' (slug: {s})", c=company_name, s=company_slug)
            return result
        
        # Step 5: Parse results
        people = parse_organic_results(
            organic_results=raw_results,
            job_title="",
            location="",
        )

        if not people:
            result.error = "parse_failed"
            log.warning("Parsing returned 0 people from {n} raw results", n=len(raw_results))
            return result

        # Step 6: Score confidence based on fallback level
        # Level 0 (direct company URL) = HIGH confidence
        # Level 1-2 (company URL + keywords) = MEDIUM confidence
        # Level 3+ (name-based fallback) = LOW confidence
        for person in people:
            if fallback_level == 0:
                person.confidence = "HIGH"
            elif fallback_level in (1, 2):
                person.confidence = "MEDIUM"
            else:
                person.confidence = "LOW"

        # Step 7: Deduplicate by LinkedIn URL
        seen_urls = set()
        deduplicated = []
        for person in people:
            if person.linkedin_url not in seen_urls:
                seen_urls.add(person.linkedin_url)
                deduplicated.append(person)

        result.people = deduplicated
        log.info(
            "Company search complete — {n} people found (level {l}, slug: {s})",
            n=len(result.people),
            l=fallback_level,
            s=company_slug or "NAME_BASED",
        )

        await append_results(request.user_id, result.people)

    except Exception as exc:
        result.error = str(exc)
        log.exception("Error during company search: {e}", e=exc)

    finally:
        sessions.record_search(
            request.user_id,
            request.job_title,
            "",
            len(result.people),
        )

    return result
