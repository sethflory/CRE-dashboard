"""
LinkedIn Profile & Company Scraper for CRE Intelligence

WORKFLOW:
1. Search for a person at a brokerage
2. Scrape their profile and work history
3. Go to company page, find other employees
4. Add employees to contacts list
5. Add previous CRE employers to brokerage list
6. Repeat for discovered firms

SETUP:
    pip install playwright
    python -m playwright install chromium

WARNING: LinkedIn actively blocks scrapers. Use responsibly with delays.
"""

import json
import os
import time
import random
from typing import Optional, List, Dict, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime

from playwright.sync_api import sync_playwright, Page, Browser

# File paths
COOKIES_FILE = 'linkedin_cookies.json'
DISCOVERED_FIRMS_FILE = 'discovered_firms.json'
DISCOVERED_CONTACTS_FILE = 'discovered_contacts.json'
ENRICHED_DATA_FILE = 'linkedin_enriched.json'

# CRE-related keywords to identify relevant firms
CRE_KEYWORDS = [
    'real estate', 'realty', 'commercial', 'property', 'properties',
    'brokerage', 'cbre', 'jll', 'cushman', 'colliers', 'newmark',
    'marcus millichap', 'investment sales', 'capital markets',
    'industrial', 'retail', 'multifamily', 'development',
    'asset management', 'property management', 'leasing', 'nai ',
    'svn', 'keller williams commercial', 'lee & associates', 'avison young',
    'berkadia', 'marcus & millichap', 'kidder mathews', 'cresa',
    'transwestern', 'savills', 'knight frank', 'eastdil'
]

# URL patterns to skip (sub-pages, overlays, etc.)
SKIP_URL_PATTERNS = ['/overlay/', '/details/', '/recent-activity/', '/single-media-viewer', '/endorsers']

# Names/text that indicate UI elements, not real people
SKIP_NAMES = [
    'view', 'see all', 'show more', 'show all', 'connect', 'message', 'follow',
    'show all posts', 'endorsements', 'show all skills', 'show all honors',
    'show all organizations', 'show all companies', 'endorsed by', 'given'
]

# Patterns that indicate non-person names in batch processing
BAD_NAME_PATTERNS = [
    'professional', 'affiliations', 'services', 'contact',
    'about', 'team', 'leadership', 'management', 'board',
    'investment', 'capital', 'advisory', 'valuation', 'group',
    'division', 'department', 'office', 'regional', 'national'
]

# Words that indicate job titles
TITLE_KEYWORDS = [
    'president', 'chairman', 'director', 'manager', 'associate', 'analyst',
    'broker', 'agent', 'executive', 'officer', 'partner', 'principal', 'vp', 'svp', 'evp'
]

# Employment types to skip when parsing work history
EMPLOYMENT_TYPES = ['full-time', 'part-time', 'contract', 'freelance', 'self-employed']

# Known non-groups (people, companies, influencers to filter out)
NON_GROUP_NAMES = {
    'Hubert Joly', 'Pat Gelsinger', 'Ian Bremmer', 'Scott Belsky',
    'Intel Corporation', 'CBRE', 'GE Capital', 'Accenture',
    'Cushman & Wakefield', 'Tony Robbins', 'Mark Cuban', 'Daymond John',
    'Arvind Krishna', 'Diana Olick', 'Deutsche Bank', 'Spencer Rascoff',
    'Heather Elias', 'David H. Stevens, CMB', 'Eric Partaker', 'Robert Herjavec',
    'Prof. Jonathan A.J. Wilson PhD DLitt', 'Nationwide', 'Bill Gates',
    'Gary Vaynerchuk', 'Grant Cardone', 'Barbara Corcoran', 'Ryan Serhant',
    'Elon Musk', 'Jeff Bezos', 'Satya Nadella', 'Tim Cook', 'Simon Sinek',
    'IBM', 'Oracle', 'Microsoft', 'J.P. Morgan', 'Fidelity Investments',
    'Cardinal Health', 'L Brands', 'CoStar Group', 'Gates Notes'
}


@dataclass
class LinkedInPerson:
    """Person discovered on LinkedIn"""
    name: str
    linkedin_url: str = ""
    headline: str = ""
    location: str = ""
    current_company: str = ""
    current_title: str = ""
    company_linkedin_url: str = ""
    work_history: List[Dict] = field(default_factory=list)
    education: List[Dict] = field(default_factory=list)  # Schools attended
    groups: List[str] = field(default_factory=list)  # LinkedIn groups (under Interests)
    recent_posts: List[Dict] = field(default_factory=list)  # Recent activity/posts
    about: str = ""  # Bio/About section
    discovered_from: str = ""  # How we found this person
    scraped_at: str = ""


@dataclass
class LinkedInCompany:
    """Company discovered on LinkedIn"""
    name: str
    linkedin_url: str = ""
    website: str = ""
    industry: str = ""
    employee_count: str = ""
    headquarters: str = ""
    discovered_from: str = ""
    is_cre_related: bool = False
    employees_scraped: List[str] = field(default_factory=list)


