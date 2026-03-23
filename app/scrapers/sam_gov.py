"""
SAM.gov scraper — uses the public SAM.gov Opportunities API v2.

No API key is required for basic read access.
Docs: https://open.gsa.gov/api/get-opportunities-public-api/
"""

import re
import requests
from typing import List, Dict, Any
from .base_scraper import BaseScraper, DIAG_PREVIEW_CHARS

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
        results, _diag = self._fetch(keywords, search_types, max_results)
        return results

    def diagnose(self, keywords: str, search_types: List[str]) -> Dict[str, Any]:
        """Return detailed diagnostic information about a search attempt."""
        _results, diag = self._fetch(keywords, search_types, max_results=5)
        return diag

    def _fetch(self, keywords: str, search_types: List[str], max_results: int = 25):
        notice_types = set()
        for st in search_types:
            notice_types.update(NOTICE_TYPE_MAP.get(st, []))

        params = {
            "keywords": keywords,
            "limit": min(max_results, 25),
            "offset": 0,
        }
        if notice_types:
            params["ptype"] = ",".join(notice_types)

        headers = {"Accept": "application/json"}
        diag: Dict[str, Any] = {
            "source": self.SOURCE_NAME,
            "url": SAM_API_URL,
            "params": params,
            "http_status": None,
            "response_size": None,
            "error": None,
            "elements_found": 0,
            "response_preview": None,
        }

        try:
            resp = requests.get(SAM_API_URL, params=params, headers=headers, timeout=15)
            diag["http_status"] = resp.status_code
            diag["response_size"] = len(resp.content)
            diag["response_preview"] = resp.text[:DIAG_PREVIEW_CHARS]
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.ConnectionError as exc:
            diag["error"] = f"Connection failed — cannot reach api.sam.gov: {exc}"
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
        except ValueError as exc:
            diag["error"] = f"Invalid JSON response: {exc}"
            return [], diag

        opportunities = data.get("opportunitiesData", [])
        diag["elements_found"] = len(opportunities)

        if not opportunities:
            # Surface any API-level error message
            api_msg = data.get("message") or data.get("error") or data.get("description")
            if api_msg:
                diag["error"] = f"API message: {api_msg}"

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

        return results, diag


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
