"""
Streamlit web UI for Vision Extractor.

Provides a visual interface for:
- Template management
- Calibration with side-by-side screenshot/data review
- Single URL extraction
- Batch job management

Usage:
    streamlit run vision_extractor/web_ui.py
"""

import json
import sys
import os
import base64
import asyncio
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False

# Fix for Playwright + Streamlit event loop conflict
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass  # Will try alternative approach

# Handle imports for both module and direct execution
try:
    from .storage import TemplateStorage, get_builtin_template
    from .template_builder import TemplateBuilder
    from .sample_selector import SampleSelector
    from .intent import ExtractionIntent, ExtractionResult
    from .core import VisionExtractor
except ImportError:
    # When run directly by Streamlit, add parent to path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from vision_extractor.storage import TemplateStorage, get_builtin_template
    from vision_extractor.template_builder import TemplateBuilder
    from vision_extractor.sample_selector import SampleSelector
    from vision_extractor.intent import ExtractionIntent, ExtractionResult
    from vision_extractor.core import VisionExtractor


def check_streamlit():
    """Check if streamlit is available."""
    if not STREAMLIT_AVAILABLE:
        print("Streamlit not installed. Install with: pip install streamlit")
        print("Then run: streamlit run vision_extractor/web_ui.py")
        return False
    return True


def check_playwright():
    """Check if Playwright is available."""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def render_template_list():
    """Render template list sidebar."""
    st.sidebar.header("Templates")

    storage = TemplateStorage()
    templates = storage.list_templates()

    # Built-in templates
    st.sidebar.subheader("Built-in")
    for name in ["linkedin_profile", "company_website"]:
        if st.sidebar.button(f"{name}", key=f"builtin_{name}"):
            st.session_state.selected_template = name
            st.session_state.template_source = "builtin"

    # User templates
    if templates:
        st.sidebar.subheader("User Templates")
        for name in templates:
            if st.sidebar.button(f"{name}", key=f"user_{name}"):
                st.session_state.selected_template = name
                st.session_state.template_source = "user"


def render_template_detail(name: str, source: str):
    """Render template details."""
    storage = TemplateStorage()

    if source == "builtin":
        intent = get_builtin_template(name)
    else:
        intent = storage.load(name)

    if not intent:
        st.error(f"Template '{name}' not found")
        return

    st.header(f"Template: {intent.name}")
    st.write(intent.description)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Scroll Positions")
        for sp in intent.scroll_positions:
            st.write(f"- **{sp.name}**: y={sp.y_offset}px")

    with col2:
        st.subheader("Fields")
        for f in intent.fields:
            req = "required" if f.required else "optional"
            st.write(f"- **{f.name}** ({f.type.value}) - {req}")

    # JSON view
    with st.expander("View JSON"):
        st.json(intent.to_dict())

    # Actions
    st.subheader("Actions")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Copy to User Templates"):
            storage.save(intent)
            st.success(f"Saved as user template")

    with col2:
        if source == "user" and st.button("Delete"):
            storage.delete(name)
            st.session_state.selected_template = None
            st.rerun()


def render_create_template():
    """Render template creation form."""
    st.header("Create Template")

    with st.form("create_template"):
        name = st.text_input("Template Name", value="custom")
        description = st.text_area(
            "Describe what to extract",
            placeholder="Extract person's name, job title, company, work history with dates..."
        )
        url_pattern = st.text_input("URL Pattern (regex)", placeholder=".*")

        submitted = st.form_submit_button("Generate Template")

        if submitted and description:
            with st.spinner("Generating template with Claude..."):
                try:
                    builder = TemplateBuilder()
                    intent = builder.from_natural_language(
                        description=description,
                        template_name=name,
                        url_pattern=url_pattern
                    )

                    st.success(f"Generated {len(intent.fields)} fields")

                    # Show preview
                    st.subheader("Generated Fields")
                    for f in intent.fields:
                        st.write(f"- **{f.name}** ({f.type.value})")

                    # Save option
                    if st.button("Save Template"):
                        storage = TemplateStorage()
                        storage.save(intent)
                        st.success("Template saved!")

                except Exception as e:
                    st.error(f"Error: {e}")


def get_api_key() -> Optional[str]:
    """Get API key from session state or environment."""
    if "anthropic_api_key" in st.session_state and st.session_state.anthropic_api_key:
        return st.session_state.anthropic_api_key
    return os.getenv("ANTHROPIC_API_KEY")


LINKEDIN_COOKIES_FILE = "linkedin_cookies.json"


