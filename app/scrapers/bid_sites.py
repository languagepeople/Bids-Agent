"""
Scrapers for public-sector bid aggregator websites.

BidNet Direct
-------------
BidNet Direct renders its search results via AngularJS (client-side JavaScript).
A plain GET request returns only the Angular application shell — the actual
solicitation data is loaded through their JSON REST API.

This scraper calls BidNet Direct's public REST API directly, bypassing the
JavaScript rendering step.  It tries several known API URL patterns in order
and uses whichever one succeeds.
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Tuple
from urllib.parse import urljoin, urlparse, quote
from .base_scraper import BaseScraper, DIAG_PREVIEW_CHARS

# Minimum HTML size (bytes) that suggests a real page vs an Angular app shell.
# Angular shells are tiny stub files (< ~2 KB) before JS hydration.
ANGULAR_SHELL_MAX_SIZE = 2000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bidnetdirect.com/",
}


# ─── BidNet Direct ───────────────────────────────────────────────────────────

class BidNetScraper(BaseScraper):
    SOURCE_NAME = "BidNet Direct"
    BASE_URL = "https://www.bidnetdirect.com"

    # Candidate API endpoints tried in order; first one that returns results wins.
    # BidNet uses an AngularJS SPA — actual data comes from these JSON endpoints.
    CANDIDATE_APIS = [
        # Primary public search API (most common pattern for Angular SPA backends)
        "https://www.bidnetdirect.com/api/v1/public/solicitations/search",
        "https://www.bidnetdirect.com/api/v1/publicSolicitations",
        "https://www.bidnetdirect.com/api/public/opportunities/search",
        # Fallback: their HTML search page (works if they ever add SSR)
        "https://www.bidnetdirect.com/public/solicitations/search",
    ]

    def search(self, keywords: str, search_types: List[str], max_results: int = 25) -> List[Dict]:
        results, _diag = self._fetch(keywords, search_types, max_results)
        return results

    def diagnose(self, keywords: str, search_types: List[str]) -> Dict[str, Any]:
        _results, diag = self._fetch(keywords, search_types, max_results=5)
        return diag

    def _fetch(self, keywords: str, search_types: List[str], max_results: int = 25
               ) -> Tuple[List[Dict], Dict[str, Any]]:
        diag: Dict[str, Any] = {
            "source": self.SOURCE_NAME,
            "url": None,
            "http_status": None,
            "response_size": None,
            "error": None,
            "elements_found": 0,
            "response_preview": None,
            "attempts": [],
        }

        for api_url in self.CANDIDATE_APIS:
            attempt: Dict[str, Any] = {"url": api_url}
            try:
                resp = requests.get(
                    api_url,
                    params=self._build_params(api_url, keywords, max_results),
                    headers=HEADERS,
                    timeout=15,
                )
                attempt["http_status"] = resp.status_code
                attempt["response_size"] = len(resp.content)
                attempt["content_type"] = resp.headers.get("Content-Type", "")
                attempt["response_preview"] = resp.text[:DIAG_PREVIEW_CHARS]

                # Check if the response is the Angular shell (empty SPA)
                if _is_angular_shell(resp.text, resp.headers.get("Content-Type", "")):
                    attempt["error"] = (
                        "Received the Angular app shell — this URL loads results via "
                        "JavaScript and cannot be scraped with plain HTTP requests."
                    )
                    diag["attempts"].append(attempt)
                    continue

                if resp.status_code == 404:
                    attempt["error"] = "404 Not Found — API endpoint does not exist at this URL"
                    diag["attempts"].append(attempt)
                    continue

                resp.raise_for_status()

                # Try to parse as JSON first, then fall back to HTML
                ct = resp.headers.get("Content-Type", "")
                if "json" in ct:
                    results = self._parse_json(resp.json(), max_results)
                    if results:
                        diag["url"] = api_url
                        diag["http_status"] = resp.status_code
                        diag["response_size"] = len(resp.content)
                        diag["elements_found"] = len(results)
                        diag["response_preview"] = resp.text[:DIAG_PREVIEW_CHARS]
                        diag["attempts"].append(attempt)
                        return results, diag
                    attempt["error"] = (
                        f"JSON response parsed successfully but contained 0 solicitations. "
                        f"Keys: {list(resp.json().keys()) if isinstance(resp.json(), dict) else 'list'}"
                    )
                else:
                    # HTML response — try to parse solicitation rows
                    results = self._parse_html(resp.text, api_url, max_results)
                    if results:
                        diag["url"] = api_url
                        diag["http_status"] = resp.status_code
                        diag["response_size"] = len(resp.content)
                        diag["elements_found"] = len(results)
                        diag["response_preview"] = resp.text[:DIAG_PREVIEW_CHARS]
                        diag["attempts"].append(attempt)
                        return results, diag
                    attempt["error"] = (
                        "HTML response parsed but 0 solicitation rows matched. "
                        f"HTML size: {len(resp.text)} bytes."
                    )

            except requests.exceptions.ConnectionError as exc:
                attempt["error"] = f"Connection failed: {exc}"
            except requests.exceptions.Timeout:
                attempt["error"] = "Timed out after 15 s"
            except requests.exceptions.HTTPError as exc:
                attempt["error"] = f"HTTP error: {exc}"
            except Exception as exc:
                attempt["error"] = f"Unexpected error: {exc}"

            diag["attempts"].append(attempt)

        # All attempts exhausted
        errors = "; ".join(
            f"[{a['url'].split('/')[-1]}] {a.get('error', 'unknown')}"
            for a in diag["attempts"]
        )
        diag["error"] = (
            "All BidNet Direct API endpoint attempts failed. "
            "BidNet Direct loads solicitations via JavaScript — see details below. "
            f"Attempts: {errors}"
        )
        return [], diag

    @staticmethod
    def _build_params(url: str, keywords: str, max_results: int) -> Dict:
        """Build query parameters appropriate for the endpoint URL."""
        base = {"q": keywords, "keywords": keywords, "page": 1, "pageSize": max_results}
        return base

    @staticmethod
    def _parse_json(data: Any, max_results: int) -> List[Dict]:
        """Parse BidNet Direct JSON API response (several possible shapes)."""
        items: List[Any] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("solicitations", "opportunities", "results", "data", "items", "records"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break

        results = []
        scraper = BidNetScraper()
        for item in items[:max_results]:
            if not isinstance(item, dict):
                continue
            r = scraper.empty_result()
            r["title"]       = item.get("title") or item.get("solicitationTitle") or item.get("name") or ""
            r["number"]      = item.get("number") or item.get("solicitationNumber") or item.get("referenceNumber") or ""
            r["company"]     = item.get("agency") or item.get("organizationName") or item.get("buyerName") or ""
            r["city"]        = _nested(item, "city", "placeOfPerformance.city")
            r["state"]       = _nested(item, "state", "placeOfPerformance.state", "stateCode")
            r["due_date"]    = (item.get("dueDate") or item.get("closingDate") or item.get("responseDeadline") or "")[:10]
            r["description"] = (item.get("description") or item.get("summary") or "")[:300]
            r["source_url"]  = item.get("url") or item.get("detailUrl") or ""
            r["site"]        = BidNetScraper.BASE_URL
            r["source_name"] = BidNetScraper.SOURCE_NAME
            r["raw_data"]    = item
            if r["title"]:
                results.append(r)
        return results

    @staticmethod
    def _parse_html(html: str, base_url: str, max_results: int) -> List[Dict]:
        """Parse an HTML search results page."""
        soup = BeautifulSoup(html, "lxml")
        results = []

        # Try multiple common row selectors used by bid platforms
        row_selectors = [
            "div.solicitation-item",
            "tr.solicitation-row",
            "tr.bid-row",
            ".bid-item",
            "div.opportunity-item",
            "li.solicitation",
            "div.result-item",
        ]
        rows = []
        for sel in row_selectors:
            rows = soup.select(sel)
            if rows:
                break

        scraper = BidNetScraper()
        for row in rows[:max_results]:
            r = scraper.empty_result()
            r["source_name"] = BidNetScraper.SOURCE_NAME
            r["site"] = BidNetScraper.BASE_URL

            link = row.find("a")
            if link:
                r["title"] = link.get_text(strip=True)
                href = link.get("href", "")
                r["source_url"] = urljoin(base_url, href)

            for label, field in [
                ("Number", "number"), ("Agency", "company"),
                ("City", "city"), ("State", "state"),
                ("Due Date", "due_date"), ("Closing Date", "due_date"),
            ]:
                tag = row.find(string=re.compile(label, re.I))
                if tag and tag.parent:
                    sibling = tag.parent.find_next_sibling()
                    if sibling:
                        r[field] = sibling.get_text(strip=True)

            desc_tag = row.select_one(".description, .sol-desc, p")
            if desc_tag:
                r["description"] = desc_tag.get_text(strip=True)[:300]

            r["raw_data"] = {"html_snippet": str(row)[:500]}
            if r["title"]:
                results.append(r)

        return results


# ─── Generic bid-site scraper (fallback) ─────────────────────────────────────

class GenericBidScraper(BaseScraper):
    """
    Generic scraper that attempts to extract bid-like table rows from any URL.
    Used as a fallback for sites not covered by dedicated scrapers.
    """

    SOURCE_NAME = "Generic"

    # Sites known to list public bids/RFPs
    TARGET_SITES = [
        ("https://www.publicpurchase.com/gems/register/register&action=contract&contractId=",
         "PublicPurchase"),
        ("https://www.demandstar.com/app/opportunities/search?keywords=",
         "DemandStar"),
    ]

    def search(self, keywords: str, search_types: List[str], max_results: int = 25) -> List[Dict]:
        results = []
        for url_template, source_name in self.TARGET_SITES:
            if len(results) >= max_results:
                break
            try:
                url = url_template + requests.utils.quote(keywords)
                resp = requests.get(url, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                parsed = self._parse_table(resp.text, source_name, resp.url)
                results.extend(parsed[: max_results - len(results)])
            except requests.RequestException:
                continue

        return results

    def _parse_table(self, html: str, source_name: str, base_url: str) -> List[Dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            r = self.empty_result()
            r["source_name"] = source_name
            r["site"] = _domain(base_url)

            # Best-effort heuristic: first cell with a link = title+URL
            link = row.find("a")
            if link:
                r["title"] = link.get_text(strip=True)
                href = link.get("href", "")
                r["source_url"] = urljoin(base_url, href) if href.startswith("/") else href

            texts = [c.get_text(strip=True) for c in cells]
            if len(texts) >= 2:
                r["description"] = " | ".join(texts[:4])[:300]

            r["raw_data"] = {"cells": texts[:8]}
            if r["title"]:
                results.append(r)

        return results


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_angular_shell(html: str, content_type: str) -> bool:
    """Return True if the response is an empty JavaScript SPA shell."""
    if "json" in content_type:
        return False
    # Angular / React shells are tiny HTML files with app-root or ng-app
    indicators = ["ng-app", "ng-version", "<app-root", "app-root></app-root",
                  "data-ng-app", "angularjs"]
    lower = html.lower()
    has_angular = any(ind in lower for ind in indicators)
    # Also flag if the body is almost empty (< 2 KB is a shell)
    is_tiny = len(html) < ANGULAR_SHELL_MAX_SIZE
    return has_angular or is_tiny


def _nested(d: dict, *keys: str) -> str:
    """Try multiple dot-path keys and return the first non-empty value."""
    for key in keys:
        parts = key.split(".")
        val = d
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part, "")
            else:
                val = ""
                break
        if val:
            return str(val)
    return ""


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url
