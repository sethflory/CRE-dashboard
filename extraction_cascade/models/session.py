"""Extraction session state management."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vision_extractor.intent import ExtractionIntent

from .field_status import FieldTracker, FieldStatus
from .provenance import ExtractionProvenance, FieldProvenance


@dataclass
class SiteMap:
    """
    Represents a mapped site structure.

    Contains discovered pages categorized by type.
    """
    base_url: str
    pages: Dict[str, List[str]] = field(default_factory=dict)  # type -> [urls]
    sitemap_urls: List[str] = field(default_factory=list)
    robots_info: Optional[Dict] = None
    crawled_links: List[str] = field(default_factory=list)

    def add_page(self, url: str, page_type: str, source: str = "crawl") -> None:
        """Add a discovered page."""
        if page_type not in self.pages:
            self.pages[page_type] = []
        if url not in self.pages[page_type]:
            self.pages[page_type].append(url)

        if source == "sitemap" and url not in self.sitemap_urls:
            self.sitemap_urls.append(url)
        elif source == "crawl" and url not in self.crawled_links:
            self.crawled_links.append(url)

    def get_pages_by_type(self, page_type: str) -> List[str]:
        """Get pages of a specific type."""
        return self.pages.get(page_type, [])

    def get_pages_for_field(self, field_name: str) -> List[str]:
        """
        Get most probable pages for extracting a field.

        Maps field names to likely page types.
        """
        field_to_page_type = {
            "leadership": ["team", "about"],
            "services": ["services", "about"],
            "specialties": ["services", "about"],
            "contact_email": ["contact", "about"],
            "contact_phone": ["contact", "about"],
            "headquarters": ["contact", "about"],
            "office_locations": ["contact", "locations"],
            "company_name": ["about", "home"],
            "about": ["about"],
        }

        page_types = field_to_page_type.get(field_name, ["about", "home"])
        pages = []
        for pt in page_types:
            pages.extend(self.get_pages_by_type(pt))
        return pages

    @property
    def total_pages(self) -> int:
        """Total number of discovered pages."""
        return sum(len(urls) for urls in self.pages.values())


@dataclass
class ExtractionSession:
    """
    Complete state for extracting from a single URL.

    Tracks field extraction, tier progression, costs,
    and generates provenance records.
    """
    url: str
    intent: ExtractionIntent
    site_map: Optional[SiteMap] = None
    field_tracker: Optional[FieldTracker] = None
    provenance: Optional[ExtractionProvenance] = None

    # Extracted data
    data: Dict[str, Any] = field(default_factory=dict)

    # Tier progression
    tiers_executed: List[str] = field(default_factory=list)
    current_tier: Optional[str] = None

    # Cost tracking
    total_cost: float = 0.0
    cost_breakdown: Dict[str, float] = field(default_factory=dict)

    # Timestamps
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def __post_init__(self):
        """Initialize field tracker and provenance after creation."""
        if self.field_tracker is None:
            self.field_tracker = FieldTracker(self.intent.fields)
        if self.provenance is None:
            self.provenance = ExtractionProvenance(
                url=self.url,
                intent_name=self.intent.name
            )

    def start_tier(self, tier_name: str) -> None:
        """Mark the start of a tier."""
        self.current_tier = tier_name
        if tier_name not in self.tiers_executed:
            self.tiers_executed.append(tier_name)
        self.provenance.add_tier(tier_name)

    def update_field(
        self,
        field_name: str,
        value: Any,
        confidence: float,
        source_url: Optional[str] = None,
        raw_context: Optional[str] = None
    ) -> None:
        """
        Update a field with extraction result.

        Updates field tracker, data dict, and provenance.
        """
        tier = self.current_tier or "unknown"
        url = source_url or self.url

        # Update field tracker
        self.field_tracker.update_field(
            field_name=field_name,
            value=value,
            confidence=confidence,
            source_tier=tier,
            source_url=url,
            raw_context=raw_context
        )

        # Update data dict if extracted successfully
        if value is not None and confidence >= FieldTracker.CONFIDENCE_THRESHOLD:
            self.data[field_name] = value

        # Update provenance
        field_def = self.intent.get_field(field_name)
        if field_def:
            prov = FieldProvenance.from_field_definition(
                definition=field_def,
                extracted_value=value,
                tier=tier if value is not None else "none",
                source_url=url,
                confidence=confidence,
                raw_context=raw_context
            )
            self.provenance.add_field(prov)

    def add_cost(self, cost: float, tier: Optional[str] = None) -> None:
        """Add to cost tracking."""
        tier_name = tier or self.current_tier or "unknown"
        self.total_cost += cost
        self.cost_breakdown[tier_name] = self.cost_breakdown.get(tier_name, 0) + cost
        self.provenance.add_cost(cost)

    def is_complete(self) -> bool:
        """Check if all required fields are extracted."""
        return self.field_tracker.is_complete()

    def get_missing_fields(self) -> List:
        """Get fields that still need extraction."""
        return self.field_tracker.get_missing_fields()

    def mark_complete(self, final_tier: Optional[str] = None) -> None:
        """Mark extraction as complete."""
        self.completed_at = datetime.now()
        if final_tier:
            self.current_tier = final_tier
        self.provenance.mark_complete()

    def get_result(self) -> Dict[str, Any]:
        """
        Get final extraction result with metadata.

        Returns data dict with _extraction_metadata field.
        """
        result = dict(self.data)
        result["_extraction_metadata"] = {
            "url": self.url,
            "intent": self.intent.name,
            "final_tier": self.current_tier,
            "tiers_used": self.tiers_executed,
            "total_cost": self.total_cost,
            "cost_breakdown": self.cost_breakdown,
            "success_rate": self.field_tracker.get_success_rate(),
            "field_summary": self.field_tracker.summary(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        return result

    def get_provenance(self) -> ExtractionProvenance:
        """Get the provenance record for this session."""
        return self.provenance

    def get_calibration_record(self) -> Dict:
        """Get calibration record for template fine-tuning."""
        return self.provenance.to_calibration_record()
