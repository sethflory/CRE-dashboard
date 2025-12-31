"""
Tests for extraction_cascade package.
Run with: pytest test_extraction_cascade.py -v
"""

import json
import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch, Mock

import pytest

from extraction_cascade.models.field_status import FieldStatus, FieldTracker, FieldResult
from extraction_cascade.models.provenance import FieldProvenance, ExtractionProvenance
from extraction_cascade.models.session import ExtractionSession, SiteMap
from extraction_cascade.tiers.site_mapper import SiteMapper, SiteMapperConfig
from extraction_cascade.tiers.dom_extractor import DOMExtractor, DOMExtractionResult
from extraction_cascade.approval.callback import (
    ApprovalCallback, ApprovalRequest, ApprovalResponse,
    ApprovalState, ScreenshotCandidate, AutoApprovalCallback
)
from extraction_cascade.storage.provenance_store import ProvenanceStore
from vision_extractor.intent import ExtractionIntent, FieldDefinition, FieldType


# --- Fixtures ---

@pytest.fixture
def sample_field_definitions():
    """Create sample field definitions for testing."""
    return [
        FieldDefinition(name="company_name", type=FieldType.STRING, required=True),
        FieldDefinition(name="services", type=FieldType.LIST, required=False),
        FieldDefinition(name="leadership", type=FieldType.LIST_OF_OBJECTS, required=False),
        FieldDefinition(name="contact_email", type=FieldType.STRING, required=True),
    ]


@pytest.fixture
def sample_intent(sample_field_definitions):
    """Create sample extraction intent."""
    from vision_extractor.intent import ScrollPosition
    return ExtractionIntent(
        name="test_company",
        description="Test company extraction template",
        fields=sample_field_definitions,
        target_url_pattern=r".*\.com",
        scroll_positions=[
            ScrollPosition(name="header", y_offset=0),
            ScrollPosition(name="body", y_offset=800),
        ]
    )


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# --- FieldTracker Tests ---

class TestFieldTracker:
    """Tests for FieldTracker."""

    def test_initialization(self, sample_field_definitions):
        tracker = FieldTracker(sample_field_definitions)

        assert len(tracker.status) == 4
        assert all(s == FieldStatus.MISSING for s in tracker.status.values())

    def test_update_field_high_confidence(self, sample_field_definitions):
        tracker = FieldTracker(sample_field_definitions)

        tracker.update_field(
            field_name="company_name",
            value="ACME Corp",
            confidence=0.9,
            source_tier="dom",
            source_url="https://acme.com"
        )

        assert tracker.status["company_name"] == FieldStatus.EXTRACTED
        assert tracker.results["company_name"].value == "ACME Corp"
        assert tracker.results["company_name"].confidence == 0.9

    def test_update_field_low_confidence(self, sample_field_definitions):
        tracker = FieldTracker(sample_field_definitions)

        tracker.update_field(
            field_name="company_name",
            value="Maybe ACME",
            confidence=0.6,
            source_tier="dom"
        )

        assert tracker.status["company_name"] == FieldStatus.LOW_CONFIDENCE

    def test_update_field_below_threshold(self, sample_field_definitions):
        tracker = FieldTracker(sample_field_definitions)

        tracker.update_field(
            field_name="company_name",
            value="Unknown",
            confidence=0.3,
            source_tier="dom"
        )

        assert tracker.status["company_name"] == FieldStatus.FAILED

    def test_get_missing_fields(self, sample_field_definitions):
        tracker = FieldTracker(sample_field_definitions)

        # Update one field
        tracker.update_field("company_name", "ACME", 0.9, "dom")

        missing = tracker.get_missing_fields()
        missing_names = [f.name for f in missing]

        assert "company_name" not in missing_names
        assert "contact_email" in missing_names  # Required field
        # Note: get_missing_fields returns ALL missing fields (both required and optional)
        # because the cascade tries to extract everything if possible
        assert "services" in missing_names  # Still missing (not yet extracted)

    def test_is_complete(self, sample_field_definitions):
        tracker = FieldTracker(sample_field_definitions)

        assert not tracker.is_complete()

        # Fill required fields
        tracker.update_field("company_name", "ACME", 0.9, "dom")
        tracker.update_field("contact_email", "info@acme.com", 0.9, "dom")

        assert tracker.is_complete()

    def test_mark_skipped(self, sample_field_definitions):
        tracker = FieldTracker(sample_field_definitions)

        tracker.mark_skipped("contact_email")

        assert tracker.status["contact_email"] == FieldStatus.SKIPPED
        # Skipped fields count as "done" for completeness
        tracker.update_field("company_name", "ACME", 0.9, "dom")
        assert tracker.is_complete()

    def test_get_success_rate(self, sample_field_definitions):
        tracker = FieldTracker(sample_field_definitions)

        assert tracker.get_success_rate() == 0.0

        tracker.update_field("company_name", "ACME", 0.9, "dom")
        tracker.update_field("services", ["Service1"], 0.8, "dom")

        assert tracker.get_success_rate() == 0.5  # 2 of 4


