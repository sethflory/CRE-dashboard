"""
VisionExtractor - Main class for hybrid vision extraction.

Generalizes the linkedin_scraper.py pattern into a reusable component.
"""

import os
import re
from typing import Dict, Any, Optional, Callable

from .intent import ExtractionIntent, ExtractionResult, FieldType
from .screenshot import ScreenshotCapture, ScreenshotConfig
from .validation import ClaudeVisionValidator


class VisionExtractor:
    """
    Hybrid vision extraction using DOM + Claude vision.

    Workflow:
    1. Navigate to URL
    2. Extract data via DOM (optional, provided by caller)
    3. Capture screenshots at configured scroll positions
    4. Validate DOM data against screenshots
    5. Correct flagged fields or batch extract if too many issues
    """

    def __init__(
        self,
        intent: ExtractionIntent,
        claude_api_key: Optional[str] = None,
        model: str = "claude-3-5-haiku-20241022",
        save_debug_screenshots: bool = False
    ):
        """
        Initialize VisionExtractor.

        Args:
            intent: ExtractionIntent defining what to extract
            claude_api_key: Anthropic API key (or use ANTHROPIC_API_KEY env var)
            model: Claude model to use
            save_debug_screenshots: Save screenshots to disk for debugging
        """
        self.intent = intent
        self.api_key = claude_api_key or os.getenv('ANTHROPIC_API_KEY')
        self.model = model

        # Initialize components
        self.screenshot_capture = ScreenshotCapture(
            ScreenshotConfig(save_debug=save_debug_screenshots)
        )
        self.validator = ClaudeVisionValidator(
            api_key=self.api_key,
            model=self.model
        ) if self.api_key else None

    def matches_url(self, url: str) -> bool:
        """Check if URL matches this intent's target pattern."""
        if not self.intent.target_url_pattern:
            return True
        return bool(re.search(self.intent.target_url_pattern, url))

    def capture_screenshots(
        self,
        page: Any,
        delay_fn: Optional[Callable[[float, float], None]] = None
    ) -> Dict[str, bytes]:
        """
        Capture screenshots at configured scroll positions.

        Args:
            page: Playwright page object
            delay_fn: Optional delay function for human-like behavior

        Returns:
            Dict mapping section names to screenshot bytes
        """
        return self.screenshot_capture.capture_for_intent(
            page,
            self.intent,
            delay_fn
        )

    def validate_extraction(
        self,
        data: Dict[str, Any],
        screenshots: Dict[str, bytes]
    ) -> Dict:
        """
        Validate extracted data against screenshots.

        Args:
            data: Extracted data dictionary
            screenshots: Dict of section_name -> screenshot bytes

        Returns:
            Validation result with flagged fields and confidence
        """
        if not self.validator:
            return {"flagged_fields": [], "confidence": 0, "error": "No API key"}

        result = self.validator.validate(data, screenshots, self.intent)
        return {
            "flagged_fields": result.flagged_fields,
            "confidence": result.confidence,
            "error": result.error
        }

    def correct_field(
        self,
        field_name: str,
        screenshot: bytes,
        current_value: Any
    ) -> Any:
        """
        Correct a specific field using Claude vision.

        Args:
            field_name: Name of field to correct
            screenshot: Relevant screenshot bytes
            current_value: Current extracted value

        Returns:
            Corrected value
        """
        if not self.validator:
            return current_value

        field = self.intent.get_field(field_name)
        if not field:
            return current_value

        return self.validator.correct_field(field, screenshot, current_value)

    def extract_all_with_vision(
        self,
        screenshots: Dict[str, bytes]
    ) -> Dict[str, Any]:
        """
        Extract all fields directly from screenshots.

        Used when DOM extraction fails or has too many issues.

        Args:
            screenshots: Dict of section_name -> screenshot bytes

        Returns:
            Extracted data dictionary
        """
        if not self.validator:
            return {}

        return self.validator.extract_all(screenshots, self.intent)

    def get_screenshot_for_field(self, field_name: str) -> str:
        """Get the screenshot section name for a field."""
        field = self.intent.get_field(field_name)
        if field:
            return field.screenshot_section
        return "header"

    def extract_and_validate(
        self,
        page: Any,
        dom_data: Optional[Dict[str, Any]] = None,
        delay_fn: Optional[Callable[[float, float], None]] = None
    ) -> ExtractionResult:
        """
        Full hybrid extraction workflow.

        Args:
            page: Playwright page object
            dom_data: Optional pre-extracted DOM data
            delay_fn: Optional delay function

        Returns:
            ExtractionResult with data, screenshots, and validation info
        """
        url = page.url
        errors = []

        # Step 1: Capture screenshots
        screenshots = self.capture_screenshots(page, delay_fn)
        if not screenshots:
            return ExtractionResult(
                url=url,
                data=dom_data or {},
                errors=["Failed to capture screenshots"]
            )

        # Step 2: If no DOM data, extract directly with vision
        if not dom_data:
            data = self.extract_all_with_vision(screenshots)
            return ExtractionResult(
                url=url,
                data=data,
                screenshots=screenshots,
                confidence=0.8,  # Direct extraction confidence
                extraction_mode="vision"
            )

        # Step 3: Validate DOM data against screenshots
        validation = self.validate_extraction(dom_data, screenshots)

        if validation.get("error"):
            errors.append(f"Validation error: {validation['error']}")

        flagged_fields = validation.get("flagged_fields", [])
        confidence = validation.get("confidence", 0.0)

        # Step 4: Decide on correction strategy
        if len(flagged_fields) > self.intent.batch_extraction_threshold:
            # Too many issues - do batch extraction
            data = self.extract_all_with_vision(screenshots)
            return ExtractionResult(
                url=url,
                data=data,
                screenshots=screenshots,
                validation_result=validation,
                confidence=0.85,
                extraction_mode="hybrid_batch"
            )

        # Step 5: Correct individual flagged fields
        corrected_data = dict(dom_data)
        for issue in flagged_fields:
            field_name = issue.get("field", "")

            # Map Claude's field names to actual attribute names if needed
            field_mapping = {
                "title": "current_title",
                "company": "current_company",
            }
            field_name = field_mapping.get(field_name, field_name)

            if field_name in corrected_data or self.intent.get_field(field_name):
                screenshot_key = self.get_screenshot_for_field(field_name)
                screenshot = screenshots.get(screenshot_key)

                if screenshot:
                    current_value = corrected_data.get(field_name)
                    corrected = self.correct_field(field_name, screenshot, current_value)
                    if corrected is not None:
                        corrected_data[field_name] = corrected

        return ExtractionResult(
            url=url,
            data=corrected_data,
            screenshots=screenshots,
            validation_result=validation,
            confidence=confidence,
            extraction_mode="hybrid"
        )


def create_extractor_from_template(
    template_name: str,
    claude_api_key: Optional[str] = None,
    **kwargs
) -> VisionExtractor:
    """
    Create a VisionExtractor from a named template.

    Args:
        template_name: Name of template (e.g., "linkedin_profile", "company_website")
        claude_api_key: Optional API key
        **kwargs: Additional VisionExtractor arguments

    Returns:
        Configured VisionExtractor
    """
    from .storage import TemplateStorage

    storage = TemplateStorage()
    intent = storage.load(template_name)

    if not intent:
        raise ValueError(f"Template '{template_name}' not found")

    return VisionExtractor(intent, claude_api_key=claude_api_key, **kwargs)