def get_linkedin_cookies() -> Optional[List[Dict]]:
    """Load LinkedIn cookies from file if they exist."""
    if os.path.exists(LINKEDIN_COOKIES_FILE):
        try:
            with open(LINKEDIN_COOKIES_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return None


def save_linkedin_cookies(cookies: List[Dict]):
    """Save LinkedIn cookies to file."""
    with open(LINKEDIN_COOKIES_FILE, 'w') as f:
        json.dump(cookies, f)


def check_linkedin_logged_in(cookies: List[Dict]) -> bool:
    """Check if cookies indicate a logged-in session."""
    if not cookies:
        return False
    cookie_names = [c.get('name', '') for c in cookies]
    # LinkedIn uses 'li_at' as the main auth cookie
    return 'li_at' in cookie_names


async def linkedin_login_async(email: str, password: str) -> Optional[List[Dict]]:
    """Perform LinkedIn login and return cookies."""
    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)  # Visible for CAPTCHA
            context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = await context.new_page()

            await page.goto("https://www.linkedin.com/login", timeout=30000)
            await page.fill('#username', email)
            await page.fill('#password', password)
            await page.click('button[type="submit"]')

            # Wait for login to complete (check for nav or error)
            try:
                await page.wait_for_selector('.global-nav__me', timeout=30000)
                # Success - get cookies
                cookies = await context.cookies()
                await browser.close()
                return cookies
            except:
                # May need manual CAPTCHA - wait longer
                await page.wait_for_selector('.global-nav__me', timeout=60000)
                cookies = await context.cookies()
                await browser.close()
                return cookies

    except Exception as e:
        print(f"Login error: {e}")
        return None


def linkedin_login(email: str, password: str) -> Optional[List[Dict]]:
    """Sync wrapper for LinkedIn login."""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(linkedin_login_async(email, password))
    finally:
        loop.close()


async def run_extraction_async(url: str, intent: ExtractionIntent, api_key: Optional[str] = None, cookies: Optional[List[Dict]] = None, headless: bool = True) -> Dict:
    """Async version of extraction using Playwright."""
    from playwright.async_api import async_playwright

    result_data = {
        "url": url,
        "screenshots": {},
        "data": {},
        "confidence": 0.0,
        "mode": "unknown",
        "errors": [],
        "api_key_missing": False
    }

    is_linkedin = 'linkedin.com' in url

    try:
        async with async_playwright() as p:
            # Use visible browser for LinkedIn to handle any challenges
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            # Add cookies if provided (for LinkedIn auth)
            if cookies and is_linkedin:
                await context.add_cookies(cookies)

            page = await context.new_page()

            # Hide webdriver flag
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            # Navigate with longer timeout - use 'load' event which is more reliable
            try:
                await page.goto(url, timeout=90000, wait_until='load')
            except Exception as nav_error:
                # Try with domcontentloaded if load times out
                result_data["errors"].append(f"Navigation slow, retrying: {str(nav_error)[:50]}")
                try:
                    await page.goto(url, timeout=60000, wait_until='domcontentloaded')
                except Exception as nav_error2:
                    result_data["errors"].append(f"Navigation failed: {str(nav_error2)}")
                    await browser.close()
                    return result_data

            # Wait for page to stabilize - LinkedIn needs more time for dynamic content
            stabilize_time = 5000 if is_linkedin else 3000
            await page.wait_for_timeout(stabilize_time)

            # Check if we got redirected to login page
            current_url = page.url
            if is_linkedin and '/login' in current_url:
                result_data["errors"].append("Redirected to login - cookies may be expired")
                result_data["needs_linkedin_login"] = True
                await browser.close()
                return result_data

            # For LinkedIn, wait for profile content to load
            if is_linkedin:
                try:
                    # Wait for profile header to be visible
                    await page.wait_for_selector('.pv-top-card', timeout=10000)
                except:
                    # Try alternative selector
                    try:
                        await page.wait_for_selector('[data-view-name="profile-card"]', timeout=5000)
                    except:
                        result_data["errors"].append("Warning: Could not detect profile content, continuing anyway")

            # Capture screenshots manually for display
            screenshots = {}
            for sp in intent.scroll_positions:
                try:
                    await page.evaluate(f"window.scrollTo(0, {sp.y_offset})")
                    wait_time = max(sp.wait_ms, 1500) if is_linkedin else max(sp.wait_ms, 1000)
                    await page.wait_for_timeout(wait_time)
                    screenshots[sp.name] = await page.screenshot()
                except Exception as e:
                    result_data["errors"].append(f"Screenshot {sp.name}: {str(e)[:50]}")

            if screenshots:
                result_data["screenshots"] = {k: base64.b64encode(v).decode() for k, v in screenshots.items()}
            else:
                result_data["errors"].append("No screenshots captured")

            # Check for API key
            if not api_key:
                result_data["api_key_missing"] = True
                result_data["errors"].append("No Claude API key - screenshots captured but no extraction performed")
                await browser.close()
                return result_data

            # Reset scroll and run extraction with Claude
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(500)

            # For Claude extraction, we need to use sync - capture screenshots and close browser first
            await browser.close()

            # Now do Claude extraction with captured screenshots
            raw_screenshots = {k: base64.b64decode(v) for k, v in result_data["screenshots"].items()}

            extractor = VisionExtractor(intent, claude_api_key=api_key, save_debug_screenshots=False)
            extracted_data = extractor.extract_all_with_vision(raw_screenshots)

            result_data["data"] = extracted_data
            result_data["confidence"] = 0.8 if extracted_data else 0.0
            result_data["mode"] = "vision"

    except Exception as e:
        result_data["errors"].append(f"Extraction error: {str(e)}")

    return result_data


