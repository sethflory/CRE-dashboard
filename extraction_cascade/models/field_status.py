"""Field status tracking for extraction cascade."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vision_extractor.intent import FieldDefinition


class FieldStatus(Enum):
    """Status of a field during extraction."""
    MISSING = "missing"           # Not yet extracted
    EXTRACTED = "extracted"       # Successfully extracted
    LOW_CONFIDENCE = "low_conf"   # Extracted but uncertain
    FAILED = "failed"             # Extraction attempted, failed
    SKIPPED = "skipped"           # User chose to skip


@dataclass
class FieldResult:
    """Result of extracting a single field."""
    value: Any
    confidence: float
    source_tier: str
    source_url: Optional[str] = None
    raw_context: Optional[str] = None  # Surrounding HTML/text for debugging


class FieldTracker:
    """
    Tracks extraction status and confidence for each field.

    Maintains state across tiers to know what's been found
    and what still needs extraction.
    """

    # Minimum confidence to consider a field "extracted"
    CONFIDENCE_THRESHOLD = 0.5

    # Confidence below this triggers LOW_CONFIDENCE status
    LOW_CONFIDENCE_THRESHOLD = 0.7

    def __init__(self, field_definitions: List[FieldDefinition]):
        """
        Initialize tracker with field definitions.

        Args:
            field_definitions: List of fields to track from ExtractionIntent
        """
        self.field_definitions = {f.name: f for f in field_definitions}
        self.status: Dict[str, FieldStatus] = {}
        self.results: Dict[str, FieldResult] = {}

        # Initialize all fields as missing
        for field_name in self.field_definitions:
            self.status[field_name] = FieldStatus.MISSING

    def update_field(
        self,
        field_name: str,
        value: Any,
        confidence: float,
        source_tier: str,
        source_url: Optional[str] = None,
        raw_context: Optional[str] = None
    ) -> None:
        """
        Update field status after extraction attempt.

        Args:
            field_name: Name of the field
            value: Extracted value (None if not found)
            confidence: Confidence score (0-1)
            source_tier: Which tier extracted this ("dom", "browser", "vision")
            source_url: URL where value was found
            raw_context: Surrounding HTML/text for debugging
        """
        if field_name not in self.field_definitions:
            return

        # Only update if this is better than what we have
        existing = self.results.get(field_name)
        if existing and existing.confidence >= confidence:
            return

        # Store result
        self.results[field_name] = FieldResult(
            value=value,
            confidence=confidence,
            source_tier=source_tier,
            source_url=source_url,
            raw_context=raw_context
        )

        # Determine status
        if value is None:
            self.status[field_name] = FieldStatus.FAILED
        elif confidence >= self.LOW_CONFIDENCE_THRESHOLD:
            self.status[field_name] = FieldStatus.EXTRACTED
        elif confidence >= self.CONFIDENCE_THRESHOLD:
            self.status[field_name] = FieldStatus.LOW_CONFIDENCE
        else:
            self.status[field_name] = FieldStatus.FAILED

    def mark_skipped(self, field_name: str) -> None:
        """Mark a field as skipped by user."""
        if field_name in self.field_definitions:
            self.status[field_name] = FieldStatus.SKIPPED

    def get_missing_fields(self) -> List[FieldDefinition]:
        """
        Get fields that still need extraction.

        Returns fields that are MISSING or LOW_CONFIDENCE (for required fields).
        """
        missing = []
        for name, definition in self.field_definitions.items():
            status = self.status.get(name, FieldStatus.MISSING)

            if status == FieldStatus.MISSING:
                missing.append(definition)
            elif status == FieldStatus.LOW_CONFIDENCE and definition.required:
                # Required fields with low confidence should be retried
                missing.append(definition)

        return missing

    def get_extracted_data(self) -> Dict[str, Any]:
        """Get all successfully extracted field values."""
        data = {}
        for name, result in self.results.items():
            if self.status.get(name) in (FieldStatus.EXTRACTED, FieldStatus.LOW_CONFIDENCE):
                data[name] = result.value
        return data

    def is_complete(self) -> bool:
        """Check if all required fields are extracted."""
        for name, definition in self.field_definitions.items():
            if definition.required:
                status = self.status.get(name, FieldStatus.MISSING)
                if status not in (FieldStatus.EXTRACTED, FieldStatus.SKIPPED):
                    return False
        return True

    def summary(self) -> Dict[str, Dict]:
        """
        Get summary of all field statuses.

        Returns dict mapping field names to status info.
        """
        summary = {}
        for name in self.field_definitions:
            status = self.status.get(name, FieldStatus.MISSING)
            result = self.results.get(name)

            summary[name] = {
                "status": status.value,
                "confidence": result.confidence if result else 0.0,
                "source_tier": result.source_tier if result else None,
                "has_value": result.value is not None if result else False,
            }

        return summary

    def get_success_rate(self) -> float:
        """Calculate extraction success rate."""
        total = len(self.field_definitions)
        if total == 0:
            return 1.0

        successful = sum(
            1 for status in self.status.values()
            if status in (FieldStatus.EXTRACTED, FieldStatus.LOW_CONFIDENCE)
        )
        return successful / total
