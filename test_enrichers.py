"""
Tests for enricher interfaces.
Run with: pytest test_enrichers.py -v
"""

from unittest.mock import patch

from enrichers.linkedin import LinkedInEnricher


def test_linkedin_enricher_uses_cookies():
    with patch("enrichers.linkedin.LinkedInScraper") as mock_scraper_cls:
        mock_scraper = mock_scraper_cls.return_value
        mock_scraper.load_cookies.return_value = True

        enricher = LinkedInEnricher(headless=True)
        contacts = [{"name": "Alex Morgan"}]
        processed = enricher.enrich_contacts(contacts, limit=1)

        assert processed == 1
        mock_scraper.run_enrichment_batch.assert_called_once()
        enricher.close()


def test_linkedin_enricher_login_failure_skips_enrich():
    with patch("enrichers.linkedin.LinkedInScraper") as mock_scraper_cls, \
         patch("enrichers.linkedin.getpass.getpass", return_value="pw"), \
         patch("builtins.input", return_value="user@example.com"):
        mock_scraper = mock_scraper_cls.return_value
        mock_scraper.load_cookies.return_value = False
        mock_scraper.login.return_value = False

        enricher = LinkedInEnricher(headless=True)
        processed = enricher.enrich_contacts([{"name": "Test"}], limit=1)

        assert processed == 0
        mock_scraper.run_enrichment_batch.assert_not_called()
        enricher.close()
