"""
Tests for LinkedIn Scraper functionality
Run with: pytest test_linkedin_scraper.py -v
"""

import pytest
import json
import os
from unittest.mock import MagicMock, patch
from dataclasses import asdict

from linkedin_scraper import (
    LinkedInScraper, LinkedInPerson, LinkedInCompany,
    CRE_KEYWORDS, DISCOVERED_CONTACTS_FILE, DISCOVERED_FIRMS_FILE,
    SKIP_URL_PATTERNS, SKIP_NAMES, BAD_NAME_PATTERNS
)


class TestLinkedInPerson:
    """Tests for LinkedInPerson dataclass"""

    def test_person_creation_minimal(self):
        """Test creating person with just name"""
        person = LinkedInPerson(name="John Doe")
        assert person.name == "John Doe"
        assert person.linkedin_url == ""
        assert person.work_history == []
        assert person.education == []
        assert person.groups == []

    def test_person_creation_full(self):
        """Test creating person with all fields"""
        person = LinkedInPerson(
            name="Jane Smith",
            linkedin_url="https://www.linkedin.com/in/janesmith/",
            headline="VP at CBRE",
            location="New York",
            current_company="CBRE",
            current_title="Vice President",
            company_linkedin_url="https://www.linkedin.com/company/cbre/",
            work_history=[{"company": "JLL", "title": "Associate"}],
            education=[{"school": "NYU", "degree": "MBA"}],
            groups=["CRE Professionals"],
            recent_posts=[{"content": "Market update..."}],
            about="Commercial real estate professional",
            discovered_from="Initial search",
            scraped_at="2025-12-22T10:00:00"
        )
        assert person.name == "Jane Smith"
        assert person.current_company == "CBRE"
        assert len(person.work_history) == 1
        assert len(person.education) == 1

    def test_person_to_dict(self):
        """Test converting person to dictionary"""
        person = LinkedInPerson(name="Test User", headline="Broker")
        data = asdict(person)
        assert data['name'] == "Test User"
        assert data['headline'] == "Broker"
        assert isinstance(data['work_history'], list)


class TestLinkedInCompany:
    """Tests for LinkedInCompany dataclass"""

    def test_company_creation(self):
        """Test creating company"""
        company = LinkedInCompany(
            name="Newmark",
            linkedin_url="https://www.linkedin.com/company/nmrk-cre/",
            is_cre_related=True
        )
        assert company.name == "Newmark"
        assert company.is_cre_related is True
        assert company.employees_scraped == []


class TestIsAlreadyEnriched:
    """Tests for is_already_enriched method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper with mocked browser"""
        with patch.object(LinkedInScraper, '_load_data'):
            scraper = LinkedInScraper(headless=True)
            scraper.discovered_contacts = {}
            return scraper

    def test_empty_url_returns_false(self, scraper):
        """Empty URL should return False"""
        assert scraper.is_already_enriched("") is False
        assert scraper.is_already_enriched(None) is False

    def test_unknown_contact_returns_false(self, scraper):
        """Unknown contact should return False"""
        assert scraper.is_already_enriched("https://www.linkedin.com/in/unknown/") is False

    def test_contact_without_scraped_at_returns_false(self, scraper):
        """Contact without scraped_at should return False"""
        person = LinkedInPerson(
            name="Test User",
            linkedin_url="https://www.linkedin.com/in/testuser/",
            headline="Some title",
            scraped_at=""  # Not scraped yet
        )
        scraper.discovered_contacts["testuser"] = person
        assert scraper.is_already_enriched("https://www.linkedin.com/in/testuser/") is False

    def test_contact_with_scraped_at_and_headline_returns_true(self, scraper):
        """Contact with scraped_at and headline should return True"""
        person = LinkedInPerson(
            name="Test User",
            linkedin_url="https://www.linkedin.com/in/testuser/",
            headline="VP at Company",
            scraped_at="2025-12-22T10:00:00"
        )
        scraper.discovered_contacts["testuser"] = person
        assert scraper.is_already_enriched("https://www.linkedin.com/in/testuser/") is True

    def test_contact_with_scraped_at_and_about_returns_true(self, scraper):
        """Contact with scraped_at and about should return True"""
        person = LinkedInPerson(
            name="Test User",
            linkedin_url="https://www.linkedin.com/in/testuser/",
            about="Experienced professional...",
            scraped_at="2025-12-22T10:00:00"
        )
        scraper.discovered_contacts["testuser"] = person
        assert scraper.is_already_enriched("https://www.linkedin.com/in/testuser/") is True

    def test_contact_with_scraped_at_but_no_content_returns_false(self, scraper):
        """Contact with scraped_at but no headline/about should return False"""
        person = LinkedInPerson(
            name="Test User",
            linkedin_url="https://www.linkedin.com/in/testuser/",
            headline="",
            about="",
            scraped_at="2025-12-22T10:00:00"
        )
        scraper.discovered_contacts["testuser"] = person
        assert scraper.is_already_enriched("https://www.linkedin.com/in/testuser/") is False

    def test_url_with_trailing_slash(self, scraper):
        """URL with trailing slash should work"""
        person = LinkedInPerson(
            name="Test User",
            headline="Title",
            scraped_at="2025-12-22T10:00:00"
        )
        scraper.discovered_contacts["testuser"] = person
        assert scraper.is_already_enriched("https://www.linkedin.com/in/testuser/") is True

    def test_url_without_trailing_slash(self, scraper):
        """URL without trailing slash should work"""
        person = LinkedInPerson(
            name="Test User",
            headline="Title",
            scraped_at="2025-12-22T10:00:00"
        )
        scraper.discovered_contacts["testuser"] = person
        assert scraper.is_already_enriched("https://www.linkedin.com/in/testuser") is True

    def test_url_with_query_params(self, scraper):
        """URL with query params should extract key correctly"""
        person = LinkedInPerson(
            name="Test User",
            headline="Title",
            scraped_at="2025-12-22T10:00:00"
        )
        scraper.discovered_contacts["testuser"] = person
        assert scraper.is_already_enriched("https://www.linkedin.com/in/testuser/?miniProfileUrn=123") is True


