"""
SAM.gov scraper — uses the public SAM.gov Opportunities API v2.

No API key is required for basic read access.
Docs: https://open.gsa.gov/api/get-opportunities-public-api/
"""

import re
import requests
from typing import List, Dict
from .base_scraper import BaseScraper

SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"

# Mapping from our internal type names to SAM notice types
NOTICE_TYPE_MAP = {
    "RFP": ["o"],        # Solicitation
    "RFQ": ["k"],        # Combined Synopsis/Solicitation  (closest)
    "RFI": ["r"],        # Sources Sought
    "Bid": ["o", "k"],
}


class SamGovScraper(BaseScraper):
    """Search federal opportunities on SAM.gov."""

    SOURCE_NAME = "SAM.gov"

    def search(self, keywords: str, search_types: List[str], max_results: int = 25) -> List[Dict]:
        notice_types = set()
        for st in search_types:
            notice_types.update(NOTICE_TYPE_MAP.get(st, []))

        params = {
            "keywords": keywords,
            "limit": min(max_results, 25),
            "offset": 0,
            "postedFrom": "",
            "postedTo": "",
        }
        if notice_types:
            params["ptype"] = ",".join(notice_types)

        headers = {"Accept": "application/json"}

        try:
            resp = requests.get(SAM_API_URL, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            return []
        except ValueError:
            return []

        opportunities = data.get("opportunitiesData", [])
        results = []
        for opp in opportunities[:max_results]:
            r = self.empty_result()
            r["title"] = opp.get("title", "")
            r["number"] = opp.get("solicitationNumber", "")
            r["site"] = f"https://sam.gov/opp/{opp.get('noticeId', '')}/view"
            r["description"] = _truncate(opp.get("description", ""), 300)
            r["company"] = opp.get("fullParentPathName", opp.get("organizationName", ""))
            r["city"] = opp.get("placeOfPerformance", {}).get("city", {}).get("name", "")
            r["state"] = opp.get("placeOfPerformance", {}).get("state", {}).get("name", "")
            r["due_date"] = _format_date(opp.get("responseDeadLine") or opp.get("archiveDate", ""))
            r["source_url"] = r["site"]
            r["source_name"] = self.SOURCE_NAME
            r["raw_data"] = opp
            results.append(r)

        return results


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + ("…" if len(text) > max_len else "")


def _format_date(raw: str) -> str:
    if not raw:
        return ""
    # SAM.gov returns ISO-ish strings; just take the date part
    return raw[:10]
