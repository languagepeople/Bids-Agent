"""
Base scraper class defining the interface all scrapers must implement.
"""

from abc import ABC, abstractmethod
from typing import List, Dict


class BaseScraper(ABC):
    """Every scraper returns a list of result dicts with a common schema."""

    # Canonical field names returned by every scraper
    FIELDS = ["title", "number", "site", "description", "city", "state",
              "company", "due_date", "source_url", "source_name", "raw_data"]

    def empty_result(self) -> Dict:
        return {f: None for f in self.FIELDS}

    @abstractmethod
    def search(self, keywords: str, search_types: List[str], max_results: int = 25) -> List[Dict]:
        """
        Perform a search and return a list of result dicts.

        Parameters
        ----------
        keywords    : space-separated search terms
        search_types: any subset of ["Bid", "RFP", "RFQ", "RFI"]
        max_results : cap on number of items to return

        Returns
        -------
        List of dicts matching FIELDS above.
        """
        raise NotImplementedError
