"""
Template builder - Create extraction templates from natural language.

Uses Claude to convert natural language descriptions into ExtractionIntent schemas.
"""

import json
import os
from typing import Optional, List

from .intent import ExtractionIntent, FieldDefinition, FieldType, ScrollPosition


class TemplateBuilder:
    """
    Build ExtractionIntent templates from natural language descriptions.

    Uses Claude to interpret extraction requirements and generate
    structured field definitions.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-haiku-20241022"):
        """
        Initialize builder.

        Args:
            api_key: Anthropic API key (or use ANTHROPIC_API_KEY env var)
            model: Claude model to use
        """
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        self.model = model
        self._client = None

    @property
    def client(self):
        """Lazy-load Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("anthropic package required. Install with: pip install anthropic")
        return self._client

    def from_natural_language(
        self,
        description: str,
        template_name: str = "custom",
        url_pattern: str = "",
        example_url: Optional[str] = None
    ) -> ExtractionIntent:
        """
        Create ExtractionIntent from natural language description.

        Args:
            description: Natural language description of what to extract
                e.g., "Extract person's name, job title, company, work history with dates"
            template_name: Name for the template
            url_pattern: Regex pattern for valid URLs
            example_url: Optional example URL for context

        Returns:
            ExtractionIntent with generated fields
        """
        prompt = self._build_generation_prompt(description, template_name, url_pattern, example_url)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            response_text = response.content[0].text.strip()
            return self._parse_intent_response(response_text, template_name, description, url_pattern)

        except Exception as e:
            print(f"[TemplateBuilder] Error: {e}")
            # Return minimal intent on error
            return ExtractionIntent(
                name=template_name,
                description=description,
                target_url_pattern=url_pattern,
                scroll_positions=[ScrollPosition(name="header", y_offset=0)],
                fields=[]
            )

    def refine_with_feedback(
        self,
        intent: ExtractionIntent,
        feedback: str
    ) -> ExtractionIntent:
        """
        Refine an existing intent based on user feedback.

        Args:
            intent: Current ExtractionIntent
            feedback: User feedback, e.g., "Add email field", "Scroll further for groups"

        Returns:
            Updated ExtractionIntent
        """
        prompt = self._build_refinement_prompt(intent, feedback)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            response_text = response.content[0].text.strip()
            return self._parse_intent_response(
                response_text,
                intent.name,
                intent.description,
                intent.target_url_pattern
            )

        except Exception as e:
            print(f"[TemplateBuilder] Refinement error: {e}")
            return intent

    def suggest_scroll_positions(
        self,
        description: str,
        page_type: str = "profile"
    ) -> List[ScrollPosition]:
        """
        Suggest scroll positions based on extraction needs.

        Args:
            description: What needs to be extracted
            page_type: Type of page ("profile", "company", "list")

        Returns:
            List of suggested ScrollPositions
        """
        # Common patterns
        profiles = [
            ScrollPosition(name="header", y_offset=0, wait_ms=500),
            ScrollPosition(name="experience", y_offset=1500, wait_ms=500),
            ScrollPosition(name="education_groups", y_offset=3000, wait_ms=500),
        ]

        company = [
            ScrollPosition(name="header", y_offset=0, wait_ms=500),
            ScrollPosition(name="services", y_offset=800, wait_ms=500),
            ScrollPosition(name="team", y_offset=1500, wait_ms=500),
        ]

        list_page = [
            ScrollPosition(name="top", y_offset=0, wait_ms=500),
            ScrollPosition(name="middle", y_offset=1000, wait_ms=500),
            ScrollPosition(name="bottom", y_offset=2000, wait_ms=500),
        ]

        patterns = {
            "profile": profiles,
            "linkedin": profiles,
            "company": company,
            "website": company,
            "list": list_page,
        }

        return patterns.get(page_type, profiles)

    def _build_generation_prompt(
        self,
        description: str,
        template_name: str,
        url_pattern: str,
        example_url: Optional[str]
    ) -> str:
        """Build prompt for template generation."""
        url_context = f"\nExample URL: {example_url}" if example_url else ""

        return f"""Generate an extraction template based on this description:

DESCRIPTION: {description}
TEMPLATE NAME: {template_name}
URL PATTERN: {url_pattern or "not specified"}{url_context}

Create a JSON object with this structure:
{{
  "scroll_positions": [
    {{"name": "section_name", "y_offset": 0, "wait_ms": 500}},
    ...
  ],
  "fields": [
    {{
      "name": "field_name",
      "type": "string|list|list_of_objects|number|boolean",
      "description": "what this field captures",
      "screenshot_section": "which scroll position captures this",
      "required": true,
      "nested_fields": []  // for list_of_objects only
    }},
    ...
  ]
}}

Guidelines:
1. Identify all fields mentioned in the description
2. Use appropriate types:
   - "string" for single values (name, title, company)
   - "list" for simple lists (skills, groups, services)
   - "list_of_objects" for complex lists (work history, education, leadership)
3. Assign each field to a screenshot_section based on typical page layout
4. Include nested_fields for list_of_objects types
5. Suggest 2-4 scroll positions to capture all content

Return ONLY valid JSON, no explanation."""

    def _build_refinement_prompt(self, intent: ExtractionIntent, feedback: str) -> str:
        """Build prompt for refining an intent."""
        current = json.dumps(intent.to_dict(), indent=2)

        return f"""Refine this extraction template based on user feedback.

CURRENT TEMPLATE:
{current}

USER FEEDBACK: {feedback}

Apply the feedback to modify the template. Common changes:
- Add/remove fields
- Change field types
- Adjust scroll positions
- Update descriptions

Return the UPDATED template as JSON with the same structure.
Return ONLY valid JSON, no explanation."""

    def _parse_intent_response(
        self,
        response_text: str,
        name: str,
        description: str,
        url_pattern: str
    ) -> ExtractionIntent:
        """Parse Claude response into ExtractionIntent."""
        # Handle markdown code blocks
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            if lines[-1].startswith('```'):
                response_text = '\n'.join(lines[1:-1])
            else:
                response_text = '\n'.join(lines[1:])

        data = json.loads(response_text)

        # Build scroll positions
        scroll_positions = []
        for sp in data.get("scroll_positions", []):
            scroll_positions.append(ScrollPosition(
                name=sp["name"],
                y_offset=sp.get("y_offset", 0),
                wait_ms=sp.get("wait_ms", 500)
            ))

        # If no scroll positions, add defaults
        if not scroll_positions:
            scroll_positions = [
                ScrollPosition(name="header", y_offset=0),
                ScrollPosition(name="content", y_offset=1000),
            ]

        # Build fields
        fields = []
        for f in data.get("fields", []):
            field = self._parse_field(f)
            if field:
                fields.append(field)

        return ExtractionIntent(
            name=name,
            description=description,
            target_url_pattern=url_pattern,
            scroll_positions=scroll_positions,
            fields=fields,
            batch_extraction_threshold=data.get("batch_extraction_threshold", 2)
        )

    def _parse_field(self, data: dict) -> Optional[FieldDefinition]:
        """Parse a field definition from dict."""
        try:
            field_type = FieldType(data.get("type", "string"))

            nested = []
            if field_type == FieldType.LIST_OF_OBJECTS and "nested_fields" in data:
                for nf in data["nested_fields"]:
                    nested_field = self._parse_field(nf)
                    if nested_field:
                        nested.append(nested_field)

            return FieldDefinition(
                name=data["name"],
                type=field_type,
                description=data.get("description", ""),
                screenshot_section=data.get("screenshot_section", "header"),
                required=data.get("required", True),
                nested_fields=nested
            )
        except (KeyError, ValueError) as e:
            print(f"[TemplateBuilder] Error parsing field: {e}")
            return None


def quick_template(
    name: str,
    description: str,
    fields: List[str],
    url_pattern: str = ""
) -> ExtractionIntent:
    """
    Quick helper to create a simple template without Claude.

    Args:
        name: Template name
        description: What this extracts
        fields: List of field names (all treated as strings)
        url_pattern: Optional URL pattern

    Returns:
        Basic ExtractionIntent
    """
    field_defs = [
        FieldDefinition(name=f, type=FieldType.STRING)
        for f in fields
    ]

    return ExtractionIntent(
        name=name,
        description=description,
        target_url_pattern=url_pattern,
        scroll_positions=[
            ScrollPosition(name="header", y_offset=0),
            ScrollPosition(name="content", y_offset=1000),
        ],
        fields=field_defs
    )
