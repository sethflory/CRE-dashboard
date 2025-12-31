"""CLI-based approval callback for terminal interaction."""

import os
import tempfile
from typing import List, Dict

from .callback import (
    ApprovalCallback,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalState,
    ScreenshotCandidate,
)


# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


class CLIApprovalCallback(ApprovalCallback):
    """
    Command-line approval implementation.

    Presents approval requests in the terminal and waits for user input.
    """

    def __init__(self, save_screenshots: bool = False, screenshot_dir: str = None):
        """
        Args:
            save_screenshots: Whether to save screenshots to disk for review
            screenshot_dir: Directory to save screenshots (default: temp dir)
        """
        self.save_screenshots = save_screenshots
        self.screenshot_dir = screenshot_dir or tempfile.gettempdir()

    def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        """Present approval request and get user decision."""
        self._print_header(request)
        self._print_context(request)
        self._print_candidates(request)
        self._print_options(request)

        choice = self._get_user_choice(request)
        return self._handle_choice(choice, request)

    def on_extraction_start(self, url: str, intent_name: str) -> None:
        print(f"\n{'='*60}")
        print(f"Starting extraction: {url}")
        print(f"Template: {intent_name}")
        print(f"{'='*60}")

    def on_tier_complete(self, tier_name: str, fields_found: int) -> None:
        tier_display = tier_name.upper()
        print(f"  [{tier_display}] Found {fields_found} fields")

    def on_extraction_complete(self, success: bool, cost: float) -> None:
        status = "SUCCESS" if success else "INCOMPLETE"
        print(f"\n{'='*60}")
        print(f"Extraction {status}")
        print(f"Total cost: ${cost:.4f}")
        print(f"{'='*60}\n")

    def _print_header(self, request: ApprovalRequest) -> None:
        print(f"\n{'='*60}")
        print(f"APPROVAL REQUIRED: Vision API Screenshots")
        print(f"{'='*60}")
        print(f"URL: {request.url}")
        print(f"Missing fields: {', '.join(request.missing_fields)}")
        print(f"Estimated cost: {request.cost_display}")
        print()

    def _print_context(self, request: ApprovalRequest) -> None:
        if request.already_extracted:
            print("Already extracted (free):")
            for key, value in request.already_extracted.items():
                display_value = self._format_value(value)
                print(f"  - {key}: {display_value}")
            print()

    def _print_candidates(self, request: ApprovalRequest) -> None:
        print("Screenshot candidates:")
        for i, candidate in enumerate(request.screenshot_candidates, 1):
            print(f"  {i}. {candidate.url}")
            print(f"     Field: {candidate.field_name}")
            print(f"     Cost: {candidate.cost_display}")
            if candidate.description:
                print(f"     Note: {candidate.description}")

            # Save screenshot if enabled
            if self.save_screenshots:
                path = self._save_screenshot(candidate, i)
                print(f"     Preview: {path}")

        print()

    def _print_options(self, request: ApprovalRequest) -> None:
        print("Options:")
        print("  [a] Approve all screenshots")
        if request.allow_partial:
            print("  [s] Select specific screenshots")
        if request.allow_skip:
            print("  [k] Skip missing fields (don't extract)")
        print("  [c] Cancel (abort extraction)")
        print()

    def _get_user_choice(self, request: ApprovalRequest) -> str:
        while True:
            choice = input("Choice: ").lower().strip()
            if choice in ['a', 's', 'k', 'c']:
                return choice
            if choice.isdigit():
                # Allow direct number selection
                return choice
            print("Invalid choice. Please enter a, s, k, or c.")

    def _handle_choice(self, choice: str, request: ApprovalRequest) -> ApprovalResponse:
        if choice == 'a':
            return ApprovalResponse(
                state=ApprovalState.APPROVED,
                approved_candidates=request.screenshot_candidates
            )

        elif choice == 's':
            return self._select_specific(request)

        elif choice == 'k':
            return ApprovalResponse(
                state=ApprovalState.SKIPPED,
                skipped_fields=request.missing_fields
            )

        elif choice == 'c':
            return ApprovalResponse(
                state=ApprovalState.REJECTED,
                rejected_candidates=request.screenshot_candidates
            )

        else:
            # Number selection
            return self._handle_number_selection(choice, request)

    def _select_specific(self, request: ApprovalRequest) -> ApprovalResponse:
        """Allow user to select specific screenshots."""
        print("\nEnter screenshot numbers to approve (comma-separated), or 'done' when finished:")
        print(f"Available: 1-{len(request.screenshot_candidates)}")

        selected_indices = set()

        while True:
            selection = input("Select: ").strip().lower()

            if selection == 'done':
                break

            # Parse comma-separated numbers
            try:
                for part in selection.split(','):
                    part = part.strip()
                    if part:
                        idx = int(part) - 1  # Convert to 0-based
                        if 0 <= idx < len(request.screenshot_candidates):
                            selected_indices.add(idx)
                        else:
                            print(f"Invalid number: {part}")
            except ValueError:
                print("Please enter numbers separated by commas, or 'done'")
                continue

            print(f"Selected: {sorted(i+1 for i in selected_indices)}")

        approved = [request.screenshot_candidates[i] for i in sorted(selected_indices)]
        rejected = [c for i, c in enumerate(request.screenshot_candidates) if i not in selected_indices]

        if not approved:
            return ApprovalResponse(
                state=ApprovalState.REJECTED,
                rejected_candidates=request.screenshot_candidates
            )

        return ApprovalResponse(
            state=ApprovalState.PARTIAL if rejected else ApprovalState.APPROVED,
            approved_candidates=approved,
            rejected_candidates=rejected
        )

    def _handle_number_selection(self, choice: str, request: ApprovalRequest) -> ApprovalResponse:
        """Handle direct number input."""
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(request.screenshot_candidates):
                approved = [request.screenshot_candidates[idx]]
                rejected = [c for i, c in enumerate(request.screenshot_candidates) if i != idx]
                return ApprovalResponse(
                    state=ApprovalState.PARTIAL,
                    approved_candidates=approved,
                    rejected_candidates=rejected
                )
        except ValueError:
            pass

        return ApprovalResponse(
            state=ApprovalState.REJECTED,
            rejected_candidates=request.screenshot_candidates
        )

    def _save_screenshot(self, candidate: ScreenshotCandidate, index: int) -> str:
        """Save screenshot to disk for preview."""
        filename = f"screenshot_{index}_{candidate.field_name}.png"
        path = os.path.join(self.screenshot_dir, filename)

        with open(path, 'wb') as f:
            f.write(candidate.screenshot_bytes)

        return path

    def _format_value(self, value) -> str:
        """Format a value for display."""
        if value is None:
            return "(none)"
        if isinstance(value, list):
            if len(value) == 0:
                return "[]"
            if len(value) <= 3:
                return str(value)
            return f"[{len(value)} items]"
        if isinstance(value, dict):
            return f"{{{len(value)} keys}}"
        if isinstance(value, str) and len(value) > 50:
            return value[:47] + "..."
        return str(value)

    def on_api_key_required(self, tier_name: str, missing_fields: List[str]) -> bool:
        """Prompt user for API key when missing."""
        tier_display = {
            "browser": "Browser Agent (Tier 3)",
            "vision": "Vision API (Tier 4)",
        }.get(tier_name, tier_name)

        print(f"\n{'='*60}")
        print(f"API KEY REQUIRED: {tier_display}")
        print(f"{'='*60}")
        print(f"\nThe ANTHROPIC_API_KEY environment variable is not set.")
        print(f"\nMissing fields that could be extracted: {', '.join(missing_fields)}")
        print(f"\nOptions:")
        print(f"  [1] Enter API key now")
        print(f"  [2] Skip this tier (continue without it)")
        print(f"  [3] Cancel extraction")

        while True:
            choice = input("\nChoice [1/2/3]: ").strip()

            if choice == '1':
                api_key = input("Enter ANTHROPIC_API_KEY: ").strip()
                if api_key:
                    os.environ['ANTHROPIC_API_KEY'] = api_key
                    print("API key set successfully.")
                    return True
                else:
                    print("No key entered.")
            elif choice == '2':
                print(f"Skipping {tier_display}.")
                return False
            elif choice == '3':
                print("Extraction cancelled.")
                raise KeyboardInterrupt("User cancelled extraction")
            else:
                print("Invalid choice. Please enter 1, 2, or 3.")


