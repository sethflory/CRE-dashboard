"""
Tier 1: Site Mapping - FREE

Maps site structure using:
- sitemap.xml parsing
- robots.txt analysis
- Link crawling from homepage
- Page categorization based on URL patterns
"""

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from extraction_cascade.models.session import SiteMap


@dataclass
class SiteMapperConfig:
    """Configuration for site mapping."""
    max_pages: int = 50                    # Maximum pages to discover
    delay_seconds: float = 1.0             # Delay between requests
    timeout: int = 15                      # Request timeout
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"


class ProgressCallback:
    """Optional callback for reporting mapping progress."""
    def on_sitemap_check(self, url: str, found: bool, page_count: int = 0) -> None:
        pass
    def on_robots_check(self, url: str, found: bool) -> None:
        pass
    def on_page_discovered(self, url: str, page_type: str, source: str) -> None:
        pass
    def on_page_crawled(self, url: str, links_found: int) -> None:
        pass
    def on_static_pattern_check(self, pattern: str, exists: bool) -> None:
        pass


class SiteMapper:
    """
    Maps site structure using free methods.

    Discovers pages via sitemap.xml, robots.txt hints,
    and crawling links from the homepage.
    """

    # Page type patterns (URL keywords -> page type)
    PAGE_PATTERNS = {
        "team": [
            "/team", "/our-team", "/about/team", "/leadership",
            "/leadership-team", "/executive-team", "/management-team",
            "/people", "/staff", "/executives", "/management",
            "/about-us/team", "/about/leadership", "/professionals",
            "/our-leadership", "/meet-the-team", "/our-people"
        ],
        "services": [
            "/services", "/our-services", "/what-we-do", "/solutions",
            "/capabilities", "/offerings", "/expertise"
        ],
        "contact": [
            "/contact", "/contact-us", "/locations", "/offices",
            "/get-in-touch", "/reach-us", "/find-us"
        ],
        "about": [
            "/about", "/about-us", "/company", "/who-we-are",
            "/our-story", "/our-company", "/overview"
        ],
        "careers": [
            "/careers", "/jobs", "/join-us", "/opportunities"
        ],
        "news": [
            "/news", "/blog", "/insights", "/press", "/media"
        ],
    }

    def __init__(self, config: Optional[SiteMapperConfig] = None, progress_callback: Optional[ProgressCallback] = None):
        """Initialize mapper with optional config and progress callback."""
        self.config = config or SiteMapperConfig()
        self.progress = progress_callback or ProgressCallback()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.user_agent
        })

    def map_site(self, base_url: str) -> SiteMap:
        """
        Build a complete site map with categorized pages.

        Args:
            base_url: Homepage URL to start mapping from

        Returns:
            SiteMap with discovered and categorized pages
        """
        # Normalize base URL
        parsed = urlparse(base_url)
        if not parsed.scheme:
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        site_map = SiteMap(base_url=base_url)

        # Always add homepage
        site_map.add_page(base_url, "home", "crawl")

        # Try sitemap.xml
        sitemap_pages = self._parse_sitemap(base_url)
        self.progress.on_sitemap_check(base_url, len(sitemap_pages) > 0, len(sitemap_pages))
        for url, page_type in sitemap_pages:
            site_map.add_page(url, page_type, "sitemap")
            self.progress.on_page_discovered(url, page_type, "sitemap")

        # Try robots.txt for hints
        robots_info = self._parse_robots(base_url)
        site_map.robots_info = robots_info
        self.progress.on_robots_check(base_url, robots_info is not None)

        # Crawl homepage for links
        homepage_links = self._crawl_homepage(base_url)
        self.progress.on_page_crawled(base_url, len(homepage_links))
        for url, page_type in homepage_links:
            site_map.add_page(url, page_type, "crawl")
            self.progress.on_page_discovered(url, page_type, "crawl")

        # Try static URL patterns for common page types
        static_pages = self._try_static_patterns(base_url)
        for url, page_type in static_pages:
            site_map.add_page(url, page_type, "pattern")
            self.progress.on_page_discovered(url, page_type, "pattern")

        return site_map

    def _parse_sitemap(self, base_url: str) -> List[tuple]:
        """
        Parse sitemap.xml if available.

        Returns list of (url, page_type) tuples.
        """
        pages = []
        sitemap_urls = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/sitemap",
        ]

        for sitemap_url in sitemap_urls:
            try:
                time.sleep(self.config.delay_seconds)
                response = self.session.get(
                    sitemap_url,
                    timeout=self.config.timeout
                )
                if response.status_code != 200:
                    continue

                # Parse XML
                root = ET.fromstring(response.content)

                # Handle namespace
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

                # Find all URLs
                for url_elem in root.findall(".//sm:url/sm:loc", ns):
                    if url_elem.text:
                        url = url_elem.text.strip()
                        page_type = self._categorize_url(url)
                        pages.append((url, page_type))

                # Also check for sitemap index (nested sitemaps)
                for sitemap_elem in root.findall(".//sm:sitemap/sm:loc", ns):
                    if sitemap_elem.text:
                        nested_pages = self._parse_nested_sitemap(sitemap_elem.text.strip())
                        pages.extend(nested_pages)

                if pages:
                    break  # Found sitemap, stop trying

            except Exception:
                continue

        return pages[:self.config.max_pages]

    def _parse_nested_sitemap(self, sitemap_url: str) -> List[tuple]:
        """Parse a nested sitemap."""
        pages = []
        try:
            time.sleep(self.config.delay_seconds)
            response = self.session.get(sitemap_url, timeout=self.config.timeout)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                for url_elem in root.findall(".//sm:url/sm:loc", ns):
                    if url_elem.text:
                        url = url_elem.text.strip()
                        page_type = self._categorize_url(url)
                        pages.append((url, page_type))
        except Exception:
            pass
        return pages

    def _parse_robots(self, base_url: str) -> Optional[Dict]:
        """
        Parse robots.txt for useful hints.

        Returns dict with sitemap URLs and allowed/disallowed patterns.
        """
        robots_url = f"{base_url}/robots.txt"
        try:
            time.sleep(self.config.delay_seconds)
            response = self.session.get(robots_url, timeout=self.config.timeout)
            if response.status_code != 200:
                return None

            info = {
                "sitemaps": [],
                "disallowed": [],
                "allowed": []
            }

            for line in response.text.split("\n"):
                line = line.strip()
                if line.lower().startswith("sitemap:"):
                    info["sitemaps"].append(line.split(":", 1)[1].strip())
                elif line.lower().startswith("disallow:"):
                    info["disallowed"].append(line.split(":", 1)[1].strip())
                elif line.lower().startswith("allow:"):
                    info["allowed"].append(line.split(":", 1)[1].strip())

            return info

        except Exception:
            return None

    def _crawl_homepage(self, base_url: str) -> List[tuple]:
        """
        Crawl homepage for internal links.

        Returns list of (url, page_type) tuples.
        """
        pages = []
        seen_urls: Set[str] = set()

        try:
            time.sleep(self.config.delay_seconds)
            response = self.session.get(base_url, timeout=self.config.timeout)
            if response.status_code != 200:
                return pages

            soup = BeautifulSoup(response.text, "html.parser")
            parsed_base = urlparse(base_url)
            base_domain = parsed_base.netloc

            # Find all links
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if not href:
                    continue

                # Resolve relative URLs
                full_url = urljoin(base_url, href)
                parsed_url = urlparse(full_url)

                # Skip external links
                if parsed_url.netloc and parsed_url.netloc != base_domain:
                    continue

                # Skip anchors, javascript, mailto, tel
                if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue

                # Normalize URL
                normalized = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
                normalized = normalized.rstrip("/")

                if normalized in seen_urls:
                    continue
                seen_urls.add(normalized)

                # Categorize and add
                page_type = self._categorize_url(normalized)
                pages.append((normalized, page_type))

                if len(pages) >= self.config.max_pages:
                    break

        except Exception:
            pass

        return pages

    def _try_static_patterns(self, base_url: str) -> List[tuple]:
        """
        Try common URL patterns to find pages.

        Returns list of (url, page_type) for pages that exist.
        """
        pages = []

        # Try common patterns for each page type
        patterns_to_try = [
            ("/team", "team"),
            ("/about/team", "team"),
            ("/leadership", "team"),
            ("/leadership-team", "team"),
            ("/our-team", "team"),
            ("/our-leadership", "team"),
            ("/executive-team", "team"),
            ("/management-team", "team"),
            ("/people", "team"),
            ("/professionals", "team"),
            ("/services", "services"),
            ("/our-services", "services"),
            ("/what-we-do", "services"),
            ("/contact", "contact"),
            ("/contact-us", "contact"),
            ("/locations", "contact"),
            ("/offices", "contact"),
            ("/about", "about"),
            ("/about-us", "about"),
            ("/company", "about"),
        ]

        for pattern, page_type in patterns_to_try:
            url = f"{base_url}{pattern}"
            exists = self._url_exists(url)
            self.progress.on_static_pattern_check(pattern, exists)
            if exists:
                pages.append((url, page_type))

        return pages

    def _url_exists(self, url: str) -> bool:
        """Check if a URL exists (returns 200)."""
        try:
            time.sleep(self.config.delay_seconds * 0.5)  # Faster check
            response = self.session.head(
                url,
                timeout=self.config.timeout,
                allow_redirects=True
            )
            return response.status_code == 200
        except Exception:
            return False

    def _categorize_url(self, url: str) -> str:
        """
        Categorize a URL by its path.

        Returns page type (team, services, contact, about, other).
        """
        parsed = urlparse(url)
        path = parsed.path.lower()

        for page_type, patterns in self.PAGE_PATTERNS.items():
            for pattern in patterns:
                if pattern in path:
                    return page_type

        # Default to "other"
        if path in ("/", ""):
            return "home"
        return "other"

    def get_page_soup(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetch a page and return parsed BeautifulSoup.

        Useful for downstream extractors.
        """
        try:
            time.sleep(self.config.delay_seconds)
            response = self.session.get(url, timeout=self.config.timeout)
            if response.status_code == 200:
                return BeautifulSoup(response.text, "html.parser")
        except Exception:
            pass
        return None
