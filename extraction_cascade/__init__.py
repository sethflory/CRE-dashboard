"""
Extraction Cascade - Cost-optimized web data extraction.

A tiered extraction system that processes URLs through progressively
more expensive methods, with user approval for costly operations.

Tiers:
    1. Site Mapping (FREE) - sitemap.xml, robots.txt, link discovery
    2. DOM Extraction (FREE) - BeautifulSoup parsing, CSS selectors
    3. Browser Agent (MODERATE) - Browser-Use with Claude for navigation
    4. Vision Queue (EXPENSIVE) - Claude Vision API with user approval
"""

from .orchestrator import CascadeOrchestrator
from .models.session import ExtractionSession
from .models.field_status import FieldStatus, FieldTracker
from .models.provenance import FieldProvenance, ExtractionProvenance

__all__ = [
    "CascadeOrchestrator",
    "ExtractionSession",
    "FieldStatus",
    "FieldTracker",
    "FieldProvenance",
    "ExtractionProvenance",
]

__version__ = "0.1.0"
