"""
DuckDuckGo HTML scraper — searches the web for bid/RFP/RFQ/RFI opportunities.

Uses DuckDuckGo's /html/ endpoint which returns regular HTML (no JavaScript,
no API key required).
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urlparse
from .base_scraper import BaseScraper

DDG_URL = "https://html.duckduckgo.com/html/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Extra context terms appended to the user query
TYPE_TERMS = {
    "RFP": "RFP",
    "RFQ": "RFQ",
    "RFI": "RFI",
    "Bid": "bid solicitation",
}


class WebSearchScraper(BaseScraper):
    """Use DuckDuckGo HTML search to find bid opportunities."""

    SOURCE_NAME = "Web Search"

    def search(self, keywords: str, search_types: List[str], max_results: int = 25) -> List[Dict]:
        results = []
        # Run one search per selected type to maximize coverage
        for stype in (search_types or ["RFP"]):
            extra = TYPE_TERMS.get(stype, stype)
            query = f"{keywords} {extra} procurement government"
            per_type = max(max_results // len(search_types), 5) if search_types else max_results
            batch = self._ddg_search(query, max_results=per_type)
            # Tag each result with its search type
            for r in batch:
                r["raw_data"]["search_type"] = stype
            results.extend(batch)
            if len(results) >= max_results:
                break

        # De-duplicate by URL
        seen_urls = set()
        unique = []
        for r in results:
            url = r.get("source_url") or ""
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(r)

        return unique[:max_results]

    def _ddg_search(self, query: str, max_results: int = 10) -> List[Dict]:
        try:
            resp = requests.post(
                DDG_URL,
                data={"q": query, "kl": "us-en"},
                headers=HEADERS,
                timeout=15,
                allow_redirects=True,
            )
            resp.raise_for_status()
        except requests.RequestException:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        for result_div in soup.select(".result")[:max_results]:
            r = self.empty_result()

            # Title + URL
            title_tag = result_div.select_one(".result__title a")
            if title_tag:
                r["title"] = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                # DuckDuckGo wraps URLs; extract the real URL
                real_url = _extract_url(href)
                r["source_url"] = real_url
                r["site"] = _domain(real_url)

            # Snippet / description
            snippet_tag = result_div.select_one(".result__snippet")
            if snippet_tag:
                r["description"] = snippet_tag.get_text(strip=True)[:300]

            r["source_name"] = self.SOURCE_NAME
            r["raw_data"] = {"query": query, "snippet": r.get("description", "")}

            if r["title"]:
                results.append(r)

        return results


def _extract_url(href: str) -> str:
    """DuckDuckGo sometimes wraps links in redirect URLs."""
    if not href:
        return ""
    # Real redirect: //duckduckgo.com/l/?uddg=<encoded_url>
    match = re.search(r"uddg=([^&]+)", href)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1))
    return href


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url