# --- FieldProvenance Tests ---

class TestFieldProvenance:
    """Tests for FieldProvenance."""

    def test_to_dict(self):
        prov = FieldProvenance(
            field_name="company_name",
            template_type=FieldType.STRING,
            template_required=True,
            extracted_value="ACME Corp",
            tier="dom",
            source_url="https://acme.com",
            confidence=0.9
        )

        d = prov.to_dict()

        assert d["field_name"] == "company_name"
        assert d["template_type"] == "string"  # FieldType.STRING.value
        assert d["extracted_value"] == "ACME Corp"
        assert d["tier"] == "dom"
        assert d["confidence"] == 0.9

    def test_to_dict_handles_none_type(self):
        prov = FieldProvenance(
            field_name="_error",
            template_type=None,
            template_required=False,
            extracted_value="Error message",
            tier="error",
            source_url="",
            confidence=0.0
        )

        d = prov.to_dict()
        assert d["template_type"] == "STRING"  # Default fallback

    def test_was_found(self):
        found = FieldProvenance(
            field_name="test",
            template_type=FieldType.STRING,
            template_required=True,
            extracted_value="value",
            tier="dom",
            source_url="",
            confidence=0.8
        )
        assert found.was_found

        not_found = FieldProvenance(
            field_name="test",
            template_type=FieldType.STRING,
            template_required=True,
            extracted_value=None,
            tier="none",
            source_url="",
            confidence=0.0
        )
        assert not not_found.was_found


# --- ExtractionProvenance Tests ---

class TestExtractionProvenance:
    """Tests for ExtractionProvenance."""

    def test_success_rate(self):
        prov = ExtractionProvenance(url="https://test.com", intent_name="test")

        prov.add_field(FieldProvenance(
            field_name="f1", template_type=FieldType.STRING, template_required=True,
            extracted_value="v1", tier="dom", source_url="", confidence=0.9
        ))
        prov.add_field(FieldProvenance(
            field_name="f2", template_type=FieldType.STRING, template_required=False,
            extracted_value=None, tier="none", source_url="", confidence=0.0
        ))

        assert prov.success_rate == 0.5

    def test_to_calibration_record(self):
        prov = ExtractionProvenance(url="https://test.com", intent_name="test")
        prov.add_tier("dom")
        prov.add_cost(0.01)

        prov.add_field(FieldProvenance(
            field_name="company_name", template_type=FieldType.STRING, template_required=True,
            extracted_value="ACME", tier="dom", source_url="https://test.com", confidence=0.9
        ))

        record = prov.to_calibration_record()

        assert record["url"] == "https://test.com"
        assert record["intent"] == "test"
        assert "company_name" in record["field_results"]
        assert record["field_results"]["company_name"]["found"] is True
        assert record["field_results"]["company_name"]["tier"] == "dom"


# --- SiteMap Tests ---

class TestSiteMap:
    """Tests for SiteMap."""

    def test_add_page(self):
        site_map = SiteMap(base_url="https://example.com")

        site_map.add_page("https://example.com/team", "team", "crawl")
        site_map.add_page("https://example.com/services", "services", "sitemap")

        assert "team" in site_map.pages
        assert "https://example.com/team" in site_map.pages["team"]
        assert "https://example.com/services" in site_map.sitemap_urls

    def test_get_pages_for_field(self):
        site_map = SiteMap(base_url="https://example.com")
        site_map.add_page("https://example.com/team", "team", "crawl")
        site_map.add_page("https://example.com/about", "about", "crawl")

        pages = site_map.get_pages_for_field("leadership")

        assert "https://example.com/team" in pages


