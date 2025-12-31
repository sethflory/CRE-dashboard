"""Provenance storage for extraction records."""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from extraction_cascade.models.provenance import ExtractionProvenance


class ProvenanceStore:
    """
    Stores and retrieves extraction provenance records.

    Provides persistence and querying for calibration and UI.
    """

    DEFAULT_FILE = "extraction_provenance.json"
    CALIBRATION_FILE = "calibration_data.json"

    def __init__(self, base_dir: str = None):
        """
        Initialize provenance store.

        Args:
            base_dir: Directory for storing provenance files
        """
        self.base_dir = base_dir or os.getcwd()
        self.provenance_file = os.path.join(self.base_dir, self.DEFAULT_FILE)
        self.calibration_file = os.path.join(self.base_dir, self.CALIBRATION_FILE)
        self._cache: Dict[str, ExtractionProvenance] = {}

    def save(self, provenance: ExtractionProvenance) -> None:
        """
        Save a provenance record.

        Args:
            provenance: The provenance record to save
        """
        # Load existing data
        data = self._load_file(self.provenance_file)

        # Add/update record (keyed by URL)
        data[provenance.url] = provenance.to_dict()

        # Save
        self._save_file(self.provenance_file, data)

        # Update cache
        self._cache[provenance.url] = provenance

        # Update calibration data
        self._update_calibration(provenance)

    def get(self, url: str) -> Optional[ExtractionProvenance]:
        """
        Get provenance for a URL.

        Args:
            url: The URL to look up

        Returns:
            ExtractionProvenance if found, None otherwise
        """
        # Check cache first
        if url in self._cache:
            return self._cache[url]

        # Load from file
        data = self._load_file(self.provenance_file)
        if url not in data:
            return None

        # Reconstruct provenance (simplified - full reconstruction would need more work)
        record = data[url]
        return self._dict_to_provenance(record)

    def get_all(self) -> List[ExtractionProvenance]:
        """Get all stored provenance records."""
        data = self._load_file(self.provenance_file)
        return [self._dict_to_provenance(record) for record in data.values()]

    def get_by_intent(self, intent_name: str) -> List[ExtractionProvenance]:
        """Get all provenance records for a specific intent."""
        all_records = self.get_all()
        return [p for p in all_records if p.intent_name == intent_name]

    def get_calibration_data(self, intent: str = None) -> Dict:
        """
        Get aggregated calibration data.

        Args:
            intent: Optional intent name to filter by

        Returns:
            Dict with calibration statistics per field
        """
        data = self._load_file(self.calibration_file)

        if intent and intent in data:
            return data[intent]

        return data

    def _update_calibration(self, provenance: ExtractionProvenance) -> None:
        """Update calibration data with a new provenance record."""
        calibration = self._load_file(self.calibration_file)
        intent = provenance.intent_name

        if intent not in calibration:
            calibration[intent] = {
                "sample_count": 0,
                "avg_success_rate": 0.0,
                "fields": {}
            }

        intent_data = calibration[intent]
        intent_data["sample_count"] += 1

        # Update running average of success rate
        n = intent_data["sample_count"]
        old_avg = intent_data["avg_success_rate"]
        intent_data["avg_success_rate"] = old_avg + (provenance.success_rate - old_avg) / n

        # Update per-field statistics
        for field_name, field_prov in provenance.fields.items():
            if field_name not in intent_data["fields"]:
                intent_data["fields"][field_name] = {
                    "sample_count": 0,
                    "success_count": 0,
                    "tier_counts": {"dom": 0, "browser": 0, "vision": 0, "none": 0},
                    "avg_confidence": 0.0
                }

            field_data = intent_data["fields"][field_name]
            field_data["sample_count"] += 1

            if field_prov.was_found:
                field_data["success_count"] += 1
                tier = field_prov.tier if field_prov.tier in field_data["tier_counts"] else "none"
                field_data["tier_counts"][tier] = field_data["tier_counts"].get(tier, 0) + 1

                # Update running average confidence
                n = field_data["success_count"]
                old_avg = field_data["avg_confidence"]
                field_data["avg_confidence"] = old_avg + (field_prov.confidence - old_avg) / n

        # Update last updated timestamp
        intent_data["last_updated"] = datetime.now().isoformat()

        self._save_file(self.calibration_file, calibration)

    def get_field_tier_recommendations(self, intent: str) -> Dict[str, str]:
        """
        Get recommended starting tier for each field based on historical success.

        Returns dict mapping field_name -> recommended_tier
        """
        calibration = self.get_calibration_data(intent)
        if not calibration or "fields" not in calibration:
            return {}

        recommendations = {}
        for field_name, field_data in calibration["fields"].items():
            tier_counts = field_data.get("tier_counts", {})

            # Find tier with highest success
            if tier_counts:
                best_tier = max(
                    [(t, c) for t, c in tier_counts.items() if t != "none"],
                    key=lambda x: x[1],
                    default=("dom", 0)
                )
                recommendations[field_name] = best_tier[0]

        return recommendations

    def _load_file(self, filepath: str) -> Dict:
        """Load JSON file."""
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_file(self, filepath: str, data: Dict) -> None:
        """Save JSON file."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)

    def _dict_to_provenance(self, record: Dict) -> ExtractionProvenance:
        """Convert a dict back to ExtractionProvenance (simplified)."""
        from extraction_cascade.models.provenance import ExtractionProvenance, FieldProvenance
        from vision_extractor.intent import FieldType

        provenance = ExtractionProvenance(
            url=record.get("url", ""),
            intent_name=record.get("intent_name", ""),
            tier_progression=record.get("tier_progression", []),
            total_cost=record.get("total_cost", 0.0)
        )

        # Parse timestamps
        if record.get("started_at"):
            try:
                provenance.started_at = datetime.fromisoformat(record["started_at"])
            except:
                pass

        if record.get("completed_at"):
            try:
                provenance.completed_at = datetime.fromisoformat(record["completed_at"])
            except:
                pass

        # Parse fields
        for field_name, field_data in record.get("fields", {}).items():
            try:
                field_type = FieldType(field_data.get("template_type", "STRING"))
            except:
                field_type = FieldType.STRING

            field_prov = FieldProvenance(
                field_name=field_name,
                template_type=field_type,
                template_required=field_data.get("template_required", False),
                extracted_value=field_data.get("extracted_value"),
                tier=field_data.get("tier", "none"),
                source_url=field_data.get("source_url", ""),
                confidence=field_data.get("confidence", 0.0),
                raw_context=field_data.get("raw_context")
            )
            provenance.fields[field_name] = field_prov

        return provenance
