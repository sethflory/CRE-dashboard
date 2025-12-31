"""
Tier 3: Browser Agent - MODERATE COST (~$0.01-0.05/task)

Uses Browser-Use with Claude to navigate and extract data
from JavaScript-rendered pages.
"""

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from extraction_cascade.models.session import SiteMap
from vision_extractor.intent import FieldDefinition, FieldType

# Browser-Use imports (may not be available in all environments)
try:
    from browser_use import Agent
    # Use browser-use's built-in LLM wrapper for compatibility
    try:
        from browser_use.llm import ChatAnthropic
    except ImportError:
        # Fallback to langchain if browser_use.llm not available
        from langchain_anthropic import ChatAnthropic
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False
    Agent = None
    ChatAnthropic = None


@dataclass
class BrowserExtractionResult:
    """Result of browser-based extraction for a single field."""
    value: Any
    confidence: float
    source_url: str
    task_description: str
    raw_output: Optional[str] = None


@dataclass
class BrowserAgentConfig:
    """Configuration for browser agent."""
    model: str = "claude-sonnet-4-5-20250929"
    headless: bool = True
    timeout_seconds: int = 120
    max_retries: int = 2


class BrowserAgent:
    """
    Uses Browser-Use with Claude to navigate and extract data.

    Wraps the browser-use library to provide structured extraction
    with task generation from field definitions.
    """

    # Approximate cost per task (varies by complexity)
    ESTIMATED_COST_PER_TASK = 0.03

    def __init__(self, config: Optional[BrowserAgentConfig] = None):
        """Initialize browser agent."""
        self.config = config or BrowserAgentConfig()
        self._llm = None
        self._cost_tracker = 0.0

        if not BROWSER_USE_AVAILABLE:
            print("Warning: browser-use not available. Install with: pip install browser-use langchain-anthropic")

    @property
    def llm(self):
        """Lazy-load the LLM."""
        if self._llm is None and BROWSER_USE_AVAILABLE:
            api_key = os.getenv('ANTHROPIC_API_KEY')
            self._llm = ChatAnthropic(model=self.config.model, api_key=api_key)
        return self._llm

    def reset(self):
        """Reset the agent state for a new extraction."""
        self._llm = None
        self._cost_tracker = 0.0

    @property
    def is_available(self) -> bool:
        """Check if browser agent is available."""
        return BROWSER_USE_AVAILABLE and os.getenv('ANTHROPIC_API_KEY') is not None

    def get_unavailable_reason(self) -> Optional[str]:
        """Get reason why browser agent is not available."""
        if not BROWSER_USE_AVAILABLE:
            return "browser-use not installed (pip install browser-use langchain-anthropic)"
        if not os.getenv('ANTHROPIC_API_KEY'):
            return "ANTHROPIC_API_KEY environment variable not set"
        return None

    def get_total_cost(self) -> float:
        """Get total cost incurred by this agent."""
        return self._cost_tracker

    async def extract_fields_async(
        self,
        url: str,
        missing_fields: List[FieldDefinition],
        site_map: Optional[SiteMap] = None
    ) -> Dict[str, BrowserExtractionResult]:
        """
        Use Browser-Use to navigate and extract missing fields.

        Args:
            url: Base URL to start from
            missing_fields: Fields that still need extraction
            site_map: Optional site map for navigation hints

        Returns:
            Dict mapping field names to extraction results
        """
        if not self.is_available:
            return {}

        results = {}

        # Group related fields to minimize browser tasks
        field_groups = self._group_fields(missing_fields)

        for group_name, fields in field_groups.items():
            # Build task description
            task = self._build_extraction_task(url, fields, site_map, group_name)

            try:
                # Run browser agent
                result = await self._run_agent(task)

                # Parse result into individual fields
                parsed = self._parse_result(result, fields, url, task)
                results.update(parsed)

                # Track cost
                self._cost_tracker += self.ESTIMATED_COST_PER_TASK

            except Exception as e:
                print(f"Browser agent error for {group_name}: {e}")
                continue

        return results

    def extract_fields(
        self,
        url: str,
        missing_fields: List[FieldDefinition],
        site_map: Optional[SiteMap] = None
    ) -> Dict[str, BrowserExtractionResult]:
        """
        Synchronous wrapper for extract_fields_async.
        """
        import warnings

        # Suppress cleanup warnings (harmless on Windows)
        warnings.filterwarnings('ignore', category=ResourceWarning)
        warnings.filterwarnings('ignore', category=DeprecationWarning)

        try:
            # Use asyncio.run() which handles event loop correctly for the platform
            return asyncio.run(self.extract_fields_async(url, missing_fields, site_map))
        except Exception as e:
            print(f"Browser agent extraction failed: {e}")
            return {}

    def _group_fields(self, fields: List[FieldDefinition]) -> Dict[str, List[FieldDefinition]]:
        """
        Group related fields to minimize browser tasks.

        Groups by likely page location.
        """
        groups = {
            'leadership': [],
            'services': [],
            'contact': [],
            'about': [],
        }

        field_to_group = {
            'leadership': 'leadership',
            'services': 'services',
            'specialties': 'services',
            'contact_email': 'contact',
            'contact_phone': 'contact',
            'main_email': 'contact',
            'main_phone': 'contact',
            'headquarters': 'contact',
            'office_locations': 'contact',
            'company_name': 'about',
            'about': 'about',
        }

        for field in fields:
            group = field_to_group.get(field.name, 'about')
            groups[group].append(field)

        # Remove empty groups
        return {k: v for k, v in groups.items() if v}

    def _build_extraction_task(
        self,
        url: str,
        fields: List[FieldDefinition],
        site_map: Optional[SiteMap],
        group_name: str
    ) -> str:
        """
        Build natural language task for Browser-Use agent.
        """
        # Get suggested pages from site map
        suggested_pages = []
        if site_map:
            for field in fields:
                pages = site_map.get_pages_for_field(field.name)
                suggested_pages.extend(pages[:2])
        suggested_pages = list(set(suggested_pages))[:3]

        # Build field descriptions
        field_descriptions = []
        for field in fields:
            type_hint = self._get_type_hint(field.type)
            required_hint = " (required)" if field.required else ""
            field_descriptions.append(f"- {field.name}: {type_hint}{required_hint}")

        fields_text = "\n".join(field_descriptions)

        # Build page suggestions
        pages_text = ""
        if suggested_pages:
            pages_text = f"\n\nSuggested pages to check:\n" + "\n".join(f"- {p}" for p in suggested_pages)

        # Build task based on group
        task_templates = {
            'leadership': f"""Navigate to {url} and find the leadership/team page.
Extract the following information about team members:
{fields_text}

For each person found, extract their name, title, email (if available), and LinkedIn URL (if available).
Return the data as JSON.{pages_text}""",

            'services': f"""Navigate to {url} and find the services page.
Extract the following information:
{fields_text}

Look for lists of services offered and asset classes/property types they specialize in.
Return the data as JSON.{pages_text}""",

            'contact': f"""Navigate to {url} and find the contact page.
Extract the following information:
{fields_text}

Look for phone numbers, email addresses, and physical addresses.
Return the data as JSON.{pages_text}""",

            'about': f"""Navigate to {url} and extract company information.
Extract the following:
{fields_text}

Look in the about page, homepage, or footer for this information.
Return the data as JSON.{pages_text}""",
        }

        return task_templates.get(group_name, task_templates['about'])

    def _get_type_hint(self, field_type: FieldType) -> str:
        """Get a human-readable type hint for prompts."""
        hints = {
            FieldType.STRING: "text value",
            FieldType.LIST: "list of items",
            FieldType.LIST_OF_OBJECTS: "list of objects with name, title, email, etc.",
            FieldType.NUMBER: "numeric value",
            FieldType.BOOLEAN: "true/false",
        }
        return hints.get(field_type, "value")

    async def _run_agent(self, task: str) -> str:
        """Run the browser-use agent with a task."""
        if not self.is_available:
            raise RuntimeError("Browser-Use not available")

        agent = Agent(
            task=task,
            llm=self.llm,
        )

        # Run with timeout
        try:
            result = await asyncio.wait_for(
                agent.run(),
                timeout=self.config.timeout_seconds
            )
            return result.final_result() if hasattr(result, 'final_result') else str(result)
        except asyncio.TimeoutError:
            raise RuntimeError(f"Agent timed out after {self.config.timeout_seconds}s")

    def _parse_result(
        self,
        result: str,
        fields: List[FieldDefinition],
        url: str,
        task: str
    ) -> Dict[str, BrowserExtractionResult]:
        """
        Parse agent result into field values.
        """
        parsed = {}

        # Try to parse as JSON
        try:
            # Find JSON in the result
            json_match = self._extract_json(result)
            if json_match:
                data = json.loads(json_match)
            else:
                data = {}
        except json.JSONDecodeError:
            data = {}

        for field in fields:
            value = None
            confidence = 0.0

            # Look for field in parsed data
            if field.name in data:
                value = data[field.name]
                confidence = 0.8
            elif field.name.replace('_', ' ') in data:
                value = data[field.name.replace('_', ' ')]
                confidence = 0.8

            # Try common variations
            variations = [
                field.name,
                field.name.replace('_', ''),
                field.name.replace('_', ' '),
                field.name.title().replace('_', ''),
            ]
            for var in variations:
                if var in data:
                    value = data[var]
                    confidence = 0.75
                    break

            if value is not None:
                parsed[field.name] = BrowserExtractionResult(
                    value=value,
                    confidence=confidence,
                    source_url=url,
                    task_description=task[:200],
                    raw_output=result[:500] if result else None
                )

        return parsed

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON from text that may contain other content."""
        # Try to find JSON object
        import re

        # Look for JSON object
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            return match.group()

        # Look for JSON array
        match = re.search(r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]', text, re.DOTALL)
        if match:
            return match.group()

        return None


# Convenience function for synchronous usage
def run_browser_extraction(
    url: str,
    fields: List[FieldDefinition],
    site_map: Optional[SiteMap] = None,
    config: Optional[BrowserAgentConfig] = None
) -> Dict[str, BrowserExtractionResult]:
    """
    Run browser extraction synchronously.

    Convenience wrapper for BrowserAgent.
    """
    agent = BrowserAgent(config)
    return agent.extract_fields(url, fields, site_map)
