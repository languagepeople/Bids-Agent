"""
Scrapers for public-sector bid aggregator websites.

BidNet Direct
-------------
BidNet Direct renders its search results via AngularJS (client-side JavaScript).
A plain HTTP request returns only the Angular application shell — real data is
fetched by JavaScript at runtime.

Strategy (tried in order):
0. Playwright headless Chromium — executes JavaScript exactly like a real browser.
   Requires: pip install playwright && playwright install chromium
1. Several known JSON REST API patterns (all return 404 in practice).
2. The public HTML search page via GET and POST (CDN returns 415/405).
3. DuckDuckGo `site:bidnetdirect.com` — BidNet pages are publicly indexed.
4. Bing `site:bidnetdirect.com` — used when DuckDuckGo is rate-limited.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Tuple, Optional
from urllib.parse import urljoin, urlparse, quote
from .base_scraper import BaseScraper, DIAG_PREVIEW_CHARS
# web_search symbols used by the DuckDuckGo site-search fallback
from .web_search import DDG_URL, RESULT_SELECTORS, _extract_url, _domain as _ddg_domain, HEADERS as DDG_HEADERS

# Minimum HTML size (bytes) that suggests a real page vs an Angular app shell.
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

# CSS selectors tried in order on BidNet's JavaScript-rendered DOM.
# AngularJS (ng-repeat) renders real <tr> rows; Angular 2+ uses component tags.
BIDNET_ROW_SELECTORS = [
    "tr[ng-repeat]",                        # AngularJS ng-repeat rows
    "tr[data-ng-repeat]",                   # alternate AngularJS syntax
    ".solicitation-list-item",
    ".solicitation-row",
    "app-solicitation-item",                # Angular 2+ component
    "app-bid-item",
    ".bid-item",
    ".opportunity-item",
    "tbody tr",                             # generic table fallback
]

# ─── Playwright setup instructions shown to users ────────────────────────────
PLAYWRIGHT_SETUP = (
    "pip install playwright && playwright install chromium"
)
PLAYWRIGHT_NOT_INSTALLED = (
    "Playwright is not installed. "
    "Playwright is required for BidNet Direct because their site loads results "
    "via JavaScript. Install it once with:\n\n"
    "    pip install playwright\n"
    "    playwright install chromium\n\n"
    "Then restart the app."
)


# ─── BidNet Direct ───────────────────────────────────────────────────────────

class BidNetScraper(BaseScraper):
    SOURCE_NAME = "BidNet Direct"
    BASE_URL = "https://www.bidnetdirect.com"

    # Candidate JSON API endpoints tried as a quick check (mostly 404 in practice)
    CANDIDATE_APIS = [
        "https://www.bidnetdirect.com/api/v1/public/solicitations/search",
        "https://www.bidnetdirect.com/api/v1/publicSolicitations",
        "https://www.bidnetdirect.com/api/public/opportunities/search",
        "https://www.bidnetdirect.com/api/v2/public/solicitations/search",
    ]

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
            "playwright_attempt": None,
            "attempts": [],
            "duckduckgo_fallback": None,
            "bing_fallback": None,
        }

        # ── Step 0: Playwright headless browser (primary — executes JS) ────────
        pw_results, pw_diag = self._playwright_bidnet_search(keywords, max_results)
        diag["playwright_attempt"] = pw_diag

        if pw_results:
            diag["url"] = pw_diag.get("url")
            diag["http_status"] = pw_diag.get("http_status")
            diag["response_size"] = pw_diag.get("response_size")
            diag["elements_found"] = len(pw_results)
            return pw_results, diag

        # Playwright failed or not installed — record the error and continue
        if pw_diag.get("error"):
            # Surface "not installed" prominently so the user knows what to do
            if "not installed" in pw_diag["error"] or "executable" in pw_diag["error"].lower():
                diag["playwright_not_installed"] = True

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

                if resp.status_code in (415, 405):
                    attempt["error"] = (
                        f"HTTP {resp.status_code} — server rejected the {method} request "
                        "(CDN/WAF bot protection). BidNet requires a real browser."
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

        # ── Step 3: DuckDuckGo site:bidnetdirect.com ──────────────────────────
        fallback_results, fallback_diag = self._site_search(
            "DuckDuckGo", keywords, max_results
        )
        diag["duckduckgo_fallback"] = fallback_diag

        if fallback_results:
            diag["url"] = "DuckDuckGo site:bidnetdirect.com (fallback)"
            diag["elements_found"] = len(fallback_results)
            diag["error"] = None
            return fallback_results, diag

        # ── Step 4: Bing site:bidnetdirect.com ────────────────────────────────
        bing_results, bing_diag = self._site_search("Bing", keywords, max_results)
        diag["bing_fallback"] = bing_diag

        if bing_results:
            diag["url"] = "Bing site:bidnetdirect.com (fallback)"
            diag["elements_found"] = len(bing_results)
            diag["error"] = None
            return bing_results, diag

        # All methods exhausted — compose a helpful error message
        if diag.get("playwright_not_installed"):
            diag["error"] = (
                "BidNet Direct search requires Playwright (headless browser). "
                "Install it once with:\n\n"
                "    pip install playwright\n"
                "    playwright install chromium\n\n"
                "Then restart the app and search again."
            )
        else:
            pw_err = pw_diag.get("error", "unknown error")
            diag["error"] = (
                f"All BidNet Direct scraping methods failed. "
                f"Playwright: {pw_err}. "
                f"DuckDuckGo fallback: {fallback_diag.get('error', '0 results')}. "
                f"Bing fallback: {bing_diag.get('error', '0 results')}."
            )
        return [], diag

    # ── Playwright headless browser ───────────────────────────────────────────

    def _playwright_bidnet_search(self, keywords: str, max_results: int
                                   ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Use Playwright headless Chromium to navigate BidNet, execute its
        JavaScript, and extract the rendered solicitation list.

        Install once:
            pip install playwright
            playwright install chromium
        """
        diag: Dict[str, Any] = {
            "method": "Playwright headless Chromium",
            "url": None,
            "http_status": None,
            "response_size": None,
            "error": None,
            "elements_found": 0,
            "selector_used": None,
            "response_preview": None,
        }

        # ── check Playwright is importable ────────────────────────────────────
        try:
            from playwright.sync_api import sync_playwright
            from playwright.sync_api import TimeoutError as PWTimeout
            from playwright._impl._errors import Error as PWError
        except ImportError:
            diag["error"] = PLAYWRIGHT_NOT_INSTALLED
            return [], diag

        search_url = f"{self.BASE_URL}/public/solicitations?keywords={quote(keywords)}"
        diag["url"] = search_url

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
                ctx = browser.new_context(
                    user_agent=BROWSER_HEADERS["User-Agent"],
                    viewport={"width": 1280, "height": 800},
                    java_script_enabled=True,
                )
                page = ctx.new_page()

                # Navigate and wait for network activity to settle so Angular
                # has time to fetch and render the solicitation list
                response = page.goto(search_url, wait_until="networkidle", timeout=20_000)
                if response:
                    diag["http_status"] = response.status

                # Try to find the solicitation list container.
                # Per-selector timeout is short (1.5 s) because the DOM is already fully
                # rendered after networkidle — elements are either present or they aren't.
                found_sel: Optional[str] = None
                for sel in BIDNET_ROW_SELECTORS:
                    try:
                        page.wait_for_selector(sel, timeout=1_500)
                        found_sel = sel
                        break
                    except PWTimeout:
                        continue

                page_html = page.content()
                diag["response_size"] = len(page_html.encode())
                diag["response_preview"] = page_html[:DIAG_PREVIEW_CHARS]

                if not found_sel:
                    # Try a broader BeautifulSoup parse as last-ditch
                    results = self._parse_html(page_html, search_url, max_results)
                    if results:
                        diag["elements_found"] = len(results)
                        diag["selector_used"] = "BeautifulSoup (broad)"
                        browser.close()
                        return results, diag

                    diag["error"] = (
                        "Playwright loaded BidNet and waited for JavaScript to render, "
                        "but no solicitation elements were found. "
                        "The site's DOM structure may have changed."
                    )
                    browser.close()
                    return [], diag

                diag["selector_used"] = found_sel

                # Extract structured data from the rendered DOM via JavaScript
                rows_data: List[Dict] = page.evaluate(
                    """(sel) => {
                        const rows = Array.from(document.querySelectorAll(sel));
                        return rows.slice(0, 50).map(row => {
                            const links = Array.from(row.querySelectorAll('a'));
                            const cells = Array.from(row.querySelectorAll('td'));
                            const firstLink = links[0] || null;
                            const getText = el => el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
                            // Look for common field labels
                            const findField = (labels) => {
                                for (const label of labels) {
                                    const el = row.querySelector(
                                        `[data-label*="${label}"], .${label.toLowerCase()}, ` +
                                        `[class*="${label.toLowerCase()}"]`
                                    );
                                    if (el) return getText(el);
                                }
                                return '';
                            };
                            return {
                                title: getText(row.querySelector(
                                    '.title, .solicitation-title, .bid-title, h3, h4, ' +
                                    '[class*="title"], [class*="name"]'
                                )) || (firstLink ? getText(firstLink) : ''),
                                url: firstLink ? firstLink.href : '',
                                number: findField(['number', 'solicitationNumber', 'bidNumber']),
                                agency: findField(['agency', 'organization', 'buyer']),
                                due_date: findField(['due', 'closing', 'deadline', 'responseDate']),
                                city: findField(['city']),
                                state: findField(['state']),
                                description: getText(row.querySelector(
                                    '.description, .summary, .details, p'
                                )),
                                cells: cells.slice(0, 8).map(c => getText(c)),
                                full_text: getText(row).slice(0, 500),
                            };
                        });
                    }""",
                    found_sel,
                )
                browser.close()
        except PWError as exc:
            err = str(exc)
            if "executable" in err.lower() or "chromium" in err.lower():
                diag["error"] = (
                    "Playwright is installed but the Chromium browser binary is missing. "
                    "Run once: playwright install chromium"
                )
            else:
                diag["error"] = f"Playwright browser error: {exc}"
            return [], diag
        except Exception as exc:
            diag["error"] = f"Playwright error: {exc}"
            return [], diag

        # Parse the extracted rows into our result schema
        results = []
        for item in rows_data[:max_results]:
            if not isinstance(item, dict):
                continue

            title = item.get("title", "").strip()
            if not title:
                # Fall back to first non-empty cell text
                cells = item.get("cells", [])
                title = next((c for c in cells if len(c) > 5), "")
            if not title:
                continue

            r = self.empty_result()
            r["title"]       = title
            r["number"]      = item.get("number", "")
            r["company"]     = item.get("agency", "")
            r["city"]        = item.get("city", "")
            r["state"]       = item.get("state", "")
            r["due_date"]    = (item.get("due_date") or "")[:10]
            r["description"] = item.get("description") or item.get("full_text", "")[:300]
            r["source_url"]  = item.get("url", "")
            r["site"]        = self.BASE_URL
            r["source_name"] = self.SOURCE_NAME
            r["raw_data"]    = {"cells": item.get("cells", []), "method": "playwright"}

            # If the scraper extracted table cells but no specific fields,
            # try to infer title/agency from cell content
            cells = item.get("cells", [])
            if not r["company"] and len(cells) > 1:
                r["company"] = cells[1]
            if not r["due_date"] and len(cells) > 3:
                # Cells with date-like content (YYYY or MM/DD)
                for cell in cells[2:]:
                    if re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}', cell):
                        r["due_date"] = cell[:10]
                        break

            results.append(r)

        diag["elements_found"] = len(results)
        if not results:
            diag["error"] = (
                f"Playwright found elements matching '{found_sel}' "
                "but could not extract any titled solicitations from them."
            )
        return results, diag

    # ── Search-engine site: fallback ──────────────────────────────────────────

    def _site_search(self, engine: str, keywords: str, max_results: int
                     ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Search `site:bidnetdirect.com <keywords>` via DuckDuckGo or Bing.
        BidNet solicitation pages are publicly indexed, so this returns real
        results when their own site blocks direct scraping.
        """
        query = f"site:bidnetdirect.com {keywords}"
        diag: Dict[str, Any] = {
            "engine": engine,
            "query": query,
            "http_status": None,
            "response_size": None,
            "error": None,
            "elements_found": 0,
            "response_preview": None,
        }

        try:
            session = requests.Session()
            if engine == "DuckDuckGo":
                resp = session.post(
                    DDG_URL,
                    data={"q": query, "kl": "us-en"},
                    headers=DDG_HEADERS,
                    timeout=15,
                    allow_redirects=True,
                )
            else:
                # Bing web search
                resp = session.get(
                    "https://www.bing.com/search",
                    params={"q": query, "count": max_results},
                    headers={
                        **BROWSER_HEADERS,
                        "Referer": "https://www.bing.com/",
                    },
                    timeout=15,
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

        if engine == "DuckDuckGo":
            results = self._parse_ddg_results(soup, query, max_results)
        else:
            results = self._parse_bing_results(soup, query, max_results)

        diag["elements_found"] = len(results)
        if not results and not diag.get("error"):
            diag["error"] = (
                f"{engine} returned a page but 0 BidNet results were found. "
                "The search engine may have returned a CAPTCHA or rate-limit page."
            )
        return results, diag

    def _parse_ddg_results(self, soup: BeautifulSoup, query: str, max_results: int) -> List[Dict]:
        results = []
        title_sel, snippet_sel = RESULT_SELECTORS[0]
        for ts, ss in RESULT_SELECTORS:
            if soup.select(ts):
                title_sel, snippet_sel = ts, ss
                break

        for result_div in soup.select(".result, .web-result")[:max_results]:
            r = self._result_from_search_div(result_div, title_sel, snippet_sel, query)
            if r:
                results.append(r)
        return results

    def _parse_bing_results(self, soup: BeautifulSoup, query: str, max_results: int) -> List[Dict]:
        """Parse Bing search result HTML."""
        results = []
        # Bing uses <li class="b_algo"> for organic results
        for item in soup.select("li.b_algo")[:max_results]:
            title_tag = item.select_one("h2 a")
            snippet_tag = item.select_one(".b_caption p, .b_algoSlug")
            if not title_tag:
                continue
            real_url = title_tag.get("href", "")
            try:
                hostname = urlparse(real_url).netloc.lower()
            except Exception:
                hostname = ""
            if hostname not in ("www.bidnetdirect.com", "bidnetdirect.com"):
                continue
            r = self.empty_result()
            r["title"]       = title_tag.get_text(strip=True)
            r["source_url"]  = real_url
            r["site"]        = self.BASE_URL
            r["source_name"] = self.SOURCE_NAME
            r["description"] = snippet_tag.get_text(strip=True)[:300] if snippet_tag else ""
            r["raw_data"]    = {"query": query, "method": "bing_site_search"}
            results.append(r)
        return results

    def _result_from_search_div(self, result_div: Any, title_sel: str, snippet_sel: str,
                                  query: str) -> Optional[Dict]:
        """Convert a DuckDuckGo result div into a result dict, keeping BidNet URLs only."""
        r = self.empty_result()
        title_tag = result_div.select_one(title_sel)
        if not title_tag:
            return None
        r["title"] = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        real_url = _extract_url(href)
        try:
            hostname = urlparse(real_url).netloc.lower()
        except Exception:
            hostname = ""
        if hostname not in ("www.bidnetdirect.com", "bidnetdirect.com"):
            return None
        r["source_url"]  = real_url
        r["site"]        = self.BASE_URL
        r["source_name"] = self.SOURCE_NAME
        snippet_tag = result_div.select_one(snippet_sel)
        if snippet_tag:
            r["description"] = snippet_tag.get_text(strip=True)[:300]
        r["raw_data"] = {"query": query, "method": "ddg_site_search"}
        return r

    # ── JSON / HTML parsers ────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(data: Any, max_results: int) -> List[Dict]:
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
        soup = BeautifulSoup(html, "lxml")
        results = []

        rows = []
        for sel in BIDNET_ROW_SELECTORS:
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
    """Generic scraper that extracts bid-like table rows from any URL."""

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

