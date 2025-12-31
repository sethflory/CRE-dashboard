"""Approval callback protocols and models."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ApprovalState(Enum):
    """State of an approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PARTIAL = "partial"  # Some items approved, some rejected
    SKIPPED = "skipped"  # User chose to skip entirely


@dataclass
class ScreenshotCandidate:
    """A screenshot candidate for user review."""
    field_name: str
    url: str
    screenshot_bytes: bytes
    estimated_cost: float = 0.003  # Approximate Vision API cost
    description: str = ""

    @property
    def cost_display(self) -> str:
        return f"${self.estimated_cost:.4f}"


@dataclass
class ApprovalRequest:
    """Request for user approval before expensive operation."""
    session_id: str
    url: str
    tier: str = "vision"

    # What's being requested
    missing_fields: List[str] = field(default_factory=list)
    screenshot_candidates: List[ScreenshotCandidate] = field(default_factory=list)

    # Cost information
    estimated_cost: float = 0.0
    cost_breakdown: Dict[str, float] = field(default_factory=dict)

    # Context
    already_extracted: Dict[str, Any] = field(default_factory=dict)
    extraction_summary: str = ""

    # Options
    allow_partial: bool = True
    allow_skip: bool = True

    @property
    def total_screenshots(self) -> int:
        return len(self.screenshot_candidates)

    @property
    def cost_display(self) -> str:
        return f"${self.estimated_cost:.4f}"


@dataclass
class ApprovalResponse:
    """User's response to an approval request."""
    state: ApprovalState
    approved_candidates: List[ScreenshotCandidate] = field(default_factory=list)
    rejected_candidates: List[ScreenshotCandidate] = field(default_factory=list)
    skipped_fields: List[str] = field(default_factory=list)
    user_notes: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def approved(self) -> bool:
        return self.state in (ApprovalState.APPROVED, ApprovalState.PARTIAL)

    @property
    def has_approved_items(self) -> bool:
        return len(self.approved_candidates) > 0


class ApprovalCallback(ABC):
    """
    Abstract base class for approval callbacks.

    Implementations handle user interaction for approval requests.
    """

    @abstractmethod
    def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        """
        Present approval request to user and return their decision.

        Args:
            request: The approval request with screenshots and cost info

        Returns:
            ApprovalResponse with user's decision
        """
        pass

    def on_extraction_start(self, url: str, intent_name: str) -> None:
        """Called when extraction starts for a URL. Override to show progress."""
        pass

    def on_tier_start(self, tier_name: str) -> None:
        """Called when a tier starts. Override to show progress."""
        pass

    def on_tier_skipped(self, tier_name: str, reason: str) -> None:
        """Called when a tier is skipped. Override to show why."""
        pass

    def on_tier_complete(self, tier_name: str, fields_found: int) -> None:
        """Called when a tier completes. Override to show progress."""
        pass

    def on_extraction_complete(self, success: bool, cost: float) -> None:
        """Called when extraction completes. Override to show summary."""
        pass

    # Detailed progress hooks for verbose mode
    def on_sitemap_check(self, url: str, found: bool, page_count: int = 0) -> None:
        """Called when sitemap.xml is checked."""
        pass

    def on_robots_check(self, url: str, found: bool) -> None:
        """Called when robots.txt is checked."""
        pass

    def on_page_discovered(self, url: str, page_type: str, source: str) -> None:
        """Called when a page is discovered during crawling."""
        pass

    def on_page_crawled(self, url: str, links_found: int) -> None:
        """Called when a page is crawled for links."""
        pass

    def on_static_pattern_check(self, pattern: str, exists: bool) -> None:
        """Called when checking static URL patterns."""
        pass

    def on_dom_extraction_start(self, page_url: str, page_type: str) -> None:
        """Called when starting DOM extraction on a page."""
        pass

    def on_dom_page_visit(self, page_url: str, page_type: str, fields_seeking: List[str]) -> None:
        """Called when visiting a page for DOM extraction."""
        pass

    def on_field_extracted(self, field_name: str, tier: str, confidence: float) -> None:
        """Called when a field is extracted."""
        pass

    def on_field_not_found(self, field_name: str, tier: str, pages_tried: List[str]) -> None:
        """Called when a field could not be extracted."""
        pass

    def on_api_key_required(self, tier_name: str, missing_fields: List[str]) -> bool:
        """
        Called when API key is required for a tier but not set.

        Args:
            tier_name: Name of the tier requiring API key
            missing_fields: Fields that still need extraction

        Returns:
            True if user provided the key and we should proceed, False to skip tier
        """
        return False  # Default: skip the tier


class AutoApprovalCallback(ApprovalCallback):
    """
    Automatically approves all requests.

    Useful for testing or batch processing where user interaction
    is not desired.
    """

    def __init__(self, max_cost: float = 1.0, log_approvals: bool = True):
        """
        Args:
            max_cost: Maximum cost to auto-approve (rejects if exceeded)
            log_approvals: Whether to print approval decisions
        """
        self.max_cost = max_cost
        self.log_approvals = log_approvals

    def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        if request.estimated_cost > self.max_cost:
            if self.log_approvals:
                print(f"Auto-reject: cost ${request.estimated_cost:.4f} exceeds max ${self.max_cost:.4f}")
            return ApprovalResponse(
                state=ApprovalState.REJECTED,
                rejected_candidates=request.screenshot_candidates
            )

        if self.log_approvals:
            print(f"Auto-approve: {len(request.screenshot_candidates)} screenshots for ${request.estimated_cost:.4f}")

        return ApprovalResponse(
            state=ApprovalState.APPROVED,
            approved_candidates=request.screenshot_candidates
        )
