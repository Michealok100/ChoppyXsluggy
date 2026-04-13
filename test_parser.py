"""
tests/test_parser.py — Unit tests for the LinkedIn snippet parser.

Run with: pytest tests/ -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from parser.linkedin_parser import parse_organic_results, parse_title_string


# ── parse_title_string ────────────────────────────────────────────────────────

class TestParseTitleString:
    def test_standard_dash_format(self):
        name, title, company = parse_title_string(
            "John Doe - Bookkeeper - ABC Construction | LinkedIn"
        )
        assert name == "John Doe"
        assert title == "Bookkeeper"
        assert company == "ABC Construction"

    def test_pipe_separator(self):
        name, title, company = parse_title_string(
            "Jane Smith | Senior Accountant | XYZ LLC | LinkedIn"
        )
        assert name == "Jane Smith"
        assert title == "Senior Accountant"
        assert company == "XYZ LLC"

    def test_at_company_format(self):
        name, title, company = parse_title_string(
            "Bob Jones - Office Manager at Acme Inc | LinkedIn"
        )
        assert name == "Bob Jones"
        assert title == "Office Manager"
        assert "Acme" in company

    def test_em_dash_separator(self):
        name, title, company = parse_title_string(
            "Alice Brown — Project Manager — TechCo"
        )
        assert name == "Alice Brown"
        assert title == "Project Manager"

    def test_two_part_title(self):
        name, title, company = parse_title_string("Someone Cool - Engineer")
        assert name == "Someone Cool"
        assert title == "Engineer"
        assert company == "Unknown"

    def test_empty_string(self):
        name, title, company = parse_title_string("")
        assert name == title == company == ""

    def test_strips_linkedin_suffix(self):
        name, title, company = parse_title_string(
            "David Lee - CPA - Big Four | LinkedIn Profile"
        )
        assert name == "David Lee"
        assert "LinkedIn" not in company


# ── parse_organic_results ─────────────────────────────────────────────────────

MOCK_RESULTS = [
    {
        "link": "https://www.linkedin.com/in/john-doe-bookkeeper",
        "title": "John Doe - Bookkeeper - ABC Corp | LinkedIn",
        "snippet": "10+ years experience in bookkeeping at ABC Corp in Birmingham, AL.",
    },
    {
        "link": "https://www.linkedin.com/in/jane-smith-cpa",
        "title": "Jane Smith | Accountant at XYZ LLC | LinkedIn",
        "snippet": "CPA with focus on small business accounting.",
    },
    {
        # Should be filtered: not a /in/ profile
        "link": "https://www.linkedin.com/company/somecompany",
        "title": "SomeCompany - LinkedIn",
        "snippet": "",
    },
    {
        # Duplicate of first entry
        "link": "https://www.linkedin.com/in/john-doe-bookkeeper?trk=blah",
        "title": "John Doe - Bookkeeper - ABC Corp | LinkedIn",
        "snippet": "",
    },
]


class TestParseOrganicResults:
    def test_returns_person_objects(self):
        people = parse_organic_results(MOCK_RESULTS, "bookkeeper", "Birmingham, Alabama")
        assert len(people) == 2  # company page + duplicate filtered

    def test_deduplication(self):
        people = parse_organic_results(MOCK_RESULTS, "bookkeeper", "Birmingham, Alabama")
        urls = [p.linkedin_url for p in people]
        assert len(urls) == len(set(urls))

    def test_company_page_excluded(self):
        people = parse_organic_results(MOCK_RESULTS, "bookkeeper", "Birmingham, Alabama")
        for p in people:
            assert "/in/" in p.linkedin_url

    def test_relevance_score_range(self):
        people = parse_organic_results(MOCK_RESULTS, "bookkeeper", "Birmingham, Alabama")
        for p in people:
            assert 0.0 <= p.relevance_score <= 1.0

    def test_sorted_by_relevance(self):
        people = parse_organic_results(MOCK_RESULTS, "bookkeeper", "Birmingham, Alabama")
        scores = [p.relevance_score for p in people]
        assert scores == sorted(scores, reverse=True)

    def test_empty_input(self):
        people = parse_organic_results([], "nurse", "Texas")
        assert people == []


# ── Query builder tests ───────────────────────────────────────────────────────

class TestQueryBuilder:
    def test_basic_query_contains_site(self):
        from scraper.xray_scraper import build_xray_query
        q = build_xray_query("bookkeeper", "Birmingham, Alabama")
        assert "site:linkedin.com/in" in q
        assert "bookkeeper" in q
        assert "Birmingham, Alabama" in q

    def test_synonyms_added_with_or(self):
        from scraper.xray_scraper import build_xray_query
        q = build_xray_query("bookkeeper", "Alabama", ["accounts payable", "CPA"])
        assert "OR" in q
        assert "accounts payable" in q

    def test_fallback_queries_ordered(self):
        from scraper.xray_scraper import build_fallback_queries
        queries = build_fallback_queries("bookkeeper", "Birmingham, Alabama")
        levels = [lvl for _, lvl in queries]
        assert levels == sorted(levels)  # monotonically increasing


# ── Location expansion tests ──────────────────────────────────────────────────

class TestLocationExpansion:
    def test_city_state_expands(self):
        from utils.synonyms import expand_location
        variants = expand_location("Birmingham, Alabama")
        assert "Birmingham, Alabama" in variants
        assert any("AL" in v for v in variants)
        assert "Alabama" in variants

    def test_single_location_unchanged(self):
        from utils.synonyms import expand_location
        variants = expand_location("Texas")
        assert "Texas" in variants


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── Industry filter tests ─────────────────────────────────────────────────────

class TestIndustryFilter:
    def test_known_industry_returns_keywords(self):
        from utils.industries import get_industry_keywords
        kw = get_industry_keywords("Healthcare")
        assert len(kw) > 0
        assert any("healthcare" in k.lower() for k in kw)

    def test_unknown_industry_returns_empty(self):
        from utils.industries import get_industry_keywords
        assert get_industry_keywords("MadeUpIndustry999") == []

    def test_case_insensitive_lookup(self):
        from utils.industries import get_industry_keywords
        assert get_industry_keywords("technology") == get_industry_keywords("Technology")

    def test_is_valid_industry(self):
        from utils.industries import is_valid_industry
        assert is_valid_industry("Finance") is True
        assert is_valid_industry("finance") is True
        assert is_valid_industry("XYZFake") is False

    def test_build_fragment_format(self):
        from utils.industries import build_industry_query_fragment
        frag = build_industry_query_fragment("Healthcare")
        assert frag.startswith("(")
        assert frag.endswith(")")
        assert "OR" in frag

    def test_build_fragment_empty_for_unknown(self):
        from utils.industries import build_industry_query_fragment
        assert build_industry_query_fragment("NoSuchIndustry") == ""

    def test_industry_list_not_empty(self):
        from utils.industries import INDUSTRY_LIST
        assert len(INDUSTRY_LIST) >= 20

    def test_query_includes_industry_fragment(self):
        from scraper.xray_scraper import build_xray_query
        q = build_xray_query("nurse", "Texas", industry="Healthcare")
        assert "healthcare" in q.lower() or "hospital" in q.lower()

    def test_query_without_industry_has_no_industry_terms(self):
        from scraper.xray_scraper import build_xray_query
        q = build_xray_query("nurse", "Texas", industry=None)
        from utils.industries import get_industry_keywords
        kw = get_industry_keywords("Healthcare")
        assert not any(k.lower() in q.lower() for k in kw)

    def test_fallback_queries_drop_industry_at_level_4(self):
        from scraper.xray_scraper import build_fallback_queries
        queries = build_fallback_queries("nurse", "Texas", industry="Healthcare")
        levels = {lvl: q for q, lvl in queries}
        # Level 4 (widest) should not contain healthcare keywords
        if 4 in levels:
            from utils.industries import get_industry_keywords
            kw = get_industry_keywords("Healthcare")
            assert not any(k.lower() in levels[4].lower() for k in kw)

    @pytest.mark.asyncio
    async def test_full_pipeline_with_industry(self, tmp_path, monkeypatch):
        import os
        monkeypatch.setenv("SERPAPI_KEY", "MOCK")
        import scraper.xray_scraper as xs
        xs._serpapi_client = None
        import config
        config.settings.SERPAPI_KEY = "MOCK"
        config.settings.DATA_DIR = tmp_path

        from models import SearchRequest
        from scraper.search_service import execute_search

        request = SearchRequest(
            job_title="bookkeeper",
            location="Birmingham, Alabama",
            industry="Finance",
            user_id=888,
            chat_id=888,
        )
        result = await execute_search(request)
        # Should still return results (mock ignores industry in fixture matching)
        assert result.error is None or result.found
