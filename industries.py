"""
utils/industries.py — Industry keyword map for X-ray search filtering.

Each key is the canonical industry name shown to the user.
Each value is a list of keywords/phrases that commonly appear on
LinkedIn profiles for people working in that industry.

The scraper injects these as extra terms into the X-ray query so
Google only surfaces profiles associated with that sector.
"""

from __future__ import annotations

# ── Industry → LinkedIn keyword groups ──────────────────────────────────────
INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    # Finance & Accounting
    "Finance":          ["finance", "financial services", "investment", "banking", "wealth management"],
    "Accounting":       ["accounting", "CPA", "audit", "tax", "bookkeeping", "accounts payable"],
    "Insurance":        ["insurance", "underwriting", "claims", "actuarial", "risk management"],

    # Technology
    "Technology":       ["software", "technology", "tech", "SaaS", "IT", "information technology"],
    "Cybersecurity":    ["cybersecurity", "information security", "infosec", "network security"],
    "Data & AI":        ["data science", "machine learning", "AI", "analytics", "big data"],

    # Healthcare
    "Healthcare":       ["healthcare", "hospital", "medical", "health system", "clinical"],
    "Pharma":           ["pharmaceutical", "biotech", "drug", "clinical trials", "life sciences"],
    "Dental":           ["dental", "dentistry", "orthodontic", "oral health"],

    # Construction & Real Estate
    "Construction":     ["construction", "general contractor", "building", "civil engineering"],
    "Real Estate":      ["real estate", "property management", "REIT", "commercial real estate"],

    # Manufacturing & Industrial
    "Manufacturing":    ["manufacturing", "production", "factory", "industrial", "assembly"],
    "Logistics":        ["logistics", "supply chain", "warehouse", "distribution", "freight"],
    "Energy":           ["energy", "oil and gas", "utilities", "renewable energy", "power"],

    # Retail & Consumer
    "Retail":           ["retail", "e-commerce", "consumer goods", "merchandise", "store"],
    "Food & Beverage":  ["food", "beverage", "restaurant", "hospitality", "food service"],

    # Professional Services
    "Legal":            ["law firm", "legal", "attorney", "counsel", "litigation"],
    "Consulting":       ["consulting", "management consulting", "advisory", "strategy"],
    "Marketing":        ["marketing", "advertising", "PR", "public relations", "media"],

    # Education
    "Education":        ["education", "university", "school", "academic", "higher education"],
    "Nonprofit":        ["nonprofit", "non-profit", "NGO", "foundation", "charity"],

    # Government & Defense
    "Government":       ["government", "federal", "municipal", "public sector", "agency"],
    "Defense":          ["defense", "military", "aerospace", "DoD", "contractor"],
}

# Flat sorted list for display in /industries command and inline keyboards
INDUSTRY_LIST: list[str] = sorted(INDUSTRY_KEYWORDS.keys())


def get_industry_keywords(industry: str) -> list[str]:
    """
    Return keyword list for *industry* (case-insensitive).
    Returns empty list if industry not found.
    """
    for key, keywords in INDUSTRY_KEYWORDS.items():
        if key.lower() == industry.lower().strip():
            return keywords
    return []


def is_valid_industry(industry: str) -> bool:
    return any(k.lower() == industry.lower().strip() for k in INDUSTRY_KEYWORDS)


def build_industry_query_fragment(industry: str) -> str:
    """
    Build the industry portion of the X-ray query.

    Returns an OR-group like:
        ("healthcare" OR "hospital" OR "medical")
    or empty string if industry is unknown / not provided.
    """
    keywords = get_industry_keywords(industry)
    if not keywords:
        return ""
    terms = " OR ".join(f'"{k}"' for k in keywords[:4])  # cap at 4 to keep URL short
    return f"({terms})"
