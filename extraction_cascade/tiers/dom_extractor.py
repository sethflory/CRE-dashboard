"""
Tier 2: DOM Extraction - FREE

Extracts data from HTML using BeautifulSoup + CSS selectors.
Ports patterns from cre_website_scraper.py.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
from bs4 import BeautifulSoup

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from extraction_cascade.models.session import SiteMap, ExtractionSession
from extraction_cascade.tiers.site_mapper import SiteMapper
from vision_extractor.intent import ExtractionIntent, FieldDefinition, FieldType


@dataclass
class DOMExtractionResult:
    """Result of DOM extraction for a single field."""
    value: Any
    confidence: float
    source_url: str
    raw_context: Optional[str] = None  # Surrounding HTML for debugging


class DOMProgressCallback:
    """Optional callback for reporting DOM extraction progress."""
    def on_dom_page_visit(self, page_url: str, page_type: str, fields_seeking: List[str]) -> None:
        pass
    def on_field_not_found(self, field_name: str, tier: str, pages_tried: List[str]) -> None:
        pass


class DOMExtractor:
    """
    Extracts fields from HTML/DOM using BeautifulSoup.

    Uses CSS selectors and pattern matching to find data.
    Tracks confidence per field for cascade decisions.
    """

    # Keywords for service detection
    SERVICE_KEYWORDS = [
        'brokerage', 'investment sales', 'capital markets', 'property management',
        'tenant representation', 'landlord representation', 'leasing',
        'valuation', 'appraisal', 'consulting', 'advisory',
        'project management', 'construction management', 'development',
        'facility management', 'asset management', 'debt placement',
        'corporate services', 'occupier services', 'research'
    ]

    # Keywords for asset class detection
    ASSET_KEYWORDS = [
        'office', 'industrial', 'retail', 'multifamily', 'apartment',
        'healthcare', 'medical', 'life science', 'hospitality', 'hotel',
        'land', 'self-storage', 'senior housing', 'student housing',
        'net lease', 'mixed-use', 'flex', 'warehouse', 'distribution',
        'data center', 'manufacturing'
    ]

    # Title patterns for leadership
    LEADERSHIP_TITLES = [
        'ceo', 'chief executive', 'president', 'chairman', 'founder',
        'managing director', 'managing principal', 'managing partner',
        'principal', 'partner', 'executive vice president', 'evp',
        'senior vice president', 'svp', 'vice president', 'vp',
        'director', 'broker', 'senior advisor', 'advisor'
    ]

    def __init__(self, site_mapper: Optional[SiteMapper] = None, progress_callback: Optional[DOMProgressCallback] = None):
        """Initialize extractor with optional site mapper for fetching pages."""
        self.site_mapper = site_mapper or SiteMapper()
        self.progress = progress_callback or DOMProgressCallback()

        # Field extractors map field names to extraction methods
        self.extractors = {
            'company_name': self._extract_company_name,
            'headquarters': self._extract_headquarters,
            'contact_email': self._extract_contact_email,
            'contact_phone': self._extract_contact_phone,
            'main_email': self._extract_contact_email,
            'main_phone': self._extract_contact_phone,
            'leadership': self._extract_leadership,
            'services': self._extract_services,
            'specialties': self._extract_specialties,
            'office_locations': self._extract_office_locations,
            'about': self._extract_about,
        }

    def extract(
        self,
        session: ExtractionSession,
        site_map: SiteMap
    ) -> Dict[str, DOMExtractionResult]:
        """
        Extract all fields from relevant pages.

        Args:
            session: Current extraction session
            site_map: Site map with discovered pages

        Returns:
            Dict mapping field names to extraction results
        """
        results = {}
        missing_fields = session.get_missing_fields()

        # Group fields by likely page type
        page_fields = self._group_fields_by_page(missing_fields)

        # Track which pages we tried for each field
        field_pages_tried: Dict[str, List[str]] = {f.name: [] for f in missing_fields}

        for page_type, fields in page_fields.items():
            # Get pages of this type
            pages = site_map.get_pages_by_type(page_type)
            if not pages:
                pages = [site_map.base_url]  # Fallback to homepage

            field_names = [f.name for f in fields]
            for page_url in pages[:3]:  # Try top 3 pages
                # Report page visit
                self.progress.on_dom_page_visit(page_url, page_type, field_names)

                soup = self.site_mapper.get_page_soup(page_url)
                if not soup:
                    continue

                for field in fields:
                    field_pages_tried[field.name].append(page_url)

                    # Skip if already extracted with high confidence
                    if field.name in results and results[field.name].confidence > 0.7:
                        continue

                    result = self._extract_field(field, soup, page_url)
                    if result and (field.name not in results or
                                   result.confidence > results[field.name].confidence):
                        results[field.name] = result

        # Report fields that weren't found
        for field in missing_fields:
            if field.name not in results:
                self.progress.on_field_not_found(
                    field.name, "dom", field_pages_tried.get(field.name, [])
                )

        return results

    def extract_from_soup(
        self,
        soup: BeautifulSoup,
        intent: ExtractionIntent,
        source_url: str
    ) -> Dict[str, DOMExtractionResult]:
        """
        Extract fields from a pre-fetched BeautifulSoup object.

        Args:
            soup: Parsed HTML
            intent: Extraction intent with field definitions
            source_url: URL of the page

        Returns:
            Dict mapping field names to extraction results
        """
        results = {}
        for field in intent.fields:
            result = self._extract_field(field, soup, source_url)
            if result:
                results[field.name] = result
        return results

    def _extract_field(
        self,
        field: FieldDefinition,
        soup: BeautifulSoup,
        source_url: str
    ) -> Optional[DOMExtractionResult]:
        """Extract a single field from soup."""
        extractor = self.extractors.get(field.name)
        if extractor:
            return extractor(soup, source_url)

        # Fallback: generic text extraction by field name
        return self._generic_extract(field, soup, source_url)

    def _group_fields_by_page(self, fields: List[FieldDefinition]) -> Dict[str, List[FieldDefinition]]:
        """Group fields by most likely page type."""
        field_to_page = {
            'leadership': 'team',
            'services': 'services',
            'specialties': 'services',
            'contact_email': 'contact',
            'contact_phone': 'contact',
            'main_email': 'contact',
            'main_phone': 'contact',
            'headquarters': 'contact',
            'office_locations': 'contact',
            'company_name': 'about',
            'about': 'about',
        }

        grouped = {}
        for field in fields:
            page_type = field_to_page.get(field.name, 'home')
            if page_type not in grouped:
                grouped[page_type] = []
            grouped[page_type].append(field)

        return grouped

    # --- Field Extractors ---

    def _extract_company_name(self, soup: BeautifulSoup, source_url: str) -> Optional[DOMExtractionResult]:
        """Extract company name."""
        # Try meta tags first
        meta_name = soup.find('meta', {'property': 'og:site_name'})
        if meta_name and meta_name.get('content'):
            return DOMExtractionResult(
                value=meta_name['content'].strip(),
                confidence=0.9,
                source_url=source_url,
                raw_context=str(meta_name)
            )

        # Try hero h1 with company context
        hero = soup.find(['div', 'section'], class_=re.compile(r'hero|banner|jumbotron', re.I))
        if hero:
            h1 = hero.find('h1')
            if h1:
                h1_text = h1.get_text().strip()
                if len(h1_text) > 3 and len(h1_text) < 100:
                    return DOMExtractionResult(
                        value=h1_text,
                        confidence=0.85,
                        source_url=source_url,
                        raw_context=str(h1)
                    )

        # Try logo link text in header/navbar
        logo_link = soup.find('a', class_=re.compile(r'logo|brand|site[-_]?name', re.I))
        if logo_link:
            logo_text = logo_link.get_text().strip()
            if logo_text and len(logo_text) > 2 and len(logo_text) < 100:
                return DOMExtractionResult(
                    value=logo_text,
                    confidence=0.8,
                    source_url=source_url,
                    raw_context=str(logo_link)
                )

        # Try logo alt text
        logo = soup.find('img', class_=re.compile(r'logo', re.I))
        if logo and logo.get('alt'):
            return DOMExtractionResult(
                value=logo['alt'].strip(),
                confidence=0.7,
                source_url=source_url,
                raw_context=str(logo)
            )

        # Try title tag (least reliable)
        title = soup.find('title')
        if title:
            title_text = title.get_text().strip()
            # Often "Company Name | Something" or "Something - Company Name"
            # Try splitting and taking longest part
            parts = re.split(r'\s*[-|–]\s*', title_text)
            if parts:
                # Take longest part as likely company name
                name = max(parts, key=len).strip()
                if name and len(name) > 2:
                    return DOMExtractionResult(
                        value=name,
                        confidence=0.6,
                        source_url=source_url,
                        raw_context=str(title)
                    )

        return None

    def _extract_contact_email(self, soup: BeautifulSoup, source_url: str) -> Optional[DOMExtractionResult]:
        """Extract primary contact email."""
        emails = self._extract_emails(soup)
        if emails:
            # Filter out common patterns
            filtered = [e for e in emails if not any(
                x in e.lower() for x in ['noreply', 'no-reply', 'donotreply']
            )]
            if filtered:
                return DOMExtractionResult(
                    value=filtered[0],
                    confidence=0.85,
                    source_url=source_url
                )
        return None

    def _extract_contact_phone(self, soup: BeautifulSoup, source_url: str) -> Optional[DOMExtractionResult]:
        """Extract primary contact phone."""
        phones = self._extract_phones(soup)
        if phones:
            return DOMExtractionResult(
                value=phones[0],
                confidence=0.85,
                source_url=source_url
            )
        return None

    def _extract_headquarters(self, soup: BeautifulSoup, source_url: str) -> Optional[DOMExtractionResult]:
        """Extract headquarters address."""
        addresses = self._extract_addresses(soup)
        if addresses:
            return DOMExtractionResult(
                value=addresses[0],
                confidence=0.7,
                source_url=source_url
            )
        return None

    def _extract_office_locations(self, soup: BeautifulSoup, source_url: str) -> Optional[DOMExtractionResult]:
        """Extract all office locations."""
        addresses = self._extract_addresses(soup)
        if addresses:
            return DOMExtractionResult(
                value=addresses,
                confidence=0.7,
                source_url=source_url
            )
        return None

    def _extract_leadership(self, soup: BeautifulSoup, source_url: str) -> Optional[DOMExtractionResult]:
        """Extract leadership team members."""
        people = []

        # Find team member containers
        containers = soup.find_all(['div', 'article', 'li'],
                                   class_=re.compile(r'team[-_]?(member|card)|person|staff|employee|profile|broker|agent|bio[-_]?card', re.I))

        if not containers:
            containers = soup.find_all(['div', 'article'],
                                       class_=re.compile(r'(?<!footer-)card(?!s)|member|people', re.I))

        for container in containers:
            person = self._parse_person_container(container, source_url)
            if person and self._is_valid_person_name(person.get('name', '')):
                # Filter to likely leadership based on title
                title = person.get('title', '').lower()
                if any(lt in title for lt in self.LEADERSHIP_TITLES):
                    people.append(person)
                elif len(people) < 20:
                    people.append(person)

        # Deduplicate by name
        seen_names: Set[str] = set()
        unique_people = []
        for p in people:
            name_key = p.get('name', '').lower().strip()
            if name_key and name_key not in seen_names:
                seen_names.add(name_key)
                unique_people.append(p)

        if unique_people:
            return DOMExtractionResult(
                value=unique_people[:30],
                confidence=0.75 if len(unique_people) > 3 else 0.5,
                source_url=source_url
            )
        return None

    def _extract_services(self, soup: BeautifulSoup, source_url: str) -> Optional[DOMExtractionResult]:
        """Extract services offered."""
        services: Set[str] = set()
        text = soup.get_text().lower()

        for keyword in self.SERVICE_KEYWORDS:
            if keyword in text:
                services.add(keyword.title())

        # Also look for service lists
        for ul in soup.find_all('ul'):
            for li in ul.find_all('li'):
                li_text = li.get_text().lower().strip()
                for keyword in self.SERVICE_KEYWORDS:
                    if keyword in li_text:
                        services.add(keyword.title())

        if services:
            return DOMExtractionResult(
                value=sorted(list(services)),
                confidence=0.7,
                source_url=source_url
            )
        return None

    def _extract_specialties(self, soup: BeautifulSoup, source_url: str) -> Optional[DOMExtractionResult]:
        """Extract asset class specialties."""
        specialties: Set[str] = set()
        text = soup.get_text().lower()

        for keyword in self.ASSET_KEYWORDS:
            if keyword in text:
                specialties.add(keyword.title())

        if specialties:
            return DOMExtractionResult(
                value=sorted(list(specialties)),
                confidence=0.7,
                source_url=source_url
            )
        return None

    def _extract_about(self, soup: BeautifulSoup, source_url: str) -> Optional[DOMExtractionResult]:
        """Extract about/description text."""
        # Try meta description
        meta = soup.find('meta', {'name': 'description'})
        if meta and meta.get('content'):
            return DOMExtractionResult(
                value=meta['content'].strip(),
                confidence=0.8,
                source_url=source_url
            )

        # Try og:description
        og_desc = soup.find('meta', {'property': 'og:description'})
        if og_desc and og_desc.get('content'):
            return DOMExtractionResult(
                value=og_desc['content'].strip(),
                confidence=0.8,
                source_url=source_url
            )

        return None

    def _generic_extract(
        self,
        field: FieldDefinition,
        soup: BeautifulSoup,
        source_url: str
    ) -> Optional[DOMExtractionResult]:
        """Generic extraction fallback for unknown fields."""
        # Try finding elements that mention the field name
        field_pattern = field.name.replace('_', '[-_\\s]?')
        elements = soup.find_all(
            ['div', 'span', 'p', 'section'],
            class_=re.compile(field_pattern, re.I)
        )

        if elements:
            text = elements[0].get_text().strip()
            if text and len(text) < 500:
                return DOMExtractionResult(
                    value=text,
                    confidence=0.4,
                    source_url=source_url,
                    raw_context=str(elements[0])[:200]
                )

        return None

    # --- Helper Methods ---

    def _extract_emails(self, soup: BeautifulSoup) -> List[str]:
        """Extract email addresses from page."""
        emails: Set[str] = set()

        # From mailto links
        for link in soup.find_all('a', href=re.compile(r'^mailto:', re.I)):
            email = link['href'].replace('mailto:', '').split('?')[0].strip()
            if '@' in email and '.' in email:
                emails.add(email.lower())

        # From text using regex
        text = soup.get_text()
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        for match in re.findall(email_pattern, text):
            if not any(x in match.lower() for x in ['example.com', 'email.com', 'domain.com']):
                emails.add(match.lower())

        return list(emails)

    def _extract_phones(self, soup: BeautifulSoup) -> List[str]:
        """Extract phone numbers from page."""
        phones: Set[str] = set()
        text = soup.get_text()

        patterns = [
            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
            r'\d{3}[-.\s]\d{3}[-.\s]\d{4}',
        ]

        for pattern in patterns:
            for match in re.findall(pattern, text):
                cleaned = re.sub(r'[^\d]', '', match)
                if len(cleaned) == 10:
                    formatted = f"({cleaned[:3]}) {cleaned[3:6]}-{cleaned[6:]}"
                    phones.add(formatted)

        return list(phones)

    def _extract_addresses(self, soup: BeautifulSoup) -> List[str]:
        """Extract street addresses."""
        addresses = []
        text = soup.get_text()

        lines = text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            if re.match(r'^\d+\s+[A-Za-z]', line) and len(line) < 100:
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    state_pattern = r'[A-Z]{2}\s+\d{5}'
                    if re.search(state_pattern, next_line) or re.search(state_pattern, line):
                        addresses.append(f"{line} {next_line}".strip())
                        continue
                addresses.append(line)

        return addresses[:5]

    def _parse_person_container(self, container, source_url: str) -> Optional[Dict]:
        """Parse a container element to extract person info."""
        person = {'source_url': source_url}

        # Look for name
        name_elem = container.find(['h2', 'h3', 'h4', 'h5', 'strong', 'b', 'span', 'div', 'p'],
                                   class_=re.compile(r'name(?!s)|heading', re.I))
        if not name_elem:
            name_elem = container.find(['h2', 'h3', 'h4', 'h5'])

        if name_elem:
            person['name'] = name_elem.get_text(separator=' ').strip()

        # Look for title/position (avoid matching 'name' class as title)
        title_elem = container.find(['p', 'span', 'div'],
                                    class_=re.compile(r'(?<!name-)title|position|role|job|designation', re.I))
        if title_elem:
            person['title'] = title_elem.get_text(separator=' ').strip()
        elif name_elem and name_elem.find_next_sibling(['p', 'span']):
            person['title'] = name_elem.find_next_sibling(['p', 'span']).get_text(separator=' ').strip()

        # Look for email
        email_link = container.find('a', href=re.compile(r'^mailto:', re.I))
        if email_link:
            person['email'] = email_link['href'].replace('mailto:', '').split('?')[0].strip()

        # Look for phone
        phone_link = container.find('a', href=re.compile(r'^tel:', re.I))
        if phone_link:
            person['phone'] = phone_link['href'].replace('tel:', '').strip()

        # Look for LinkedIn
        linkedin_link = container.find('a', href=re.compile(r'linkedin\.com', re.I))
        if linkedin_link:
            person['linkedin'] = linkedin_link['href']

        # Clean up name
        if 'name' in person:
            person['name'] = ' '.join(person['name'].split())
            person['name'] = re.sub(r',?\s*(CCIM|SIOR|CPM|MAI|CPA|MBA|JD|PhD).*$', '', person['name'], flags=re.I)

        # Clean up title
        if 'title' in person:
            person['title'] = ' '.join(person['title'].split())[:100]

        return person if person.get('name') else None

    def _is_valid_person_name(self, name: str) -> bool:
        """Check if a string looks like a valid person name."""
        if not name or len(name) < 3 or len(name) > 50:
            return False

        words = name.split()
        if len(words) < 2 or len(words) > 5:
            return False

        if not all(w[0].isupper() for w in words if w):
            return False

        bad_patterns = [
            'click', 'watch', 'discover', 'learn', 'read', 'view', 'see',
            'http', 'www', '.com', 'download', 'subscribe', 'contact',
            'valuation', 'advisory', 'services', 'solutions', 'capital',
            'about', 'our team', 'leadership team', 'meet the', 'news',
            ' - ', ' | ', ' & ', 'llc', 'inc', 'corp'
        ]
        name_lower = name.lower()
        if any(pattern in name_lower for pattern in bad_patterns):
            return False

        if name.isupper() or any(c.isdigit() for c in name):
            return False

        return True
