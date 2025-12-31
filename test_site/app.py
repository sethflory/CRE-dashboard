"""
Local test website for extraction cascade development.

Simulates various challenges:
- Static vs JavaScript-rendered content
- Dropdown menus
- Different HTML patterns for team/services/contact
- Various page structures

Run with: python test_site/app.py
Then visit: http://localhost:5000
"""

from flask import Flask, render_template, jsonify
import os

app = Flask(__name__, template_folder='templates', static_folder='static')

# Test data - known values for verification
COMPANY_DATA = {
    "name": "Acme Commercial Real Estate",
    "headquarters": "123 Main Street, Columbus, OH 43215",
    "main_phone": "(614) 555-1234",
    "main_email": "info@acme-cre.com",
    "about": "Acme CRE is a leading commercial real estate firm specializing in office, industrial, and retail properties across the Midwest.",
}

LEADERSHIP = [
    {"name": "John Smith", "title": "Chief Executive Officer", "email": "jsmith@acme-cre.com", "linkedin": "https://linkedin.com/in/johnsmith"},
    {"name": "Sarah Johnson", "title": "President", "email": "sjohnson@acme-cre.com", "linkedin": "https://linkedin.com/in/sarahjohnson"},
    {"name": "Michael Chen", "title": "Chief Financial Officer", "email": "mchen@acme-cre.com", "linkedin": "https://linkedin.com/in/michaelchen"},
    {"name": "Emily Davis", "title": "Managing Director, Brokerage", "email": "edavis@acme-cre.com", "linkedin": "https://linkedin.com/in/emilydavis"},
    {"name": "Robert Wilson", "title": "Senior Vice President", "email": "rwilson@acme-cre.com", "linkedin": "https://linkedin.com/in/robertwilson"},
]

SERVICES = [
    "Brokerage",
    "Capital Markets",
    "Property Management",
    "Tenant Representation",
    "Landlord Representation",
    "Investment Sales",
    "Valuation & Advisory",
]

SPECIALTIES = [
    "Office",
    "Industrial",
    "Retail",
    "Multifamily",
    "Healthcare",
    "Mixed-Use",
]

OFFICES = [
    {"city": "Columbus", "state": "OH", "address": "123 Main Street", "phone": "(614) 555-1234"},
    {"city": "Cleveland", "state": "OH", "address": "456 Erie Ave", "phone": "(216) 555-5678"},
    {"city": "Cincinnati", "state": "OH", "address": "789 River Road", "phone": "(513) 555-9012"},
]


@app.route('/')
def home():
    """Homepage with basic company info."""
    return render_template('home.html', company=COMPANY_DATA, services=SERVICES[:3])


@app.route('/about')
def about():
    """About page with company description."""
    return render_template('about.html', company=COMPANY_DATA)


@app.route('/team')
def team():
    """Team page - content loaded via JavaScript (Tier 3 required)."""
    return render_template('team_js.html')


@app.route('/team-static')
def team_static():
    """Static team page - for testing Tier 2 extraction."""
    return render_template('team_static.html', leadership=LEADERSHIP)


@app.route('/api/team')
def api_team():
    """API endpoint for JS-rendered team page."""
    return jsonify({"leadership": LEADERSHIP})


@app.route('/leadership')
def leadership():
    """Alternative leadership page URL - also JS rendered."""
    return render_template('team_js.html')


@app.route('/services')
def services():
    """Services page."""
    return render_template('services.html', services=SERVICES, specialties=SPECIALTIES)


@app.route('/contact')
def contact():
    """Contact page with office locations."""
    return render_template('contact.html', company=COMPANY_DATA, offices=OFFICES)


@app.route('/people')
def people_search():
    """People search page (like Newmark) - dropdown parent."""
    return render_template('people_search.html')


# Sitemap for crawler
@app.route('/sitemap.xml')
def sitemap():
    """XML sitemap."""
    pages = [
        '/', '/about', '/team', '/leadership',
        '/services', '/contact', '/people'
    ]
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for page in pages:
        xml += f'  <url><loc>http://localhost:5000{page}</loc></url>\n'
    xml += '</urlset>'
    return xml, 200, {'Content-Type': 'application/xml'}


@app.route('/robots.txt')
def robots():
    """Robots.txt."""
    return "User-agent: *\nAllow: /\nSitemap: http://localhost:5000/sitemap.xml", 200, {'Content-Type': 'text/plain'}


# Expected values endpoint for testing
@app.route('/api/expected')
def expected_values():
    """Returns expected extraction values for test verification."""
    return jsonify({
        "company_name": COMPANY_DATA["name"],
        "headquarters": COMPANY_DATA["headquarters"],
        "main_email": COMPANY_DATA["main_email"],
        "main_phone": COMPANY_DATA["main_phone"],
        "about": COMPANY_DATA["about"],
        "services": SERVICES,
        "specialties": SPECIALTIES,
        "leadership": LEADERSHIP,
        "offices": OFFICES,
    })


if __name__ == '__main__':
    print("\n" + "="*60)
    print("EXTRACTION CASCADE TEST SITE")
    print("="*60)
    print(f"Running at: http://localhost:5000")
    print()
    print("Test pages:")
    print("  /              - Homepage (static)")
    print("  /about         - About page (static)")
    print("  /team          - Team page (JS RENDERED - needs Tier 3)")
    print("  /leadership    - Leadership (JS RENDERED - needs Tier 3)")
    print("  /services      - Services page (static)")
    print("  /contact       - Contact page (static)")
    print("  /people        - People search (JS + interactive)")
    print()
    print("  /team-static   - Static team page (for Tier 2 testing)")
    print("  /api/expected  - Expected values for verification")
    print("="*60 + "\n")

    app.run(debug=True, port=5000)
