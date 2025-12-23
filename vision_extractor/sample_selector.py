"""
Sample selection for calibration.

Provides utilities for selecting representative samples from URL lists.
"""

import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Set
from urllib.parse import urlparse


@dataclass
class SampleSet:
    """A set of selected samples for calibration."""
    urls: List[str]
    selection_method: str  # "random", "manual", "stratified", "per_company"
    metadata: Dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.urls)

    def __iter__(self):
        return iter(self.urls)


class SampleSelector:
    """
    Select representative samples for calibration.

    Supports multiple selection strategies:
    - Random sampling
    - Manual user selection
    - Stratified sampling by domain
    - Contact sampling (1+ per company)
    """

    def __init__(self, urls: Optional[List[str]] = None):
        """
        Initialize selector.

        Args:
            urls: Optional initial list of URLs
        """
        self.urls = urls or []

    def set_urls(self, urls: List[str]):
        """Set the URL list to select from."""
        self.urls = urls

    def random_sample(self, n: int = 3) -> SampleSet:
        """
        Select n random URLs.

        Args:
            n: Number of samples to select

        Returns:
            SampleSet with random selection
        """
        if not self.urls:
            return SampleSet(urls=[], selection_method="random")

        n = min(n, len(self.urls))
        selected = random.sample(self.urls, n)

        return SampleSet(
            urls=selected,
            selection_method="random",
            metadata={"total_available": len(self.urls)}
        )

    def stratified_sample(self, n: int = 3) -> SampleSet:
        """
        Select samples stratified by domain.

        Ensures diverse coverage across different domains/sites.

        Args:
            n: Number of samples to select

        Returns:
            SampleSet with stratified selection
        """
        if not self.urls:
            return SampleSet(urls=[], selection_method="stratified")

        # Group by domain
        by_domain: Dict[str, List[str]] = {}
        for url in self.urls:
            try:
                domain = urlparse(url).netloc
                if domain not in by_domain:
                    by_domain[domain] = []
                by_domain[domain].append(url)
            except:
                continue

        # Select evenly from each domain
        selected = []
        domains = list(by_domain.keys())
        random.shuffle(domains)

        while len(selected) < n and domains:
            for domain in domains[:]:
                if len(selected) >= n:
                    break
                if by_domain[domain]:
                    url = random.choice(by_domain[domain])
                    selected.append(url)
                    by_domain[domain].remove(url)
                    if not by_domain[domain]:
                        domains.remove(domain)

        return SampleSet(
            urls=selected,
            selection_method="stratified",
            metadata={
                "domains_covered": len(set(urlparse(u).netloc for u in selected)),
                "total_domains": len(by_domain)
            }
        )

    def user_select(
        self,
        prompt_fn: Callable[[List[str]], List[int]],
        max_display: int = 20
    ) -> SampleSet:
        """
        Allow user to manually select samples.

        Args:
            prompt_fn: Function that takes list of URLs and returns selected indices
            max_display: Maximum URLs to display for selection

        Returns:
            SampleSet with user selections
        """
        if not self.urls:
            return SampleSet(urls=[], selection_method="manual")

        display_urls = self.urls[:max_display]
        selected_indices = prompt_fn(display_urls)

        selected = [display_urls[i] for i in selected_indices if 0 <= i < len(display_urls)]

        return SampleSet(
            urls=selected,
            selection_method="manual",
            metadata={"user_selected": True}
        )

    def contact_sample(
        self,
        contacts_by_company: Dict[str, List[str]],
        min_per_company: int = 1,
        max_total: Optional[int] = None
    ) -> SampleSet:
        """
        Select contacts ensuring at least N per company.

        Used for Phase B contact enrichment.

        Args:
            contacts_by_company: Dict mapping company name to list of contact URLs
            min_per_company: Minimum contacts to select per company
            max_total: Maximum total contacts to select

        Returns:
            SampleSet with contact selections
        """
        selected = []
        companies_with_contacts = 0

        for company, contacts in contacts_by_company.items():
            if not contacts:
                continue

            companies_with_contacts += 1
            n = min(min_per_company, len(contacts))
            selected.extend(random.sample(contacts, n))

            if max_total and len(selected) >= max_total:
                break

        if max_total:
            selected = selected[:max_total]

        return SampleSet(
            urls=selected,
            selection_method="per_company",
            metadata={
                "companies_covered": companies_with_contacts,
                "min_per_company": min_per_company
            }
        )

    def filter_by_pattern(self, pattern: str) -> 'SampleSelector':
        """
        Filter URLs by regex pattern.

        Args:
            pattern: Regex pattern to match

        Returns:
            New SampleSelector with filtered URLs
        """
        import re
        filtered = [u for u in self.urls if re.search(pattern, u)]
        return SampleSelector(filtered)

    def exclude_processed(self, processed: Set[str]) -> 'SampleSelector':
        """
        Exclude already processed URLs.

        Args:
            processed: Set of URLs to exclude

        Returns:
            New SampleSelector with filtered URLs
        """
        filtered = [u for u in self.urls if u not in processed]
        return SampleSelector(filtered)


def select_samples_interactive(
    urls: List[str],
    n: int = 3,
    method: str = "random"
) -> SampleSet:
    """
    Interactive helper for sample selection.

    Args:
        urls: List of URLs to select from
        n: Number of samples
        method: Selection method ("random", "stratified", "manual")

    Returns:
        SampleSet with selected samples
    """
    selector = SampleSelector(urls)

    if method == "random":
        return selector.random_sample(n)
    elif method == "stratified":
        return selector.stratified_sample(n)
    elif method == "manual":
        def cli_prompt(display_urls: List[str]) -> List[int]:
            print("\nSelect samples (enter numbers separated by commas):")
            for i, url in enumerate(display_urls, 1):
                print(f"  [{i}] {url}")
            response = input("\nSelection: ")
            try:
                return [int(x.strip()) - 1 for x in response.split(",")]
            except:
                return []
        return selector.user_select(cli_prompt)
    else:
        return selector.random_sample(n)
