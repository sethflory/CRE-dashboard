# CRE Career Intelligence Dashboard

A toolkit for job seekers breaking into the Commercial Real Estate (CRE) industry. Scrapes firm websites and LinkedIn to build a database of target companies, contacts, and networking opportunities.

## Live Dashboard

View the interactive dashboard: [CRE Career Intelligence Dashboard](./cre_dashboard.html)

**Features:**
- Interactive map of target markets with distance rings from Columbus
- CRE transaction volume heatmap overlay (toggle view)
- Services matrix showing what each firm offers
- University and professional group connections for networking
- Contact cards with LinkedIn links

## Components

### 1. Website Scraper (`cre_website_scraper.py`)
Extracts firm data from company websites:
- Services offered (Brokerage, Capital Markets, Property Management, etc.)
- Asset specialties (Office, Industrial, Retail, Multifamily, etc.)
- Contact information and leadership names

### 2. LinkedIn Scraper (`linkedin_scraper.py`)
Enriches contact data from LinkedIn profiles:
- Current title and company
- Education history (universities)
- Professional groups and associations
- Work history and career progression
- Colleague discovery

### 3. Pipeline (`cre_pipeline.py`)
Orchestrates the full workflow:
- Scrape websites for all target firms
- Enrich contacts via LinkedIn
- Export to Excel/CSV

### 4. Dashboard (`cre_dashboard.html`)
Static HTML dashboard for GitHub Pages:
- No backend required
- Loads data from JS files
- Interactive filtering and visualization

## Setup

```bash
# Install dependencies
pip install -r scraper_requirements.txt
pip install playwright
python -m playwright install chromium
```

## Usage

### Scrape Firm Websites
```bash
python cre_website_scraper.py
```
Outputs: `scraped_firms.json`, `scraped_firms.csv`, `scraped_firms_leadership.csv`

### Enrich Contacts via LinkedIn

**First time - login and save cookies:**
```bash
python linkedin_scraper.py --login
```
This opens a browser for you to log in manually. Cookies are saved for future runs.

**Enrich one person per company:**
```bash
python linkedin_scraper.py --one-per-company --limit 10
```

**Enrich specific person:**
```bash
python linkedin_scraper.py --search "John Smith" --company "JLL"
```

### View Dashboard
Open `cre_dashboard.html` in a browser, or deploy to GitHub Pages.

## Data Files

| File | Description | Git |
|------|-------------|-----|
| `scraped_firms.json` | Firm data from websites | ✅ |
| `discovered_contacts.json` | All contacts found | ❌ |
| `linkedin_cookies.json` | Session cookies | ❌ |
| `data_contacts.js` | Dashboard data (auto-generated) | ❌ |
| `data_firms.js` | Dashboard data (auto-generated) | ❌ |
| `data_cre_markets.js` | CRE transaction volume data | ✅ |

## Target Markets

The dashboard covers 8 markets with 44 target firms:

| Market | Firms | Example Companies |
|--------|-------|-------------------|
| Columbus | 17 | JLL, Cushman & Wakefield, CBRE, NAI Ohio Equities |
| Charlotte | 9 | Trinity Partners, Foundry Commercial, Childress Klein |
| Chicago | 6 | NAI Hiffman, SVN Chicago, Interra Realty |
| Pittsburgh | 5 | Newmark, Hanna Commercial, PCRE |
| Cincinnati | 4 | NAI Bergman, APEX Commercial |
| Indianapolis | 3 | Bradley Company, JLL, Cushman & Wakefield |
| Cleveland | 2 | CRESCO, Newmark |
| Savannah | 2 | NAI Mopper Benton, Avison Young |

## CRE Market Data

The heatmap visualization uses 2023 transaction volume data:

| Rank | Market | Volume |
|------|--------|--------|
| 1 | Dallas | $18.8B |
| 2 | Los Angeles | $17.1B |
| 3 | New York | $12.1B |
| 4 | Chicago | $11.9B |
| 5 | Atlanta | $11.5B |
| 28 | Columbus | $2.1B |

Source: [Terrydale Capital](https://terrydalecapital.com/learn/top-5-cre-markets), [Altus Group](https://www.altusgroup.com/insights/us-cre-transactions-q4-2024/)

## Testing

```bash
pytest test_*.py -v
```

123 tests covering all components.

## Known Issues

1. **Company field parsing** - LinkedIn scraper sometimes captures titles instead of company names
2. **Celebrity contacts** - Some discovered "colleagues" are influencers, not actual employees
3. **Location validation** - Need to filter contacts outside target geography

## Legal Note

- Respect website terms of service and robots.txt
- LinkedIn scraping requires your own authenticated session
- Use reasonable request delays
- For personal/research use only

## License

MIT
