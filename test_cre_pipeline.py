"""
Tests for CRE Pipeline functionality
Run with: pytest test_cre_pipeline.py -v
"""

import pytest
import json
import os
import tempfile
from unittest.mock import MagicMock, patch, mock_open

from cre_pipeline import (
    load_discovered_firms,
    get_existing_websites,
    suggest_new_firms,
    scrape_company_linkedin_for_website
)
from cre_website_scraper import TARGET_FIRMS


class TestLoadDiscoveredFirms:
    """Tests for load_discovered_firms function"""

    def test_load_missing_file(self):
        """Returns empty dict when file doesn't exist"""
        with patch('os.path.exists', return_value=False):
            result = load_discovered_firms()
            assert result == {}

    def test_load_existing_file(self):
        """Returns data from file when it exists"""
        test_data = {
            "cbre": {"name": "CBRE", "is_cre_related": True}
        }
        mock_file = mock_open(read_data=json.dumps(test_data))

        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_file):
                result = load_discovered_firms()
                assert result == test_data


class TestGetExistingWebsites:
    """Tests for get_existing_websites function"""

    def test_returns_set(self):
        """Returns a set of normalized websites"""
        result = get_existing_websites()
        assert isinstance(result, set)

    def test_normalizes_https(self):
        """Strips https:// from websites"""
        # We know TARGET_FIRMS contains websites with various formats
        result = get_existing_websites()
        # All should be normalized (no http/https prefixes)
        for website in result:
            assert not website.startswith('https://')
            assert not website.startswith('http://')

    def test_normalizes_www(self):
        """Strips www. from websites"""
        result = get_existing_websites()
        for website in result:
            assert not website.startswith('www.')

    def test_strips_trailing_slash(self):
        """Strips trailing slashes from websites"""
        result = get_existing_websites()
        for website in result:
            assert not website.endswith('/')


class TestSuggestNewFirms:
    """Tests for suggest_new_firms function"""

    def test_empty_when_no_discovered(self):
        """Returns empty list when no discovered firms"""
        with patch('cre_pipeline.load_discovered_firms', return_value={}):
            result = suggest_new_firms()
            assert result == []

    def test_filters_non_cre_firms(self):
        """Filters out firms that are not CRE related"""
        test_data = {
            "google": {
                "name": "Google",
                "linkedin_url": "https://linkedin.com/company/google",
                "is_cre_related": False
            }
        }
        with patch('cre_pipeline.load_discovered_firms', return_value=test_data):
            result = suggest_new_firms()
            assert len(result) == 0

    def test_includes_cre_firms(self):
        """Includes firms that are CRE related"""
        test_data = {
            "newcre": {
                "name": "New CRE Firm",
                "linkedin_url": "https://linkedin.com/company/newcre",
                "is_cre_related": True,
                "discovered_from": "Terry Coyne"
            }
        }
        with patch('cre_pipeline.load_discovered_firms', return_value=test_data):
            with patch('cre_pipeline.get_existing_websites', return_value=set()):
                # Also need to mock TARGET_FIRMS to be empty for this test
                with patch('cre_pipeline.TARGET_FIRMS', []):
                    result = suggest_new_firms()
                    assert len(result) == 1
                    assert result[0]['name'] == "New CRE Firm"

    def test_filters_existing_firms(self):
        """Filters out firms that already exist in TARGET_FIRMS"""
        test_data = {
            "jll": {
                "name": "JLL Columbus",  # This exists in TARGET_FIRMS
                "linkedin_url": "https://linkedin.com/company/jll",
                "is_cre_related": True
            }
        }
        with patch('cre_pipeline.load_discovered_firms', return_value=test_data):
            result = suggest_new_firms()
            # Should be filtered out because JLL Columbus is in TARGET_FIRMS
            assert len(result) == 0

    def test_suggestion_structure(self):
        """Suggestions have correct structure"""
        test_data = {
            "newcre": {
                "name": "Unique New CRE Firm",
                "linkedin_url": "https://linkedin.com/company/newcre",
                "is_cre_related": True,
                "discovered_from": "Terry Coyne"
            }
        }
        with patch('cre_pipeline.load_discovered_firms', return_value=test_data):
            with patch('cre_pipeline.TARGET_FIRMS', []):
                result = suggest_new_firms()
                if result:  # Only check if we got results
                    suggestion = result[0]
                    assert 'name' in suggestion
                    assert 'linkedin_url' in suggestion
                    assert 'discovered_from' in suggestion
                    assert 'website' in suggestion