# --- ApprovalCallback Tests ---

class TestAutoApprovalCallback:
    """Tests for AutoApprovalCallback."""

    def test_approve_under_max_cost(self):
        callback = AutoApprovalCallback(max_cost=0.10, log_approvals=False)

        request = ApprovalRequest(
            session_id="test",
            url="https://test.com",
            estimated_cost=0.05,
            screenshot_candidates=[
                ScreenshotCandidate(field_name="f1", url="https://test.com", screenshot_bytes=b"")
            ]
        )

        response = callback.request_approval(request)

        assert response.state == ApprovalState.APPROVED
        assert len(response.approved_candidates) == 1

    def test_reject_over_max_cost(self):
        callback = AutoApprovalCallback(max_cost=0.05, log_approvals=False)

        request = ApprovalRequest(
            session_id="test",
            url="https://test.com",
            estimated_cost=0.10,
            screenshot_candidates=[]
        )

        response = callback.request_approval(request)

        assert response.state == ApprovalState.REJECTED


# --- ProvenanceStore Tests ---

class TestProvenanceStore:
    """Tests for ProvenanceStore."""

    def test_save_and_get(self, temp_dir):
        store = ProvenanceStore(base_dir=temp_dir)

        prov = ExtractionProvenance(url="https://test.com", intent_name="test")
        prov.add_field(FieldProvenance(
            field_name="company_name", template_type=FieldType.STRING, template_required=True,
            extracted_value="ACME", tier="dom", source_url="https://test.com", confidence=0.9
        ))

        store.save(prov)

        # Retrieve
        loaded = store.get("https://test.com")

        assert loaded is not None
        assert loaded.url == "https://test.com"
        assert "company_name" in loaded.fields

    def test_calibration_data(self, temp_dir):
        store = ProvenanceStore(base_dir=temp_dir)

        # Save two provenance records
        for i in range(2):
            prov = ExtractionProvenance(url=f"https://test{i}.com", intent_name="test")
            prov.add_field(FieldProvenance(
                field_name="company_name", template_type=FieldType.STRING, template_required=True,
                extracted_value="ACME", tier="dom", source_url="", confidence=0.9
            ))
            store.save(prov)

        calibration = store.get_calibration_data("test")

        assert calibration["sample_count"] == 2
        assert "company_name" in calibration["fields"]
        assert calibration["fields"]["company_name"]["success_count"] == 2


# --- SiteMapper Tests ---