class TestHelperMethods:
    """Tests for helper methods"""

    @pytest.fixture
    def scraper(self):
        """Create scraper with mocked browser"""
        with patch.object(LinkedInScraper, '_load_data'):
            scraper = LinkedInScraper(headless=True)
            return scraper

    def test_extract_profile_key_standard(self, scraper):
        """Test extracting key from standard URL"""
        assert scraper._extract_profile_key("https://www.linkedin.com/in/terrycoyne/") == "terrycoyne"

    def test_extract_profile_key_no_slash(self, scraper):
        """Test extracting key without trailing slash"""
        assert scraper._extract_profile_key("https://www.linkedin.com/in/terrycoyne") == "terrycoyne"

    def test_extract_profile_key_with_query(self, scraper):
        """Test extracting key with query params"""
        assert scraper._extract_profile_key("https://www.linkedin.com/in/terrycoyne?miniProfile=123") == "terrycoyne"

    def test_extract_profile_key_complex(self, scraper):
        """Test extracting complex key"""
        assert scraper._extract_profile_key("https://www.linkedin.com/in/john-doe-123abc/") == "john-doe-123abc"

    def test_extract_profile_key_empty(self, scraper):
        """Test empty URL returns empty string"""
        assert scraper._extract_profile_key("") == ""
        assert scraper._extract_profile_key(None) == ""

    def test_extract_profile_key_no_in(self, scraper):
        """Test URL without /in/ returns empty string"""
        assert scraper._extract_profile_key("https://www.linkedin.com/company/test") == ""

    def test_normalize_url_relative(self, scraper):
        """Test normalizing relative URL"""
        assert scraper._normalize_url("/in/terrycoyne/") == "https://www.linkedin.com/in/terrycoyne/"

    def test_normalize_url_absolute(self, scraper):
        """Test absolute URL stays absolute"""
        assert scraper._normalize_url("https://www.linkedin.com/in/terrycoyne/") == "https://www.linkedin.com/in/terrycoyne/"

    def test_normalize_url_strips_query(self, scraper):
        """Test query params are stripped"""
        assert scraper._normalize_url("https://www.linkedin.com/in/test?foo=bar") == "https://www.linkedin.com/in/test"

    def test_normalize_url_empty(self, scraper):
        """Test empty URL returns empty"""
        assert scraper._normalize_url("") == ""

    def test_should_skip_url_overlay(self, scraper):
        """Test overlay URLs are skipped"""
        assert scraper._should_skip_url("https://linkedin.com/in/user/overlay/contact") is True

    def test_should_skip_url_details(self, scraper):
        """Test details URLs are skipped"""
        assert scraper._should_skip_url("https://linkedin.com/in/user/details/experience") is True

    def test_should_skip_url_normal(self, scraper):
        """Test normal profile URLs are not skipped"""
        assert scraper._should_skip_url("https://linkedin.com/in/terrycoyne/") is False

    def test_should_skip_name_ui_text(self, scraper):
        """Test UI text is skipped"""
        assert scraper._should_skip_name("Connect") is True
        assert scraper._should_skip_name("Show all posts") is True
        assert scraper._should_skip_name("View profile") is True

    def test_should_skip_name_real_name(self, scraper):
        """Test real names are not skipped"""
        assert scraper._should_skip_name("Terry Coyne") is False
        assert scraper._should_skip_name("John Smith") is False

    def test_should_skip_name_empty(self, scraper):
        """Test empty name is skipped"""
        assert scraper._should_skip_name("") is True

    def test_is_valid_person_name_valid(self, scraper):
        """Test valid names pass"""
        assert scraper._is_valid_person_name("John Doe") is True
        assert scraper._is_valid_person_name("Terry Coyne") is True
        assert scraper._is_valid_person_name("John Michael Smith") is True

    def test_is_valid_person_name_single_word(self, scraper):
        """Test single word names fail"""
        assert scraper._is_valid_person_name("John") is False

    def test_is_valid_person_name_lowercase(self, scraper):
        """Test lowercase names fail"""
        assert scraper._is_valid_person_name("john doe") is False

    def test_is_valid_person_name_bad_pattern(self, scraper):
        """Test bad patterns fail"""
        assert scraper._is_valid_person_name("Leadership Team") is False
        assert scraper._is_valid_person_name("Professional Services") is False


