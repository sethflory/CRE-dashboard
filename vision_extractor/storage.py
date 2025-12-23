"""
Template storage and persistence.

Handles saving/loading extraction templates to/from JSON files.
"""

import json
import os
from typing import Optional, List, Dict
from pathlib import Path

from .intent import ExtractionIntent


class TemplateStorage:
    """
    Persistent storage for extraction templates.

    Templates are stored as JSON files in a configurable directory.
    """

    DEFAULT_DIR = "config/extraction_templates"

    def __init__(self, template_dir: Optional[str] = None):
        """
        Initialize storage.

        Args:
            template_dir: Directory for template files. Defaults to config/extraction_templates/
        """
        self.template_dir = Path(template_dir or self.DEFAULT_DIR)
        self._ensure_dir()

    def _ensure_dir(self):
        """Create template directory if it doesn't exist."""
        self.template_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, name: str) -> Path:
        """Get file path for a template name."""
        # Normalize name to filename
        filename = name.replace(" ", "_").lower()
        if not filename.endswith(".json"):
            filename += ".json"
        return self.template_dir / filename

    def save(self, intent: ExtractionIntent) -> str:
        """
        Save an extraction intent to disk.

        Args:
            intent: ExtractionIntent to save

        Returns:
            Path to saved file
        """
        path = self._get_path(intent.name)
        data = intent.to_dict()

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        return str(path)

    def load(self, name: str) -> Optional[ExtractionIntent]:
        """
        Load an extraction intent by name.

        Args:
            name: Template name or filename

        Returns:
            ExtractionIntent or None if not found
        """
        path = self._get_path(name)

        if not path.exists():
            # Try without normalization
            alt_path = self.template_dir / name
            if alt_path.exists():
                path = alt_path
            elif (alt_path.with_suffix('.json')).exists():
                path = alt_path.with_suffix('.json')
            else:
                return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ExtractionIntent.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error loading template {name}: {e}")
            return None

    def delete(self, name: str) -> bool:
        """
        Delete a template.

        Args:
            name: Template name

        Returns:
            True if deleted, False if not found
        """
        path = self._get_path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_templates(self) -> List[str]:
        """
        List all available template names.

        Returns:
            List of template names (without .json extension)
        """
        templates = []
        for path in self.template_dir.glob("*.json"):
            templates.append(path.stem)
        return sorted(templates)

    def exists(self, name: str) -> bool:
        """Check if a template exists."""
        return self._get_path(name).exists()

    def get_template_info(self, name: str) -> Optional[Dict]:
        """
        Get basic info about a template without loading fully.

        Returns:
            Dict with name, description, fields count, or None
        """
        intent = self.load(name)
        if not intent:
            return None

        return {
            "name": intent.name,
            "description": intent.description,
            "fields_count": len(intent.fields),
            "scroll_positions": len(intent.scroll_positions),
            "confidence_score": intent.confidence_score,
            "calibrated_from": len(intent.calibrated_from),
        }


def get_builtin_template(name: str) -> Optional[ExtractionIntent]:
    """
    Get a built-in template by name.

    Built-in templates are defined in code, not loaded from files.

    Args:
        name: Template name ("linkedin_profile" or "company_website")

    Returns:
        ExtractionIntent or None
    """
    from .intent import FieldDefinition, FieldType, ScrollPosition, AttributeLinking

    if name == "linkedin_profile":
        return ExtractionIntent(
            name="linkedin_profile",
            description="Extract contact profile and link to company attributes",
            target_url_pattern=r"linkedin\.com/in/",
            scroll_positions=[
                ScrollPosition(name="header", y_offset=0, wait_ms=500),
                ScrollPosition(name="experience", y_offset=1500, wait_ms=500),
                ScrollPosition(name="education_groups", y_offset=3000, wait_ms=500),
            ],
            fields=[
                FieldDefinition(name="name", type=FieldType.STRING, screenshot_section="header"),
                FieldDefinition(name="headline", type=FieldType.STRING, screenshot_section="header"),
                FieldDefinition(name="location", type=FieldType.STRING, screenshot_section="header"),
                FieldDefinition(name="current_company", type=FieldType.STRING, screenshot_section="header"),
                FieldDefinition(name="current_title", type=FieldType.STRING, screenshot_section="header"),
                FieldDefinition(
                    name="work_history",
                    type=FieldType.LIST_OF_OBJECTS,
                    screenshot_section="experience",
                    nested_fields=[
                        FieldDefinition(name="company", type=FieldType.STRING),
                        FieldDefinition(name="title", type=FieldType.STRING),
                        FieldDefinition(name="years", type=FieldType.STRING, required=False),
                    ]
                ),
                FieldDefinition(
                    name="education",
                    type=FieldType.LIST_OF_OBJECTS,
                    screenshot_section="education_groups",
                    nested_fields=[
                        FieldDefinition(name="school", type=FieldType.STRING),
                        FieldDefinition(name="degree", type=FieldType.STRING, required=False),
                        FieldDefinition(name="years", type=FieldType.STRING, required=False),
                    ]
                ),
                FieldDefinition(
                    name="groups",
                    type=FieldType.LIST,
                    screenshot_section="education_groups",
                    description="LinkedIn groups/associations"
                ),
            ],
            batch_extraction_threshold=2,
            attribute_linking=AttributeLinking(
                match_services=True,
                match_specialties=True,
                source_fields=["headline", "current_title", "work_history"]
            )
        )

    elif name == "company_website":
        return ExtractionIntent(
            name="company_website",
            description="Extract company attributes from CRE firm websites",
            target_url_pattern=r".*/(about|team|services|company)",
            scroll_positions=[
                ScrollPosition(name="header", y_offset=0, wait_ms=500),
                ScrollPosition(name="services", y_offset=800, wait_ms=500),
                ScrollPosition(name="team", y_offset=1500, wait_ms=500),
            ],
            fields=[
                FieldDefinition(
                    name="company_name",
                    type=FieldType.STRING,
                    screenshot_section="header"
                ),
                FieldDefinition(
                    name="headquarters",
                    type=FieldType.STRING,
                    screenshot_section="header"
                ),
                FieldDefinition(
                    name="services",
                    type=FieldType.LIST,
                    screenshot_section="services",
                    description="Lines of business (Brokerage, Capital Markets, Property Management, etc.)"
                ),
                FieldDefinition(
                    name="specialties",
                    type=FieldType.LIST,
                    screenshot_section="services",
                    description="Asset classes (Office, Industrial, Retail, Multifamily, Healthcare, etc.)"
                ),
                FieldDefinition(
                    name="products",
                    type=FieldType.LIST,
                    screenshot_section="services",
                    description="Product offerings or platforms if applicable",
                    required=False
                ),
                FieldDefinition(
                    name="leadership",
                    type=FieldType.LIST_OF_OBJECTS,
                    screenshot_section="team",
                    nested_fields=[
                        FieldDefinition(name="name", type=FieldType.STRING),
                        FieldDefinition(name="title", type=FieldType.STRING),
                        FieldDefinition(name="linkedin_url", type=FieldType.STRING, required=False),
                    ]
                ),
            ],
            batch_extraction_threshold=2
        )

    return None
