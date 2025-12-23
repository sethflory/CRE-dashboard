"""
Vision-based enricher using VisionExtractor.

Provides a BaseEnricher implementation that uses Claude vision
for profile extraction with hybrid DOM/vision workflow.
"""

import getpass
from typing import Dict, List, Optional

from .base import BaseEnricher

# Import vision extractor components
try:
    from vision_extractor import (
        VisionExtractor,
        TemplateStorage,
        get_builtin_template,
    )
    VISION_EXTRACTOR_AVAILABLE = True
except ImportError:
    VISION_EXTRACTOR_AVAILABLE = False


class VisionEnricher(BaseEnricher):
    """
    LinkedIn enricher using VisionExtractor for hybrid DOM/vision extraction.

    This enricher uses the generalized VisionExtractor component for
    profile extraction with Claude vision validation and correction.
    """

    def __init__(
        self,
        headless: bool = False,
        template_name: str = "linkedin_profile",
        claude_api_key: Optional[str] = None,
        save_debug: bool = False
    ):
        """
        Initialize vision enricher.

        Args:
            headless: Run browser in headless mode
            template_name: Extraction template name
            claude_api_key: Anthropic API key (or use env var)
            save_debug: Save debug screenshots
        """
        if not VISION_EXTRACTOR_AVAILABLE:
            raise ImportError("vision_extractor package not found")

        self.headless = headless
        self.template_name = template_name
        self.claude_api_key = claude_api_key
        self.save_debug = save_debug

        # Load extraction template
        storage = TemplateStorage()
        self.intent = storage.load(template_name)
        if not self.intent:
            self.intent = get_builtin_template(template_name)
        if not self.intent:
            raise ValueError(f"Template '{template_name}' not found")

        # Create extractor
        self.extractor = VisionExtractor(
            self.intent,
            claude_api_key=claude_api_key,
            save_debug_screenshots=save_debug
        )

        # Browser state (lazy init)
        self._playwright = None
        self._browser = None
        self._page = None
        self._logged_in = False

    def _start_browser(self):
        """Start browser if not already running."""
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                args=['--disable-blink-features=AutomationControlled']
            )
            self._page = self._browser.new_page(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            self._page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

    def ensure_login(self) -> bool:
        """Ensure we have an authenticated LinkedIn session."""
        self._start_browser()

        # Try loading cookies
        import os
        import json
        cookies_file = 'linkedin_cookies.json'

        if os.path.exists(cookies_file):
            self._page.goto("https://www.linkedin.com")
            with open(cookies_file, 'r') as f:
                cookies = json.load(f)
            self._page.context.add_cookies(cookies)
            self._page.reload()

            try:
                self._page.wait_for_selector('.global-nav__me', timeout=5000)
                self._logged_in = True
                return True
            except:
                pass

        # Manual login
        email = input("LinkedIn Email: ")
        password = getpass.getpass("LinkedIn Password: ")

        self._page.goto("https://www.linkedin.com/login")
        self._page.fill('#username', email)
        self._page.fill('#password', password)
        self._page.click('button[type="submit"]')

        try:
            self._page.wait_for_selector('.global-nav__me', timeout=30000)
            self._logged_in = True

            # Save cookies
            cookies = self._page.context.cookies()
            with open(cookies_file, 'w') as f:
                json.dump(cookies, f)

            return True
        except:
            return False

    def enrich_contacts(self, contacts: List[Dict], limit: Optional[int] = None) -> int:
        """
        Enrich contacts using vision extraction.

        Args:
            contacts: List of contact dicts with 'linkedin' URL field
            limit: Maximum contacts to process

        Returns:
            Number of contacts processed
        """
        if not contacts:
            return 0

        if not self.ensure_login():
            print("Failed to login to LinkedIn")
            return 0

        batch = contacts[:limit] if limit else contacts
        processed = 0

        import time
        import random

        for contact in batch:
            url = contact.get('linkedin', contact.get('linkedin_url', ''))
            if not url:
                continue

            try:
                # Navigate to profile
                self._page.goto(url)
                time.sleep(random.uniform(2, 4))

                # Run vision extraction
                result = self.extractor.extract_and_validate(
                    self._page,
                    delay_fn=lambda a, b: time.sleep(random.uniform(a, b))
                )

                if result.success:
                    # Update contact with extracted data
                    contact.update({
                        'name': result.data.get('name', contact.get('name', '')),
                        'headline': result.data.get('headline', ''),
                        'location': result.data.get('location', ''),
                        'current_company': result.data.get('current_company', ''),
                        'current_title': result.data.get('current_title', ''),
                        'work_history': result.data.get('work_history', []),
                        'education': result.data.get('education', []),
                        'groups': result.data.get('groups', []),
                        'enriched': True,
                        'enrichment_confidence': result.confidence,
                        'enrichment_mode': result.extraction_mode,
                    })
                    processed += 1
                    print(f"✓ Enriched: {contact.get('name', url)}")
                else:
                    print(f"✗ Failed: {url} - {result.errors}")

                # Rate limiting
                time.sleep(random.uniform(3, 6))

            except Exception as e:
                print(f"Error enriching {url}: {e}")

        return processed

    def close(self) -> None:
        """Release resources."""
        if self._page:
            self._page.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._page = self._browser = self._playwright = None
