"""
Base scraper class defining the interface all scrapers must implement.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any

# Number of characters of the raw HTTP response to include in diagnostics.
DIAG_PREVIEW_CHARS = 600


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

    def diagnose(self, keywords: str, search_types: List[str]) -> Dict[str, Any]:
        """
        Return a diagnostic dict describing the outcome of an attempted search.
        Subclasses should override this to provide richer information.

        Minimum keys:
          source, url, http_status, response_size, error, elements_found, response_preview
        """
        try:
            results = self.search(keywords, search_types, max_results=5)
            return {
                "source": getattr(self, "SOURCE_NAME", type(self).__name__),
                "url": None,
                "http_status": None,
                "response_size": None,
                "error": None if results else "search() returned 0 results (no detailed diagnostics available)",
                "elements_found": len(results),
                "response_preview": None,
            }
        except Exception as exc:
            return {
                "source": getattr(self, "SOURCE_NAME", type(self).__name__),
                "url": None,
                "http_status": None,
                "response_size": None,
                "error": str(exc),
                "elements_found": 0,
                "response_preview": None,
            }
