import getpass
from typing import Dict, List, Optional

from linkedin_scraper import LinkedInScraper
from .base import BaseEnricher


class LinkedInEnricher(BaseEnricher):
    """LinkedIn enricher wrapper around LinkedInScraper."""

    def __init__(self, headless: bool = False):
        self.scraper = LinkedInScraper(headless=headless)

    def ensure_login(self) -> bool:
        """Ensure we have an authenticated LinkedIn session."""
        if self.scraper.load_cookies():
            return True
        email = input("LinkedIn Email: ")
        password = getpass.getpass("LinkedIn Password: ")
        return self.scraper.login(email, password)

    def enrich_contacts(self, contacts: List[Dict], limit: Optional[int] = None) -> int:
        if not contacts:
            return 0
        batch = contacts[:limit] if limit else contacts
        if not self.ensure_login():
            return 0
        self.scraper.run_enrichment_batch(batch, limit=len(batch))
        return len(batch)

    def close(self) -> None:
        self.scraper.quit()
