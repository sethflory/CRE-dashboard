"""
CRE Firm Website Scraper
Extracts leadership, services, contact info from commercial real estate firm websites

SETUP:
    pip install requests beautifulsoup4

USAGE:
    python cre_website_scraper.py

OUTPUT:
    - scraped_firms.csv         (firm-level summary)
    - scraped_firms_leadership.csv  (all contacts found)
    - scraped_firms.json        (full structured data)

CUSTOMIZATION:
    - Edit TARGET_FIRMS list at bottom to add/remove companies
    - Adjust delay_seconds in scraper init (default 2s between requests)
    - Modify leadership_titles list to capture different roles

NOTE: Run on local machine or server with unrestricted internet access.
      Some sites may block scrapers - results vary by site structure.
"""

import requests
from bs4 import BeautifulSoup
import re
import time
import json
import os
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
import csv
from datetime import datetime

# Cache and data file paths
URL_CACHE_FILE = 'url_cache.json'
RESULTS_FILE = 'scraped_firms.json'

@dataclass
class Person:
    name: str
    title: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    bio_snippet: str = ""
    source_url: str = ""

@dataclass
class FirmData:
    company_name: str
    website: str
    scraped_at: str = ""
    # Contact Info
    main_phone: str = ""
    main_email: str = ""
    headquarters_address: str = ""
    # Leadership
    leadership: List[Person] = field(default_factory=list)
    # Services
    services: List[str] = field(default_factory=list)
    # Specialties/Asset Classes
    specialties: List[str] = field(default_factory=list)
    # Office Locations Found
    office_locations: List[str] = field(default_factory=list)
    # Metadata
    pages_scraped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def load_url_cache() -> Dict:
    """Load cached URLs from previous runs"""
    if os.path.exists(URL_CACHE_FILE):
        try:
            with open(URL_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_url_cache(cache: Dict):
    """Save discovered URLs to cache"""
    with open(URL_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2)

def load_previous_results() -> Dict[str, dict]:
    """Load previously scraped firm data"""
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Index by website for easy lookup
                return {firm['website']: firm for firm in data}
        except:
            pass
    return {}


class CREWebsiteScraper:
    """Scraper for commercial real estate firm websites"""

    def __init__(self, delay_seconds=2, url_cache=None):
        self.delay = delay_seconds
        self.url_cache = url_cache or {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        
        # Common page patterns for CRE firms
        self.team_patterns = [
            '/team', '/our-team', '/about/team', '/about-us/team',
            '/leadership', '/about/leadership', '/our-leadership',
            '/people', '/professionals', '/brokers', '/agents',
            '/about/people', '/company/team', '/staff',
            '/about', '/about-us', '/company'
        ]
        
        self.services_patterns = [
            '/services', '/our-services', '/what-we-do',
            '/solutions', '/capabilities', '/expertise',
            '/brokerage', '/property-management'
        ]
        
        self.contact_patterns = [
            '/contact', '/contact-us', '/locations',
            '/offices', '/find-us'
        ]
        
        # Keywords indicating services
        self.service_keywords = [
            'brokerage', 'investment sales', 'capital markets', 'property management',
            'tenant representation', 'landlord representation', 'leasing',
            'valuation', 'appraisal', 'consulting', 'advisory',
            'project management', 'construction management', 'development',
            'facility management', 'asset management', 'debt placement',
            'corporate services', 'occupier services', 'research'
        ]
        
        # Keywords indicating asset classes
        self.asset_keywords = [
            'office', 'industrial', 'retail', 'multifamily', 'apartment',
            'healthcare', 'medical', 'life science', 'hospitality', 'hotel',
            'land', 'self-storage', 'senior housing', 'student housing',
            'net lease', 'mixed-use', 'flex', 'warehouse', 'distribution',
            'data center', 'manufacturing'
        ]
        
        # Title patterns for leadership
        self.leadership_titles = [
            'ceo', 'chief executive', 'president', 'chairman', 'founder',
            'managing director', 'managing principal', 'managing partner',
            'principal', 'partner', 'executive vice president', 'evp',
            'senior vice president', 'svp', 'vice president', 'vp',
            'director', 'broker', 'senior advisor', 'advisor'
        ]
    
    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch and parse a webpage"""
        try:
            time.sleep(self.delay)
            response = self.session.get(url, timeout=15, allow_redirects=True)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except requests.exceptions.RequestException as e:
            print(f"  Error fetching {url}: {str(e)[:50]}")
            return None
    
    def find_links_by_keywords(self, soup: BeautifulSoup, base_url: str, keywords: List[str]) -> List[str]:
        """Find links on page that match keywords in href or link text"""
        found_urls = []
        seen = set()

        for link in soup.find_all('a', href=True):
            href = link['href'].lower()
            text = link.get_text().lower().strip()

            # Skip external links, anchors, javascript, etc.
            if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
                continue

            # Check if any keyword matches href or link text
            for keyword in keywords:
                if keyword in href or keyword in text:
                    full_url = urljoin(base_url, link['href'])
                    # Only include URLs from same domain
                    if urlparse(base_url).netloc in full_url and full_url not in seen:
                        seen.add(full_url)
                        found_urls.append(full_url)
                    break

        return found_urls

    def find_page(self, base_url: str, patterns: List[str], homepage_soup: BeautifulSoup = None, page_type: str = None) -> Optional[tuple]:
        """Try to find a page by checking cache, crawling links, then falling back to static patterns"""

        # Define keywords for different page types
        keyword_map = {
            'team': ['team', 'leadership', 'people', 'staff', 'broker', 'agent', 'professional', 'advisor', 'who we are', 'meet'],
            'services': ['service', 'solution', 'capabilit', 'expertise', 'what we do', 'brokerage', 'management'],
            'contact': ['contact', 'location', 'office', 'find us', 'reach us', 'get in touch'],
        }

        # Determine page type and keywords
        if not page_type:
            for ptype in keyword_map.keys():
                if any(ptype in p or f'/{ptype}' in p for p in patterns[:3]):
                    page_type = ptype
                    break
        keywords = keyword_map.get(page_type, [])

        # Cache key for this site + page type
        cache_key = f"{base_url}|{page_type}"

        # FIRST: Check URL cache from previous runs
        if cache_key in self.url_cache:
            cached_url = self.url_cache[cache_key]
            print(f"    Using cached URL: {cached_url}", flush=True)
            soup = self.fetch_page(cached_url)
            if soup:
                title = soup.find('title')
                if title and '404' not in title.text.lower() and 'not found' not in title.text.lower():
                    return cached_url, soup
            # Cache miss - URL no longer valid, remove it
            print(f"    Cached URL invalid, re-crawling...", flush=True)
            del self.url_cache[cache_key]

        # SECOND: Try crawling links from homepage if provided
        if homepage_soup and keywords:
            crawled_urls = self.find_links_by_keywords(homepage_soup, base_url, keywords)
            if crawled_urls:
                print(f"    Crawled {len(crawled_urls)} matching links", flush=True)
            for url in crawled_urls[:5]:  # Try top 5 matching links
                soup = self.fetch_page(url)
                if soup:
                    title = soup.find('title')
                    if title and '404' not in title.text.lower() and 'not found' not in title.text.lower():
                        print(f"    -> Found via crawl: {url}", flush=True)
                        # Save to cache for next run
                        self.url_cache[cache_key] = url
                        return url, soup

        # THIRD: Fallback to static URL patterns
        for pattern in patterns:
            url = urljoin(base_url, pattern)
            soup = self.fetch_page(url)
            if soup:
                # Check if it's a real page (not 404 soft redirect)
                title = soup.find('title')
                if title and '404' not in title.text.lower() and 'not found' not in title.text.lower():
                    # Save to cache for next run
                    self.url_cache[cache_key] = url
                    return url, soup

        return None, None
    
    def extract_emails(self, soup: BeautifulSoup) -> List[str]:
        """Extract email addresses from page"""
        emails = set()
        
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
    
    def extract_phones(self, soup: BeautifulSoup) -> List[str]:
        """Extract phone numbers from page"""
        phones = set()
        text = soup.get_text()
        
        # Various phone patterns
        patterns = [
            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # (XXX) XXX-XXXX or XXX-XXX-XXXX
            r'\d{3}[-.\s]\d{3}[-.\s]\d{4}',  # XXX.XXX.XXXX
        ]
        
        for pattern in patterns:
            for match in re.findall(pattern, text):
                # Clean up
                cleaned = re.sub(r'[^\d]', '', match)
                if len(cleaned) == 10:
                    formatted = f"({cleaned[:3]}) {cleaned[3:6]}-{cleaned[6:]}"
                    phones.add(formatted)
        
        return list(phones)
    
    def extract_addresses(self, soup: BeautifulSoup) -> List[str]:
        """Extract street addresses"""
        addresses = []
        text = soup.get_text()
        
        # Look for address patterns
        # This is simplified - addresses are tricky
        lines = text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            # Look for street number + street name pattern
            if re.match(r'^\d+\s+[A-Za-z]', line) and len(line) < 100:
                # Check if next line might be city, state zip
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    state_pattern = r'[A-Z]{2}\s+\d{5}'
                    if re.search(state_pattern, next_line) or re.search(state_pattern, line):
                        addresses.append(f"{line} {next_line}".strip())
                        continue
                addresses.append(line)
        
        return addresses[:5]  # Limit to 5
    
    def _is_valid_person_name(self, name: str) -> bool:
        """Check if a string looks like a valid person name"""
        if not name or len(name) < 3:
            return False

        # Must be reasonable length (2-50 chars)
        if len(name) > 50:
            return False

        # Must have 2-5 words (First Last or First Middle Last, etc.)
        words = name.split()
        if len(words) < 2 or len(words) > 5:
            return False

        # Each word should start with capital letter (names)
        if not all(w[0].isupper() for w in words if w):
            return False

        # Should not contain these patterns (headlines, categories, links)
        bad_patterns = [
            'click', 'watch', 'discover', 'learn', 'read', 'view', 'see',
            'http', 'www', '.com', 'download', 'subscribe', 'contact',
            'valuation', 'advisory', 'services', 'solutions', 'capital',
            'investment', 'brokerage', 'management', 'board of', 'global',
            'about', 'our team', 'leadership team', 'meet the', 'news',
            ' - ', ' | ', ' & ', 'llc', 'inc', 'corp'
        ]
        name_lower = name.lower()
        if any(pattern in name_lower for pattern in bad_patterns):
            return False

        # Should not be all caps
        if name.isupper():
            return False

        # Should not have numbers
        if any(c.isdigit() for c in name):
            return False

        return True

    def extract_leadership(self, soup: BeautifulSoup, source_url: str) -> List[Person]:
        """Extract leadership/team members from page"""
        people = []

        # Common containers for team members - be specific
        containers = soup.find_all(['div', 'article', 'li'],
                                   class_=re.compile(r'team[-_]?member|person|staff|employee|profile|broker|agent|bio[-_]?card', re.I))

        # If no specific containers, try card-style layouts
        if not containers:
            containers = soup.find_all(['div', 'article'],
                                       class_=re.compile(r'card(?!s)|member|people', re.I))

        for container in containers:
            person = self._parse_person_container(container, source_url)
            if person and person.name and self._is_valid_person_name(person.name):
                # Filter to likely leadership based on title
                if person.title:
                    title_lower = person.title.lower()
                    if any(lt in title_lower for lt in self.leadership_titles):
                        people.append(person)
                elif len(people) < 20:  # Include some without titles if we don't have many
                    people.append(person)
        
        # Deduplicate by name
        seen_names = set()
        unique_people = []
        for p in people:
            name_key = p.name.lower().strip()
            if name_key not in seen_names and len(name_key) > 2:
                seen_names.add(name_key)
                unique_people.append(p)
        
        return unique_people[:30]  # Limit to 30
    
    def _parse_person_container(self, container, source_url: str) -> Optional[Person]:
        """Parse a container element to extract person info"""
        person = Person(name="", source_url=source_url)

        # Look for name - usually in h2, h3, h4, or strong/b
        name_elem = container.find(['h2', 'h3', 'h4', 'h5', 'strong', 'b', 'span'],
                                   class_=re.compile(r'name|title|heading', re.I))
        if not name_elem:
            name_elem = container.find(['h2', 'h3', 'h4', 'h5'])

        if name_elem:
            # Use separator=' ' to handle cases like <h4>First<span>Last</span></h4>
            person.name = name_elem.get_text(separator=' ').strip()

        # Look for title/position
        title_elem = container.find(['p', 'span', 'div'],
                                    class_=re.compile(r'title|position|role|job|designation', re.I))
        if title_elem:
            person.title = title_elem.get_text(separator=' ').strip()
        else:
            # Try next sibling after name
            if name_elem and name_elem.find_next_sibling(['p', 'span']):
                person.title = name_elem.find_next_sibling(['p', 'span']).get_text(separator=' ').strip()
        
        # Look for email
        email_link = container.find('a', href=re.compile(r'^mailto:', re.I))
        if email_link:
            person.email = email_link['href'].replace('mailto:', '').split('?')[0].strip()
        
        # Look for phone
        phone_link = container.find('a', href=re.compile(r'^tel:', re.I))
        if phone_link:
            person.phone = phone_link['href'].replace('tel:', '').strip()
        
        # Look for LinkedIn
        linkedin_link = container.find('a', href=re.compile(r'linkedin\.com', re.I))
        if linkedin_link:
            person.linkedin = linkedin_link['href']
        
        # Clean up name (remove extra whitespace, titles)
        if person.name:
            person.name = ' '.join(person.name.split())
            # Remove common suffixes that got included
            person.name = re.sub(r',?\s*(CCIM|SIOR|CPM|MAI|CPA|MBA|JD|PhD).*$', '', person.name, flags=re.I)
        
        # Clean up title
        if person.title:
            person.title = ' '.join(person.title.split())[:100]  # Limit length
        
        return person if person.name else None
    
    def extract_services(self, soup: BeautifulSoup) -> List[str]:
        """Extract services offered"""
        services = set()
        text = soup.get_text().lower()
        
        for keyword in self.service_keywords:
            if keyword in text:
                services.add(keyword.title())
        
        # Also look for service lists
        for ul in soup.find_all('ul'):
            for li in ul.find_all('li'):
                li_text = li.get_text().lower().strip()
                for keyword in self.service_keywords:
                    if keyword in li_text:
                        services.add(keyword.title())
        
        return sorted(list(services))
    
    def extract_specialties(self, soup: BeautifulSoup) -> List[str]:
        """Extract asset class specialties"""
        specialties = set()
        text = soup.get_text().lower()
        
        for keyword in self.asset_keywords:
            if keyword in text:
                specialties.add(keyword.title())
        
        return sorted(list(specialties))
    
    def scrape_firm(self, company_name: str, website: str) -> FirmData:
        """Main method to scrape a single firm"""
        print(f"\nScraping: {company_name} ({website})", flush=True)
        
        # Normalize website URL
        if not website.startswith('http'):
            website = 'https://' + website
        website = website.rstrip('/')
        
        firm = FirmData(
            company_name=company_name,
            website=website,
            scraped_at=datetime.now().isoformat()
        )
        
        # Scrape homepage first
        print(f"  Fetching homepage...", flush=True)
        homepage = self.fetch_page(website)
        if homepage:
            firm.pages_scraped.append(website)
            firm.services.extend(self.extract_services(homepage))
            firm.specialties.extend(self.extract_specialties(homepage))
            emails = self.extract_emails(homepage)
            phones = self.extract_phones(homepage)
            if emails:
                firm.main_email = emails[0]
            if phones:
                firm.main_phone = phones[0]
        else:
            firm.errors.append(f"Could not fetch homepage: {website}")
            return firm
        
        # Find and scrape team/leadership page (crawl homepage links first)
        print(f"  Looking for team/leadership page...", flush=True)
        team_url, team_soup = self.find_page(website, self.team_patterns, homepage_soup=homepage)
        if team_soup:
            print(f"  Found: {team_url}")
            firm.pages_scraped.append(team_url)
            firm.leadership = self.extract_leadership(team_soup, team_url)
            print(f"  Extracted {len(firm.leadership)} people")

        # Find and scrape services page (crawl homepage links first)
        print(f"  Looking for services page...", flush=True)
        services_url, services_soup = self.find_page(website, self.services_patterns, homepage_soup=homepage)
        if services_soup:
            print(f"  Found: {services_url}")
            firm.pages_scraped.append(services_url)
            firm.services.extend(self.extract_services(services_soup))
            firm.specialties.extend(self.extract_specialties(services_soup))

        # Find and scrape contact page (crawl homepage links first)
        print(f"  Looking for contact page...", flush=True)
        contact_url, contact_soup = self.find_page(website, self.contact_patterns, homepage_soup=homepage)
        if contact_soup:
            print(f"  Found: {contact_url}")
            firm.pages_scraped.append(contact_url)
            if not firm.main_email:
                emails = self.extract_emails(contact_soup)
                if emails:
                    firm.main_email = emails[0]
            if not firm.main_phone:
                phones = self.extract_phones(contact_soup)
                if phones:
                    firm.main_phone = phones[0]
            addresses = self.extract_addresses(contact_soup)
            if addresses:
                firm.headquarters_address = addresses[0]
                firm.office_locations = addresses
        
        # Deduplicate services and specialties
        firm.services = sorted(list(set(firm.services)))
        firm.specialties = sorted(list(set(firm.specialties)))
        
        return firm
    
    def scrape_multiple(self, firms: List[Dict]) -> List[FirmData]:
        """Scrape multiple firms"""
        results = []
        total = len(firms)
        
        for i, firm in enumerate(firms, 1):
            print(f"\n{'='*60}", flush=True)
            print(f"Progress: {i}/{total}", flush=True)
            
            try:
                result = self.scrape_firm(
                    company_name=firm.get('name', ''),
                    website=firm.get('website', '')
                )
                results.append(result)
            except Exception as e:
                print(f"  ERROR: {str(e)}")
                results.append(FirmData(
                    company_name=firm.get('name', ''),
                    website=firm.get('website', ''),
                    errors=[str(e)]
                ))
        
        return results


def export_to_csv(firms: List[FirmData], filename: str):
    """Export scraped data to CSV"""
    
    # Main firm data
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Company Name', 'Website', 'Main Phone', 'Main Email',
            'HQ Address', 'Services', 'Specialties', 
            'Leadership Count', 'Pages Scraped', 'Scraped At', 'Errors'
        ])
        
        for firm in firms:
            writer.writerow([
                firm.company_name,
                firm.website,
                firm.main_phone,
                firm.main_email,
                firm.headquarters_address,
                '; '.join(firm.services),
                '; '.join(firm.specialties),
                len(firm.leadership),
                len(firm.pages_scraped),
                firm.scraped_at,
                '; '.join(firm.errors)
            ])
    
    # Leadership data in separate file
    leadership_file = filename.replace('.csv', '_leadership.csv')
    with open(leadership_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Company Name', 'Person Name', 'Title', 'Email', 'Phone', 'LinkedIn', 'Source URL'
        ])
        
        for firm in firms:
            for person in firm.leadership:
                writer.writerow([
                    firm.company_name,
                    person.name,
                    person.title,
                    person.email,
                    person.phone,
                    person.linkedin,
                    person.source_url
                ])
    
    print(f"\nExported to {filename}")
    print(f"Leadership exported to {leadership_file}")


def export_to_json(firms: List[FirmData], filename: str):
    """Export to JSON for further processing"""
    data = []
    for firm in firms:
        firm_dict = asdict(firm)
        # Convert Person objects
        firm_dict['leadership'] = [asdict(p) if hasattr(p, '__dict__') else p for p in firm.leadership]
        data.append(firm_dict)
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported to {filename}")


# ============================================================
# TARGET FIRMS TO SCRAPE
# ============================================================

# 47 verified accessible firms as of Dec 2024
# (CBRE and Colliers block scrapers with 403)
TARGET_FIRMS = [
    # Columbus (14 firms)
    {"name": "JLL Columbus", "website": "www.us.jll.com/en/locations/midwest/columbus"},
    {"name": "Cushman & Wakefield Columbus", "website": "www.cushmanwakefield.com/en/united-states/offices/columbus"},
    {"name": "Avison Young Columbus", "website": "www.avisonyoung.us/web/columbus"},
    {"name": "Marcus & Millichap Columbus", "website": "www.marcusmillichap.com/about-us/offices/columbus-ohio"},
    {"name": "Newmark Columbus", "website": "www.nmrk.com/offices/columbus"},
    {"name": "Lee & Associates Columbus", "website": "www.lee-associates.com/columbus/"},
    {"name": "NAI Ohio Equities", "website": "www.ohioequities.com"},
    {"name": "Best Corporate Real Estate", "website": "www.bestcorporaterealestate.com"},
    {"name": "The Robert Weiler Company", "website": "rweiler.com"},
    {"name": "KRG Real Estate", "website": "krgre.com"},
    {"name": "DRK & Company Realty", "website": "drk-realty.com"},
    {"name": "Hanna Commercial Real Estate", "website": "hannacre.com"},
    {"name": "Equity Commercial Real Estate", "website": "equity.net"},
    {"name": "Nationwide Realty Investors", "website": "www.nationwiderealtyinvestors.com"},
    {"name": "CASTO", "website": "castoinfo.com"},
    {"name": "Thrive Companies", "website": "thrivecos.com"},
    {"name": "Kaufman Development", "website": "www.livekaufman.com"},

    # Cincinnati (4 firms)
    {"name": "Cushman & Wakefield Cincinnati", "website": "www.cushmanwakefield.com/en/united-states/offices/cincinnati"},
    {"name": "Lee & Associates Cincinnati", "website": "www.lee-cincinnati.com"},
    {"name": "NAI Bergman", "website": "bergmancommercial.com"},

    # Dayton (1 firm)
    {"name": "APEX Commercial Group", "website": "apexcommercialgroup.com"},

    # Cleveland (2 firms)
    {"name": "Cushman & Wakefield CRESCO", "website": "crescorealestate.com"},
    {"name": "Newmark Cleveland", "website": "terrycoyne.com"},

    # Indianapolis (5 firms)
    {"name": "Cushman & Wakefield Indianapolis", "website": "www.cushmanwakefield.com/en/united-states/offices/indianapolis"},
    {"name": "JLL Indianapolis", "website": "www.us.jll.com/en/locations/midwest/indianapolis"},
    {"name": "Bradley Company", "website": "www.bradleyco.com"},
    {"name": "Lee & Associates Indianapolis", "website": "www.lee-associates.com/offices/"},

    # Chicago (6 firms)
    {"name": "NAI Hiffman", "website": "hiffman.com"},
    {"name": "JLL Chicago", "website": "www.us.jll.com/en/locations/midwest/chicago"},
    {"name": "Cushman & Wakefield Chicago", "website": "www.cushmanwakefield.com/en/united-states/offices/chicago"},
    {"name": "SVN Chicago Commercial", "website": "svnchicago.com"},
    {"name": "Interra Realty", "website": "interrarealty.com"},

    # Pittsburgh (4 firms)
    {"name": "JLL Pittsburgh", "website": "www.us.jll.com/en/locations/northeast/pittsburgh"},
    {"name": "Newmark Pittsburgh", "website": "www.nmrk.com/offices/pittsburgh"},
    {"name": "Pennsylvania Commercial Real Estate", "website": "www.penncom.com"},
    {"name": "Hanna Commercial Pittsburgh", "website": "hannacre.com"},

    # Charlotte (8 firms)
    {"name": "JLL Charlotte", "website": "www.us.jll.com/en/locations/southeast/charlotte"},
    {"name": "Cushman & Wakefield Charlotte", "website": "www.cushmanwakefield.com/en/united-states/offices/charlotte"},
    {"name": "Trinity Partners", "website": "www.trinity-partners.com"},
    {"name": "Lincoln Property Company Charlotte", "website": "lpc.com/office/charlotte/"},
    {"name": "Foundry Commercial", "website": "www.foundrycommercial.com/locations/charlotte/"},
    {"name": "Childress Klein", "website": "childressklein.com"},
    {"name": "The Keith Corporation", "website": "thekeithcorp.com"},
    {"name": "Lee & Associates Charlotte", "website": "www.lee-associates.com/offices/"},

    # Savannah (3 firms)
    {"name": "Avison Young Savannah", "website": "www.avisonyoung.us/web/savannah"},
    {"name": "NAI Mopper Benton", "website": "www.naisavannah.com"},
]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='CRE Firm Website Scraper')
    parser.add_argument('--rescrape-all', action='store_true', help='Re-scrape all firms, ignoring previous results')
    parser.add_argument('--delay', type=int, default=2, help='Delay between requests in seconds (default: 2)')
    args = parser.parse_args()

    print("="*60)
    print("CRE FIRM WEBSITE SCRAPER")
    print("="*60)

    # Load previous data
    url_cache = load_url_cache()
    previous_results = load_previous_results()

    print(f"Target firms: {len(TARGET_FIRMS)}")
    print(f"Cached URLs: {len(url_cache)}")
    print(f"Previously scraped: {len(previous_results)} firms")

    # Determine which firms to scrape
    if args.rescrape_all:
        firms_to_scrape = TARGET_FIRMS
        print("Mode: Re-scraping ALL firms")
    else:
        # Only scrape firms not previously scraped
        firms_to_scrape = []
        for firm in TARGET_FIRMS:
            website = firm['website']
            if not website.startswith('http'):
                website = 'https://' + website
            website = website.rstrip('/')
            if website not in previous_results:
                firms_to_scrape.append(firm)

        print(f"New firms to scrape: {len(firms_to_scrape)}")
        if len(firms_to_scrape) == 0:
            print("All firms already scraped. Use --rescrape-all to refresh.")

    if firms_to_scrape:
        print("Starting in 3 seconds...")
        time.sleep(3)

        scraper = CREWebsiteScraper(delay_seconds=args.delay, url_cache=url_cache)
        new_results = scraper.scrape_multiple(firms_to_scrape)

        # Save updated URL cache
        save_url_cache(scraper.url_cache)
        print(f"\nSaved {len(scraper.url_cache)} URLs to cache")

        # Merge new results with previous results
        all_results_dict = previous_results.copy()
        for firm in new_results:
            all_results_dict[firm.website] = asdict(firm)

        # Convert back to list
        all_results = [FirmData(**data) if isinstance(data, dict) else data for data in all_results_dict.values()]

        # For FirmData reconstruction, handle leadership
        final_results = []
        for data in all_results_dict.values():
            if isinstance(data, dict):
                # Reconstruct Person objects for leadership
                leadership = [Person(**p) if isinstance(p, dict) else p for p in data.get('leadership', [])]
                data['leadership'] = leadership
                final_results.append(FirmData(**data))
            else:
                final_results.append(data)

        results = final_results
    else:
        # No new firms to scrape, just use previous results
        results = []
        for data in previous_results.values():
            leadership = [Person(**p) if isinstance(p, dict) else p for p in data.get('leadership', [])]
            data['leadership'] = leadership
            results.append(FirmData(**data))

    # Export results
    export_to_csv(results, 'scraped_firms.csv')
    export_to_json(results, RESULTS_FILE)

    # Print summary
    print("\n" + "="*60)
    print("SCRAPING COMPLETE - SUMMARY")
    print("="*60)

    total_leadership = sum(len(f.leadership) for f in results)
    firms_with_leadership = sum(1 for f in results if f.leadership)
    firms_with_errors = sum(1 for f in results if f.errors)

    print(f"Total firms in database: {len(results)}")
    print(f"Firms with leadership found: {firms_with_leadership}")
    print(f"Total leadership contacts: {total_leadership}")
    print(f"Firms with errors: {firms_with_errors}")

    print("\nTop firms by contacts found:")
    sorted_firms = sorted(results, key=lambda x: len(x.leadership), reverse=True)
    for firm in sorted_firms[:10]:
        print(f"  {firm.company_name}: {len(firm.leadership)} people, {len(firm.services)} services")
