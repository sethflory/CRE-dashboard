"""
Cascade Orchestrator - Coordinates the extraction cascade.

Runs through tiers from cheapest to most expensive,
stopping when all required fields are extracted.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision_extractor.intent import ExtractionIntent

from .models.session import ExtractionSession, SiteMap
from .models.provenance import FieldProvenance
from .tiers.site_mapper import SiteMapper, SiteMapperConfig, ProgressCallback
from .tiers.dom_extractor import DOMExtractor, DOMProgressCallback
from .tiers.browser_agent import BrowserAgent, BrowserAgentConfig
from .tiers.vision_queue import VisionQueue, VisionQueueConfig
from .approval.callback import ApprovalCallback, AutoApprovalCallback


class CallbackProgressAdapter(ProgressCallback):
    """Adapts ApprovalCallback to ProgressCallback interface."""

    def __init__(self, callback: ApprovalCallback):
        self.callback = callback

    def on_sitemap_check(self, url: str, found: bool, page_count: int = 0) -> None:
        self.callback.on_sitemap_check(url, found, page_count)

    def on_robots_check(self, url: str, found: bool) -> None:
        self.callback.on_robots_check(url, found)

    def on_page_discovered(self, url: str, page_type: str, source: str) -> None:
        self.callback.on_page_discovered(url, page_type, source)

    def on_page_crawled(self, url: str, links_found: int) -> None:
        self.callback.on_page_crawled(url, links_found)

    def on_static_pattern_check(self, pattern: str, exists: bool) -> None:
        self.callback.on_static_pattern_check(pattern, exists)


class DOMCallbackAdapter(DOMProgressCallback):
    """Adapts ApprovalCallback to DOMProgressCallback interface."""

    def __init__(self, callback: ApprovalCallback):
        self.callback = callback

    def on_dom_page_visit(self, page_url: str, page_type: str, fields_seeking: list) -> None:
        self.callback.on_dom_page_visit(page_url, page_type, fields_seeking)

    def on_field_not_found(self, field_name: str, tier: str, pages_tried: list) -> None:
        self.callback.on_field_not_found(field_name, tier, pages_tried)


@dataclass
class CascadeConfig:
    """Configuration for the cascade orchestrator."""
    # Tier enablement
    enable_site_mapping: bool = True
    enable_dom_extraction: bool = True
    enable_browser_agent: bool = True
    enable_vision: bool = True

    # Tier-specific configs
    site_mapper_config: Optional[SiteMapperConfig] = None
    browser_agent_config: Optional[BrowserAgentConfig] = None
    vision_config: Optional[VisionQueueConfig] = None

    # Behavior
    stop_on_complete: bool = True  # Stop when all required fields found
    max_tiers: int = 4  # Maximum tiers to execute


class CascadeOrchestrator:
    """
    Orchestrates the extraction cascade for a single URL.

    Progresses through tiers, tracking field completion
    and requesting user approval for expensive operations.

    Tiers:
        1. Site Mapping (FREE) - Discover pages
        2. DOM Extraction (FREE) - Extract from HTML
        3. Browser Agent (MODERATE) - Browser-Use + Claude
        4. Vision Queue (EXPENSIVE) - Claude Vision with approval
    """

    def __init__(
        self,
        intent: ExtractionIntent,
        approval_callback: Optional[ApprovalCallback] = None,
        config: Optional[CascadeConfig] = None
    ):
        """
        Initialize orchestrator.

        Args:
            intent: Extraction intent defining what to extract
            approval_callback: Callback for Tier 4 approvals
            config: Optional cascade configuration
        """
        self.intent = intent
        self.approval_callback = approval_callback or AutoApprovalCallback()
        self.config = config or CascadeConfig()

        # Initialize tiers with progress callback adapters
        progress_adapter = CallbackProgressAdapter(self.approval_callback)
        dom_adapter = DOMCallbackAdapter(self.approval_callback)
        self.site_mapper = SiteMapper(self.config.site_mapper_config, progress_adapter)
        self.dom_extractor = DOMExtractor(self.site_mapper, dom_adapter)
        self.browser_agent = BrowserAgent(self.config.browser_agent_config)
        self.vision_queue = VisionQueue(
            intent,
            self.approval_callback,
            self.config.vision_config
        )

    def extract(self, url: str) -> ExtractionSession:
        """
        Run the full extraction cascade for a URL.

        Args:
            url: Target URL to extract from

        Returns:
            ExtractionSession with results and metadata
        """
        # Create session
        session_id = str(uuid.uuid4())[:8]
        session = ExtractionSession(url=url, intent=self.intent)

        # Notify callback
        self.approval_callback.on_extraction_start(url, self.intent.name)

        try:
            # Tier 1: Site Mapping
            if self.config.enable_site_mapping:
                self._run_tier_1(session)
                if self._should_stop(session):
                    return self._finalize(session, "site_mapping")

            # Tier 2: DOM Extraction
            if self.config.enable_dom_extraction:
                self._run_tier_2(session)
                if self._should_stop(session):
                    return self._finalize(session, "dom")

            # Tier 3: Browser Agent
            if self.config.enable_browser_agent:
                missing_fields = session.get_missing_fields()
                if missing_fields:
                    if self.browser_agent.is_available:
                        self._run_tier_3(session)
                        if self._should_stop(session):
                            return self._finalize(session, "browser")
                    else:
                        reason = self.browser_agent.get_unavailable_reason() or "Unknown"
                        # Check if it's an API key issue and prompt user
                        if "ANTHROPIC_API_KEY" in reason:
                            field_names = [f.name for f in missing_fields]
                            if self.approval_callback.on_api_key_required("browser", field_names):
                                # User provided key, reinitialize and run
                                self.browser_agent = BrowserAgent(self.config.browser_agent_config)
                                if self.browser_agent.is_available:
                                    self._run_tier_3(session)
                                    if self._should_stop(session):
                                        return self._finalize(session, "browser")
                        else:
                            self.approval_callback.on_tier_skipped("browser", reason)

            # Tier 4: Vision Queue
            if self.config.enable_vision:
                missing_fields = session.get_missing_fields()
                if missing_fields:
                    if self.vision_queue.is_available:
                        self._run_tier_4(session, session_id)
                    else:
                        reason = self.vision_queue.get_unavailable_reason() or "Unknown"
                        # Check if it's an API key issue and prompt user
                        if "ANTHROPIC_API_KEY" in reason:
                            field_names = [f.name for f in missing_fields]
                            if self.approval_callback.on_api_key_required("vision", field_names):
                                # User provided key, reinitialize and run
                                self.vision_queue = VisionQueue(
                                    self.intent,
                                    self.approval_callback,
                                    self.config.vision_config
                                )
                                if self.vision_queue.is_available:
                                    self._run_tier_4(session, session_id)
                        else:
                            self.approval_callback.on_tier_skipped("vision", reason)

            return self._finalize(session, "vision" if self.config.enable_vision else "browser")

        except Exception as e:
            session.provenance.add_field(FieldProvenance(
                field_name="_error",
                template_type=None,
                template_required=False,
                extracted_value=str(e),
                tier="error",
                source_url=url,
                confidence=0.0
            ))
            return self._finalize(session, "error")

    def _run_tier_1(self, session: ExtractionSession) -> None:
        """Run Tier 1: Site Mapping."""
        session.start_tier("site_mapping")
        self.approval_callback.on_tier_start("site_mapping")

        site_map = self.site_mapper.map_site(session.url)
        session.site_map = site_map

        # Site mapping doesn't extract fields directly,
        # but we record the discovery
        self.approval_callback.on_tier_complete("site_mapping", site_map.total_pages)

    def _run_tier_2(self, session: ExtractionSession) -> None:
        """Run Tier 2: DOM Extraction."""
        session.start_tier("dom")
        self.approval_callback.on_tier_start("dom")

        if not session.site_map:
            session.site_map = SiteMap(base_url=session.url)

        results = self.dom_extractor.extract(session, session.site_map)

        # Update session with results
        fields_found = 0
        for field_name, result in results.items():
            session.update_field(
                field_name=field_name,
                value=result.value,
                confidence=result.confidence,
                source_url=result.source_url,
                raw_context=result.raw_context
            )
            if result.value is not None:
                fields_found += 1
                self.approval_callback.on_field_extracted(field_name, "dom", result.confidence)

        self.approval_callback.on_tier_complete("dom", fields_found)

    def _run_tier_3(self, session: ExtractionSession) -> None:
        """Run Tier 3: Browser Agent."""
        session.start_tier("browser")
        self.approval_callback.on_tier_start("browser")

        missing_fields = session.get_missing_fields()
        if not missing_fields:
            return

        results = self.browser_agent.extract_fields(
            session.url,
            missing_fields,
            session.site_map
        )

        # Update session with results
        fields_found = 0
        for field_name, result in results.items():
            session.update_field(
                field_name=field_name,
                value=result.value,
                confidence=result.confidence,
                source_url=result.source_url,
                raw_context=result.raw_output
            )
            if result.value is not None:
                fields_found += 1
                self.approval_callback.on_field_extracted(field_name, "browser", result.confidence)

        # Track cost
        session.add_cost(self.browser_agent.get_total_cost(), "browser")

        self.approval_callback.on_tier_complete("browser", fields_found)

    def _run_tier_4(self, session: ExtractionSession, session_id: str) -> None:
        """Run Tier 4: Vision Queue."""
        session.start_tier("vision")
        self.approval_callback.on_tier_start("vision")

        missing_fields = session.get_missing_fields()
        if not missing_fields:
            return

        results = self.vision_queue.extract_with_approval(
            session_id=session_id,
            url=session.url,
            missing_fields=missing_fields,
            site_map=session.site_map,
            already_extracted=session.field_tracker.get_extracted_data()
        )

        # Update session with results
        fields_found = 0
        for field_name, result in results.items():
            session.update_field(
                field_name=field_name,
                value=result.value,
                confidence=result.confidence,
                source_url=result.source_url
            )
            if result.value is not None:
                fields_found += 1
                self.approval_callback.on_field_extracted(field_name, "vision", result.confidence)

        # Track cost
        session.add_cost(self.vision_queue.get_total_cost(), "vision")

        self.approval_callback.on_tier_complete("vision", fields_found)

    def _should_stop(self, session: ExtractionSession) -> bool:
        """Check if we should stop the cascade early."""
        if not self.config.stop_on_complete:
            return False
        # Stop only if ALL fields are extracted (not just required ones)
        missing = session.get_missing_fields()
        return len(missing) == 0

    def _finalize(self, session: ExtractionSession, final_tier: str) -> ExtractionSession:
        """Finalize the extraction session."""
        session.mark_complete(final_tier)

        # Calculate success
        success = session.is_complete()

        # Notify callback
        self.approval_callback.on_extraction_complete(success, session.total_cost)

        return session


def extract_url(
    url: str,
    intent_name: str = "company_website",
    approval_callback: Optional[ApprovalCallback] = None,
    config: Optional[CascadeConfig] = None
) -> ExtractionSession:
    """
    Convenience function to extract data from a URL.

    Args:
        url: Target URL
        intent_name: Name of extraction template to use
        approval_callback: Optional callback for approvals
        config: Optional cascade config

    Returns:
        ExtractionSession with results
    """
    from vision_extractor.storage import TemplateStorage

    # Load intent
    storage = TemplateStorage()
    intent = storage.load(intent_name)

    if not intent:
        raise ValueError(f"Template '{intent_name}' not found")

    # Create orchestrator and run
    orchestrator = CascadeOrchestrator(
        intent=intent,
        approval_callback=approval_callback,
        config=config
    )

    return orchestrator.extract(url)
