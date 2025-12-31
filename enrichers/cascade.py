"""
Cascade Enricher - Enricher implementation using the extraction cascade.

Implements the BaseEnricher interface for integration with
existing enrichment pipelines.
"""

from typing import Dict, List, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichers.base import BaseEnricher
from extraction_cascade.orchestrator import CascadeOrchestrator, CascadeConfig
from extraction_cascade.approval.callback import ApprovalCallback, AutoApprovalCallback
from extraction_cascade.storage.provenance_store import ProvenanceStore
from vision_extractor.intent import ExtractionIntent
from vision_extractor.storage import TemplateStorage


class CascadeEnricher(BaseEnricher):
    """
    Enricher using the cost-optimized extraction cascade.

    Implements BaseEnricher interface for integration with
    existing CRE pipeline.
    """

    def __init__(
        self,
        intent_name: str = "company_website",
        approval_callback: Optional[ApprovalCallback] = None,
        config: Optional[CascadeConfig] = None,
        save_provenance: bool = True,
        provenance_dir: Optional[str] = None
    ):
        """
        Initialize cascade enricher.

        Args:
            intent_name: Name of extraction template to use
            approval_callback: Callback for Tier 4 approvals
            config: Optional cascade configuration
            save_provenance: Whether to save provenance records
            provenance_dir: Directory for provenance storage
        """
        self.intent_name = intent_name
        self.approval_callback = approval_callback or AutoApprovalCallback()
        self.config = config
        self.save_provenance = save_provenance

        # Load intent
        storage = TemplateStorage()
        self.intent = storage.load(intent_name)
        if not self.intent:
            raise ValueError(f"Template '{intent_name}' not found")

        # Create orchestrator
        self.orchestrator = CascadeOrchestrator(
            intent=self.intent,
            approval_callback=self.approval_callback,
            config=config
        )

        # Provenance store
        self.provenance_store = ProvenanceStore(provenance_dir) if save_provenance else None

        # Stats
        self._processed_count = 0
        self._total_cost = 0.0

    def enrich_contacts(self, contacts: List[Dict], limit: Optional[int] = None) -> int:
        """
        Enrich contacts using the cascade for each URL.

        Args:
            contacts: List of contact dicts with 'website' or 'linkedin_url' keys
            limit: Maximum number of contacts to process

        Returns:
            Number of contacts successfully enriched
        """
        processed = 0
        batch = contacts[:limit] if limit else contacts

        for contact in batch:
            # Get URL to process
            url = contact.get('website') or contact.get('linkedin_url')
            if not url:
                continue

            try:
                # Run extraction
                session = self.orchestrator.extract(url)

                # Update contact with extracted data
                if session.data:
                    contact.update(session.data)

                # Add metadata
                contact['_extraction_metadata'] = {
                    'url': session.url,
                    'intent': self.intent_name,
                    'final_tier': session.current_tier,
                    'tiers_used': session.tiers_executed,
                    'total_cost': session.total_cost,
                    'success_rate': session.field_tracker.get_success_rate(),
                    'completed_at': session.completed_at.isoformat() if session.completed_at else None,
                }

                # Save provenance
                if self.provenance_store:
                    self.provenance_store.save(session.get_provenance())

                # Track stats
                self._processed_count += 1
                self._total_cost += session.total_cost
                processed += 1

            except Exception as e:
                print(f"Error enriching {url}: {e}")
                contact['_extraction_error'] = str(e)
                continue

        return processed

    def enrich_single(self, url: str) -> Dict:
        """
        Enrich a single URL.

        Args:
            url: URL to extract from

        Returns:
            Dict with extracted data and metadata
        """
        session = self.orchestrator.extract(url)

        # Save provenance
        if self.provenance_store:
            self.provenance_store.save(session.get_provenance())

        # Track stats
        self._processed_count += 1
        self._total_cost += session.total_cost

        return session.get_result()

    def get_stats(self) -> Dict:
        """Get enrichment statistics."""
        return {
            'processed_count': self._processed_count,
            'total_cost': self._total_cost,
            'avg_cost_per_url': self._total_cost / self._processed_count if self._processed_count > 0 else 0,
        }

    def get_calibration_data(self) -> Dict:
        """Get calibration data for the current intent."""
        if self.provenance_store:
            return self.provenance_store.get_calibration_data(self.intent_name)
        return {}

    def close(self) -> None:
        """Release resources held by the enricher."""
        # No resources to release currently
        pass


def create_enricher(
    intent_name: str = "company_website",
    interactive: bool = True,
    max_auto_approve_cost: float = 0.10
) -> CascadeEnricher:
    """
    Create a cascade enricher with sensible defaults.

    Args:
        intent_name: Template to use
        interactive: If True, use CLI approval; if False, auto-approve
        max_auto_approve_cost: Max cost for auto-approval (when interactive=False)

    Returns:
        Configured CascadeEnricher
    """
    if interactive:
        from extraction_cascade.approval.cli_approval import CLIApprovalCallback
        callback = CLIApprovalCallback()
    else:
        callback = AutoApprovalCallback(max_cost=max_auto_approve_cost)

    return CascadeEnricher(
        intent_name=intent_name,
        approval_callback=callback
    )
