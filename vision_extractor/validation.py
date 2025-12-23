"""
Validation and correction using Claude vision.

Validates extracted data against screenshots and corrects mismatches.
"""

import json
import base64
from typing import Dict, Any, Optional, List

from .intent import ExtractionIntent, FieldDefinition, FieldType, ValidationResult


class ClaudeVisionValidator:
    """
    Validates and corrects extracted data using Claude vision API.

    Uses a hybrid approach:
    1. Validate DOM-extracted data against screenshots
    2. Correct individual fields that have issues
    3. Fall back to batch extraction if too many issues
    """

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        self.api_key = api_key
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

    def validate(
        self,
        data: Dict[str, Any],
        screenshots: Dict[str, bytes],
        intent: ExtractionIntent
    ) -> ValidationResult:
        """
        Validate extracted data against screenshots.

        Args:
            data: Extracted data dictionary
            screenshots: Dict of section_name -> screenshot bytes
            intent: ExtractionIntent with field definitions

        Returns:
            ValidationResult with flagged fields and confidence
        """
        if not screenshots:
            return ValidationResult(flagged_fields=[], confidence=0.0, error="No screenshots provided")

        try:
            # Encode screenshots as base64
            images = self._encode_screenshots(screenshots)

            # Build validation prompt
            prompt = self._build_validation_prompt(data, intent)

            # Call Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": images + [{"type": "text", "text": prompt}]
                }]
            )

            response_text = response.content[0].text.strip()

            # Parse response
            result = self._parse_validation_response(response_text)
            return ValidationResult(
                flagged_fields=result.get("flagged_fields", []),
                confidence=result.get("confidence", 0.0)
            )

        except json.JSONDecodeError as e:
            return ValidationResult(flagged_fields=[], confidence=0.0, error=f"Parse error: {e}")
        except Exception as e:
            return ValidationResult(flagged_fields=[], confidence=0.0, error=str(e))

    def correct_field(
        self,
        field: FieldDefinition,
        screenshot: bytes,
        current_value: Any
    ) -> Any:
        """
        Correct a specific field using Claude vision.

        Args:
            field: Field definition
            screenshot: Relevant screenshot bytes
            current_value: Current extracted value

        Returns:
            Corrected value (same type as field.type)
        """
        prompt = self._build_correction_prompt(field, current_value)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.standard_b64encode(screenshot).decode('utf-8')
                            }
                        },
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            response_text = response.content[0].text.strip()
            return self._parse_corrected_value(response_text, field.type)

        except Exception as e:
            print(f"[Correction] Error correcting {field.name}: {e}")
            return current_value

    def extract_all(
        self,
        screenshots: Dict[str, bytes],
        intent: ExtractionIntent
    ) -> Dict[str, Any]:
        """
        Extract all fields directly from screenshots (batch mode).

        Used when validation finds too many issues with DOM extraction.

        Args:
            screenshots: Dict of section_name -> screenshot bytes
            intent: ExtractionIntent with field definitions

        Returns:
            Extracted data dictionary
        """
        # Encode screenshots that we need
        section_names = intent.get_section_names()
        images = []
        for name in section_names:
            if name in screenshots:
                images.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(screenshots[name]).decode()
                    }
                })

        # Build extraction prompt
        prompt = self._build_batch_extraction_prompt(intent)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": images + [{"type": "text", "text": prompt}]
                }]
            )

            response_text = response.content[0].text.strip()
            return self._parse_extraction_response(response_text, intent)

        except Exception as e:
            print(f"[Batch Extract] Error: {e}")
            return {}

    def _encode_screenshots(self, screenshots: Dict[str, bytes]) -> List[Dict]:
        """Encode screenshots as base64 for API."""
        images = []
        for name, img_data in screenshots.items():
            images.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(img_data).decode('utf-8')
                }
            })
        return images

    def _build_validation_prompt(self, data: Dict[str, Any], intent: ExtractionIntent) -> str:
        """Build prompt for validation."""
        # Format data for display
        data_str = json.dumps(data, indent=2, default=str)

        return f"""Compare this parsed {intent.name} data against the screenshots provided.

PARSED DATA:
{data_str}

FIELDS TO VALIDATE:
{', '.join(f.name for f in intent.fields)}

Review the screenshots and identify fields that appear INCORRECT or MISSING.
Common issues to check:
- Missing entries visible in screenshot
- Incorrect parsing
- Empty fields that have visible data

Return JSON with this exact format:
{{
  "flagged_fields": [
    {{"field": "field_name", "issue": "missing_entry|incorrect|empty", "details": "explanation"}}
  ],
  "confidence": 0.85
}}

If all data looks correct, return: {{"flagged_fields": [], "confidence": 0.95}}

Return ONLY valid JSON, no other text."""

    def _build_correction_prompt(self, field: FieldDefinition, current_value: Any) -> str:
        """Build prompt for correcting a specific field."""
        base_prompts = {
            "education": """Extract ALL education entries visible in this screenshot.
Return a JSON array where each entry has: school, degree (if visible), years (if visible).
Example: [{"school": "Ohio State University", "degree": "BS Finance", "years": "2010-2014"}]""",

            "work_history": """Extract ALL work history entries visible in this screenshot.
Return a JSON array where each entry has: company, title, years (if visible).
Example: [{"company": "CBRE", "title": "Senior VP", "years": "2020-Present"}]""",

            "groups": """List ALL groups/associations visible in the screenshot.
Return a JSON array of group names.
Example: ["NAIOP", "ULI", "CCIM Institute"]""",

            "services": """List ALL services/lines of business visible.
Return a JSON array of service names.
Example: ["Capital Markets", "Brokerage", "Property Management"]""",

            "specialties": """List ALL specialties/asset classes visible.
Return a JSON array of specialty names.
Example: ["Office", "Industrial", "Retail"]""",

            "leadership": """Extract ALL leadership/team members visible.
Return a JSON array where each entry has: name, title, linkedin_url (if visible).
Example: [{"name": "John Smith", "title": "CEO", "linkedin_url": ""}]""",
        }

        # Use field-specific prompt if available, otherwise generic
        if field.name in base_prompts:
            prompt = base_prompts[field.name]
        elif field.description:
            prompt = f"Extract: {field.description}"
        else:
            prompt = f"Extract the {field.name} from this screenshot."

        # Add type-specific formatting instructions
        if field.type == FieldType.STRING:
            prompt += "\nReturn just the value as a string."
        elif field.type in (FieldType.LIST, FieldType.LIST_OF_OBJECTS):
            prompt += "\nReturn as a JSON array."

        prompt += f"\n\nCurrent parsed value: {json.dumps(current_value)}\n"
        prompt += "\nReturn the CORRECTED value. If current value appears correct, return it unchanged."
        prompt += "\nReturn ONLY the value (JSON for arrays/objects, plain string for text fields), no explanation."

        return prompt

    def _build_batch_extraction_prompt(self, intent: ExtractionIntent) -> str:
        """Build prompt for batch extraction of all fields."""
        fields_desc = []
        for f in intent.fields:
            type_hint = f.type.value
            if f.nested_fields:
                nested = [nf.name for nf in f.nested_fields]
                type_hint = f"array of objects with: {', '.join(nested)}"
            fields_desc.append(f"- {f.name} ({type_hint}): {f.description}")

        return f"""Extract all information from these {intent.name} screenshots.

FIELDS TO EXTRACT:
{chr(10).join(fields_desc)}

Return a JSON object with all fields:
{{
{chr(10).join(f'  "{f.name}": ...' for f in intent.fields)}
}}

Guidelines:
- Only include data that is clearly visible in the screenshots
- Use empty string "" for missing string fields
- Use empty array [] for missing list fields
- For nested objects, include all visible subfields

Return ONLY valid JSON, no other text."""

    def _parse_validation_response(self, response_text: str) -> Dict:
        """Parse validation response from Claude."""
        # Handle markdown code blocks
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            if lines[-1].startswith('```'):
                response_text = '\n'.join(lines[1:-1])
            else:
                response_text = '\n'.join(lines[1:])

        return json.loads(response_text)

    def _parse_corrected_value(self, response_text: str, field_type: FieldType) -> Any:
        """Parse corrected value from Claude response."""
        # Handle markdown code blocks
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            if lines[-1].startswith('```'):
                response_text = '\n'.join(lines[1:-1])
            else:
                response_text = '\n'.join(lines[1:])

        response_text = response_text.strip()

        # Parse based on field type
        if field_type == FieldType.STRING:
            # Remove quotes if present
            if response_text.startswith('"') and response_text.endswith('"'):
                return response_text[1:-1]
            return response_text
        elif field_type in (FieldType.LIST, FieldType.LIST_OF_OBJECTS):
            return json.loads(response_text)
        elif field_type == FieldType.NUMBER:
            return float(response_text) if '.' in response_text else int(response_text)
        elif field_type == FieldType.BOOLEAN:
            return response_text.lower() in ('true', 'yes', '1')
        else:
            try:
                return json.loads(response_text)
            except:
                return response_text

    def _parse_extraction_response(self, response_text: str, intent: ExtractionIntent) -> Dict[str, Any]:
        """Parse batch extraction response."""
        # Handle markdown code blocks
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            if lines[-1].startswith('```'):
                response_text = '\n'.join(lines[1:-1])
            else:
                response_text = '\n'.join(lines[1:])

        return json.loads(response_text)
