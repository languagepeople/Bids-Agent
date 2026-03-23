"""
Dedicated scrapers for popular public-sector bid aggregator websites:
  - BidNet Direct  (https://www.bidnetdirect.com)
  - OpenGovBids / PublicPurchase  (https://www.publicpurchase.com)
  - BidSync  (https://www.bidsync.com)

These sites publish bids publicly; we scrape their search pages.
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin, urlparse
from .base_scraper import BaseScraper

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ─── BidNet Direct ───────────────────────────────────────────────────────────

class BidNetScraper(BaseScraper):
    SOURCE_NAME = "BidNet Direct"
    BASE_URL = "https://www.bidnetdirect.com"
    SEARCH_URL = "https://www.bidnetdirect.com/public/solicitations/search"

    def search(self, keywords: str, search_types: List[str], max_results: int = 25) -> List[Dict]:
        params = {"q": keywords, "page": 1}
        try:
            resp = requests.get(self.SEARCH_URL, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.RequestException:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        for row in soup.select("div.solicitation-item, tr.sol-row, .bid-item")[:max_results]:
            r = self.empty_result()
            r["source_name"] = self.SOURCE_NAME

            title_tag = row.select_one("a.sol-title, .bid-title a, h3 a, h4 a")
            if title_tag:
                r["title"] = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                r["source_url"] = urljoin(self.BASE_URL, href)
                r["site"] = self.BASE_URL

            for label, field in [("Number", "number"), ("Agency", "company"),
                                  ("City", "city"), ("State", "state"),
                                  ("Due Date", "due_date"), ("Closing Date", "due_date")]:
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


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url
