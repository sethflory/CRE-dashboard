"""
ExtractionIntent - Schema definitions for vision extraction templates.

Defines the structure for what to extract from webpages using Claude vision.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any


class FieldType(Enum):
    """Supported field types for extraction."""
    STRING = "string"
    LIST = "list"
    LIST_OF_OBJECTS = "list_of_objects"
    NUMBER = "number"
    BOOLEAN = "boolean"


@dataclass
class FieldDefinition:
    """Definition of a single field to extract."""
    name: str                           # Field name, e.g., "current_title"
    type: FieldType                     # Field type
    description: str = ""               # Description for Claude prompt
    screenshot_section: str = "header"  # Which screenshot captures this field
    required: bool = True               # Whether field is required
    nested_fields: List['FieldDefinition'] = field(default_factory=list)  # For LIST_OF_OBJECTS

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "screenshot_section": self.screenshot_section,
            "required": self.required,
        }
        if self.nested_fields:
            result["nested_fields"] = [f.to_dict() for f in self.nested_fields]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FieldDefinition':
        """Create from dictionary."""
        nested = []
        if "nested_fields" in data:
            nested = [cls.from_dict(f) for f in data["nested_fields"]]
        return cls(
            name=data["name"],
            type=FieldType(data["type"]),
            description=data.get("description", ""),
            screenshot_section=data.get("screenshot_section", "header"),
            required=data.get("required", True),
            nested_fields=nested,
        )


@dataclass
class ScrollPosition:
    """Defines a scroll position for screenshot capture."""
    name: str           # Section name, e.g., "header", "experience"
    y_offset: int       # Scroll offset in pixels
    wait_ms: int = 500  # Wait time after scrolling

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "y_offset": self.y_offset,
            "wait_ms": self.wait_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScrollPosition':
        return cls(
            name=data["name"],
            y_offset=data["y_offset"],
            wait_ms=data.get("wait_ms", 500),
        )


@dataclass
class AttributeLinking:
    """Configuration for linking extracted data to company attributes."""
    match_services: bool = False      # Link to company services
    match_specialties: bool = False   # Link to company specialties
    source_fields: List[str] = field(default_factory=list)  # Fields to analyze

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_services": self.match_services,
            "match_specialties": self.match_specialties,
            "source": ",".join(self.source_fields),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AttributeLinking':
        source = data.get("source", "")
        source_fields = [s.strip() for s in source.split(",")] if source else []
        return cls(
            match_services=data.get("match_services", False),
            match_specialties=data.get("match_specialties", False),
            source_fields=source_fields,
        )


@dataclass
class ExtractionIntent:
    """
    Complete extraction intent/template.

    Defines what to extract from a webpage, including:
    - Target URL patterns
    - Scroll positions for screenshots
    - Fields to extract
    - Validation thresholds
    """
    name: str                                   # Template name
    description: str                            # Natural language description
    target_url_pattern: str                     # Regex for valid URLs
    scroll_positions: List[ScrollPosition]      # Screenshot capture positions
    fields: List[FieldDefinition]               # Fields to extract
    batch_extraction_threshold: int = 2         # Switch to batch if >N issues
    calibrated_from: List[str] = field(default_factory=list)  # URLs used for calibration
    confidence_score: float = 0.0               # Calibration confidence
    attribute_linking: Optional[AttributeLinking] = None  # For contact→company linking

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "description": self.description,
            "target_url_pattern": self.target_url_pattern,
            "scroll_positions": [sp.to_dict() for sp in self.scroll_positions],
            "fields": [f.to_dict() for f in self.fields],
            "batch_extraction_threshold": self.batch_extraction_threshold,
            "calibrated_from": self.calibrated_from,
            "confidence_score": self.confidence_score,
        }
        if self.attribute_linking:
            result["attribute_linking"] = self.attribute_linking.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExtractionIntent':
        """Create from dictionary."""
        scroll_positions = [ScrollPosition.from_dict(sp) for sp in data.get("scroll_positions", [])]
        fields = [FieldDefinition.from_dict(f) for f in data.get("fields", [])]

        attr_linking = None
        if "attribute_linking" in data:
            attr_linking = AttributeLinking.from_dict(data["attribute_linking"])

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            target_url_pattern=data.get("target_url_pattern", ""),
            scroll_positions=scroll_positions,
            fields=fields,
            batch_extraction_threshold=data.get("batch_extraction_threshold", 2),
            calibrated_from=data.get("calibrated_from", []),
            confidence_score=data.get("confidence_score", 0.0),
            attribute_linking=attr_linking,
        )

    def get_field(self, name: str) -> Optional[FieldDefinition]:
        """Get a field definition by name."""
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def get_fields_for_section(self, section: str) -> List[FieldDefinition]:
        """Get all fields that should be extracted from a given screenshot section."""
        return [f for f in self.fields if f.screenshot_section == section]

    def get_section_names(self) -> List[str]:
        """Get unique section names from scroll positions."""
        return [sp.name for sp in self.scroll_positions]


@dataclass
class ExtractionResult:
    """Result of an extraction operation."""
    url: str
    data: Dict[str, Any]
    screenshots: Dict[str, bytes] = field(default_factory=dict)
    validation_result: Optional[Dict] = None
    confidence: float = 0.0
    errors: List[str] = field(default_factory=list)
    extraction_mode: str = "dom"  # "dom", "vision", "hybrid"

    @property
    def success(self) -> bool:
        """Whether extraction was successful."""
        return len(self.errors) == 0 and self.confidence > 0.5


@dataclass
class ValidationResult:
    """Result of validation against screenshots."""
    flagged_fields: List[Dict[str, str]]  # [{"field": ..., "issue": ..., "details": ...}]
    confidence: float
    error: Optional[str] = None

    @property
    def issues_count(self) -> int:
        return len(self.flagged_fields)

    @property
    def needs_batch_extraction(self) -> bool:
        """Check if too many issues warrant full batch extraction."""
        return self.issues_count > 2
