"""
Tests for CRE Website Scraper functionality
Run with: pytest test_cre_website_scraper.py -v
"""

import pytest
import json
import os
import tempfile
from unittest.mock import MagicMock, patch
from dataclasses import asdict
from bs4 import BeautifulSoup

from cre_website_scraper import (
    CREWebsiteScraper, Person, FirmData,
    load_url_cache, save_url_cache, load_previous_results,
    export_to_csv, export_to_json,
    URL_CACHE_FILE, RESULTS_FILE
)


class TestPerson:
    """Tests for Person dataclass"""

    def test_person_creation_minimal(self):
        """Test creating person with just name"""
        person = Person(name="John Doe")
        assert person.name == "John Doe"
        assert person.title == ""
        assert person.email == ""
        assert person.phone == ""

    def test_person_creation_full(self):
        """Test creating person with all fields"""
        person = Person(
            name="Jane Smith",
            title="Managing Director",
            email="jane@company.com",
            phone="(555) 123-4567",
            linkedin="https://linkedin.com/in/janesmith",
            bio_snippet="Experienced professional",
            source_url="https://company.com/team"
        )
        assert person.name == "Jane Smith"
        assert person.title == "Managing Director"
        assert person.email == "jane@company.com"

    def test_person_to_dict(self):
        """Test converting person to dictionary"""
        person = Person(name="Test User", title="Broker")
        data = asdict(person)
        assert data['name'] == "Test User"
        assert data['title'] == "Broker"


class TestFirmData:
    """Tests for FirmData dataclass"""

    def test_firmdata_creation_minimal(self):
        """Test creating firm with minimal data"""
        firm = FirmData(company_name="Test Corp", website="https://test.com")
        assert firm.company_name == "Test Corp"
        assert firm.website == "https://test.com"
        assert firm.leadership == []
        assert firm.services == []

    def test_firmdata_creation_full(self):
        """Test creating firm with full data"""
        person = Person(name="John CEO", title="CEO")
        firm = FirmData(
            company_name="Big CRE Firm",
            website="https://bigcre.com",
            main_phone="(555) 000-0000",
            main_email="info@bigcre.com",
            leadership=[person],
            services=["Brokerage", "Leasing"],
            specialties=["Office", "Industrial"]
        )
        assert firm.company_name == "Big CRE Firm"
        assert len(firm.leadership) == 1
        assert len(firm.services) == 2


