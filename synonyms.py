"""
utils/synonyms.py — Job-title synonym map + location expansion helpers.

The scraper uses these to build fallback X-ray queries when the
initial exact search returns no results.
"""

from __future__ import annotations

# ── Job-title synonym groups ─────────────────────────────────────────────────
# Keys are normalised lowercase.  Values are lists of common alternatives.
# Add new roles freely — the more entries, the better recall.

TITLE_SYNONYMS: dict[str, list[str]] = {
    # Finance / Accounting
    "bookkeeper": ["bookkeeping", "accounts payable", "accounts receivable", "accounting clerk"],
    "accountant": ["CPA", "staff accountant", "senior accountant", "financial accountant"],
    "cfo": ["chief financial officer", "VP finance", "finance director"],
    "controller": ["financial controller", "comptroller"],

    # Operations / Admin
    "office manager": ["administrative manager", "operations manager", "admin manager"],
    "executive assistant": ["EA", "executive admin", "personal assistant", "PA"],
    "receptionist": ["front desk", "office coordinator", "administrative assistant"],

    # HR
    "hr manager": ["human resources manager", "people manager", "HR director", "talent manager"],
    "recruiter": ["talent acquisition", "staffing specialist", "hiring manager"],

    # Engineering
    "software engineer": ["software developer", "SWE", "backend engineer", "full stack developer"],
    "data engineer": ["data pipeline engineer", "ETL developer", "analytics engineer"],
    "devops engineer": ["site reliability engineer", "SRE", "platform engineer", "cloud engineer"],
    "product manager": ["PM", "senior product manager", "technical product manager"],

    # Sales / Marketing
    "sales manager": ["account manager", "sales director", "regional sales manager"],
    "marketing manager": ["digital marketing manager", "brand manager", "marketing director"],

    # Healthcare
    "nurse": ["RN", "registered nurse", "staff nurse", "charge nurse"],
    "physician": ["doctor", "MD", "medical doctor", "attending physician"],

    # Construction / Trades
    "project manager": ["PM", "construction manager", "site manager", "project coordinator"],
    "estimator": ["cost estimator", "project estimator", "quantity surveyor"],

    # General catch-all (keep at end)
    "manager": ["director", "head of", "lead", "supervisor"],
    "engineer": ["specialist", "analyst", "architect"],
}


def get_synonyms(job_title: str) -> list[str]:
    """
    Return synonym list for *job_title*.
    Falls back to splitting the title into individual keywords if no
    exact match is found.
    """
    key = job_title.lower().strip()
    if key in TITLE_SYNONYMS:
        return TITLE_SYNONYMS[key]

    # Partial match — find the most specific entry that is a substring
    for k, v in TITLE_SYNONYMS.items():
        if k in key or key in k:
            return v

    # No match — generate basic keyword variants
    words = key.split()
    return [" ".join(words[::-1])] if len(words) > 1 else []


# ── Location expansion helpers ───────────────────────────────────────────────

# US state abbreviation → full name
US_STATE_ABBR: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}


def expand_location(location: str) -> list[str]:
    """
    Return progressively broader location strings.

    e.g. "Birmingham, Alabama"  →
        ["Birmingham, Alabama", "Birmingham, AL", "Alabama", "United States"]
    """
    location = location.strip()
    variants: list[str] = [location]

    parts = [p.strip() for p in location.split(",")]

    if len(parts) == 2:
        city, region = parts
        # Add abbreviation variant if region is a US state full name
        for abbr, full in US_STATE_ABBR.items():
            if full.lower() == region.lower():
                variants.append(f"{city}, {abbr}")
                break
            if abbr.lower() == region.lower():
                variants.append(f"{city}, {full}")
                break

        # Add just the region (state / country)
        variants.append(region)

    # Final fallback: remove location entirely (handled in scraper)
    return variants
