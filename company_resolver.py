"""
company_resolver.py — Resolve company information from URLs.

Handles:
  - LinkedIn company URLs: https://www.linkedin.com/company/example-company/
  - Website URLs: https://examplecompany.com

Extracts company name and metadata.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import Optional
from pydantic import BaseModel

from logger import log


class CompanyInfo(BaseModel):
    """Resolved company information."""
    company_name: str
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    domain: Optional[str] = None


def extract_company_from_url(url: str) -> CompanyInfo | None:
    """
    Extract company information from a LinkedIn company URL or website URL.

    Args:
        url: LinkedIn company URL or website domain

    Returns:
        CompanyInfo if successful, None if URL cannot be parsed
    """
    if not url or not isinstance(url, str):
        log.warning("Invalid URL input: {u}", u=url)
        return None

    url = url.strip()

    # ── LinkedIn company URL ──────────────────────────────────────────────────
    if "linkedin.com/company/" in url.lower():
        return _resolve_linkedin_company(url)

    # ── Website domain ────────────────────────────────────────────────────────
    if _is_valid_domain(url):
        return _resolve_website_domain(url)

    log.warning("Could not recognize URL format: {u}", u=url)
    return None


def _resolve_linkedin_company(url: str) -> CompanyInfo | None:
    """Extract company slug from LinkedIn company URL."""
    try:
        # Normalize: https://www.linkedin.com/company/example-company/ → "example-company"
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")

        # Extract slug between /company/ and trailing /
        match = re.search(r"/company/([^/]+)", path)
        if not match:
            log.warning("Could not extract company slug from: {u}", u=url)
            return None

        slug = match.group(1)

        # Convert slug to company name
        # Example: "example-company" → "Example Company"
        company_name = " ".join(word.capitalize() for word in slug.split("-"))

        # Normalize LinkedIn URL
        linkedin_url = f"https://www.linkedin.com/company/{slug}/"

        log.info("Resolved LinkedIn company: {n} ({s})", n=company_name, s=slug)

        return CompanyInfo(
            company_name=company_name,
            linkedin_url=linkedin_url,
            domain=None,
            website=None,
        )

    except Exception as exc:
        log.warning("Error parsing LinkedIn company URL: {e}", e=exc)
        return None


def _resolve_website_domain(url: str) -> CompanyInfo | None:
    """Extract company information from a website domain."""
    try:
        # Normalize: remove http://, https://, www., trailing /
        url = url.lower().strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")

        if not domain:
            log.warning("Could not extract domain from URL: {u}", u=url)
            return None

        # Extract company name from domain
        # Example: "examplecompany.com" → "Example Company"
        # Example: "example-clinic.com" → "Example Clinic"
        company_slug = domain.split(".")[0]
        company_name = " ".join(word.capitalize() for word in company_slug.split("-"))

        # Reconstruct website URL (without path)
        website = f"https://{domain}"

        log.info("Resolved website domain: {n} ({d})", n=company_name, d=domain)

        return CompanyInfo(
            company_name=company_name,
            website=website,
            domain=domain,
            linkedin_url=None,
        )

    except Exception as exc:
        log.warning("Error parsing website domain: {e}", e=exc)
        return None


def _is_valid_domain(url: str) -> bool:
    """Check if URL looks like a valid domain."""
    url = url.lower().strip()

    # Remove protocol if present
    if url.startswith(("http://", "https://")):
        url = url.split("//", 1)[1]

    # Remove trailing slash and path
    url = url.split("/")[0]

    # Must have at least one dot and valid TLD
    if "." not in url:
        return False

    # Basic domain pattern
    domain_pattern = re.compile(r"^[a-z0-9]([a-z0-9-]*\.)*[a-z]{2,}$")
    return bool(domain_pattern.match(url))