def run_extraction(url: str, intent: ExtractionIntent, api_key: Optional[str] = None, cookies: Optional[List[Dict]] = None, headless: bool = True) -> Optional[Dict]:
    """Run extraction on a single URL and return results with screenshots."""
    if not check_playwright():
        return None

    # For LinkedIn URLs, check for cookies
    is_linkedin = 'linkedin.com' in url
    if is_linkedin and not cookies:
        cookies = get_linkedin_cookies()
        if not check_linkedin_logged_in(cookies):
            return {
                "url": url,
                "screenshots": {},
                "data": {},
                "confidence": 0.0,
                "mode": "error",
                "errors": ["LinkedIn authentication required. Please log in first."],
                "api_key_missing": False,
                "needs_linkedin_login": True
            }

    # Use a new event loop for Playwright async operations
    loop = None
    try:
        # Run async extraction
        if sys.platform == 'win32':
            # Windows needs special handling
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(run_extraction_async(url, intent, api_key, cookies, headless))
        return result

    except Exception as e:
        return {
            "url": url,
            "screenshots": {},
            "data": {},
            "confidence": 0.0,
            "mode": "error",
            "errors": [f"Event loop error: {str(e)}"],
            "api_key_missing": False
        }
    finally:
        if loop:
            try:
                loop.close()
            except:
                pass


