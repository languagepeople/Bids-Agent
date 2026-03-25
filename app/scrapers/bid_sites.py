"""
Scrapers for public-sector bid aggregator websites.

BidNet Direct
-------------
BidNet Direct renders its search results via AngularJS (client-side JavaScript).
A plain GET request to their HTML route returns only the Angular application
shell — the actual solicitation data is fetched by JavaScript at runtime.

Strategy (tried in order):
1. Several known JSON REST API patterns (all returned 404 in testing).
2. The public HTML search page via GET and POST (returns 415 from their CDN).
3. DuckDuckGo `site:bidnetdirect.com` search — BidNet pages are publicly
   indexed, so this reliably returns real solicitations without needing
   direct API access.  Results link directly to the BidNet solicitation pages.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Tuple
from urllib.parse import urljoin, urlparse, quote
from .base_scraper import BaseScraper, DIAG_PREVIEW_CHARS
# web_search symbols used by the DuckDuckGo site-search fallback
from .web_search import DDG_URL, RESULT_SELECTORS, _extract_url, _domain as _ddg_domain, HEADERS as DDG_HEADERS

# Minimum HTML size (bytes) that suggests a real page vs an Angular app shell.
# Angular shells are tiny stub files (< ~2 KB) before JS hydration.
ANGULAR_SHELL_MAX_SIZE = 2000

# Browser-like headers for HTML page requests
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bidnetdirect.com/",
}

# JSON-specific headers for API requests
API_HEADERS = {
    "User-Agent": BROWSER_HEADERS["User-Agent"],
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bidnetdirect.com/",
}

# Keep HEADERS alias for GenericBidScraper compatibility
HEADERS = BROWSER_HEADERS


# ─── BidNet Direct ───────────────────────────────────────────────────────────

class BidNetScraper(BaseScraper):
    SOURCE_NAME = "BidNet Direct"
    BASE_URL = "https://www.bidnetdirect.com"

    # Candidate JSON API endpoints tried in order.
    # BidNet uses an AngularJS SPA — actual data comes from internal JSON endpoints.
    CANDIDATE_APIS = [
        "https://www.bidnetdirect.com/api/v1/public/solicitations/search",
        "https://www.bidnetdirect.com/api/v1/publicSolicitations",
        "https://www.bidnetdirect.com/api/public/opportunities/search",
        "https://www.bidnetdirect.com/api/v2/public/solicitations/search",
    ]

    # HTML search page — tried last; returns 415 when CDN rejects bot UA
    HTML_SEARCH_URL = "https://www.bidnetdirect.com/public/solicitations/search"

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

        # ── Step 1: try JSON API endpoints ────────────────────────────────────
        for api_url in self.CANDIDATE_APIS:
            attempt: Dict[str, Any] = {"url": api_url}
            try:
                resp = requests.get(
                    api_url,
                    params={"q": keywords, "keywords": keywords,
                            "page": 1, "pageSize": max_results},
                    headers=API_HEADERS,
                    timeout=15,
                )
                attempt["http_status"] = resp.status_code
                attempt["response_size"] = len(resp.content)
                attempt["content_type"] = resp.headers.get("Content-Type", "")
                attempt["response_preview"] = resp.text[:DIAG_PREVIEW_CHARS]

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
                        "JSON response contained 0 solicitations. "
                        f"Keys: {list(resp.json().keys()) if isinstance(resp.json(), dict) else 'list'}"
                    )
                else:
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

        # ── Step 2: try HTML search page (GET then POST) ──────────────────────
        for method, extra_kw in [("GET", {}), ("POST", {"data": {"q": keywords}})]:
            attempt = {"url": self.HTML_SEARCH_URL, "method": method}
            try:
                req_kwargs: Dict[str, Any] = {
                    "headers": BROWSER_HEADERS,
                    "timeout": 15,
                    **extra_kw,
                }
                if method == "GET":
                    req_kwargs["params"] = {"q": keywords}
                    resp = requests.get(self.HTML_SEARCH_URL, **req_kwargs)
                else:
                    resp = requests.post(self.HTML_SEARCH_URL, **req_kwargs)

                attempt["http_status"] = resp.status_code
                attempt["response_size"] = len(resp.content)
                attempt["content_type"] = resp.headers.get("Content-Type", "")
                attempt["response_preview"] = resp.text[:DIAG_PREVIEW_CHARS]

                if resp.status_code == 415:
                    attempt["error"] = (
                        f"HTTP 415 — server rejected the {method} request (CDN/WAF bot protection). "
                        "BidNet requires a real browser session with cookies and JS execution."
                    )
                    diag["attempts"].append(attempt)
                    continue

                if resp.status_code == 404:
                    attempt["error"] = "404 Not Found"
                    diag["attempts"].append(attempt)
                    continue

                if _is_angular_shell(resp.text, resp.headers.get("Content-Type", "")):
                    attempt["error"] = "Received Angular app shell — results rendered by JavaScript"
                    diag["attempts"].append(attempt)
                    continue

                resp.raise_for_status()
                results = self._parse_html(resp.text, self.HTML_SEARCH_URL, max_results)
                if results:
                    diag["url"] = self.HTML_SEARCH_URL
                    diag["http_status"] = resp.status_code
                    diag["response_size"] = len(resp.content)
                    diag["elements_found"] = len(results)
                    diag["response_preview"] = resp.text[:DIAG_PREVIEW_CHARS]
                    diag["attempts"].append(attempt)
                    return results, diag
                attempt["error"] = "HTML page returned but 0 solicitation rows matched"

            except requests.exceptions.HTTPError as exc:
                attempt["error"] = f"HTTP error: {exc}"
            except requests.RequestException as exc:
                attempt["error"] = str(exc)
            except Exception as exc:
                attempt["error"] = f"Unexpected error: {exc}"

            diag["attempts"].append(attempt)

        # ── Step 3: DuckDuckGo site:bidnetdirect.com fallback ─────────────────
        fallback_results, fallback_diag = self._duckduckgo_site_search(
            keywords, search_types, max_results
        )
        diag["duckduckgo_fallback"] = fallback_diag

        if fallback_results:
            diag["url"] = "DuckDuckGo site:bidnetdirect.com (fallback)"
            diag["elements_found"] = len(fallback_results)
            diag["error"] = None
            return fallback_results, diag

        # All methods exhausted
        api_errors = "; ".join(
            f"[{a['url'].split('/')[-1]}] {a.get('error', 'unknown')}"
            for a in diag["attempts"]
        )
        diag["error"] = (
            "All BidNet Direct scraping methods failed. "
            f"Direct API attempts: {api_errors}. "
            f"DuckDuckGo fallback: {fallback_diag.get('error', 'returned 0 results')}."
        )
        return [], diag

    def _duckduckgo_site_search(self, keywords: str, search_types: List[str],
                                 max_results: int) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Search DuckDuckGo for `site:bidnetdirect.com <keywords>`.
        BidNet solicitation pages are publicly indexed, so this returns real results
        when BidNet's own API is inaccessible.
        """
        query = f"site:bidnetdirect.com {keywords} solicitation"
        diag: Dict[str, Any] = {
            "query": query,
            "method": "DuckDuckGo site:bidnetdirect.com",
            "http_status": None,
            "response_size": None,
            "error": None,
            "elements_found": 0,
            "response_preview": None,
        }

        try:
            session = requests.Session()
            resp = session.post(
                DDG_URL,
                data={"q": query, "kl": "us-en"},
                headers=DDG_HEADERS,
                timeout=15,
                allow_redirects=True,
            )
            diag["http_status"] = resp.status_code
            diag["response_size"] = len(resp.content)
            diag["response_preview"] = resp.text[:DIAG_PREVIEW_CHARS]
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            diag["error"] = f"Connection failed: {exc}"
            return [], diag
        except requests.exceptions.HTTPError as exc:
            diag["error"] = f"HTTP {resp.status_code}: {resp.text[:100]}"
            return [], diag
        except requests.RequestException as exc:
            diag["error"] = str(exc)
            return [], diag

        soup = BeautifulSoup(resp.text, "lxml")

        # Find matching selector
        title_sel = RESULT_SELECTORS[0][0]
        snippet_sel = RESULT_SELECTORS[0][1]
        for ts, ss in RESULT_SELECTORS:
            if soup.select(ts):
                title_sel, snippet_sel = ts, ss
                break

        results = []
        for result_div in soup.select(".result, .web-result")[:max_results]:
            r = self.empty_result()

            title_tag = result_div.select_one(title_sel)
            if not title_tag:
                continue

            r["title"] = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            real_url = _extract_url(href)
            r["source_url"] = real_url
            r["site"] = self.BASE_URL
            r["source_name"] = self.SOURCE_NAME

            snippet_tag = result_div.select_one(snippet_sel)
            if snippet_tag:
                r["description"] = snippet_tag.get_text(strip=True)[:300]

            r["raw_data"] = {"query": query, "method": "duckduckgo_site_search"}

            # Only keep results that point to BidNet (check the parsed hostname,
            # not a substring, to avoid matching URLs like evil.com/bidnetdirect.com)
            try:
                hostname = urlparse(real_url).netloc.lower()
            except Exception:
                hostname = ""
            if r["title"] and (hostname == "www.bidnetdirect.com" or
                                hostname == "bidnetdirect.com"):
                results.append(r)

        diag["elements_found"] = len(results)
        if not results and not diag.get("error"):
            if not soup.select(title_sel):
                diag["error"] = (
                    "DuckDuckGo returned no results — the page may have no matching entries "
                    "or DuckDuckGo rate-limited the request."
                )
            else:
                diag["error"] = (
                    "DuckDuckGo returned results but none pointed to bidnetdirect.com. "
                    "BidNet pages may not be indexed for these keywords."
                )
        return results, diag

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
                resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
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
    indicators = ["ng-app", "ng-version", "<app-root", "app-root></app-root",
                  "data-ng-app", "angularjs"]
    lower = html.lower()
    has_angular = any(ind in lower for ind in indicators)
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