class TestIsCRECompany:
    """Tests for _is_cre_company method"""

    @pytest.fixture
    def scraper(self):
        """Create scraper with mocked browser"""
        with patch.object(LinkedInScraper, '_load_data'):
            scraper = LinkedInScraper(headless=True)
            return scraper

    def test_cbre_is_cre(self, scraper):
        """CBRE should be recognized as CRE"""
        assert scraper._is_cre_company("CBRE") is True
        assert scraper._is_cre_company("cbre") is True

    def test_jll_is_cre(self, scraper):
        """JLL should be recognized as CRE"""
        assert scraper._is_cre_company("JLL") is True
        assert scraper._is_cre_company("JLL Properties") is True

    def test_newmark_is_cre(self, scraper):
        """Newmark should be recognized as CRE"""
        assert scraper._is_cre_company("Newmark") is True
        assert scraper._is_cre_company("Newmark Group") is True

    def test_colliers_is_cre(self, scraper):
        """Colliers should be recognized as CRE"""
        assert scraper._is_cre_company("Colliers") is True
        assert scraper._is_cre_company("Colliers International") is True

    def test_cushman_is_cre(self, scraper):
        """Cushman & Wakefield should be recognized as CRE"""
        assert scraper._is_cre_company("Cushman & Wakefield") is True

    def test_real_estate_keyword(self, scraper):
        """Companies with 'real estate' should be recognized"""
        assert scraper._is_cre_company("ABC Real Estate Group") is True
        assert scraper._is_cre_company("Commercial Real Estate Partners") is True

    def test_brokerage_keyword(self, scraper):
        """Companies with 'brokerage' should be recognized"""
        assert scraper._is_cre_company("Smith Brokerage") is True

    def test_non_cre_company(self, scraper):
        """Non-CRE companies should return False"""
        assert scraper._is_cre_company("Google") is False
        assert scraper._is_cre_company("Microsoft") is False
        assert scraper._is_cre_company("Amazon") is False

    def test_empty_company(self, scraper):
        """Empty company name should return False"""
        assert scraper._is_cre_company("") is False


class TestProfileURLKeyExtraction:
    """Tests for extracting profile key from LinkedIn URLs"""

    def test_extract_key_standard_url(self):
        """Test extracting key from standard URL"""
        url = "https://www.linkedin.com/in/terrycoyne/"
        key = url.split('/in/')[-1].strip('/').split('/')[0]
        assert key == "terrycoyne"

    def test_extract_key_with_query_params(self):
        """Test extracting key from URL with query params"""
        url = "https://www.linkedin.com/in/terrycoyne/?miniProfileUrn=abc123"
        key = url.split('/in/')[-1].strip('/').split('/')[0].split('?')[0]
        assert key == "terrycoyne"

    def test_extract_key_complex_id(self):
        """Test extracting key with complex ID"""
        url = "https://www.linkedin.com/in/john-doe-123abc/"
        key = url.split('/in/')[-1].strip('/').split('/')[0]
        assert key == "john-doe-123abc"


