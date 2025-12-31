# Extraction Cascade Test Site

A local Flask website designed to test the extraction cascade with controlled, known content.

## Quick Start

```bash
cd test_site
python app.py
```

Then visit: http://localhost:5000

## Test Pages

| URL | Type | Challenge |
|-----|------|-----------|
| `/` | Homepage | Static HTML with basic company info |
| `/about` | About page | Static HTML with company description |
| `/team` | Team page | **STATIC HTML** - Leadership directly in HTML |
| `/team-js` | Team page | **JS RENDERED** - Content loaded via JavaScript |
| `/leadership` | Alt team URL | Same as `/team`, tests URL discovery |
| `/services` | Services | Static list of services and specialties |
| `/contact` | Contact | Office locations and contact info |
| `/people` | People search | **INTERACTIVE** - Dropdown filters, JS results |

## Extraction Challenges

1. **Static vs JavaScript Content**
   - `/team` has leadership in HTML (Tier 2 should find it)
   - `/team-js` loads the same data via JS (needs Tier 3 or 4)

2. **Dropdown Navigation**
   - "People" nav item is a dropdown with links
   - Tests navigation menu parsing

3. **Search/Filter Interface**
   - `/people` has search form with filters
   - Results loaded via JavaScript

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/api/team` | Returns leadership data as JSON |
| `/api/expected` | Returns all expected values for test verification |
| `/sitemap.xml` | XML sitemap for crawler |
| `/robots.txt` | Robots.txt with sitemap reference |

## Expected Values

The test site uses known data that can be verified:

**Company:**
- Name: "Acme Commercial Real Estate"
- Headquarters: "123 Main Street, Columbus, OH 43215"
- Phone: "(614) 555-1234"
- Email: "info@acme-cre.com"

**Leadership (5 people):**
- John Smith, CEO
- Sarah Johnson, President
- Michael Chen, CFO
- Emily Davis, Managing Director, Brokerage
- Robert Wilson, SVP

**Services (7):**
- Brokerage, Capital Markets, Property Management, Tenant Rep, Landlord Rep, Investment Sales, Valuation & Advisory

**Specialties (6):**
- Office, Industrial, Retail, Multifamily, Healthcare, Mixed-Use

## Testing the Cascade

```bash
# Test against static team page (Tier 2 should succeed)
python -m extraction_cascade extract http://localhost:5000 --verbose

# Verify expected values
curl http://localhost:5000/api/expected
```

## Adding New Test Cases

1. Add route in `app.py`
2. Create template in `templates/`
3. Add known data to the test data dictionaries
4. Document the extraction challenge