def render_calibration():
    """Render calibration interface with full workflow."""
    st.header("Calibration")

    # Check Playwright
    if not check_playwright():
        st.error("Playwright not installed. Install with:")
        st.code("pip install playwright && python -m playwright install chromium")
        st.info("Or use CLI:")
        st.code("python -m vision_extractor calibrate --template <name> --urls <file>")
        return

    # Initialize session state for calibration
    if "calibration_results" not in st.session_state:
        st.session_state.calibration_results = []
    if "calibration_running" not in st.session_state:
        st.session_state.calibration_running = False
    if "linkedin_logged_in" not in st.session_state:
        # Check for existing cookies
        cookies = get_linkedin_cookies()
        st.session_state.linkedin_logged_in = check_linkedin_logged_in(cookies)

    # LinkedIn Authentication section
    st.subheader("LinkedIn Authentication")
    if st.session_state.linkedin_logged_in:
        st.success("LinkedIn: Logged in (cookies found)")
        if st.button("Clear LinkedIn session"):
            if os.path.exists(LINKEDIN_COOKIES_FILE):
                os.remove(LINKEDIN_COOKIES_FILE)
            st.session_state.linkedin_logged_in = False
            st.rerun()
    else:
        st.warning("LinkedIn: Not logged in. Required for LinkedIn profile extraction.")

        with st.expander("Login to LinkedIn", expanded=True):
            st.info("A browser window will open for login. Complete any CAPTCHA if prompted.")
            col1, col2 = st.columns(2)
            with col1:
                linkedin_email = st.text_input("LinkedIn Email", key="li_email")
            with col2:
                linkedin_password = st.text_input("LinkedIn Password", type="password", key="li_pass")

            if st.button("Login to LinkedIn", type="primary"):
                if linkedin_email and linkedin_password:
                    with st.spinner("Opening browser for LinkedIn login... Complete CAPTCHA if needed."):
                        cookies = linkedin_login(linkedin_email, linkedin_password)
                        if cookies and check_linkedin_logged_in(cookies):
                            save_linkedin_cookies(cookies)
                            st.session_state.linkedin_logged_in = True
                            st.success("LinkedIn login successful!")
                            st.rerun()
                        else:
                            st.error("Login failed. Check credentials or try again.")
                else:
                    st.error("Please enter both email and password")

    st.divider()

    # API Key section
    st.subheader("Claude API Key")
    api_key = get_api_key()
    if api_key:
        st.success("API key configured (from environment or session)")
    else:
        st.warning("No API key found. Enter your Anthropic API key to enable extraction.")

    new_api_key = st.text_input(
        "Anthropic API Key",
        type="password",
        placeholder="sk-ant-...",
        help="Required for Claude vision extraction. Get one at console.anthropic.com"
    )
    if new_api_key:
        st.session_state.anthropic_api_key = new_api_key
        api_key = new_api_key
        st.success("API key set for this session")

    st.divider()

    # Template selection
    storage = TemplateStorage()
    all_templates = ["linkedin_profile", "company_website"] + storage.list_templates()
    template_name = st.selectbox("Select Template", all_templates)

    # Load template
    intent = storage.load(template_name)
    if not intent:
        intent = get_builtin_template(template_name)

    if intent:
        with st.expander("Template Details"):
            st.write(f"**Fields:** {', '.join(f.name for f in intent.fields)}")
            st.write(f"**Scroll positions:** {', '.join(sp.name for sp in intent.scroll_positions)}")

    # URL input
    st.subheader("URLs to Calibrate")
    urls_text = st.text_area(
        "Enter URLs (one per line)",
        height=150,
        placeholder="https://www.linkedin.com/in/example1\nhttps://www.linkedin.com/in/example2"
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        n_samples = st.slider("Samples to process", 1, 10, 3)
    with col2:
        selection_method = st.radio("Selection", ["Random", "First N", "All"], horizontal=True)
    with col3:
        headless_mode = st.checkbox("Headless browser", value=True, help="Uncheck to see browser window (useful for debugging)")

    # Run calibration button
    if st.button("Run Calibration", type="primary", disabled=st.session_state.calibration_running):
        if not urls_text.strip():
            st.error("Please enter at least one URL")
        elif not intent:
            st.error("Please select a valid template")
        else:
            urls = [u.strip() for u in urls_text.split("\n") if u.strip() and not u.startswith('#')]

            if selection_method == "Random":
                selector = SampleSelector(urls)
                samples = list(selector.random_sample(n_samples))
            elif selection_method == "First N":
                samples = urls[:n_samples]
            else:
                samples = urls

            st.session_state.calibration_running = True
            st.session_state.calibration_results = []

            # Progress tracking
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, url in enumerate(samples):
                status_text.text(f"Processing {i+1}/{len(samples)}: {url[:60]}...")
                progress_bar.progress((i) / len(samples))

                result = run_extraction(url, intent, api_key=api_key, headless=headless_mode)
                if result:
                    st.session_state.calibration_results.append(result)

                progress_bar.progress((i + 1) / len(samples))

            status_text.text("Calibration complete!")
            st.session_state.calibration_running = False
            st.rerun()

    # Display results
    if st.session_state.calibration_results:
        st.subheader("Calibration Results")

        # Summary metrics
        results = st.session_state.calibration_results
        successful = [r for r in results if not r["errors"] and r["confidence"] > 0]

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Processed", len(results))
        with col2:
            st.metric("Successful", len(successful))
        with col3:
            avg_conf = sum(r["confidence"] for r in results) / len(results) if results else 0
            st.metric("Avg Confidence", f"{avg_conf:.1%}")

        # Individual results
        st.subheader("Sample Results")

        for i, result in enumerate(results):
            with st.expander(f"Sample {i+1}: {result['url'][:50]}...", expanded=(i == 0)):

                if result.get("api_key_missing"):
                    st.warning("No API key - showing screenshots only (no extraction)")
                elif result["errors"] and not result.get("api_key_missing"):
                    st.error(f"Errors: {', '.join(result['errors'])}")

                # Always show confidence/mode if we have them
                if result["confidence"] > 0 or result["mode"] != "unknown":
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Confidence:** {result['confidence']:.1%}")
                    with col2:
                        st.write(f"**Mode:** {result['mode']}")

                st.write("---")

                # Always show screenshots if we have them
                if result["screenshots"]:
                    st.write("**Screenshots:**")
                    cols = st.columns(len(result["screenshots"]))
                    for j, (name, img_b64) in enumerate(result["screenshots"].items()):
                        with cols[j]:
                            st.write(f"*{name}*")
                            st.image(base64.b64decode(img_b64), use_container_width=True)

                # Show extracted data if available
                if result["data"]:
                    st.write("**Extracted Data:**")
                    for key, value in result["data"].items():
                        if isinstance(value, list):
                            st.write(f"**{key}:** ({len(value)} items)")
                            if value and len(value) <= 5:
                                for item in value:
                                    if isinstance(item, dict):
                                        st.json(item)
                                    else:
                                        st.write(f"  - {item}")
                            elif value:
                                st.write(f"  First 3: {value[:3]}")
                        else:
                            val_str = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                            st.write(f"**{key}:** {val_str}")

                    # JSON download
                    st.download_button(
                        f"Download JSON",
                        json.dumps(result["data"], indent=2, default=str),
                        f"extraction_{i+1}.json",
                        "application/json",
                        key=f"download_{i}"
                    )
                elif not result.get("api_key_missing"):
                    st.warning("No data extracted")

        # Export all results
        st.subheader("Export")
        col1, col2 = st.columns(2)
        with col1:
            all_data = [r["data"] for r in results if r["data"]]
            st.download_button(
                "Download All Results (JSON)",
                json.dumps(all_data, indent=2, default=str),
                "calibration_results.json",
                "application/json"
            )
        with col2:
            if st.button("Clear Results"):
                st.session_state.calibration_results = []
                st.rerun()


def render_extract():
    """Render single URL extraction."""
    st.header("Extract Single URL")

    # Check Playwright
    if not check_playwright():
        st.error("Playwright not installed. Install with:")
        st.code("pip install playwright && python -m playwright install chromium")
        return

    # Initialize session state
    if "extract_result" not in st.session_state:
        st.session_state.extract_result = None

    # API Key section
    api_key = get_api_key()
    if not api_key:
        st.warning("No API key configured. Set it in the Calibrate page or enter below.")
        new_api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            placeholder="sk-ant-...",
            key="extract_api_key"
        )
        if new_api_key:
            st.session_state.anthropic_api_key = new_api_key
            api_key = new_api_key

    # Template selection
    storage = TemplateStorage()
    all_templates = ["linkedin_profile", "company_website"] + storage.list_templates()
    template_name = st.selectbox("Template", all_templates, key="extract_template")

    # Load template
    intent = storage.load(template_name)
    if not intent:
        intent = get_builtin_template(template_name)

    # URL input
    url = st.text_input("URL to extract", placeholder="https://www.linkedin.com/in/example")

    # Options
    headless_mode = st.checkbox("Headless browser", value=True, key="extract_headless", help="Uncheck to see browser window")

    # Extract button
    if st.button("Extract", type="primary"):
        if not url:
            st.error("Please enter a URL")
        elif not intent:
            st.error("Please select a valid template")
        else:
            with st.spinner(f"Extracting from {url}..."):
                result = run_extraction(url, intent, api_key=api_key, headless=headless_mode)
                st.session_state.extract_result = result

    # Display result
    if st.session_state.extract_result:
        result = st.session_state.extract_result

        st.subheader("Extraction Result")

        if result["errors"]:
            st.error(f"Errors: {', '.join(result['errors'])}")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Confidence", f"{result['confidence']:.1%}")
        with col2:
            st.metric("Mode", result['mode'])

        # Screenshots
        if result["screenshots"]:
            st.subheader("Screenshots")
            cols = st.columns(len(result["screenshots"]))
            for j, (name, img_b64) in enumerate(result["screenshots"].items()):
                with cols[j]:
                    st.write(f"**{name}**")
                    st.image(base64.b64decode(img_b64), use_container_width=True)

        # Data
        st.subheader("Extracted Data")
        if result["data"]:
            st.json(result["data"])

            st.download_button(
                "Download JSON",
                json.dumps(result["data"], indent=2, default=str),
                "extraction.json",
                "application/json"
            )
        else:
            st.warning("No data extracted")

        if st.button("Clear"):
            st.session_state.extract_result = None
            st.rerun()


def main():
    """Main Streamlit app."""
    if not check_streamlit():
        return

    st.set_page_config(
        page_title="Vision Extractor",
        page_icon="V",
        layout="wide"
    )

    st.title("Vision Extractor")
    st.write("Hybrid Claude vision extraction for web data")

    # Initialize session state
    if "selected_template" not in st.session_state:
        st.session_state.selected_template = None
        st.session_state.template_source = None

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Page",
        ["Templates", "Create", "Calibrate", "Extract"]
    )

    # Render template list in sidebar
    render_template_list()

    # Main content
    if page == "Templates":
        if st.session_state.selected_template:
            render_template_detail(
                st.session_state.selected_template,
                st.session_state.template_source
            )
        else:
            st.info("Select a template from the sidebar to view details.")

    elif page == "Create":
        render_create_template()

    elif page == "Calibrate":
        render_calibration()

    elif page == "Extract":
        render_extract()


if __name__ == "__main__":
    main()
