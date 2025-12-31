"""Field provenance tracking for fine-tuning and UI display."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import json
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vision_extractor.intent import FieldDefinition, FieldType


@dataclass
class FieldProvenance:
    """
    Tracks how a single field was extracted.

    Maps template field definition to the actual extracted value,
    including metadata about extraction source and confidence.
    """
    field_name: str                           # Template field name
    template_type: FieldType                  # Expected type from template
    template_required: bool                   # Whether field was required
    extracted_value: Any                      # What we found (None if not found)
    tier: str                                 # Which tier succeeded ("dom", "browser", "vision", or "none")
    source_url: str                           # URL where value was found
    confidence: float                         # Extraction confidence (0-1)
    raw_context: Optional[str] = None         # Surrounding HTML/text for debugging
    timestamp: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_field_definition(
        cls,
        definition: FieldDefinition,
        extracted_value: Any,
        tier: str,
        source_url: str,
        confidence: float,
        raw_context: Optional[str] = None
    ) -> "FieldProvenance":
        """Create provenance from a field definition and extraction result."""
        return cls(
            field_name=definition.name,
            template_type=definition.type,
            template_required=definition.required,
            extracted_value=extracted_value,
            tier=tier,
            source_url=source_url,
            confidence=confidence,
            raw_context=raw_context
        )

    def to_dict(self) -> Dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "field_name": self.field_name,
            "template_type": self.template_type.value if self.template_type else "STRING",
            "template_required": self.template_required,
            "extracted_value": self._serialize_value(self.extracted_value),
            "tier": self.tier,
            "source_url": self.source_url,
            "confidence": self.confidence,
            "raw_context": self.raw_context,
            "timestamp": self.timestamp.isoformat(),
        }

    def _serialize_value(self, value: Any) -> Any:
        """Serialize value for JSON storage."""
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, dict)):
            return value
        # For complex objects, convert to string
        return str(value)

    @property
    def was_found(self) -> bool:
        """Check if the field was successfully extracted."""
        return self.extracted_value is not None and self.tier != "none"


@dataclass
class ExtractionProvenance:
    """
    Full provenance record for an extraction session.

    Tracks all field mappings, costs, and tier progression
    for a single URL extraction.
    """
    url: str                                  # Target URL
    intent_name: str                          # Template name (e.g., "company_website")
    fields: Dict[str, FieldProvenance] = field(default_factory=dict)
    tier_progression: List[str] = field(default_factory=list)  # Tiers executed
    total_cost: float = 0.0                   # Cumulative API costs
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def add_field(self, provenance: FieldProvenance) -> None:
        """Add or update field provenance."""
        self.fields[provenance.field_name] = provenance

    def add_tier(self, tier_name: str) -> None:
        """Record that a tier was executed."""
        if tier_name not in self.tier_progression:
            self.tier_progression.append(tier_name)

    def add_cost(self, cost: float) -> None:
        """Add to cumulative cost."""
        self.total_cost += cost

    def mark_complete(self) -> None:
        """Mark extraction as complete."""
        self.completed_at = datetime.now()

    @property
    def unmatched_fields(self) -> List[str]:
        """Get list of fields that weren't extracted."""
        return [
            name for name, prov in self.fields.items()
            if not prov.was_found
        ]

    @property
    def success_rate(self) -> float:
        """Calculate extraction success rate."""
        if not self.fields:
            return 0.0
        found = sum(1 for prov in self.fields.values() if prov.was_found)
        return found / len(self.fields)

    @property
    def final_tier(self) -> str:
        """Get the last tier that was executed."""
        return self.tier_progression[-1] if self.tier_progression else "none"

    def to_calibration_record(self) -> Dict:
        """
        Export for template calibration/fine-tuning.

        Returns a summary suitable for analyzing extraction patterns.
        """
        return {
            "url": self.url,
            "intent": self.intent_name,
            "field_results": {
                name: {
                    "found": prov.was_found,
                    "tier": prov.tier,
                    "confidence": prov.confidence,
                    "template_type": prov.template_type.value,
                    "required": prov.template_required,
                }
                for name, prov in self.fields.items()
            },
            "success_rate": self.success_rate,
            "tiers_used": self.tier_progression,
            "total_cost": self.total_cost,
            "duration_seconds": (
                (self.completed_at - self.started_at).total_seconds()
                if self.completed_at else None
            ),
        }

    def to_dict(self) -> Dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "url": self.url,
            "intent_name": self.intent_name,
            "fields": {name: prov.to_dict() for name, prov in self.fields.items()},
            "tier_progression": self.tier_progression,
            "total_cost": self.total_cost,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def to_ui_display(self) -> Dict:
        """
        Format for UI display.

        Returns a structure suitable for rendering in a dashboard.
        """
        return {
            "url": self.url,
            "template": self.intent_name,
            "success_rate": f"{self.success_rate:.0%}",
            "success_count": f"{sum(1 for p in self.fields.values() if p.was_found)}/{len(self.fields)}",
            "total_cost": f"${self.total_cost:.4f}",
            "fields": [
                {
                    "name": name,
                    "value": self._format_value(prov.extracted_value),
                    "source": prov.tier.upper() if prov.was_found else "-",
                    "confidence": f"{prov.confidence:.0%}" if prov.was_found else "-",
                    "found": prov.was_found,
                }
                for name, prov in self.fields.items()
            ],
        }

    def _format_value(self, value: Any) -> str:
        """Format a value for display."""
        if value is None:
            return "Not found"
        if isinstance(value, list):
            if len(value) == 0:
                return "[]"
            if len(value) <= 3:
                return json.dumps(value)
            return f"[{len(value)} items]"
        if isinstance(value, dict):
            return f"{{{len(value)} keys}}"
        if isinstance(value, str) and len(value) > 50:
            return value[:47] + "..."
        return str(value)
