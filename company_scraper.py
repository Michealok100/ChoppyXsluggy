"""
company_scraper.py — Scrape company websites for team member information.

Lightweight parsing with BeautifulSoup.
Targets common team/about/leadership pages.
No full-site crawling; just ~5 likely pages.
"""

from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from logger import log


# Common team page URLs to try
TEAM_PAGE_PATHS = [
    "/team",
    "/our-team",
    "/staff",
    "/about",
    "/leadership",
    "/providers",
    "/people",
    "/team-members",
    "/about-us",
    "/leadership-team",
]


class CompanyScraper:
    """Lightweight company website scraper."""

    def __init__(
        self,
        timeout: float = 10.0,
        max_pages: int = 5,
    ):
        self.timeout = timeout
        self.max_pages = max_pages
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,  # Strict: only fetch the exact page
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def scrape_team_pages(self, domain: str) -> list[dict]:
        """
        Scrape team pages from a company website.

        Args:
            domain: Company domain (e.g., "examplecompany.com")

        Returns:
            List of discovered people: [{"name": str, "title": str, "url": str}, ...]
        """
        if not domain:
            return []

        # Normalize domain
        domain = domain.replace("www.", "").strip()
        base_url = f"https://{domain}"

        client = await self._get_client()
        people = []
        pages_tried = 0

        for path in TEAM_PAGE_PATHS[:self.max_pages]:
            if pages_tried >= self.max_pages:
                break

            url = urljoin(base_url, path)
            pages_tried += 1

            try:
                log.debug("Scraping team page: {u}", u=url)
                response = await client.get(url)

                # Only process 2xx responses
                if response.status_code < 200 or response.status_code >= 300:
                    log.debug(
                        "Team page not found: {u} ({s})",
                        u=url,
                        s=response.status_code,
                    )
                    continue

                html = response.text
                discovered = _parse_team_page(html)

                if discovered:
                    log.info("Found {n} people on {u}", n=len(discovered), u=url)
                    people.extend(discovered)
                    # If we found people, stop searching other pages
                    break

            except asyncio.TimeoutError:
                log.warning("Timeout scraping: {u}", u=url)
            except Exception as exc:
                log.debug("Error scraping {u}: {e}", u=url, e=exc)

        log.info("Company website scrape complete: {n} total people", n=len(people))
        return people


def _parse_team_page(html: str) -> list[dict]:
    """
    Parse HTML from a team page and extract person names/titles.

    Very conservative approach: only extract obvious patterns.
    """
    if not html:
        return []

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        log.warning("Failed to parse HTML: {e}", e=exc)
        return []

    people = []

    # ── Strategy 1: Look for common team-member div/article patterns ─────────

    # Common class patterns for team members
    selectors = [
        ".team-member",
        ".staff-member",
        ".team-card",
        ".staff-card",
        ".person",
        "[class*='team-item']",
        "[class*='staff-item']",
    ]

    for selector in selectors:
        containers = soup.select(selector)
        if containers:
            log.debug("Found {n} team containers with selector: {s}", n=len(containers), s=selector)
            for container in containers:
                person = _extract_person_from_container(container)
                if person:
                    people.append(person)

    # ── Strategy 2: Look for h2/h3 + p pattern (common on simple pages) ──────

    if not people:
        headings = soup.find_all(["h2", "h3"])
        for heading in headings:
            # Get the next paragraph as the title
            next_p = heading.find_next("p")
            if next_p:
                name = heading.get_text(strip=True)
                title = next_p.get_text(strip=True)

                # Filter out common noise
                if (
                    len(name) > 2
                    and len(title) > 2
                    and not _is_noise(name)
                    and not _is_noise(title)
                ):
                    people.append({"name": name, "title": title, "url": None})

    # Deduplicate and clean
    people = _deduplicate_people(people)

    return people


def _extract_person_from_container(container) -> Optional[dict]:
    """Extract person info from a container element."""
    try:
        # Try common selectors within the container
        name_elem = container.select_one(
            "[class*='name'], h2, h3, h4, .person-name, .staff-name"
        )
        title_elem = container.select_one(
            "[class*='title'], [class*='position'], [class*='role'], .person-title, .job-title, p"
        )

        name = name_elem.get_text(strip=True) if name_elem else None
        title = title_elem.get_text(strip=True) if title_elem else None

        if name and len(name) > 2 and not _is_noise(name):
            return {
                "name": name,
                "title": title if title and len(title) > 2 else "Team Member",
                "url": None,
            }

    except Exception:
        pass

    return None


def _is_noise(text: str) -> bool:
    """Check if text is likely noise (not a real name/title)."""
    noise_patterns = [
        "read more",
        "learn more",
        "contact",
        "email",
        "phone",
        "linkedin",
        "posted",
        "share",
        "click",
        "subscribe",
        "follow",
        "like",
        "upcoming",
        "events",
        "news",
        "social",
    ]

    text_lower = text.lower()
    return any(pattern in text_lower for pattern in noise_patterns)


def _deduplicate_people(people: list[dict]) -> list[dict]:
    """Remove exact duplicates based on name + title."""
    seen = set()
    unique = []

    for person in people:
        key = (person.get("name", "").lower(), person.get("title", "").lower())
        if key not in seen and key != ("", ""):
            seen.add(key)
            unique.append(person)

    return unique


# Module-level singleton
_scraper: Optional[CompanyScraper] = None


def get_scraper() -> CompanyScraper:
    """Get or create the global scraper instance."""
    global _scraper
    if _scraper is None:
        _scraper = CompanyScraper(timeout=10.0, max_pages=5)
    return _scraper