class VerboseCLICallback(CLIApprovalCallback):
    """
    Verbose CLI callback with detailed progress reporting.

    Shows granular progress for site mapping, crawling, and extraction.
    """

    def __init__(self, save_screenshots: bool = False, screenshot_dir: str = None, use_colors: bool = True):
        super().__init__(save_screenshots, screenshot_dir)
        self.use_colors = use_colors
        self._discovered_pages: Dict[str, List[str]] = {}
        self._fields_extracted: List[str] = []
        self._current_tier: str = ""
        self._base_url: str = ""
        self._pages_visited: List[str] = []

    def _c(self, text: str, color: str) -> str:
        """Apply color if colors are enabled."""
        if self.use_colors:
            return f"{color}{text}{Colors.ENDC}"
        return text

    def on_extraction_start(self, url: str, intent_name: str) -> None:
        self._base_url = url.rstrip('/')
        self._discovered_pages = {}
        self._pages_visited = []
        print(f"\n{self._c('='*70, Colors.BOLD)}")
        print(f"{self._c('EXTRACTION CASCADE', Colors.BOLD + Colors.CYAN)}")
        print(f"{self._c('='*70, Colors.BOLD)}")
        print(f"  URL:      {self._c(url, Colors.BLUE)}")
        print(f"  Template: {intent_name}")
        print()

    def on_tier_start(self, tier_name: str) -> None:
        self._current_tier = tier_name
        tier_info = {
            "site_mapping": ("TIER 1: Site Mapping", "FREE", "Discovering site structure..."),
            "dom": ("TIER 2: DOM Extraction", "FREE", "Extracting from HTML..."),
            "browser": ("TIER 3: Browser Agent", "~$0.01-0.05", "Using AI browser navigation..."),
            "vision": ("TIER 4: Vision API", "~$0.003/img", "Analyzing screenshots..."),
        }
        name, cost, desc = tier_info.get(tier_name, (tier_name.upper(), "?", ""))
        print(f"\n{self._c(f'[{name}]', Colors.BOLD)} {self._c(f'({cost})', Colors.DIM)}")
        print(f"  {desc}")

    def on_tier_skipped(self, tier_name: str, reason: str) -> None:
        tier_display = {
            "browser": "TIER 3: Browser Agent",
            "vision": "TIER 4: Vision API",
        }.get(tier_name, tier_name.upper())
        print(f"\n{self._c(f'[{tier_display}]', Colors.BOLD)} {self._c('SKIPPED', Colors.YELLOW)}")
        print(f"  {self._c('Reason:', Colors.RED)} {reason}")

    def on_tier_complete(self, tier_name: str, fields_found: int) -> None:
        if fields_found > 0:
            print(f"  {self._c(f'-> {fields_found} fields extracted', Colors.GREEN)}")
        else:
            print(f"  {self._c('-> No new fields extracted', Colors.YELLOW)}")

    def on_sitemap_check(self, url: str, found: bool, page_count: int = 0) -> None:
        if found:
            print(f"    {self._c('[sitemap.xml]', Colors.GREEN)} Found {page_count} pages")
        else:
            print(f"    {self._c('[sitemap.xml]', Colors.DIM)} Not found")

    def on_robots_check(self, url: str, found: bool) -> None:
        if found:
            print(f"    {self._c('[robots.txt]', Colors.GREEN)} Found")
        else:
            print(f"    {self._c('[robots.txt]', Colors.DIM)} Not found")

    def on_page_crawled(self, url: str, links_found: int) -> None:
        print(f"    {self._c('[homepage]', Colors.GREEN)} Crawled, found {links_found} internal links")

    def on_page_discovered(self, url: str, page_type: str, source: str) -> None:
        # Track discovered pages by type
        if page_type not in self._discovered_pages:
            self._discovered_pages[page_type] = []
        if url not in self._discovered_pages[page_type]:
            self._discovered_pages[page_type].append(url)

    def on_static_pattern_check(self, pattern: str, exists: bool) -> None:
        # Only show found patterns to reduce noise
        if exists:
            print(f"    {self._c('[pattern]', Colors.GREEN)} {pattern} exists")

    def on_dom_extraction_start(self, page_url: str, page_type: str) -> None:
        short_url = page_url.split('/')[-1] or 'homepage'
        print(f"    Extracting from: {short_url} ({page_type})")

    def on_dom_page_visit(self, page_url: str, page_type: str, fields_seeking: List[str]) -> None:
        self._pages_visited.append(page_url)
        short_url = page_url.replace(self._base_url, '') or '/'
        fields_str = ', '.join(fields_seeking[:3])
        if len(fields_seeking) > 3:
            fields_str += f", +{len(fields_seeking) - 3} more"
        print(f"    {self._c('Visiting:', Colors.CYAN)} {short_url}")
        print(f"      Looking for: {fields_str}")

    def on_field_extracted(self, field_name: str, tier: str, confidence: float) -> None:
        self._fields_extracted.append(field_name)
        conf_color = Colors.GREEN if confidence >= 0.8 else Colors.YELLOW if confidence >= 0.5 else Colors.RED
        print(f"      {self._c('+', Colors.GREEN)} {field_name}: {self._c(f'{confidence:.0%}', conf_color)} confidence")

    def on_field_not_found(self, field_name: str, tier: str, pages_tried: List[str]) -> None:
        pages_str = ', '.join(p.replace(self._base_url, '') or '/' for p in pages_tried[:3])
        if len(pages_tried) > 3:
            pages_str += f", +{len(pages_tried) - 3} more"
        print(f"      {self._c('-', Colors.RED)} {field_name}: {self._c('not found', Colors.RED)}")
        if pages_tried:
            print(f"        Tried: {pages_str}")

    def on_extraction_complete(self, success: bool, cost: float) -> None:
        print(f"\n{self._c('-'*70, Colors.DIM)}")

        # Show discovered pages summary with URLs
        if self._discovered_pages:
            print(f"\n{self._c('Site Map:', Colors.BOLD)}")
            for page_type, urls in sorted(self._discovered_pages.items()):
                print(f"  {self._c(page_type, Colors.CYAN)}: {len(urls)} page(s)")
                for url in urls[:5]:  # Show up to 5 URLs per type
                    short_url = url.replace(self._base_url, '') if hasattr(self, '_base_url') else url
                    if len(short_url) > 60:
                        short_url = short_url[:57] + "..."
                    print(f"    {self._c('-', Colors.DIM)} {short_url or '/'}")
                if len(urls) > 5:
                    print(f"    {self._c(f'... and {len(urls) - 5} more', Colors.DIM)}")

        # Show completion status
        status = self._c("COMPLETE", Colors.GREEN) if success else self._c("INCOMPLETE", Colors.YELLOW)
        print(f"\n{self._c('Status:', Colors.BOLD)} {status}")
        print(f"{self._c('Total cost:', Colors.BOLD)} ${cost:.4f}")
        print()

    def on_api_key_required(self, tier_name: str, missing_fields: List[str]) -> bool:
        """Prompt user for API key when missing (with colors)."""
        tier_display = {
            "browser": "Browser Agent (Tier 3)",
            "vision": "Vision API (Tier 4)",
        }.get(tier_name, tier_name)

        print(f"\n{self._c('='*60, Colors.BOLD)}")
        print(f"{self._c('API KEY REQUIRED:', Colors.YELLOW)} {self._c(tier_display, Colors.BOLD)}")
        print(f"{self._c('='*60, Colors.BOLD)}")
        print(f"\n{self._c('ANTHROPIC_API_KEY', Colors.RED)} environment variable is not set.")
        print(f"\nMissing fields: {self._c(', '.join(missing_fields), Colors.CYAN)}")
        print(f"\n{self._c('Options:', Colors.BOLD)}")
        print(f"  {self._c('[1]', Colors.GREEN)} Enter API key now")
        print(f"  {self._c('[2]', Colors.YELLOW)} Skip this tier")
        print(f"  {self._c('[3]', Colors.RED)} Cancel extraction")

        while True:
            choice = input(f"\n{self._c('Choice', Colors.BOLD)} [1/2/3]: ").strip()

            if choice == '1':
                api_key = input(f"Enter {self._c('ANTHROPIC_API_KEY', Colors.CYAN)}: ").strip()
                if api_key:
                    os.environ['ANTHROPIC_API_KEY'] = api_key
                    print(f"{self._c('API key set successfully.', Colors.GREEN)}")
                    return True
                else:
                    print(f"{self._c('No key entered.', Colors.RED)}")
            elif choice == '2':
                print(f"{self._c(f'Skipping {tier_display}.', Colors.YELLOW)}")
                return False
            elif choice == '3':
                print(f"{self._c('Extraction cancelled.', Colors.RED)}")
                raise KeyboardInterrupt("User cancelled extraction")
            else:
                print(f"{self._c('Invalid choice. Please enter 1, 2, or 3.', Colors.RED)}")