class TestNameValidation:
    """Tests for name validation logic used in batch enrichment"""

    def is_valid_name(self, name: str) -> bool:
        """Replicate the name validation logic from run_enrichment_batch"""
        if not name or len(name) < 3:
            return False

        words = name.split()
        if len(words) < 2 or len(words) > 5:
            return False
        if not all(w[0].isupper() for w in words if w):
            return False

        name_lower = name.lower()
        bad_patterns = [
            'professional', 'affiliations', 'services', 'contact',
            'about', 'team', 'leadership', 'management', 'board',
            'investment', 'capital', 'advisory', 'valuation', 'group',
            'division', 'department', 'office', 'regional', 'national'
        ]
        if any(p in name_lower for p in bad_patterns):
            return False

        return True

    def test_valid_two_word_name(self):
        """Two word names should be valid"""
        assert self.is_valid_name("John Doe") is True
        assert self.is_valid_name("Terry Coyne") is True

    def test_valid_three_word_name(self):
        """Three word names should be valid"""
        assert self.is_valid_name("John Michael Doe") is True

    def test_single_word_name_invalid(self):
        """Single word names should be invalid"""
        assert self.is_valid_name("John") is False

    def test_too_many_words_invalid(self):
        """Names with more than 5 words should be invalid"""
        assert self.is_valid_name("John Michael David William Thomas Smith") is False

    def test_lowercase_first_letter_invalid(self):
        """Names with lowercase first letters should be invalid"""
        assert self.is_valid_name("john doe") is False
        assert self.is_valid_name("John doe") is False

    def test_short_name_invalid(self):
        """Names shorter than 3 chars should be invalid"""
        assert self.is_valid_name("Jo") is False
        assert self.is_valid_name("") is False

    def test_bad_pattern_professional(self):
        """Names containing 'professional' should be invalid"""
        assert self.is_valid_name("Professional Services") is False

    def test_bad_pattern_leadership(self):
        """Names containing 'leadership' should be invalid"""
        assert self.is_valid_name("Leadership Team") is False

    def test_bad_pattern_investment(self):
        """Names containing 'investment' should be invalid"""
        assert self.is_valid_name("Investment Advisory") is False


class TestSkipPatterns:
    """Tests for URL skip patterns used when finding employees"""

    @pytest.fixture
    def scraper(self):
        """Create scraper with mocked browser"""
        with patch.object(LinkedInScraper, '_load_data'):
            scraper = LinkedInScraper(headless=True)
            return scraper

    def should_skip_url(self, url: str) -> bool:
        """Replicate skip pattern logic using constants"""
        return any(pattern in url for pattern in SKIP_URL_PATTERNS)

    def test_overlay_url_skipped(self):
        """Overlay URLs should be skipped"""
        assert self.should_skip_url("https://www.linkedin.com/in/user/overlay/contact-info/") is True

    def test_details_url_skipped(self):
        """Details URLs should be skipped"""
        assert self.should_skip_url("https://www.linkedin.com/in/user/details/experience/") is True

    def test_activity_url_skipped(self):
        """Recent activity URLs should be skipped"""
        assert self.should_skip_url("https://www.linkedin.com/in/user/recent-activity/all/") is True

    def test_endorsers_url_skipped(self):
        """Endorsers URLs should be skipped"""
        assert self.should_skip_url("https://www.linkedin.com/in/user/endorsers/skill/123") is True

    def test_normal_profile_not_skipped(self):
        """Normal profile URLs should not be skipped"""
        assert self.should_skip_url("https://www.linkedin.com/in/terrycoyne/") is False
        assert self.should_skip_url("https://www.linkedin.com/in/john-doe-123/") is False


class TestSkipNames:
    """Tests for name skip patterns used when finding employees"""

    def should_skip_name(self, name: str) -> bool:
        """Replicate skip name logic using constants"""
        if not name:
            return True
        name_lower = name.lower()
        if any(skip in name_lower for skip in SKIP_NAMES):
            return True
        if name_lower.startswith('show all') or 'endorsement' in name_lower:
            return True
        return False

    def test_view_skipped(self):
        """'View' should be skipped"""
        assert self.should_skip_name("View all") is True

    def test_connect_skipped(self):
        """'Connect' should be skipped"""
        assert self.should_skip_name("Connect") is True

    def test_show_all_posts_skipped(self):
        """'Show all posts' should be skipped"""
        assert self.should_skip_name("Show all posts") is True

    def test_endorsement_skipped(self):
        """Endorsement text should be skipped"""
        assert self.should_skip_name("5 endorsements") is True

    def test_real_name_not_skipped(self):
        """Real names should not be skipped"""
        assert self.should_skip_name("Terry Coyne") is False
        assert self.should_skip_name("John Smith") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
