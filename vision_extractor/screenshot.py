"""
Screenshot capture utilities for vision extraction.

Handles multi-viewport screenshot capture at different scroll positions.
"""

import time
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass

from .intent import ExtractionIntent, ScrollPosition


@dataclass
class ScreenshotConfig:
    """Configuration for screenshot capture."""
    save_debug: bool = False           # Save screenshots to disk for debugging
    debug_prefix: str = "screenshot"   # Prefix for debug files
    viewport_width: int = 1920
    viewport_height: int = 1080
    full_page: bool = False           # Capture full page vs viewport


class ScreenshotCapture:
    """
    Captures screenshots at configured scroll positions.

    Works with Playwright page objects to capture screenshots at
    different scroll positions defined in an ExtractionIntent.
    """

    def __init__(self, config: Optional[ScreenshotConfig] = None):
        self.config = config or ScreenshotConfig()

    def capture_at_positions(
        self,
        page: Any,  # Playwright Page object
        scroll_positions: list[ScrollPosition],
        delay_fn: Optional[Callable[[float, float], None]] = None
    ) -> Dict[str, bytes]:
        """
        Capture screenshots at each defined scroll position.

        Args:
            page: Playwright page object
            scroll_positions: List of ScrollPosition to capture
            delay_fn: Optional delay function (min_sec, max_sec) for human-like behavior

        Returns:
            Dict mapping section names to screenshot bytes
        """
        screenshots = {}

        for position in scroll_positions:
            try:
                # Scroll to position
                page.evaluate(f"window.scrollTo(0, {position.y_offset})")

                # Wait after scrolling
                wait_sec = position.wait_ms / 1000.0
                if delay_fn:
                    delay_fn(wait_sec * 0.5, wait_sec * 1.5)
                else:
                    time.sleep(wait_sec)

                # Capture screenshot
                screenshot_bytes = page.screenshot(full_page=self.config.full_page)
                screenshots[position.name] = screenshot_bytes

                # Save debug screenshot if configured
                if self.config.save_debug:
                    filename = f"{self.config.debug_prefix}_{position.name}.png"
                    with open(filename, 'wb') as f:
                        f.write(screenshot_bytes)

            except Exception as e:
                # Log error but continue with other positions
                print(f"[Screenshot] Error capturing {position.name}: {e}")

        return screenshots

    def capture_element(
        self,
        page: Any,
        selector: str,
        fallback_viewport: bool = True
    ) -> Optional[bytes]:
        """
        Capture screenshot of a specific element.

        Args:
            page: Playwright page object
            selector: CSS selector for element
            fallback_viewport: If element not found, capture viewport instead

        Returns:
            Screenshot bytes or None
        """
        try:
            element = page.query_selector(selector)
            if element:
                return element.screenshot()
            elif fallback_viewport:
                return page.screenshot(full_page=False)
            return None
        except Exception as e:
            print(f"[Screenshot] Error capturing element {selector}: {e}")
            if fallback_viewport:
                try:
                    return page.screenshot(full_page=False)
                except:
                    pass
            return None

    def capture_for_intent(
        self,
        page: Any,
        intent: ExtractionIntent,
        delay_fn: Optional[Callable[[float, float], None]] = None
    ) -> Dict[str, bytes]:
        """
        Capture all screenshots required by an ExtractionIntent.

        Args:
            page: Playwright page object
            intent: ExtractionIntent defining scroll positions
            delay_fn: Optional delay function for human-like behavior

        Returns:
            Dict mapping section names to screenshot bytes
        """
        return self.capture_at_positions(
            page,
            intent.scroll_positions,
            delay_fn
        )


def get_default_linkedin_positions() -> list[ScrollPosition]:
    """Default scroll positions for LinkedIn profile extraction."""
    return [
        ScrollPosition(name="header", y_offset=0, wait_ms=500),
        ScrollPosition(name="experience", y_offset=1500, wait_ms=500),
        ScrollPosition(name="education_groups", y_offset=3000, wait_ms=500),
    ]


def get_default_company_positions() -> list[ScrollPosition]:
    """Default scroll positions for company website extraction."""
    return [
        ScrollPosition(name="header", y_offset=0, wait_ms=500),
        ScrollPosition(name="services", y_offset=800, wait_ms=500),
        ScrollPosition(name="team", y_offset=1500, wait_ms=500),
    ]
