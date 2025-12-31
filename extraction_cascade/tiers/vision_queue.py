"""
Tier 4: Vision Queue - EXPENSIVE (requires user approval)

Captures screenshots and uses Claude Vision API for extraction.
Uses existing vision_extractor components.
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from extraction_cascade.models.session import SiteMap
from extraction_cascade.approval.callback import (
    ApprovalCallback,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalState,
    ScreenshotCandidate,
)

# Vision extractor imports
try:
    from vision_extractor.core import VisionExtractor
    from vision_extractor.screenshot import ScreenshotCapture, ScreenshotConfig
    from vision_extractor.validation import ClaudeVisionValidator
    from vision_extractor.intent import ExtractionIntent, FieldDefinition
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False
    VisionExtractor = None
    ScreenshotCapture = None

# Playwright for browser control
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@dataclass
class VisionExtractionResult:
    """Result of vision-based extraction."""
    value: Any
    confidence: float
    source_url: str
    screenshot_used: bool = True
    raw_response: Optional[str] = None


@dataclass
class VisionQueueConfig:
    """Configuration for vision queue."""
    cost_per_screenshot: float = 0.003  # Approximate Vision API cost
    model: str = "claude-3-5-haiku-20241022"
    save_debug_screenshots: bool = False


class VisionQueue:
    """
    Manages screenshot queue for Claude Vision extraction.

    Captures screenshots, queues for user approval,
    and extracts data from approved screenshots.
    """

    def __init__(
        self,
        intent: ExtractionIntent,
        approval_callback: ApprovalCallback,
        config: Optional[VisionQueueConfig] = None
    ):
        """
        Initialize vision queue.

        Args:
            intent: Extraction intent with field definitions
            approval_callback: Callback for user approval
            config: Optional configuration
        """
        self.intent = intent
        self.approval_callback = approval_callback
        self.config = config or VisionQueueConfig()

        self._cost_tracker = 0.0
        self._validator = None
        self._screenshot_capture = None

        if not VISION_AVAILABLE:
            print("Warning: vision_extractor not available")

    @property
    def is_available(self) -> bool:
        """Check if vision extraction is available."""
        return VISION_AVAILABLE and PLAYWRIGHT_AVAILABLE and os.getenv('ANTHROPIC_API_KEY') is not None

    def get_unavailable_reason(self) -> Optional[str]:
        """Get reason why vision queue is not available."""
        if not VISION_AVAILABLE:
            return "vision_extractor not available"
        if not PLAYWRIGHT_AVAILABLE:
            return "playwright not installed (pip install playwright && playwright install)"
        if not os.getenv('ANTHROPIC_API_KEY'):
            return "ANTHROPIC_API_KEY environment variable not set"
        return None

    @property
    def validator(self):
        """Lazy-load the vision validator."""
        if self._validator is None and VISION_AVAILABLE:
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if api_key:
                self._validator = ClaudeVisionValidator(
                    api_key=api_key,
                    model=self.config.model
                )
        return self._validator

    @property
    def screenshot_capture(self):
        """Lazy-load screenshot capture."""
        if self._screenshot_capture is None and VISION_AVAILABLE:
            self._screenshot_capture = ScreenshotCapture(
                ScreenshotConfig(save_debug=self.config.save_debug_screenshots)
            )
        return self._screenshot_capture

    def get_total_cost(self) -> float:
        """Get total cost incurred."""
        return self._cost_tracker

    def extract_with_approval(
        self,
        session_id: str,
        url: str,
        missing_fields: List[FieldDefinition],
        site_map: Optional[SiteMap],
        already_extracted: Dict[str, Any]
    ) -> Dict[str, VisionExtractionResult]:
        """
        Extract fields using vision with user approval.

        Args:
            session_id: Unique session identifier
            url: Target URL
            missing_fields: Fields that need extraction
            site_map: Site map for navigation
            already_extracted: Data already extracted (for context)

        Returns:
            Dict mapping field names to extraction results
        """
        if not self.is_available:
            return {}

        # Prepare screenshot candidates
        candidates = self._prepare_candidates(url, missing_fields, site_map)

        if not candidates:
            return {}

        # Calculate cost
        total_cost = sum(c.estimated_cost for c in candidates)

        # Build approval request
        request = ApprovalRequest(
            session_id=session_id,
            url=url,
            tier="vision",
            missing_fields=[f.name for f in missing_fields],
            screenshot_candidates=candidates,
            estimated_cost=total_cost,
            cost_breakdown={c.field_name: c.estimated_cost for c in candidates},
            already_extracted=already_extracted
        )

        # Get user approval
        response = self.approval_callback.request_approval(request)

        if not response.has_approved_items:
            return {}

        # Extract from approved screenshots
        results = self._extract_approved(response.approved_candidates, missing_fields)

        return results

    def _prepare_candidates(
        self,
        url: str,
        fields: List[FieldDefinition],
        site_map: Optional[SiteMap]
    ) -> List[ScreenshotCandidate]:
        """
        Prepare screenshot candidates for each field.

        Captures screenshots from likely pages.
        """
        candidates = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            try:
                for field in fields:
                    # Get most likely URLs for this field
                    urls_to_try = self._get_urls_for_field(url, field, site_map)

                    for page_url in urls_to_try[:2]:  # Try up to 2 pages per field
                        try:
                            page.goto(page_url, wait_until="networkidle", timeout=30000)

                            # Scroll to likely position for this field
                            scroll_position = self._get_scroll_position(field)
                            if scroll_position > 0:
                                page.evaluate(f"window.scrollTo(0, {scroll_position})")
                                page.wait_for_timeout(500)

                            # Capture screenshot
                            screenshot = page.screenshot()

                            candidates.append(ScreenshotCandidate(
                                field_name=field.name,
                                url=page_url,
                                screenshot_bytes=screenshot,
                                estimated_cost=self.config.cost_per_screenshot,
                                description=f"Screenshot for {field.name} from {page_url}"
                            ))

                        except Exception as e:
                            print(f"Error capturing {page_url}: {e}")
                            continue

            finally:
                browser.close()

        return candidates

    def _get_urls_for_field(
        self,
        base_url: str,
        field: FieldDefinition,
        site_map: Optional[SiteMap]
    ) -> List[str]:
        """Get most likely URLs for a field."""
        if site_map:
            pages = site_map.get_pages_for_field(field.name)
            if pages:
                return pages

        # Fallback: try common patterns
        field_to_path = {
            'leadership': ['/team', '/about/team', '/leadership'],
            'services': ['/services', '/what-we-do'],
            'contact_email': ['/contact', '/contact-us'],
            'contact_phone': ['/contact', '/contact-us'],
            'headquarters': ['/contact', '/about'],
            'office_locations': ['/contact', '/locations'],
        }

        paths = field_to_path.get(field.name, ['/about'])
        return [f"{base_url.rstrip('/')}{path}" for path in paths]

    def _get_scroll_position(self, field: FieldDefinition) -> int:
        """Get scroll position for a field."""
        # Use field's screenshot_section if defined
        if hasattr(field, 'screenshot_section'):
            section_positions = {
                'header': 0,
                'experience': 500,
                'education': 1000,
                'footer': 2000,
            }
            return section_positions.get(field.screenshot_section, 0)

        # Default positions by field type
        field_positions = {
            'leadership': 300,
            'services': 200,
            'contact_email': 500,
            'headquarters': 500,
        }
        return field_positions.get(field.name, 0)

    def _extract_approved(
        self,
        candidates: List[ScreenshotCandidate],
        fields: List[FieldDefinition]
    ) -> Dict[str, VisionExtractionResult]:
        """Extract data from approved screenshots."""
        results = {}

        if not self.validator:
            return results

        # Group candidates by field
        field_candidates = {}
        for candidate in candidates:
            if candidate.field_name not in field_candidates:
                field_candidates[candidate.field_name] = []
            field_candidates[candidate.field_name].append(candidate)

        # Extract from each field's screenshots
        for field_name, candidates_for_field in field_candidates.items():
            field_def = self.intent.get_field(field_name)
            if not field_def:
                continue

            for candidate in candidates_for_field:
                try:
                    # Use vision validator to extract
                    extracted = self.validator.extract_field(
                        field_def,
                        candidate.screenshot_bytes
                    )

                    if extracted is not None:
                        results[field_name] = VisionExtractionResult(
                            value=extracted,
                            confidence=0.85,
                            source_url=candidate.url,
                            screenshot_used=True
                        )
                        self._cost_tracker += self.config.cost_per_screenshot
                        break  # Got result, move to next field

                except Exception as e:
                    print(f"Vision extraction error for {field_name}: {e}")
                    continue

        return results


def run_vision_extraction(
    intent: ExtractionIntent,
    url: str,
    missing_fields: List[FieldDefinition],
    site_map: Optional[SiteMap] = None,
    already_extracted: Optional[Dict[str, Any]] = None,
    approval_callback: Optional[ApprovalCallback] = None
) -> Dict[str, VisionExtractionResult]:
    """
    Convenience function for vision extraction.

    Creates a VisionQueue and runs extraction with approval.
    """
    from extraction_cascade.approval.cli_approval import CLIApprovalCallback

    callback = approval_callback or CLIApprovalCallback()
    queue = VisionQueue(intent, callback)

    return queue.extract_with_approval(
        session_id="standalone",
        url=url,
        missing_fields=missing_fields,
        site_map=site_map,
        already_extracted=already_extracted or {}
    )
