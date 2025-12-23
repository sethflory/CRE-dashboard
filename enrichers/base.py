from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class BaseEnricher(ABC):
    """Base interface for enrichers that add data to contacts/nodes."""

    @abstractmethod
    def enrich_contacts(self, contacts: List[Dict], limit: Optional[int] = None) -> int:
        """Enrich a list of contacts and return how many were processed."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release resources held by the enricher."""
        raise NotImplementedError
