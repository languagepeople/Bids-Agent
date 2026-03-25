"""
DuckDuckGo HTML scraper — searches the web for bid/RFP/RFQ/RFI opportunities.

Uses DuckDuckGo's /html/ endpoint which returns regular HTML (no JavaScript,
no API key required).
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse
from .base_scraper import BaseScraper, DIAG_PREVIEW_CHARS

DDG_URL = "https://html.duckduckgo.com/html/"

# Full browser-like headers — missing Accept causes DDG to return a non-HTML response
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded",
}

# Extra context terms appended to the user query
TYPE_TERMS = {
    "RFP": "RFP",
    "RFQ": "RFQ",
    "RFI": "RFI",
    "Bid": "bid solicitation",
}

# Ordered list of CSS selectors to try (DDG updates their HTML structure periodically)
RESULT_SELECTORS = [
    (".result__title a", ".result__snippet"),   # classic DDG layout
    (".result-title a",  ".result-snippet"),    # alternative names
    ("h2 a",             ".result__body"),      # simplified layout
    ("a.result__a",      ".result__snippet"),   # another variant
]

# Seconds to wait between sequential DDG queries to reduce rate-limit risk
DDG_QUERY_DELAY = 1.0
# Max document types to query per search session (caps the number of DDG requests)
MAX_QUERY_TYPES_PER_SEARCH = 2


class WebSearchScraper(BaseScraper):
    """Use DuckDuckGo HTML search to find bid opportunities."""

    SOURCE_NAME = "Web Search"

    def search(self, keywords: str, search_types: List[str], max_results: int = 25) -> List[Dict]:
        results, _diag = self._run_search(keywords, search_types, max_results)
        return results

    def diagnose(self, keywords: str, search_types: List[str]) -> Dict[str, Any]:
        _results, diag = self._run_search(keywords, search_types, max_results=5)
        return diag

    def _run_search(self, keywords: str, search_types: List[str], max_results: int = 25
                    ) -> Tuple[List[Dict], Dict[str, Any]]:
        query_types = search_types or ["RFP"]
        # Cap at MAX_QUERY_TYPES_PER_SEARCH queries per search to reduce rate-limit risk
        query_types = query_types[:MAX_QUERY_TYPES_PER_SEARCH]
        per_type = max(max_results // len(query_types), 5)
        all_results = []
        all_diags: List[Dict] = []

        for i, stype in enumerate(query_types):
            # Brief pause between queries to be polite and avoid bot detection
            if i > 0:
                time.sleep(DDG_QUERY_DELAY)

            extra = TYPE_TERMS.get(stype, stype)
            query = f"{keywords} {extra} procurement government"
            batch, diag = self._ddg_search(query, max_results=per_type)
            for r in batch:
                r["raw_data"]["search_type"] = stype
            all_results.extend(batch)
            all_diags.append(diag)
            if len(all_results) >= max_results:
                break

        # De-duplicate by URL
        seen_urls: set = set()
        unique = []
        for r in all_results:
            url = r.get("source_url") or ""
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(r)

        # Aggregate diagnostics — surface the first error found
        combined_diag: Dict[str, Any] = {
            "source": self.SOURCE_NAME,
            "url": DDG_URL,
            "http_status": None,
            "response_size": None,
            "error": None,
            "elements_found": len(unique),
            "response_preview": None,
            "per_query": all_diags,
        }
        for d in all_diags:
            if d.get("error"):
                combined_diag["error"] = d["error"]
                combined_diag["http_status"] = d.get("http_status")
                break
        if all_diags:
            combined_diag["http_status"] = all_diags[0].get("http_status")
            combined_diag["response_size"] = all_diags[0].get("response_size")
            combined_diag["response_preview"] = all_diags[0].get("response_preview")

        return unique[:max_results], combined_diag

    def _ddg_search(self, query: str, max_results: int = 10) -> Tuple[List[Dict], Dict[str, Any]]:
        diag: Dict[str, Any] = {
            "query": query,
            "http_status": None,
            "response_size": None,
            "error": None,
            "elements_found": 0,
            "selector_used": None,
            "response_preview": None,
        }

        try:
            # Use a session so DDG cookies are maintained across redirects
            session = requests.Session()
            resp = session.post(
                DDG_URL,
                data={"q": query, "kl": "us-en"},
                headers=HEADERS,
                timeout=15,
                allow_redirects=True,
            )
            diag["http_status"] = resp.status_code
            diag["response_size"] = len(resp.content)
            diag["response_preview"] = resp.text[:DIAG_PREVIEW_CHARS]
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            diag["error"] = f"Connection failed — cannot reach html.duckduckgo.com: {exc}"
            return [], diag
        except requests.exceptions.Timeout:
            diag["error"] = "Request timed out after 15 s"
            return [], diag
        except requests.exceptions.HTTPError as exc:
            diag["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return [], diag
        except requests.RequestException as exc:
            diag["error"] = str(exc)
            return [], diag

        soup = BeautifulSoup(resp.text, "lxml")

        # Try each selector pair until one matches
        title_sel, snippet_sel = RESULT_SELECTORS[0]
        for ts, ss in RESULT_SELECTORS:
            if soup.select(ts):
                title_sel, snippet_sel = ts, ss
                diag["selector_used"] = ts
                break
        else:
            # No selector matched — report the HTML tag summary for debugging
            tags = [t.name for t in soup.find_all(True, limit=30)]
            diag["error"] = (
                f"No result elements found on DuckDuckGo page. "
                f"HTML tags present: {', '.join(dict.fromkeys(tags))}. "
                f"The page structure may have changed or the request was blocked/rate-limited."
            )
            return [], diag

        results = []
        for result_div in soup.select(".result, .web-result")[:max_results]:
            r = self.empty_result()

            title_tag = result_div.select_one(title_sel)
            if title_tag:
                r["title"] = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                real_url = _extract_url(href)
                r["source_url"] = real_url
                r["site"] = _domain(real_url)

            snippet_tag = result_div.select_one(snippet_sel)
            if snippet_tag:
                r["description"] = snippet_tag.get_text(strip=True)[:300]

            r["source_name"] = self.SOURCE_NAME
            r["raw_data"] = {"query": query, "snippet": r.get("description", "")}

            if r["title"]:
                results.append(r)

        diag["elements_found"] = len(results)
        if not results and not diag.get("error"):
            diag["error"] = (
                f"Selector '{title_sel}' matched the page but extracted 0 titled results. "
                "DuckDuckGo may have returned a CAPTCHA or rate-limit page. "
                "Try waiting 30 seconds and searching again."
            )

        return results, diag


def _extract_url(href: str) -> str:
    """DuckDuckGo sometimes wraps links in redirect URLs."""
    if not href:
        return ""
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