class TestSiteMapper:
    """Tests for SiteMapper."""

    def test_categorize_url(self):
        mapper = SiteMapper()

        assert mapper._categorize_url("https://example.com/team") == "team"
        assert mapper._categorize_url("https://example.com/our-team") == "team"
        assert mapper._categorize_url("https://example.com/services") == "services"
        assert mapper._categorize_url("https://example.com/contact-us") == "contact"
        assert mapper._categorize_url("https://example.com/about") == "about"
        assert mapper._categorize_url("https://example.com/") == "home"
        assert mapper._categorize_url("https://example.com/random") == "other"

    @patch('extraction_cascade.tiers.site_mapper.requests.Session')
    def test_map_site_with_mock(self, mock_session_cls):
        """Test site mapping with mocked HTTP requests."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        # Mock sitemap response (404)
        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404
        mock_session.get.return_value = mock_response_404

        mapper = SiteMapper(SiteMapperConfig(delay_seconds=0))

        site_map = mapper.map_site("https://example.com")

        assert site_map.base_url == "https://example.com"
        assert "home" in site_map.pages


# --- DOMExtractor Tests ---

class TestDOMExtractor:
    """Tests for DOMExtractor."""

    def test_extract_emails(self):
        from bs4 import BeautifulSoup

        # Note: example.com is filtered out by the extractor, so we use a real-looking domain
        html = """
        <html>
        <body>
            <a href="mailto:info@acmecorp.com">Contact us</a>
            <p>Email: support@acmecorp.com for help</p>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')

        extractor = DOMExtractor()
        emails = extractor._extract_emails(soup)

        assert "info@acmecorp.com" in emails
        assert "support@acmecorp.com" in emails

    def test_extract_phones(self):
        from bs4 import BeautifulSoup

        html = """
        <html>
        <body>
            <p>Call us: (555) 123-4567</p>
            <p>Or 555.987.6543</p>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')

        extractor = DOMExtractor()
        phones = extractor._extract_phones(soup)

        assert "(555) 123-4567" in phones
        assert "(555) 987-6543" in phones

    def test_is_valid_person_name(self):
        extractor = DOMExtractor()

        # Valid names
        assert extractor._is_valid_person_name("John Smith")
        assert extractor._is_valid_person_name("Mary Jane Watson")

        # Invalid names
        assert not extractor._is_valid_person_name("")
        assert not extractor._is_valid_person_name("A")  # Too short
        assert not extractor._is_valid_person_name("John")  # Single word
        assert not extractor._is_valid_person_name("JOHN SMITH")  # All caps
        assert not extractor._is_valid_person_name("john smith")  # No caps
        assert not extractor._is_valid_person_name("Click Here To Learn More")

    def test_extract_company_name_from_title(self):
        from bs4 import BeautifulSoup

        html = """
        <html>
        <head><title>ACME Corporation | Leading Solutions</title></head>
        <body></body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')

        extractor = DOMExtractor()
        result = extractor._extract_company_name(soup, "https://acme.com")

        assert result is not None
        assert result.value == "ACME Corporation"
        assert result.confidence > 0.5


# --- ExtractionSession Tests ---

class TestExtractionSession:
    """Tests for ExtractionSession."""

    def test_session_initialization(self, sample_intent):
        session = ExtractionSession(url="https://test.com", intent=sample_intent)

        assert session.url == "https://test.com"
        assert session.field_tracker is not None
        assert session.provenance is not None
        assert len(session.tiers_executed) == 0

    def test_update_field(self, sample_intent):
        session = ExtractionSession(url="https://test.com", intent=sample_intent)
        session.start_tier("dom")

        session.update_field(
            field_name="company_name",
            value="ACME Corp",
            confidence=0.9,
            source_url="https://test.com"
        )

        assert session.data["company_name"] == "ACME Corp"
        assert session.field_tracker.status["company_name"] == FieldStatus.EXTRACTED
        assert "company_name" in session.provenance.fields

    def test_get_result(self, sample_intent):
        session = ExtractionSession(url="https://test.com", intent=sample_intent)
        session.start_tier("dom")
        session.update_field("company_name", "ACME", 0.9)
        session.mark_complete("dom")

        result = session.get_result()

        assert result["company_name"] == "ACME"
        assert "_extraction_metadata" in result
        assert result["_extraction_metadata"]["final_tier"] == "dom"


# --- Integration Tests ---

class TestCascadeIntegration:
    """Integration tests for the full cascade."""

    @patch('extraction_cascade.tiers.site_mapper.requests.Session')
    def test_orchestrator_dom_only(self, mock_session_cls, sample_intent):
        """Test orchestrator with DOM extraction only."""
        from extraction_cascade.orchestrator import CascadeOrchestrator, CascadeConfig

        # Mock HTTP responses
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_homepage = MagicMock()
        mock_homepage.status_code = 200
        mock_homepage.text = """
        <html>
        <head>
            <title>ACME Corporation - Home</title>
            <meta name="description" content="ACME is a leading company">
        </head>
        <body>
            <p>Email: info@acme.com</p>
        </body>
        </html>
        """
        mock_session.get.return_value = mock_homepage
        mock_session.head.return_value = mock_homepage

        # Create orchestrator with browser and vision disabled
        config = CascadeConfig(
            enable_browser_agent=False,
            enable_vision=False
        )
        callback = AutoApprovalCallback(log_approvals=False)
        orchestrator = CascadeOrchestrator(sample_intent, callback, config)

        # Run extraction
        session = orchestrator.extract("https://acme.com")

        assert session.url == "https://acme.com"
        assert "site_mapping" in session.tiers_executed
        assert "dom" in session.tiers_executed
        assert session.total_cost == 0.0  # DOM is free


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
