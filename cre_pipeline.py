"""
CRE Intelligence Pipeline
Combines website scraping and LinkedIn enrichment

WORKFLOW:
1. Scrape websites for firm info and leadership
2. Enrich contacts via LinkedIn
3. Discover new firms from work history
4. Add discovered firms to scrape queue
5. Repeat

USAGE:
    python cre_pipeline.py --scrape           # Scrape websites only
    python cre_pipeline.py --enrich           # Enrich with LinkedIn
    python cre_pipeline.py --discover         # Show discovered firms
    python cre_pipeline.py --add-discovered   # Add discovered firms to TARGET_FIRMS
    python cre_pipeline.py --full             # Full pipeline
"""

import json
import os
import argparse
from datetime import datetime

# Import our scrapers
from cre_website_scraper import (
    TARGET_FIRMS, CREWebsiteScraper, FirmData, Person,
    load_url_cache, save_url_cache, load_previous_results,
    export_to_csv, export_to_json, RESULTS_FILE
)
from linkedin_scraper import LinkedInScraper, DISCOVERED_FIRMS_FILE


def load_discovered_firms():
    """Load discovered firms from LinkedIn scraping"""
    if os.path.exists(DISCOVERED_FIRMS_FILE):
        with open(DISCOVERED_FIRMS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def get_existing_websites():
    """Get set of websites already in TARGET_FIRMS"""
    websites = set()
    for firm in TARGET_FIRMS:
        website = firm.get('website', '').lower()
        # Normalize
        website = website.replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')
        websites.add(website)
    return websites


def suggest_new_firms():
    """Suggest new firms to add based on LinkedIn discoveries"""
    discovered = load_discovered_firms()
    existing = get_existing_websites()

    suggestions = []
    for key, firm in discovered.items():
        if not firm.get('is_cre_related'):
            continue

        name = firm.get('name', '')
        linkedin_url = firm.get('linkedin_url', '')

        # Check if we already have this firm
        name_lower = name.lower()
        already_have = False
        for existing_name in [f['name'].lower() for f in TARGET_FIRMS]:
            if name_lower in existing_name or existing_name in name_lower:
                already_have = True
                break

        if not already_have:
            suggestions.append({
                'name': name,
                'linkedin_url': linkedin_url,
                'discovered_from': firm.get('discovered_from', ''),
                'website': ''  # Need to find website
            })

    return suggestions


def scrape_company_linkedin_for_website(scraper: LinkedInScraper, company_linkedin_url: str) -> str:
    """Scrape LinkedIn company page to find website"""
    if not company_linkedin_url or not scraper.logged_in or not scraper.page:
        return ""

    try:
        scraper.page.goto(company_linkedin_url)
        scraper._random_delay(3, 5)

        # Look for website link on company page
        website_selectors = [
            'a[href*="http"][data-control-name="top_card_website"]',
            'a[data-test-id="about-us-link"]',
            'dd a[href*="http"]:not([href*="linkedin"])'
        ]

        for selector in website_selectors:
            try:
                website_elem = scraper.page.query_selector(selector)
                if website_elem:
                    href = website_elem.get_attribute('href')
                    if href and 'linkedin' not in href:
                        return href
            except:
                continue

        # Try about page
        about_url = company_linkedin_url.rstrip('/') + '/about/'
        scraper.page.goto(about_url)
        scraper._random_delay(2, 4)

        # Look for website link on about page
        try:
            website_elem = scraper.page.query_selector('a[href*="http"]:not([href*="linkedin"])')
            if website_elem:
                href = website_elem.get_attribute('href')
                if href and 'linkedin' not in href:
                    return href
        except:
            pass

    except Exception as e:
        print(f"Error getting company website: {e}")

    return ""


def run_website_scraper():
    """Run the website scraper"""
    print("\n" + "="*60)
    print("PHASE 1: WEBSITE SCRAPING")
    print("="*60)

    url_cache = load_url_cache()
    previous_results = load_previous_results()

    # Find new firms to scrape
    firms_to_scrape = []
    for firm in TARGET_FIRMS:
        website = firm['website']
        if not website.startswith('http'):
            website = 'https://' + website
        website = website.rstrip('/')
        if website not in previous_results:
            firms_to_scrape.append(firm)

    print(f"Target firms: {len(TARGET_FIRMS)}")
    print(f"Previously scraped: {len(previous_results)}")
    print(f"New to scrape: {len(firms_to_scrape)}")

    if not firms_to_scrape:
        print("All firms already scraped.")
        return

    scraper = CREWebsiteScraper(delay_seconds=2, url_cache=url_cache)
    new_results = scraper.scrape_multiple(firms_to_scrape)

    save_url_cache(scraper.url_cache)

    # Merge results
    from dataclasses import asdict
    all_results_dict = previous_results.copy()
    for firm in new_results:
        all_results_dict[firm.website] = asdict(firm)

    # Save merged results
    final_results = []
    for data in all_results_dict.values():
        if isinstance(data, dict):
            leadership = [Person(**p) if isinstance(p, dict) else p for p in data.get('leadership', [])]
            data['leadership'] = leadership
            final_results.append(FirmData(**data))
        else:
            final_results.append(data)

    export_to_csv(final_results, 'scraped_firms.csv')
    export_to_json(final_results, RESULTS_FILE)

    print(f"\nScraped {len(new_results)} new firms")
    print(f"Total in database: {len(final_results)}")


def run_linkedin_enrichment(limit: int = 10):
    """Run LinkedIn enrichment on scraped contacts"""
    print("\n" + "="*60)
    print("PHASE 2: LINKEDIN ENRICHMENT")
    print("="*60)

    # Load contacts from scraped firms
    if not os.path.exists(RESULTS_FILE):
        print("No scraped firms found. Run website scraper first.")
        return

    with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
        firms = json.load(f)

    # Collect contacts without LinkedIn data
    contacts_to_enrich = []
    for firm in firms:
        for person in firm.get('leadership', []):
            # Skip if already has LinkedIn
            if person.get('linkedin'):
                continue
            # Skip invalid names
            name = person.get('name', '')
            if len(name) < 3 or any(x in name.lower() for x in ['click', 'watch', 'discover', 'http']):
                continue

            contacts_to_enrich.append({
                'name': name,
                'title': person.get('title', ''),
                'company': firm['company_name']
            })

    print(f"Contacts needing enrichment: {len(contacts_to_enrich)}")

    if not contacts_to_enrich:
        print("All contacts already enriched!")
        return

    # Limit number to process
    contacts_to_process = contacts_to_enrich[:limit]
    print(f"Processing first {len(contacts_to_process)} contacts")

    # Start LinkedIn scraper
    scraper = LinkedInScraper(headless=False)

    try:
        if not scraper.load_cookies():
            print("\nNeed to login to LinkedIn first.")
            import getpass
            email = input("LinkedIn Email: ")
            password = getpass.getpass("LinkedIn Password: ")
            if not scraper.login(email, password):
                print("Login failed!")
                return

        # Enrich contacts
        scraper.run_enrichment_batch(contacts_to_process, limit=len(contacts_to_process))

        # Show discovered firms
        discovered = list(scraper.discovered_firms.values())
        if discovered:
            print(f"\n=== Discovered {len(discovered)} CRE firms from work history ===")
            for firm in discovered:
                print(f"  {firm.name} (from {firm.discovered_from})")

    finally:
        scraper.quit()


def show_discovered_firms():
    """Display discovered firms"""
    print("\n" + "="*60)
    print("DISCOVERED CRE FIRMS")
    print("="*60)

    suggestions = suggest_new_firms()

    if not suggestions:
        print("No new firms discovered yet.")
        print("Run LinkedIn enrichment to discover firms from work history.")
        return

    print(f"Found {len(suggestions)} potential new firms:\n")
    for i, firm in enumerate(suggestions, 1):
        print(f"{i}. {firm['name']}")
        if firm['linkedin_url']:
            print(f"   LinkedIn: {firm['linkedin_url']}")
        print(f"   Discovered from: {firm['discovered_from']}")
        print()


def add_discovered_firms_to_target():
    """Interactively add discovered firms to TARGET_FIRMS"""
    print("\n" + "="*60)
    print("ADD DISCOVERED FIRMS")
    print("="*60)

    suggestions = suggest_new_firms()

    if not suggestions:
        print("No new firms to add.")
        return

    print(f"Found {len(suggestions)} potential new firms.\n")

    # Try to get websites via LinkedIn
    scraper = LinkedInScraper(headless=False)
    added_firms = []

    try:
        if scraper.load_cookies():
            for firm in suggestions:
                print(f"\n{firm['name']}")

                # Try to get website from LinkedIn
                website = ""
                if firm.get('linkedin_url'):
                    print(f"  Getting website from LinkedIn...")
                    website = scrape_company_linkedin_for_website(scraper, firm['linkedin_url'])
                    if website:
                        print(f"  Found: {website}")

                if not website:
                    website = input(f"  Enter website (or skip): ").strip()

                if website:
                    added_firms.append({
                        'name': firm['name'],
                        'website': website
                    })
                    print(f"  Added: {firm['name']} -> {website}")

                scraper._random_delay(2, 4)
        else:
            print("Not logged into LinkedIn. Enter websites manually.\n")
            for firm in suggestions:
                print(f"\n{firm['name']}")
                website = input(f"  Enter website (or skip): ").strip()
                if website:
                    added_firms.append({
                        'name': firm['name'],
                        'website': website
                    })

    finally:
        scraper.quit()

    if added_firms:
        # Save to a file for manual addition to TARGET_FIRMS
        output_file = 'new_target_firms.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(added_firms, f, indent=2)

        print(f"\n=== Added {len(added_firms)} firms ===")
        print(f"Saved to {output_file}")
        print("\nAdd these to TARGET_FIRMS in cre_website_scraper.py:")
        for firm in added_firms:
            print(f'    {{"name": "{firm["name"]}", "website": "{firm["website"]}"}},')


def run_full_pipeline():
    """Run the complete pipeline"""
    print("="*60)
    print("CRE INTELLIGENCE FULL PIPELINE")
    print("="*60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Phase 1: Website scraping
    run_website_scraper()

    # Phase 2: LinkedIn enrichment
    print("\nProceed to LinkedIn enrichment? (y/n): ", end="")
    if input().lower() == 'y':
        limit = input("How many contacts to enrich? (default 10): ").strip()
        limit = int(limit) if limit.isdigit() else 10
        run_linkedin_enrichment(limit)

        # Phase 3: Show discovered firms
        show_discovered_firms()

        # Phase 4: Add discovered firms
        print("\nAdd discovered firms to target list? (y/n): ", end="")
        if input().lower() == 'y':
            add_discovered_firms_to_target()

    print("\n" + "="*60)
    print("PIPELINE COMPLETE")
    print("="*60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='CRE Intelligence Pipeline')
    parser.add_argument('--scrape', action='store_true', help='Run website scraper only')
    parser.add_argument('--enrich', action='store_true', help='Run LinkedIn enrichment')
    parser.add_argument('--enrich-limit', type=int, default=10, help='Max contacts to enrich')
    parser.add_argument('--discover', action='store_true', help='Show discovered firms')
    parser.add_argument('--add-discovered', action='store_true', help='Add discovered firms to target')
    parser.add_argument('--full', action='store_true', help='Run full pipeline')
    args = parser.parse_args()

    if args.scrape:
        run_website_scraper()
    elif args.enrich:
        run_linkedin_enrichment(args.enrich_limit)
    elif args.discover:
        show_discovered_firms()
    elif args.add_discovered:
        add_discovered_firms_to_target()
    elif args.full:
        run_full_pipeline()
    else:
        parser.print_help()