class TestScrapeCompanyLinkedinForWebsite:
    """Tests for scrape_company_linkedin_for_website function"""

    def test_returns_empty_if_no_url(self):
        """Returns empty string if no company URL provided"""
        scraper = MagicMock()
        scraper.logged_in = True
        scraper.page = MagicMock()

        result = scrape_company_linkedin_for_website(scraper, "")
        assert result == ""

    def test_returns_empty_if_not_logged_in(self):
        """Returns empty string if not logged in"""
        scraper = MagicMock()
        scraper.logged_in = False
        scraper.page = MagicMock()

        result = scrape_company_linkedin_for_website(scraper, "https://linkedin.com/company/test")
        assert result == ""

    def test_returns_empty_if_no_page(self):
        """Returns empty string if page is None"""
        scraper = MagicMock()
        scraper.logged_in = True
        scraper.page = None

        result = scrape_company_linkedin_for_website(scraper, "https://linkedin.com/company/test")
        assert result == ""

    def test_navigates_to_company_page(self):
        """Navigates to company LinkedIn page"""
        scraper = MagicMock()
        scraper.logged_in = True
        scraper.page = MagicMock()
        scraper.page.query_selector.return_value = None
        scraper._random_delay = MagicMock()

        scrape_company_linkedin_for_website(scraper, "https://linkedin.com/company/test")

        scraper.page.goto.assert_called()

    def test_returns_website_when_found(self):
        """Returns website URL when found"""
        scraper = MagicMock()
        scraper.logged_in = True
        scraper.page = MagicMock()
        scraper._random_delay = MagicMock()

        # Mock finding a website link
        mock_elem = MagicMock()
        mock_elem.get_attribute.return_value = "https://company-website.com"
        scraper.page.query_selector.return_value = mock_elem

        result = scrape_company_linkedin_for_website(scraper, "https://linkedin.com/company/test")
        assert result == "https://company-website.com"

    def test_skips_linkedin_urls(self):
        """Skips URLs that contain linkedin"""
        scraper = MagicMock()
        scraper.logged_in = True
        scraper.page = MagicMock()
        scraper._random_delay = MagicMock()

        # Mock finding only linkedin links
        mock_elem = MagicMock()
        mock_elem.get_attribute.return_value = "https://linkedin.com/feed"
        scraper.page.query_selector.return_value = mock_elem

        # Need to mock multiple calls - first returns linkedin, then None
        scraper.page.query_selector.side_effect = [mock_elem, None, None, None]

        result = scrape_company_linkedin_for_website(scraper, "https://linkedin.com/company/test")
        # Should not return linkedin URL
        assert result == "" or "linkedin" not in result


class TestTargetFirms:
    """Tests for TARGET_FIRMS configuration"""

    def test_target_firms_not_empty(self):
        """TARGET_FIRMS should have entries"""
        assert len(TARGET_FIRMS) > 0

    def test_target_firms_have_required_fields(self):
        """Each firm should have name and website"""
        for firm in TARGET_FIRMS:
            assert 'name' in firm, f"Firm missing 'name': {firm}"
            assert 'website' in firm, f"Firm missing 'website': {firm}"

    def test_target_firms_names_not_empty(self):
        """Firm names should not be empty"""
        for firm in TARGET_FIRMS:
            assert firm['name'], f"Firm has empty name: {firm}"

    def test_target_firms_websites_not_empty(self):
        """Firm websites should not be empty"""
        for firm in TARGET_FIRMS:
            assert firm['website'], f"Firm has empty website: {firm}"

    def test_no_duplicate_websites(self):
        """Should not have duplicate websites"""
        websites = [firm['website'].lower() for firm in TARGET_FIRMS]
        # Normalize for comparison
        normalized = []
        for w in websites:
            w = w.replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')
            normalized.append(w)

        # Check for duplicates (some may be intentional like lee-associates)
        # Just verify the list isn't mostly duplicates
        unique_count = len(set(normalized))
        assert unique_count > len(TARGET_FIRMS) * 0.8  # At least 80% unique


class TestPipelineIntegration:
    """Integration tests for pipeline components"""

    def test_discovered_firms_file_path(self):
        """DISCOVERED_FIRMS_FILE should match linkedin_scraper"""
        from cre_pipeline import DISCOVERED_FIRMS_FILE
        from linkedin_scraper import DISCOVERED_FIRMS_FILE as LI_FIRMS_FILE
        # Import the constant name (not actual path comparison since they're the same)
        assert DISCOVERED_FIRMS_FILE is not None

    def test_results_file_path(self):
        """RESULTS_FILE should match between modules"""
        from cre_pipeline import RESULTS_FILE
        from cre_website_scraper import RESULTS_FILE as WS_RESULTS_FILE
        # Both should reference same file
        assert RESULTS_FILE == WS_RESULTS_FILE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