class TestCacheAndPersistence:
    """Tests for cache and persistence functions"""

    def test_load_url_cache_missing_file(self):
        """Test loading cache when file doesn't exist"""
        with patch('os.path.exists', return_value=False):
            cache = load_url_cache()
            assert cache == {}

    def test_load_previous_results_missing_file(self):
        """Test loading results when file doesn't exist"""
        with patch('os.path.exists', return_value=False):
            results = load_previous_results()
            assert results == {}

    def test_save_and_load_url_cache(self):
        """Test saving and loading URL cache"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = os.path.join(tmpdir, 'test_cache.json')
            test_cache = {'https://test.com|team': 'https://test.com/our-team'}

            with patch('cre_website_scraper.URL_CACHE_FILE', cache_file):
                save_url_cache(test_cache)

                # Verify file was created
                assert os.path.exists(cache_file)

                # Load and verify
                with open(cache_file, 'r') as f:
                    loaded = json.load(f)
                assert loaded == test_cache


class TestCREWebsiteScraper:
    """Tests for CREWebsiteScraper class"""

    @pytest.fixture
    def scraper(self):
        """Create scraper instance"""
        return CREWebsiteScraper(delay_seconds=0)

    def test_scraper_initialization(self, scraper):
        """Test scraper initializes correctly"""
        assert scraper.delay == 0
        assert scraper.url_cache == {}
        assert len(scraper.team_patterns) > 0
        assert len(scraper.leadership_titles) > 0

    def test_scraper_with_cache(self):
        """Test scraper initializes with provided cache"""
        cache = {'key': 'value'}
        scraper = CREWebsiteScraper(delay_seconds=0, url_cache=cache)
        assert scraper.url_cache == cache


class TestIsValidPersonName:
    """Tests for _is_valid_person_name method"""

    @pytest.fixture
    def scraper(self):
        return CREWebsiteScraper(delay_seconds=0)

    def test_valid_two_word_name(self, scraper):
        """Two word names should be valid"""
        assert scraper._is_valid_person_name("John Doe") is True
        assert scraper._is_valid_person_name("Terry Coyne") is True

    def test_valid_three_word_name(self, scraper):
        """Three word names should be valid"""
        assert scraper._is_valid_person_name("John Michael Doe") is True

    def test_single_word_invalid(self, scraper):
        """Single word names should be invalid"""
        assert scraper._is_valid_person_name("John") is False

    def test_too_long_invalid(self, scraper):
        """Names over 50 chars should be invalid"""
        long_name = "John " * 20
        assert scraper._is_valid_person_name(long_name.strip()) is False

    def test_too_many_words_invalid(self, scraper):
        """Names with more than 5 words should be invalid"""
        assert scraper._is_valid_person_name("One Two Three Four Five Six") is False

    def test_lowercase_invalid(self, scraper):
        """Names not starting with capitals should be invalid"""
        assert scraper._is_valid_person_name("john doe") is False

    def test_bad_patterns_invalid(self, scraper):
        """Names containing bad patterns should be invalid"""
        assert scraper._is_valid_person_name("Click Here Now") is False
        assert scraper._is_valid_person_name("Investment Services") is False
        assert scraper._is_valid_person_name("About Our Team") is False

    def test_all_caps_invalid(self, scraper):
        """All caps names should be invalid"""
        assert scraper._is_valid_person_name("JOHN DOE") is False

    def test_numbers_invalid(self, scraper):
        """Names with numbers should be invalid"""
        assert scraper._is_valid_person_name("John Doe 3rd") is False

    def test_empty_invalid(self, scraper):
        """Empty names should be invalid"""
        assert scraper._is_valid_person_name("") is False
        assert scraper._is_valid_person_name("  ") is False


class TestExtractEmails:
    """Tests for extract_emails method"""

    @pytest.fixture
    def scraper(self):
        return CREWebsiteScraper(delay_seconds=0)

    def test_extract_mailto_link(self, scraper):
        """Extract email from mailto link"""
        html = '<a href="mailto:test@company.com">Contact</a>'
        soup = BeautifulSoup(html, 'html.parser')
        emails = scraper.extract_emails(soup)
        assert 'test@company.com' in emails

    def test_extract_email_from_text(self, scraper):
        """Extract email from page text"""
        html = '<p>Contact us at info@example.org for more info</p>'
        soup = BeautifulSoup(html, 'html.parser')
        emails = scraper.extract_emails(soup)
        assert 'info@example.org' in emails

    def test_skip_example_domains(self, scraper):
        """Skip emails from example domains"""
        html = '<p>Email: test@example.com or user@domain.com</p>'
        soup = BeautifulSoup(html, 'html.parser')
        emails = scraper.extract_emails(soup)
        assert 'test@example.com' not in emails

    def test_multiple_emails(self, scraper):
        """Extract multiple emails"""
        html = '''
        <a href="mailto:one@test.com">One</a>
        <a href="mailto:two@test.com">Two</a>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        emails = scraper.extract_emails(soup)
        assert len(emails) == 2


class TestExtractPhones:
    """Tests for extract_phones method"""

    @pytest.fixture
    def scraper(self):
        return CREWebsiteScraper(delay_seconds=0)

    def test_extract_standard_phone(self, scraper):
        """Extract standard phone format"""
        html = '<p>Call us: 555-123-4567</p>'
        soup = BeautifulSoup(html, 'html.parser')
        phones = scraper.extract_phones(soup)
        assert '(555) 123-4567' in phones

    def test_extract_parentheses_phone(self, scraper):
        """Extract phone with parentheses"""
        html = '<p>Phone: (555) 987-6543</p>'
        soup = BeautifulSoup(html, 'html.parser')
        phones = scraper.extract_phones(soup)
        assert '(555) 987-6543' in phones

    def test_extract_dotted_phone(self, scraper):
        """Extract phone with dots"""
        html = '<p>Tel: 555.111.2222</p>'
        soup = BeautifulSoup(html, 'html.parser')
        phones = scraper.extract_phones(soup)
        assert '(555) 111-2222' in phones


class TestExtractServices:
    """Tests for extract_services method"""

    @pytest.fixture
    def scraper(self):
        return CREWebsiteScraper(delay_seconds=0)

    def test_extract_service_keywords(self, scraper):
        """Extract services from text"""
        html = '<p>We offer brokerage and property management services.</p>'
        soup = BeautifulSoup(html, 'html.parser')
        services = scraper.extract_services(soup)
        assert 'Brokerage' in services
        assert 'Property Management' in services

    def test_extract_services_from_list(self, scraper):
        """Extract services from ul/li"""
        html = '''
        <ul>
            <li>Investment Sales</li>
            <li>Leasing Services</li>
        </ul>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        services = scraper.extract_services(soup)
        assert 'Investment Sales' in services
        assert 'Leasing' in services


class TestExtractSpecialties:
    """Tests for extract_specialties method"""

    @pytest.fixture
    def scraper(self):
        return CREWebsiteScraper(delay_seconds=0)

    def test_extract_asset_classes(self, scraper):
        """Extract asset class specialties"""
        html = '<p>We specialize in office, industrial, and retail properties.</p>'
        soup = BeautifulSoup(html, 'html.parser')
        specialties = scraper.extract_specialties(soup)
        assert 'Office' in specialties
        assert 'Industrial' in specialties
        assert 'Retail' in specialties


class TestFindLinksbyKeywords:
    """Tests for find_links_by_keywords method"""

    @pytest.fixture
    def scraper(self):
        return CREWebsiteScraper(delay_seconds=0)

    def test_find_team_links(self, scraper):
        """Find links matching team keywords"""
        html = '''
        <a href="/team">Our Team</a>
        <a href="/about">About Us</a>
        <a href="/leadership">Leadership</a>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        links = scraper.find_links_by_keywords(soup, 'https://example.com', ['team', 'leadership'])
        assert len(links) == 2

    def test_skip_external_links(self, scraper):
        """Skip external links"""
        html = '''
        <a href="https://other.com/team">Other Team</a>
        <a href="/team">Our Team</a>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        links = scraper.find_links_by_keywords(soup, 'https://example.com', ['team'])
        assert len(links) == 1
        assert 'example.com' in links[0]

    def test_skip_mailto_links(self, scraper):
        """Skip mailto links"""
        html = '''
        <a href="mailto:team@example.com">Email Team</a>
        <a href="/team">Our Team</a>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        links = scraper.find_links_by_keywords(soup, 'https://example.com', ['team'])
        assert len(links) == 1


class TestExportFunctions:
    """Tests for export functions"""

    def test_export_to_json(self):
        """Test JSON export"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, 'test.json')
            firm = FirmData(
                company_name="Test Corp",
                website="https://test.com",
                leadership=[Person(name="John Doe", title="CEO")]
            )

            export_to_json([firm], filepath)

            assert os.path.exists(filepath)
            with open(filepath, 'r') as f:
                data = json.load(f)
            assert len(data) == 1
            assert data[0]['company_name'] == "Test Corp"

    def test_export_to_csv(self):
        """Test CSV export"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, 'test.csv')
            firm = FirmData(
                company_name="Test Corp",
                website="https://test.com",
                leadership=[Person(name="John Doe", title="CEO")]
            )

            export_to_csv([firm], filepath)

            assert os.path.exists(filepath)
            # Also creates leadership file
            leadership_file = filepath.replace('.csv', '_leadership.csv')
            assert os.path.exists(leadership_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