class LinkedInScraper:
    """LinkedIn scraper for CRE intelligence gathering"""

    def __init__(self, headless: bool = False):
        self.playwright = None
        self.browser: Browser = None
        self.page: Page = None
        self.headless = headless
        self.logged_in = False

        # Data stores
        self.discovered_firms: Dict[str, LinkedInCompany] = {}
        self.discovered_contacts: Dict[str, LinkedInPerson] = {}
        self.processed_profiles: Set[str] = set()
        self.processed_companies: Set[str] = set()

        self._load_data()

    def _random_delay(self, min_sec: float = 2, max_sec: float = 5):
        """Random delay to appear human"""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)

    def _log(self, msg: str):
        """Print with timestamp"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    # ==================== URL & NAME HELPERS ====================

    def _extract_profile_key(self, url: str) -> str:
        """Extract profile key from LinkedIn URL (e.g., 'terrycoyne' from '/in/terrycoyne/')"""
        if not url or '/in/' not in url:
            return ""
        return url.split('/in/')[-1].strip('/').split('/')[0].split('?')[0]

    def _normalize_url(self, href: str, base: str = "https://www.linkedin.com") -> str:
        """Normalize a LinkedIn URL - ensure it's absolute and clean"""
        if not href:
            return ""
        url = href.split('?')[0]  # Remove query params
        if not url.startswith('http'):
            url = base + url
        return url

    def _should_skip_url(self, url: str) -> bool:
        """Check if URL should be skipped (overlays, details pages, etc.)"""
        return any(pattern in url for pattern in SKIP_URL_PATTERNS)

    def _should_skip_name(self, name: str) -> bool:
        """Check if name is actually UI text and should be skipped"""
        if not name:
            return True
        name_lower = name.lower()
        if any(skip in name_lower for skip in SKIP_NAMES):
            return True
        if name_lower.startswith('show all') or 'endorsement' in name_lower:
            return True
        return False

    def _is_valid_person_name(self, name: str) -> bool:
        """Validate that a string looks like a real person's name"""
        if not name or len(name) < 3:
            return False
        words = name.split()
        if len(words) < 2 or len(words) > 5:
            return False
        if not all(w[0].isupper() for w in words if w):
            return False
        name_lower = name.lower()
        if any(p in name_lower for p in BAD_NAME_PATTERNS):
            return False
        return True

    def _looks_like_person_name(self, text: str) -> bool:
        """Heuristic for group filtering: detect person-name style strings."""
        if not text:
            return False
        text = text.strip()
        words = text.split()
        if len(words) < 2 or len(words) > 4:
            return False
        if any(ch.isdigit() for ch in text):
            return False
        # Allow initials but otherwise expect title-case words.
        for word in words:
            if len(word) == 1 and word.isupper():
                continue
            if not (word[0].isupper() and (len(word) == 1 or word[1:].islower())):
                return False
        return True

    def _looks_like_company_name(self, text: str) -> bool:
        """Heuristic for company names to avoid misclassifying as titles/groups."""
        if not text:
            return False
        lowered = text.lower()
        company_tokens = [
            'inc', 'llc', 'corp', 'co', 'company', 'corporation', 'ltd',
            'capital', 'partners', 'properties', 'realty', 'holdings', 'group',
            'investments', 'bank', 'associates', 'technology'
        ]
        return any(tok in lowered for tok in company_tokens)

    def _looks_like_title(self, text: str) -> bool:
        """Heuristic for job titles."""
        if not text:
            return False
        lowered = text.lower()
        return any(tw in lowered for tw in TITLE_KEYWORDS)

    def _is_invalid_company_name(self, text: str) -> bool:
        """Filter out UI noise or titles captured as company names."""
        if not text:
            return True
        lowered = text.lower().strip()
        if lowered.startswith('you both worked at'):
            return True
        if lowered in {'private company', 'public company', 'company', 'self-employed', 'freelance'}:
            return True
        if self._looks_like_title(text) and not self._looks_like_company_name(text):
            return True
        return False

    def _is_valid_group_name(self, text: str, skip_names: Optional[Set[str]] = None) -> bool:
        """Filter for professional groups, not people/companies/newsletters."""
        if not text:
            return False
        name = text.strip()
        lowered = name.lower()

        if skip_names and name in skip_names:
            return False

        # Reject obvious non-groups.
        if self._looks_like_person_name(name):
            return False

        if self._looks_like_company_name(name):
            group_keywords = [
                'association', 'society', 'council', 'institute', 'network',
                'chapter', 'roundtable', 'forum', 'club', 'community', 'chamber',
                'professionals', 'executives', 'leaders', 'investors',
                'real estate', 'commercial', 'proptech', 'prop tech', 'cre',
                'alumni'
            ]
            if not any(kw in lowered for kw in group_keywords):
                return False

        newsletter_keywords = ['newsletter', 'edition', 'digest', 'report', 'insider']
        if any(kw in lowered for kw in newsletter_keywords):
            return False

        return len(name) > 2

    def _clean_person_record(self, person: LinkedInPerson):
        """Normalize fields for consistent contact records."""
        # Normalize groups to professional groups only.
        if person.groups:
            cleaned_groups = []
            seen = set()
            for group in person.groups:
                if not self._is_valid_group_name(group, skip_names=NON_GROUP_NAMES):
                    continue
                if group not in seen:
                    cleaned_groups.append(group)
                    seen.add(group)
            person.groups = cleaned_groups

        # Clear invalid or title-like company values and try to promote to title if needed.
        if person.current_company and self._is_invalid_company_name(person.current_company):
            if not person.current_title and self._looks_like_title(person.current_company):
                person.current_title = person.current_company
            person.current_company = ""

        # Fix company using work history or headline.
        if not person.current_company:
            if person.work_history:
                first = person.work_history[0]
                company = first.get('company', '')
                if company and not self._is_invalid_company_name(company):
                    person.current_company = company
                    if first.get('company_linkedin'):
                        person.company_linkedin_url = first.get('company_linkedin', '')
            elif person.headline and (' at ' in person.headline or ' @ ' in person.headline):
                split_token = ' at ' if ' at ' in person.headline else ' @ '
                _, company_part = person.headline.split(split_token, 1)
                company_part = company_part.split('|')[0].strip()
                if company_part and not self._is_invalid_company_name(company_part):
                    person.current_company = company_part

        # Remove titles that are actually company names or duplicates of company.
        if person.current_title and person.current_company and person.current_title.strip() == person.current_company.strip():
            person.current_title = ""

        if (not person.current_title) or self._looks_like_company_name(person.current_title):
            # Try headline parsing if available.
            if person.headline and (' at ' in person.headline or ' @ ' in person.headline):
                split_token = ' at ' if ' at ' in person.headline else ' @ '
                title_part, _ = person.headline.split(split_token, 1)
                title_part = title_part.split('|')[0].strip()
                if title_part and self._looks_like_title(title_part):
                    person.current_title = title_part

            # Fallback to first work history title.
            if not person.current_title and person.work_history:
                title = person.work_history[0].get('title', '')
                if title and self._looks_like_title(title):
                    person.current_title = title

    def _find_section_by_id_or_text(self, section_id: str, header_text: str):
        """Find a section by ID or header text"""
        # Try by ID first
        section = self.page.query_selector(f'section:has(#{section_id})')
        if section:
            return section

        # Try finding element by ID and getting parent section
        elem = self.page.query_selector(f'#{section_id}')
        if elem:
            section = elem.evaluate('el => el.closest("section")')
            if section:
                return section

        # Fall back to searching sections by header text
        sections = self.page.query_selector_all('section')
        for section in sections:
            try:
                text = section.inner_text()[:100] if section else ""
                if header_text in text:
                    return section
            except:
                continue
        return None

    # ==================== BROWSER MANAGEMENT ====================

    def start(self):
        """Start the browser"""
        if not self.browser:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=['--disable-blink-features=AutomationControlled']
            )
            self.page = self.browser.new_page(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            self.page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        self._log("Browser started")

    def quit(self):
        """Close browser and save data"""
        self._save_data()
        if self.page:
            self.page.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        self.page = self.browser = self.playwright = None
        self._log("Browser closed")

    # ==================== LOGIN / COOKIES ====================

    def save_cookies(self):
        """Save cookies for future sessions"""
        if self.page:
            cookies = self.page.context.cookies()
            with open(COOKIES_FILE, 'w') as f:
                json.dump(cookies, f)
            self._log(f"Saved {len(cookies)} cookies")

    def load_cookies(self) -> bool:
        """Load cookies from previous session"""
        if not os.path.exists(COOKIES_FILE):
            self._log("No saved cookies found")
            return False

        self.start()
        self.page.goto("https://www.linkedin.com")
        self._random_delay(2, 3)

        with open(COOKIES_FILE, 'r') as f:
            cookies = json.load(f)

        self.page.context.add_cookies(cookies)
        self.page.reload()
        self._random_delay(3, 5)

        if self._is_logged_in():
            self.logged_in = True
            self._log("Logged in via cookies")
            return True
        else:
            self._log("Cookies expired")
            return False

    def _is_logged_in(self) -> bool:
        """Check if logged into LinkedIn"""
        try:
            self.page.wait_for_selector('.global-nav__me, .feed-identity-module', timeout=5000)
            return True
        except:
            return False

    def login(self, email: str, password: str) -> bool:
        """Login to LinkedIn"""
        self.start()
        self._log("Navigating to LinkedIn login...")
        self.page.goto("https://www.linkedin.com/login")
        self._random_delay(3, 5)

        try:
            email_field = self.page.wait_for_selector('#username', timeout=10000)
            email_field.type(email, delay=random.randint(50, 150))
            self._random_delay(0.5, 1)

            password_field = self.page.locator('#password')
            password_field.type(password, delay=random.randint(50, 150))
            self._random_delay(0.5, 1)

            self.page.click('button[type="submit"]')
            self._log("Submitted login, waiting...")
            self._random_delay(5, 8)

            if "checkpoint" in self.page.url or "challenge" in self.page.url:
                self._log("Security challenge! Complete it in the browser, then press Enter...")
                input()
                self._random_delay(2, 3)

            if self._is_logged_in():
                self.logged_in = True
                self.save_cookies()
                self._log("Login successful!")
                return True
            else:
                self._log("Login failed")
                return False

        except Exception as e:
            self._log(f"Login error: {e}")
            return False

    # ==================== DATA PERSISTENCE ====================

    def _load_data(self):
        """Load previously discovered data"""
        if os.path.exists(DISCOVERED_FIRMS_FILE):
            try:
                with open(DISCOVERED_FIRMS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, firm in data.items():
                        self.discovered_firms[key] = LinkedInCompany(**firm)
            except Exception as e:
                self._log(f"Error loading firms: {e}")

        if os.path.exists(DISCOVERED_CONTACTS_FILE):
            try:
                with open(DISCOVERED_CONTACTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, person in data.items():
                        self.discovered_contacts[key] = LinkedInPerson(**person)
                        self.processed_profiles.add(person.get('linkedin_url', ''))
            except Exception as e:
                self._log(f"Error loading contacts: {e}")

    def _save_data(self):
        """Save discovered data"""
        # Normalize all contact records before persisting.
        for contact in self.discovered_contacts.values():
            try:
                self._clean_person_record(contact)
            except Exception:
                continue

        # Save firms
        firms_data = {k: asdict(v) for k, v in self.discovered_firms.items()}
        with open(DISCOVERED_FIRMS_FILE, 'w', encoding='utf-8') as f:
            json.dump(firms_data, f, indent=2)

        # Save contacts
        contacts_data = {k: asdict(v) for k, v in self.discovered_contacts.items()}
        with open(DISCOVERED_CONTACTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(contacts_data, f, indent=2)

        self._log(f"Saved {len(self.discovered_firms)} firms, {len(self.discovered_contacts)} contacts")

        # Regenerate JS files for dashboard
        self._regenerate_dashboard_data()

    def _regenerate_dashboard_data(self):
        """Regenerate JS data files for the HTML dashboard"""
        # Known non-groups (people, companies, influencers to filter out)
        skip_groups = NON_GROUP_NAMES

        group_keywords = ['council', 'association', 'chamber', 'roundtable', 'insights',
                          'innovation', 'technology', 'administration', 'investors',
                          'newsletter', 'real estate', 'data center', 'machine learning',
                          'alumni']

        def is_likely_group(name):
            if name in skip_groups:
                return False
            if not self._is_valid_group_name(name, skip_names=skip_groups):
                return False
            name_lower = name.lower()
            if any(kw in name_lower for kw in group_keywords):
                return True
            if '|' in name or '&' in name:
                return True
            return False

        def normalize_company(company):
            if 'JLL' in company or 'jll' in company.lower():
                return 'JLL'
            elif 'Cushman' in company or 'cushman' in company.lower():
                return 'Cushman & Wakefield'
            elif 'Avison' in company or 'avison' in company.lower():
                return 'Avison Young'
            elif 'Marcus' in company:
                return 'Marcus & Millichap'
            elif 'Newmark' in company:
                return 'Newmark'
            elif 'Lee & Associates' in company or 'Lee &' in company:
                return 'Lee & Associates'
            elif 'Ohio Equities' in company or 'NAI Ohio' in company:
                return 'NAI Ohio Equities'
            elif 'Best Corporate' in company:
                return 'Best Corporate Real Estate'
            elif 'Weiler' in company or 'Robert Weiler' in company:
                return 'The Robert Weiler Company'
            elif 'KRG' in company:
                return 'KRG Real Estate'
            return company

        try:
            # Generate contacts JS
            contacts_js = {}
            for key, person in self.discovered_contacts.items():
                p = asdict(person) if hasattr(person, '__dataclass_fields__') else person
                enriched = bool(p.get('scraped_at') and p.get('headline'))

                raw_groups = p.get('groups', [])
                filtered_groups = [g for g in raw_groups if is_likely_group(g)]

                contacts_js[key] = {
                    'name': p['name'],
                    'linkedin_url': p['linkedin_url'],
                    'headline': p.get('headline', ''),
                    'location': p.get('location', ''),
                    'current_company': normalize_company(p.get('current_company', '')),
                    'education': p.get('education', []),
                    'groups': filtered_groups,
                    'about': (p.get('about', '') or '')[:200],
                    'enriched': enriched
                }

            with open('data_contacts.js', 'w', encoding='utf-8') as f:
                f.write('const contacts = ')
                json.dump(contacts_js, f, indent=2)
                f.write(';')

            # Generate firms JS (with market assignment)
            firms_js = []
            if os.path.exists('scraped_firms.json'):
                with open('scraped_firms.json', 'r', encoding='utf-8') as f:
                    firms_raw = json.load(f)

                for firm in firms_raw:
                    name = firm['company_name']
                    # Assign market based on company name
                    market = 'Other'
                    if 'Columbus' in name: market = 'Columbus'
                    elif 'Cincinnati' in name: market = 'Cincinnati'
                    elif 'Cleveland' in name or 'CRESCO' in name or 'Coyne' in name: market = 'Cleveland'
                    elif 'Indianapolis' in name: market = 'Indianapolis'
                    elif 'Chicago' in name or 'Hiffman' in name or 'Interra' in name or 'SVN' in name: market = 'Chicago'
                    elif 'Pittsburgh' in name or 'Hanna' in name or 'Pennsylvania' in name: market = 'Pittsburgh'
                    elif 'Charlotte' in name or 'Trinity' in name or 'Foundry' in name or 'Childress' in name or 'Keith' in name or 'Lincoln' in name: market = 'Charlotte'
                    elif 'Savannah' in name or 'Mopper' in name: market = 'Savannah'
                    elif any(x in name for x in ['Ohio Equities', 'Best Corporate', 'Weiler', 'KRG', 'DRK', 'Equity', 'Nationwide', 'CASTO', 'Thrive', 'Kaufman']): market = 'Columbus'
                    elif 'Bergman' in name or 'APEX' in name: market = 'Cincinnati'
                    elif 'Bradley' in name: market = 'Indianapolis'

                    firms_js.append({
                        'company_name': firm['company_name'],
                        'website': firm['website'],
                        'market': market,
                        'main_phone': firm.get('main_phone', ''),
                        'services': firm.get('services', []),
                        'specialties': firm.get('specialties', [])
                    })

                with open('data_firms.js', 'w', encoding='utf-8') as f:
                    f.write('const firms = ')
                    json.dump(firms_js, f, indent=2)
                    f.write(';')

            # Generate graph JSON (nodes + edges)
            def slugify(value: str) -> str:
                cleaned = ''.join(ch.lower() if ch.isalnum() else '-' for ch in value.strip())
                while '--' in cleaned:
                    cleaned = cleaned.replace('--', '-')
                return cleaned.strip('-')

            nodes = []
            edges = []
            node_ids = set()

            def add_node(node_id: str, node_type: str, label: str, attributes=None):
                if node_id in node_ids:
                    return
                node_ids.add(node_id)
                nodes.append({
                    'id': node_id,
                    'type': node_type,
                    'label': label,
                    'attributes': attributes or {}
                })

            def add_edge(edge_type: str, from_id: str, to_id: str, attributes=None):
                edge_id = f"{edge_type}:{from_id}->{to_id}"
                edges.append({
                    'id': edge_id,
                    'type': edge_type,
                    'from': from_id,
                    'to': to_id,
                    'attributes': attributes or {}
                })

            # Companies + Markets
            for firm in firms_js:
                company_id = f"company:{slugify(firm['company_name'])}"
                add_node(company_id, 'Company', firm['company_name'], {
                    'website': firm.get('website', ''),
                    'services': firm.get('services', []),
                    'specialties': firm.get('specialties', []),
                    'market': firm.get('market', '')
                })
                if firm.get('market'):
                    market_id = f"market:{slugify(firm['market'])}"
                    add_node(market_id, 'Market', firm['market'])
                    add_edge('operates_in', company_id, market_id)

            # People + Groups + Universities
            for key, person in contacts_js.items():
                person_id = f"person:{slugify(key)}"
                add_node(person_id, 'Person', person['name'], {
                    'headline': person.get('headline', ''),
                    'location': person.get('location', ''),
                    'linkedin_url': person.get('linkedin_url', ''),
                    'enriched': person.get('enriched', False)
                })

                company_name = person.get('current_company', '').strip()
                if company_name:
                    company_id = f"company:{slugify(company_name)}"
                    add_node(company_id, 'Company', company_name)
                    add_edge('employed_by', person_id, company_id)

                for group in person.get('groups', []):
                    if not group:
                        continue
                    group_id = f"group:{slugify(group)}"
                    add_node(group_id, 'Group', group)
                    add_edge('member_of', person_id, group_id)

                for edu in person.get('education', []):
                    school = edu.get('school', '').strip()
                    if not school:
                        continue
                    uni_id = f"university:{slugify(school)}"
                    add_node(uni_id, 'University', school)
                    add_edge('educated_at', person_id, uni_id)

            with open('graph.json', 'w', encoding='utf-8') as f:
                json.dump({'nodes': nodes, 'edges': edges}, f, indent=2)

            self._log(f"Regenerated dashboard JS files ({len(contacts_js)} contacts)")
        except Exception as e:
            self._log(f"Error regenerating dashboard data: {e}")

    # ==================== PERSON SCRAPING ====================

    def search_person(self, name: str, company: str = "") -> List[str]:
        """Search for person, return profile URLs"""
        if not self.logged_in:
            return []

        query = f"{name} {company}".strip()
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={query.replace(' ', '%20')}"

        self._log(f"Searching: {query}")
        self.page.goto(search_url)
        self._random_delay(4, 6)

        profile_urls = []
        try:
            # Wait for page to settle - multiple possible selectors for search results
            try:
                self.page.wait_for_selector('.search-results-container, .scaffold-layout__main, ul[role="list"]', timeout=15000)
            except:
                self._log("Waiting for any content...")
                self._random_delay(2, 3)

            self._random_delay(1, 2)

            # Take debug screenshot to see what's on the page
            self.page.screenshot(path='search_debug.png')
            self._log("Debug screenshot saved to search_debug.png")

            # Method 1: Look for all links containing /in/
            all_links = self.page.query_selector_all('a[href*="/in/"]')
            self._log(f"Found {len(all_links)} links with /in/")

            for link in all_links[:10]:
                try:
                    href = link.get_attribute('href')
                    if href and '/in/' in href and '/search/' not in href:
                        # Extract clean profile URL
                        if 'linkedin.com/in/' in href:
                            profile_url = href.split('?')[0]
                        else:
                            # Relative URL
                            profile_url = 'https://www.linkedin.com' + href.split('?')[0]

                        if profile_url not in profile_urls:
                            profile_urls.append(profile_url)
                            self._log(f"  Found profile URL: {profile_url}")
                except:
                    continue

            # Method 2: Look for entity result cards and extract links
            if not profile_urls:
                self._log("Trying entity result cards...")
                cards = self.page.query_selector_all('div.entity-result, li.reusable-search__result-container, div[data-chameleon-result-urn]')
                self._log(f"Found {len(cards)} result cards")

                for card in cards[:5]:
                    try:
                        link = card.query_selector('a[href*="/in/"]')
                        if link:
                            href = link.get_attribute('href')
                            if href and '/in/' in href:
                                profile_url = href.split('?')[0]
                                if not profile_url.startswith('http'):
                                    profile_url = 'https://www.linkedin.com' + profile_url
                                if profile_url not in profile_urls:
                                    profile_urls.append(profile_url)
                    except:
                        continue

            # Method 3: Click approach - find clickable name element
            if not profile_urls:
                self._log("Trying click approach to navigate to profile...")

                # Try multiple selectors for the clickable name
                click_selectors = [
                    'a.app-aware-link span[aria-hidden="true"]',  # Name text in search results
                    '.entity-result__title-text a',  # Entity result title link
                    'span.entity-result__title-text a',
                    '.reusable-search__result-container a.app-aware-link',
                    'li[class*="search"] a[href*="/in/"]',
                    'div[class*="result"] a[href*="/in/"]'
                ]

                for selector in click_selectors:
                    try:
                        elem = self.page.query_selector(selector)
                        if elem:
                            self._log(f"  Found clickable element with: {selector}")
                            elem.click()
                            self._random_delay(3, 5)

                            current_url = self.page.url
                            if '/in/' in current_url:
                                profile_url = current_url.split('?')[0]
                                profile_urls.append(profile_url)
                                self._log(f"  Navigated to profile: {profile_url}")
                                break
                    except Exception as e:
                        continue

                # Last resort: just click anything that looks like a person's name
                if not profile_urls:
                    try:
                        # Look for span with a name-like text pattern
                        name_spans = self.page.query_selector_all('span[aria-hidden="true"]')
                        for span in name_spans[:20]:
                            text = span.inner_text().strip()
                            # Check if it looks like the name we searched for
                            if name.split()[0].lower() in text.lower():
                                self._log(f"  Found name match: {text}")
                                parent_link = span.evaluate('el => el.closest("a")')
                                if parent_link:
                                    span.click()
                                    self._random_delay(3, 5)

                                    current_url = self.page.url
                                    if '/in/' in current_url:
                                        profile_url = current_url.split('?')[0]
                                        profile_urls.append(profile_url)
                                        self._log(f"  Navigated to profile: {profile_url}")
                                        break
                    except Exception as e:
                        self._log(f"  Name match click failed: {e}")

            self._log(f"Total profiles found: {len(profile_urls)}")

        except Exception as e:
            self._log(f"Search error: {e}")
            try:
                self.page.screenshot(path='search_error.png')
                self._log("Error screenshot saved to search_error.png")
            except:
                pass

        return profile_urls

    def scrape_person_profile(self, profile_url: str, discovered_from: str = "") -> Optional[LinkedInPerson]:
        """Scrape a LinkedIn profile"""
        if not self.logged_in:
            return None

        # Skip if already processed
        if profile_url in self.processed_profiles:
            self._log(f"Already processed: {profile_url}")
            return self.discovered_contacts.get(self._extract_profile_key(profile_url))

        self._log(f"Scraping profile: {profile_url}")
        self.page.goto(profile_url)
        self._random_delay(3, 5)

        # Take debug screenshot of profile page
        self.page.screenshot(path='profile_debug.png')
        self._log("Profile screenshot saved to profile_debug.png")

        person = LinkedInPerson(
            name="",
            linkedin_url=profile_url,
            discovered_from=discovered_from,
            scraped_at=datetime.now().isoformat()
        )

        try:
            self.page.wait_for_selector('h1', timeout=10000)

            # Name - the main h1 on the profile
            name_elem = self.page.query_selector('h1')
            if name_elem:
                person.name = name_elem.inner_text().strip()
                self._log(f"  Found name: {person.name}")

            # Headline - div right after the name section
            headline_elem = self.page.query_selector('div.text-body-medium')
            if headline_elem:
                person.headline = headline_elem.inner_text().strip()

            # Location - look for text containing location patterns
            location_selectors = [
                'span.text-body-small.inline',
                'div.text-body-small span:first-child',
                '[class*="top-card"] span.text-body-small'
            ]
            for sel in location_selectors:
                loc_elem = self.page.query_selector(sel)
                if loc_elem:
                    text = loc_elem.inner_text().strip()
                    if text and 'connection' not in text.lower():
                        person.location = text
                        break

            # Current company - look for company link in the profile header badges
            company_selectors = [
                'a[href*="/company/"] span',  # Company name in link
                'button[aria-label*="Current company"]',
                'div[class*="experience"] a[href*="/company/"]',
                'section a[href*="/company/"]'
            ]
            for sel in company_selectors:
                company_elem = self.page.query_selector(sel)
                if company_elem:
                    text = company_elem.inner_text().strip()
                    if text and len(text) > 1 and not self._is_invalid_company_name(text):
                        person.current_company = text
                        self._log(f"  Found company: {person.current_company}")
                        break

            # Company LinkedIn URL
            company_link = self.page.query_selector('a[href*="/company/"]')
            if company_link:
                href = company_link.get_attribute('href')
                if href:
                    person.company_linkedin_url = href.split('?')[0]
                    if not person.company_linkedin_url.startswith('http'):
                        person.company_linkedin_url = 'https://www.linkedin.com' + person.company_linkedin_url

            # About/Bio section - try multiple selectors
            about_selectors = [
                'section:has(#about) div.display-flex span[aria-hidden="true"]',
                'section:has(#about) span[aria-hidden="true"]',
                'section[id*="about"] span[aria-hidden="true"]',
                '#about ~ div span[aria-hidden="true"]',
                'div[class*="about"] span'
            ]
            for sel in about_selectors:
                about_elem = self.page.query_selector(sel)
                if about_elem:
                    about_text = about_elem.inner_text().strip()
                    if about_text and len(about_text) > 20:
                        person.about = about_text[:1000]  # Increased limit for full bio
                        break

            # Extract work history (need to scroll)
            self._extract_work_history(person)

            # If headline has a clean "Title at Company" format, use it as fallback.
            if person.headline and (' at ' in person.headline or ' @ ' in person.headline):
                split_token = ' at ' if ' at ' in person.headline else ' @ '
                title_part, company_part = person.headline.split(split_token, 1)
                title_part = title_part.split('|')[0].strip()
                company_part = company_part.split('|')[0].strip()
                if not person.current_title and title_part and self._looks_like_title(title_part):
                    person.current_title = title_part
                if (not person.current_company or self._is_invalid_company_name(person.current_company)) and company_part:
                    if not self._is_invalid_company_name(company_part):
                        person.current_company = company_part

            # Extract education
            self._extract_education(person)

            # Extract groups (under Interests)
            self._extract_groups(person)

            # Extract recent posts from Activity section
            self._extract_recent_posts(person)

            self._log(f"  Name: {person.name}")
            self._log(f"  Headline: {person.headline[:60]}..." if len(person.headline) > 60 else f"  Headline: {person.headline}")
            self._log(f"  About: {len(person.about)} chars" if person.about else "  About: not found")
            self._log(f"  Work history: {len(person.work_history)} positions")
            self._log(f"  Education: {len(person.education)} schools")
            self._log(f"  Groups: {len(person.groups)} groups")
            self._log(f"  Recent posts: {len(person.recent_posts)} posts")

            # Process work history for CRE firms
            self._process_work_history(person)

            # Normalize fields for consistent data
            self._clean_person_record(person)

            # Save person
            key = self._extract_profile_key(profile_url)
            self.discovered_contacts[key] = person
            self.processed_profiles.add(profile_url)

        except Exception as e:
            self._log(f"Error scraping profile: {e}")

        return person

    def _extract_work_history(self, person: LinkedInPerson):
        """Extract work experience"""
        try:
            # Scroll down to load experience section
            for scroll_pos in [500, 1000, 1500, 2000]:
                self.page.evaluate(f"window.scrollTo(0, {scroll_pos})")
                self._random_delay(0.5, 1)

            # Take screenshot after scrolling to see experience
            self.page.screenshot(path='profile_scrolled.png')
            self._log("Scrolled profile screenshot saved to profile_scrolled.png")

            # Find experience section
            experience_section = self.page.query_selector('section:has(#experience), section[id*="experience"]')

            if not experience_section:
                sections = self.page.query_selector_all('section')
                for section in sections:
                    header_text = section.inner_text()[:100] if section else ""
                    if 'Experience' in header_text:
                        experience_section = section
                        break

            if not experience_section:
                self._log("  Could not find experience section")
                return

            # Find company groups (each company entry has logo + positions)
            # Look for list items that contain company links
            company_entries = experience_section.query_selector_all('li.artdeco-list__item, li[class*="pvs-list__item"]')
            self._log(f"  Found {len(company_entries)} experience entries")

            current_company = None
            current_company_linkedin = None

            for entry in company_entries[:15]:
                try:
                    entry_text = entry.inner_text()

                    # Skip entries that look like durations only
                    if entry_text.strip().endswith('mos') and len(entry_text.strip()) < 20:
                        continue

                    # Check if this entry has a company link (new company group)
                    company_link = entry.query_selector('a[href*="/company/"]')
                    if company_link:
                        href = company_link.get_attribute('href')
                        if href:
                            current_company_linkedin = href.split('?')[0]
                            if not current_company_linkedin.startswith('http'):
                                current_company_linkedin = 'https://www.linkedin.com' + current_company_linkedin

                        # Get company name - look for the text in/near the link
                        company_name_elem = company_link.query_selector('span[aria-hidden="true"]')
                        if company_name_elem:
                            current_company = company_name_elem.inner_text().strip()
                        else:
                            # Try getting visible text from the link area
                            link_text = company_link.inner_text().strip()
                            if link_text and not link_text.endswith('mos') and 'yrs' not in link_text:
                                current_company = link_text.split('\n')[0].strip()

                        # Clean up company name - remove "logo" suffix and similar artifacts
                        if current_company:
                            current_company = current_company.replace(' logo', '').replace(' Logo', '').strip()

                    # Extract all text spans to find titles
                    all_spans = entry.query_selector_all('span[aria-hidden="true"]')

                    for span in all_spans:
                        text = span.inner_text().strip()
                        if not text:
                            continue

                        # Skip duration patterns
                        if 'yrs' in text or 'mos' in text or text.startswith('Apr') or text.startswith('Aug') or text.startswith('Jan') or ' - ' in text:
                            continue
                        # Skip company name (already captured)
                        if text == current_company:
                            continue
                        # Skip "Full-time", "Part-time" etc
                        if text.lower() in EMPLOYMENT_TYPES:
                            continue

                        # This is likely a job title
                        if len(text) > 3 and len(text) < 80:
                            # Check if it looks like a title (contains typical title words or is capitalized)
                            is_title = self._looks_like_title(text) or (text[0].isupper() and ' ' in text and not self._looks_like_company_name(text))

                            if is_title and current_company:
                                position = {
                                    'company': current_company,
                                    'title': text,
                                    'company_linkedin': current_company_linkedin
                                }

                                # Avoid duplicates
                                is_dup = any(
                                    p.get('company') == position['company'] and p.get('title') == position['title']
                                    for p in person.work_history
                                )
                                if not is_dup:
                                    person.work_history.append(position)
                                    self._log(f"  Position: {text} at {current_company}")

                                    # Set current company/title from first position
                                    if not person.current_title and position.get('title'):
                                        person.current_title = position['title']
                                    if not person.current_company or self._is_invalid_company_name(person.current_company):
                                        person.current_company = position['company']
                                        if position.get('company_linkedin'):
                                            person.company_linkedin_url = position['company_linkedin']

                except Exception as e:
                    continue

        except Exception as e:
            self._log(f"Error extracting work history: {e}")

    def _extract_education(self, person: LinkedInPerson):
        """Extract education history"""
        try:
            # Scroll to make sure education section is loaded
            self.page.evaluate("window.scrollTo(0, 1500)")
            self._random_delay(0.5, 1)

            # Find education section - try multiple approaches
            education_section = None

            # Method 1: Look for section with education id
            education_section = self.page.query_selector('section:has(#education)')

            # Method 2: Look for div with education id
            if not education_section:
                edu_header = self.page.query_selector('#education')
                if edu_header:
                    education_section = edu_header.evaluate('el => el.closest("section")')

            # Method 3: Search all sections for Education text
            if not education_section:
                sections = self.page.query_selector_all('section')
                for section in sections:
                    try:
                        # Look for Education header specifically
                        header = section.query_selector('h2 span, div[class*="title"] span')
                        if header:
                            header_text = header.inner_text().strip()
                            if header_text == 'Education':
                                education_section = section
                                break
                    except:
                        continue

            if not education_section:
                self._log("  Could not find education section")
                return

            self._log("  Found education section")

            # Find education entries - look for list items with school links
            edu_entries = education_section.query_selector_all('li')
            self._log(f"  Found {len(edu_entries)} education entries")

            for entry in edu_entries[:10]:
                try:
                    edu = {}
                    entry_text = entry.inner_text()

                    # Skip very short entries
                    if len(entry_text.strip()) < 5:
                        continue

                    # School name - try school link first
                    school_link = entry.query_selector('a[href*="/school/"]')
                    if school_link:
                        school_name_elem = school_link.query_selector('span[aria-hidden="true"]')
                        if school_name_elem:
                            edu['school'] = school_name_elem.inner_text().strip()

                    # If no school link, look for bold/prominent text
                    if not edu.get('school'):
                        # Try various selectors for school name
                        name_selectors = [
                            'span.t-bold span[aria-hidden="true"]',
                            'div.t-bold span[aria-hidden="true"]',
                            'span[aria-hidden="true"]'
                        ]
                        for sel in name_selectors:
                            elem = entry.query_selector(sel)
                            if elem:
                                text = elem.inner_text().strip()
                                # Check if it looks like a school name
                                if text and len(text) > 3 and ('university' in text.lower() or 'college' in text.lower() or 'school' in text.lower() or text[0].isupper()):
                                    edu['school'] = text
                                    break

                    # Get all spans to find degree and years
                    spans = entry.query_selector_all('span[aria-hidden="true"]')
                    for span in spans:
                        text = span.inner_text().strip()
                        if not text or text == edu.get('school'):
                            continue

                        # Look for degree patterns
                        degree_keywords = ['degree', 'bachelor', 'master', 'mba', 'phd', 'bs', 'ba', 'ms', 'ma', 'jd', 'md', 'political science', 'business', 'engineering', 'science', 'arts']
                        if any(kw in text.lower() for kw in degree_keywords):
                            edu['degree'] = text
                        # Look for year patterns
                        elif ' - ' in text and any(c.isdigit() for c in text):
                            edu['years'] = text
                        elif text.isdigit() and len(text) == 4:  # Just a year
                            if not edu.get('years'):
                                edu['years'] = text

                    if edu.get('school'):
                        # Avoid duplicates
                        is_dup = any(e.get('school') == edu['school'] for e in person.education)
                        if not is_dup:
                            person.education.append(edu)
                            self._log(f"  Education: {edu.get('school')} - {edu.get('degree', 'N/A')}")

                except Exception as e:
                    continue

        except Exception as e:
            self._log(f"Error extracting education: {e}")

    def _extract_groups(self, person: LinkedInPerson):
        """Extract groups from Interests section"""
        try:
            # Need to scroll down more to find Interests section
            self.page.evaluate("window.scrollTo(0, 3000)")
            self._random_delay(1, 2)

            # Find interests section
            interests_section = self.page.query_selector('section:has(#interests), section[id*="interests"]')

            if not interests_section:
                sections = self.page.query_selector_all('section')
                for section in sections:
                    header_text = section.inner_text()[:100] if section else ""
                    if 'Interests' in header_text:
                        interests_section = section
                        break

            if not interests_section:
                return

            # Look for Groups tab/button and click it if present
            groups_tab = interests_section.query_selector('button:has-text("Groups"), a:has-text("Groups")')
            if groups_tab:
                try:
                    groups_tab.click()
                    self._random_delay(1, 2)
                except:
                    pass

            # Find group entries - look specifically for group links
            group_entries = interests_section.query_selector_all('a[href*="/groups/"], li[class*="pvs-list__item"]')

            for entry in group_entries[:20]:
                try:
                    # Get group name
                    name_elem = entry.query_selector('span[aria-hidden="true"]')
                    if name_elem:
                        group_name = name_elem.inner_text().strip()

                        # Skip if it looks like a school (filter out education items that appear in interests)
                        school_keywords = ['university', 'college', 'school', 'institute', 'academy']
                        is_school = any(kw in group_name.lower() for kw in school_keywords)

                        if group_name and group_name not in person.groups and not is_school and self._is_valid_group_name(group_name, skip_names=NON_GROUP_NAMES):
                            person.groups.append(group_name)
                            self._log(f"  Group: {group_name}")
                except:
                    continue

        except Exception as e:
            self._log(f"Error extracting groups: {e}")

    def _extract_recent_posts(self, person: LinkedInPerson, limit: int = 2):
        """Extract recent posts from Activity/Featured section"""
        try:
            # Scroll back up to find Activity/Featured section
            self.page.evaluate("window.scrollTo(0, 400)")
            self._random_delay(1, 2)

            # Try Featured section first (usually has curated posts)
            featured_section = self.page.query_selector('section:has(#featured), section[id*="featured"]')

            if not featured_section:
                sections = self.page.query_selector_all('section')
                for section in sections:
                    header_text = section.inner_text()[:100] if section else ""
                    if 'Featured' in header_text or 'Activity' in header_text:
                        featured_section = section
                        break

            if featured_section:
                # Find post cards in Featured section
                post_cards = featured_section.query_selector_all('li, div[class*="feed"], div[class*="update"]')

                for card in post_cards[:limit]:
                    try:
                        post = {}

                        # Get post text/content
                        text_elem = card.query_selector('span[aria-hidden="true"], div.feed-shared-text, span.break-words')
                        if text_elem:
                            post_text = text_elem.inner_text().strip()
                            if post_text and len(post_text) > 10:
                                post['content'] = post_text[:500]  # Limit length

                        # Get post type (Post, Article, etc.)
                        type_elem = card.query_selector('span.t-black--light, span.t-normal')
                        if type_elem:
                            post_type = type_elem.inner_text().strip()
                            if post_type and len(post_type) < 30:
                                post['type'] = post_type

                        # Get link if it's an article or external content
                        link_elem = card.query_selector('a[href*="http"]')
                        if link_elem:
                            href = link_elem.get_attribute('href')
                            if href and 'linkedin.com' not in href:
                                post['link'] = href

                        if post.get('content'):
                            person.recent_posts.append(post)
                            content_preview = post['content'][:60] + '...' if len(post['content']) > 60 else post['content']
                            self._log(f"  Post: {content_preview}")

                    except Exception as e:
                        continue

            # If no Featured posts, try Activity section
            if not person.recent_posts:
                # Go to Activity page
                activity_url = person.linkedin_url.rstrip('/') + '/recent-activity/all/'
                self.page.goto(activity_url)
                self._random_delay(2, 3)

                # Find activity posts
                activity_items = self.page.query_selector_all('div.feed-shared-update-v2, div[data-urn*="activity"]')

                for item in activity_items[:limit]:
                    try:
                        post = {}

                        text_elem = item.query_selector('span.break-words, div.feed-shared-text span')
                        if text_elem:
                            post_text = text_elem.inner_text().strip()
                            if post_text and len(post_text) > 10:
                                post['content'] = post_text[:500]

                        if post.get('content'):
                            person.recent_posts.append(post)

                    except:
                        continue

                # Navigate back to profile
                self.page.goto(person.linkedin_url)
                self._random_delay(1, 2)

        except Exception as e:
            self._log(f"Error extracting posts: {e}")

    def _is_cre_company(self, company_name: str) -> bool:
        """Check if company is CRE related"""
        name_lower = company_name.lower()
        return any(kw in name_lower for kw in CRE_KEYWORDS)

    def _process_work_history(self, person: LinkedInPerson):
        """Process work history to find CRE firms"""
        for pos in person.work_history:
            company = pos.get('company', '')
            company_url = pos.get('company_linkedin', '')

            if not company:
                continue

            if self._is_cre_company(company):
                key = company.lower().strip()

                if key not in self.discovered_firms:
                    firm = LinkedInCompany(
                        name=company,
                        linkedin_url=company_url,
                        discovered_from=person.name,
                        is_cre_related=True
                    )
                    self.discovered_firms[key] = firm
                    self._log(f"  -> Discovered CRE firm: {company}")

    # ==================== COMPANY SCRAPING ====================

    def _extract_person_from_link(self, link, company_name: str, discovered_from: str) -> Optional[LinkedInPerson]:
        """Extract person info from a profile link element"""
        try:
            href = link.get_attribute('href')
            if not href or '/in/' not in href:
                return None

            # Normalize URL
            link_url = self._normalize_url(href)

            # Skip overlay/details pages
            if self._should_skip_url(link_url):
                return None

            # Get name from link
            name = ""
            name_span = link.query_selector('span[aria-hidden="true"], span')
            if name_span:
                name = name_span.inner_text().strip()
            if not name:
                name = link.inner_text().strip()

            # Clean name - take first line if multiline
            if name:
                name = name.split('\n')[0].strip()

            # Validate name
            if not name or len(name) < 3 or len(name) > 60:
                return None
            if self._should_skip_name(name):
                return None

            # Try to find title from sibling elements
            title = ""
            try:
                sibling_text = self.page.evaluate(
                    '(el) => { let p = el.parentElement; let next = p?.nextElementSibling; return next?.innerText || ""; }',
                    link
                )
                if sibling_text and len(sibling_text) < 100:
                    title = sibling_text.split('\n')[0].strip()
                    # Don't use button text as title
                    if title.lower() in ['connect', 'follow', 'message', 'pending', 'following']:
                        title = ""
            except:
                pass

            return LinkedInPerson(
                name=name,
                linkedin_url=link_url,
                current_company=company_name,
                current_title=title,
                discovered_from=discovered_from
            )
        except:
            return None

    def scrape_company_employees_from_profile(self, profile_url: str, company_name: str = "", limit: int = 20) -> List[LinkedInPerson]:
        """Find employees from 'People you may know from X's company' section on profile page"""
        if not self.logged_in:
            return []

        self._log(f"Looking for company employees from profile sidebar...")
        employees = []

        try:
            # Navigate to the profile page
            self.page.goto(profile_url)
            self._random_delay(3, 5)

            # Scroll to top to see sidebar
            self.page.evaluate("window.scrollTo(0, 0)")
            self._random_delay(1, 2)

            # Try clicking "Show more" to expand the list
            for selector in ['button:has-text("Show more")', 'a:has-text("Show more")']:
                try:
                    btn = self.page.query_selector(selector)
                    if btn:
                        self._log("Found 'Show more' button, clicking...")
                        btn.click()
                        self._random_delay(3, 5)
                        break
                except:
                    continue

            # Find all profile links on page
            all_links = self.page.query_selector_all('a[href*="/in/"]')
            self._log(f"Found {len(all_links)} profile links")

            seen_urls = {profile_url}  # Don't add the source person
            discovered_from = f"People you may know: {company_name}"

            for link in all_links:
                person = self._extract_person_from_link(link, company_name, discovered_from)
                if not person:
                    continue

                # Skip duplicates
                if person.linkedin_url in seen_urls or person.linkedin_url in self.processed_profiles:
                    continue
                seen_urls.add(person.linkedin_url)

                employees.append(person)

                # Save to discovered contacts
                key = self._extract_profile_key(person.linkedin_url)
                if key and key not in self.discovered_contacts:
                    self.discovered_contacts[key] = person
                    title_display = person.current_title[:40] if person.current_title else 'No title'
                    self._log(f"  Found: {person.name} - {title_display}")

            self._log(f"Found {len(employees)} employees from sidebar")

        except Exception as e:
            self._log(f"Error scraping company employees: {e}")

        return employees

    # ==================== MAIN ENRICHMENT WORKFLOW ====================

    def enrich_from_person(self, name: str, company: str) -> Dict:
        """
        Full enrichment workflow starting from a person:
        1. Search and scrape person
        2. Extract work history -> discover CRE firms
        3. Go to current company -> find other employees
        """
        results = {
            'person': None,
            'new_contacts': [],
            'new_firms': []
        }

        # Step 1: Find and scrape the person
        profile_urls = self.search_person(name, company)
        if not profile_urls:
            self._log(f"Could not find: {name} at {company}")
            return results

        self._random_delay(2, 4)
        person = self.scrape_person_profile(profile_urls[0], f"Initial search: {name}")
        if not person:
            return results

        results['person'] = person

        # Step 2: Work history already processed in scrape_person_profile
        initial_firms = len(self.discovered_firms)

        # Step 3: Find other employees at their current company
        # Use the "People you may know from X's company" section on the profile
        self._random_delay(3, 5)
        new_employees = self.scrape_company_employees_from_profile(
            person.linkedin_url,
            person.current_company,
            limit=15
        )
        results['new_contacts'] = new_employees

        # Count new firms
        results['new_firms'] = list(self.discovered_firms.values())[initial_firms:]

        self._save_data()
        return results

    def enrich_company(self, company_name: str, company_linkedin_url: str = "") -> Dict:
        """
        Enrich by company:
        1. Search for a person at the company
        2. Scrape their profile to find colleagues
        3. Optionally deep-scrape some employees for work history
        """
        results = {
            'company': company_name,
            'employees': [],
            'new_firms': []
        }

        # Search for someone at the company
        self._log(f"Searching for employees at: {company_name}")
        profile_urls = self.search_person("", company_name)

        if not profile_urls:
            self._log(f"Could not find anyone at {company_name}")
            return results

        # Scrape the first person's profile
        initial_firms = len(self.discovered_firms)
        first_person = self.scrape_person_profile(profile_urls[0], f"Company search: {company_name}")

        if first_person:
            # Find colleagues from their profile sidebar
            self._random_delay(2, 4)
            employees = self.scrape_company_employees_from_profile(
                first_person.linkedin_url,
                company_name,
                limit=25
            )
            results['employees'] = employees

            # Deep-scrape first 5 employees for work history
            for emp in employees[:5]:
                if emp.linkedin_url and emp.linkedin_url not in self.processed_profiles:
                    self._random_delay(4, 7)
                    self.scrape_person_profile(emp.linkedin_url, f"Employee of {company_name}")

        results['new_firms'] = list(self.discovered_firms.values())[initial_firms:]
        self._save_data()
        return results

    def is_already_enriched(self, linkedin_url: str) -> bool:
        """Check if a contact has already been fully enriched"""
        key = self._extract_profile_key(linkedin_url)
        if not key:
            return False
        if key in self.discovered_contacts:
            contact = self.discovered_contacts[key]
            # Consider enriched if has scraped_at timestamp and headline/about
            if contact.scraped_at and (contact.headline or contact.about):
                return True
        return False

    def run_enrichment_batch(self, contacts: List[Dict], limit: int = 10):
        """Run enrichment on a batch of contacts"""
        self._log(f"Starting batch enrichment of {min(limit, len(contacts))} contacts")

        processed = 0
        skipped = 0
        for contact in contacts[:limit]:
            name = contact.get('name', '')
            company = contact.get('company', '')
            linkedin_url = contact.get('linkedin_url', '')

            # Skip if already enriched
            if linkedin_url and self.is_already_enriched(linkedin_url):
                self._log(f"Skipping already enriched: {name}")
                skipped += 1
                continue

            # Validate it looks like a real person name
            if not self._is_valid_person_name(name):
                continue

            self._log(f"\n{'='*50}")
            self._log(f"[{processed+1}/{limit}] Enriching: {name} at {company}")

            try:
                results = self.enrich_from_person(name, company)

                if results['person']:
                    self._log(f"  Found: {results['person'].name}")
                    self._log(f"  Work history: {len(results['person'].work_history)} positions")
                    self._log(f"  New employees found: {len(results['new_contacts'])}")
                    self._log(f"  New firms discovered: {len(results['new_firms'])}")

                processed += 1
                self._random_delay(5, 10)

            except Exception as e:
                self._log(f"Error enriching {name}: {e}")

        self._save_data()
        self._log(f"\n{'='*50}")
        self._log(f"Batch complete: {processed} processed, {skipped} skipped (already enriched)")
        self._log(f"Total contacts: {len(self.discovered_contacts)}")
        self._log(f"Total firms: {len(self.discovered_firms)}")

    def enrich_one_per_company(self, companies: List[Dict], limit: int = None) -> Dict:
        """
        Enrich the first (or next) person from each company.

        Args:
            companies: List of dicts with 'name' key (company names)
            limit: Max number of companies to process (None = all)

        Returns:
            Dict with stats about what was processed
        """
        if not self.logged_in:
            self._log("Not logged in!")
            return {'processed': 0, 'skipped': 0, 'errors': 0}

        stats = {'processed': 0, 'skipped': 0, 'errors': 0, 'companies_covered': []}

        # Get companies we already have contacts for
        covered_companies = set()
        for contact in self.discovered_contacts.values():
            if contact.current_company:
                covered_companies.add(contact.current_company.lower())

        self._log(f"Starting one-per-company enrichment")
        self._log(f"Total companies: {len(companies)}")
        self._log(f"Already have contacts at: {len(covered_companies)} companies")

        companies_to_process = companies[:limit] if limit else companies

        for i, company_info in enumerate(companies_to_process):
            company_name = company_info.get('name', '')
            if not company_name:
                continue

            # Check if we already have someone from this company
            company_key = company_name.lower()
            # Also check partial matches (e.g., "Newmark" matches "Newmark Columbus")
            already_have = False
            for covered in covered_companies:
                if company_key in covered or covered in company_key:
                    already_have = True
                    break
            # Also check exact company names in contacts
            for contact in self.discovered_contacts.values():
                if contact.current_company and company_key in contact.current_company.lower():
                    already_have = True
                    break

            if already_have:
                self._log(f"[{i+1}/{len(companies_to_process)}] Skipping {company_name} - already have contact")
                stats['skipped'] += 1
                continue

            self._log(f"\n{'='*50}")
            self._log(f"[{i+1}/{len(companies_to_process)}] Searching for someone at: {company_name}")

            try:
                # Search for anyone at this company
                profile_urls = self.search_person("", company_name)

                if not profile_urls:
                    self._log(f"  No profiles found for {company_name}")
                    stats['errors'] += 1
                    continue

                # Scrape the first person found
                person = self.scrape_person_profile(profile_urls[0], f"Company search: {company_name}")

                if person:
                    self._log(f"  Found: {person.name}")
                    self._log(f"  Title: {person.current_title}")
                    self._log(f"  Work history: {len(person.work_history)} positions")

                    # Also find colleagues
                    self._random_delay(2, 4)
                    colleagues = self.scrape_company_employees_from_profile(
                        person.linkedin_url,
                        company_name,
                        limit=10
                    )
                    self._log(f"  Colleagues found: {len(colleagues)}")

                    stats['processed'] += 1
                    stats['companies_covered'].append(company_name)
                    covered_companies.add(company_name.lower())
                else:
                    stats['errors'] += 1

                self._save_data()
                self._random_delay(5, 10)

            except Exception as e:
                self._log(f"  Error: {e}")
                stats['errors'] += 1

        self._save_data()
        self._log(f"\n{'='*50}")
        self._log(f"ONE-PER-COMPANY COMPLETE")
        self._log(f"  Processed: {stats['processed']}")
        self._log(f"  Skipped (already had): {stats['skipped']}")
        self._log(f"  Errors: {stats['errors']}")
        self._log(f"  Total contacts: {len(self.discovered_contacts)}")

        return stats

    # ==================== REPORTING ====================

    def print_summary(self):
        """Print summary of discovered data"""
        print("\n" + "="*60)
        print("LINKEDIN DISCOVERY SUMMARY")
        print("="*60)

        print(f"\nDiscovered Contacts: {len(self.discovered_contacts)}")
        for key, person in list(self.discovered_contacts.items())[:10]:
            print(f"  - {person.name}: {person.current_title[:40]} at {person.current_company}")
        if len(self.discovered_contacts) > 10:
            print(f"  ... and {len(self.discovered_contacts) - 10} more")

        print(f"\nDiscovered CRE Firms: {len(self.discovered_firms)}")
        for key, firm in list(self.discovered_firms.items())[:10]:
            print(f"  - {firm.name} (from {firm.discovered_from})")
        if len(self.discovered_firms) > 10:
            print(f"  ... and {len(self.discovered_firms) - 10} more")

    def get_new_firms_for_scraping(self) -> List[Dict]:
        """Get list of discovered firms to add to website scraping"""
        new_firms = []
        for key, firm in self.discovered_firms.items():
            if firm.is_cre_related:
                new_firms.append({
                    'name': firm.name,
                    'website': firm.website,
                    'linkedin_url': firm.linkedin_url,
                    'discovered_from': firm.discovered_from
                })
        return new_firms


# ==================== CLI ====================

if __name__ == "__main__":
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description='LinkedIn CRE Intelligence Scraper')
    parser.add_argument('--login', action='store_true', help='Login to LinkedIn')
    parser.add_argument('--search', type=str, help='Search and enrich a person')
    parser.add_argument('--company', type=str, default='', help='Company filter for search')
    parser.add_argument('--enrich-company', type=str, help='Enrich by company name')
    parser.add_argument('--batch', action='store_true', help='Batch enrich from scraped_firms.json')
    parser.add_argument('--one-per-company', action='store_true', help='Enrich one person from each TARGET_FIRMS company')
    parser.add_argument('--limit', type=int, default=10, help='Limit for batch processing')
    parser.add_argument('--summary', action='store_true', help='Show discovery summary')
    parser.add_argument('--new-firms', action='store_true', help='Show new firms for scraping')
    args = parser.parse_args()

    scraper = LinkedInScraper(headless=False)

    try:
        if args.login:
            email = input("LinkedIn Email: ")
            password = getpass.getpass("LinkedIn Password: ")
            scraper.login(email, password)

        elif args.search:
            if scraper.load_cookies():
                results = scraper.enrich_from_person(args.search, args.company)
                scraper.print_summary()
            else:
                print("Please login first with --login")

        elif args.enrich_company:
            if scraper.load_cookies():
                results = scraper.enrich_company(args.enrich_company)
                scraper.print_summary()
            else:
                print("Please login first with --login")

        elif args.batch:
            if scraper.load_cookies():
                # Load contacts from scraped firms
                with open('scraped_firms.json', 'r', encoding='utf-8') as f:
                    firms = json.load(f)

                contacts = []
                for firm in firms:
                    for person in firm.get('leadership', []):
                        person['company'] = firm['company_name']
                        contacts.append(person)

                print(f"Found {len(contacts)} contacts in scraped_firms.json")
                scraper.run_enrichment_batch(contacts, args.limit)
                scraper.print_summary()
            else:
                print("Please login first with --login")

        elif args.one_per_company:
            if scraper.load_cookies():
                # Import TARGET_FIRMS from website scraper
                from cre_website_scraper import TARGET_FIRMS
                print(f"Loaded {len(TARGET_FIRMS)} companies from TARGET_FIRMS")
                scraper.enrich_one_per_company(TARGET_FIRMS, limit=args.limit)
                scraper.print_summary()
            else:
                print("Please login first with --login")

        elif args.summary:
            scraper.print_summary()

        elif args.new_firms:
            firms = scraper.get_new_firms_for_scraping()
            print(f"\n=== New CRE Firms for Scraping ({len(firms)}) ===")
            for f in firms:
                print(f"  {f['name']}")
                if f['linkedin_url']:
                    print(f"    LinkedIn: {f['linkedin_url']}")
                print(f"    Found via: {f['discovered_from']}")

        else:
            parser.print_help()

    finally:
        scraper.quit()
