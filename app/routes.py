"""
Flask routes / REST API for the Bids Agent application.
"""

import json
import os
from flask import Blueprint, request, jsonify, send_file, current_app

from .database import (
    save_search, update_search_count, get_searches, get_search,
    save_results, get_results, get_all_results,
    save_mapping, get_mappings, delete_mapping,
)
from .export import export_to_excel, DEFAULT_MAPPING
from .scrapers.sam_gov import SamGovScraper
from .scrapers.web_search import WebSearchScraper
from .scrapers.bid_sites import BidNetScraper

api = Blueprint("api", __name__, url_prefix="/api")

# ─── Available scrapers ───────────────────────────────────────────────────────
SCRAPERS = {
    "sam_gov":    SamGovScraper(),
    "web_search": WebSearchScraper(),
    "bidnet":     BidNetScraper(),
}

# Default keyword presets for the language-access use-case
DEFAULT_KEYWORDS = [
    "Translation",
    "Translating",
    "Interpreting",
    "Interpretation",
    "Language Access",
    "OPI",
    "VRI",
]

# ─── Search endpoints ─────────────────────────────────────────────────────────

@api.route("/search", methods=["POST"])
def search():
    """
    POST /api/search
    Body: {
        "keywords": "Translation",
        "search_types": ["RFP", "RFQ"],
        "sources": ["sam_gov", "web_search"],
        "max_results": 25
    }

    Response includes a "source_errors" dict so the UI can surface
    per-source failure messages even when total results > 0.
    """
    body = request.get_json(force=True) or {}
    keywords = (body.get("keywords") or "").strip()
    if not keywords:
        return jsonify({"error": "keywords is required"}), 400

    search_types = body.get("search_types") or ["RFP", "RFQ", "RFI", "Bid"]
    sources = body.get("sources") or list(SCRAPERS.keys())
    max_results = int(body.get("max_results") or 25)

    search_id = save_search(keywords, search_types, sources)

    all_results = []
    source_errors: dict = {}   # key = source_key, value = error string

    for source_key in sources:
        scraper = SCRAPERS.get(source_key)
        if scraper is None:
            source_errors[source_key] = "Unknown source key"
            continue
        try:
            results = scraper.search(keywords, search_types, max_results=max_results)
            all_results.extend(results)
            if not results:
                source_errors[source_key] = (
                    "Search returned 0 results. "
                    "Use the Diagnose button next to this source for details."
                )
        except Exception as exc:
            msg = str(exc)
            source_errors[source_key] = msg
            current_app.logger.warning(
                "Scraper %s failed for keywords=%r types=%r: %s",
                source_key, keywords, search_types, exc,
            )

    # De-duplicate by source_url, keep first occurrence
    seen_urls: set = set()
    unique_results = []
    for r in all_results:
        url_key = r.get("source_url") or r.get("title") or ""
        if url_key not in seen_urls:
            seen_urls.add(url_key)
            unique_results.append(r)

    saved = save_results(search_id, unique_results[:max_results])
    update_search_count(search_id, len(saved))

    return jsonify({
        "search_id": search_id,
        "count": len(saved),
        "results": saved,
        "source_errors": source_errors,
    })


@api.route("/searches", methods=["GET"])
def list_searches():
    return jsonify(get_searches())


@api.route("/searches/<int:search_id>", methods=["GET"])
def get_search_results(search_id):
    search = get_search(search_id)
    if not search:
        return jsonify({"error": "Not found"}), 404
    results = get_results(search_id)
    return jsonify({"search": search, "results": results})


@api.route("/results", methods=["GET"])
def all_results():
    return jsonify(get_all_results())


# ─── Diagnostics endpoint ─────────────────────────────────────────────────────

@api.route("/debug/scraper", methods=["POST"])
def debug_scraper():
    """
    POST /api/debug/scraper
    Body: {
        "source":       "bidnet",
        "keywords":     "Translation",
        "search_types": ["RFP"]
    }

    Returns detailed diagnostic information: HTTP status, response size,
    number of parsed elements, error messages, and a snippet of the raw
    response — so the user can see exactly why a scraper is returning 0 results.
    """
    body = request.get_json(force=True) or {}
    source_key = (body.get("source") or "").strip()
    keywords   = (body.get("keywords") or "Translation").strip()
    search_types = body.get("search_types") or ["RFP", "RFQ", "RFI", "Bid"]

    if not source_key:
        return jsonify({"error": "source is required"}), 400

    scraper = SCRAPERS.get(source_key)
    if scraper is None:
        return jsonify({"error": f"Unknown source '{source_key}'"}), 404

    try:
        diag = scraper.diagnose(keywords, search_types)
    except Exception as exc:
        diag = {
            "source": source_key,
            "error": f"diagnose() raised an unexpected exception: {exc}",
            "elements_found": 0,
        }

    return jsonify(diag)


# ─── Export endpoint ──────────────────────────────────────────────────────────

@api.route("/export", methods=["POST"])
def export():
    """
    POST /api/export
    Body: {
        "search_id": 1,              (optional, exports all if omitted)
        "result_ids": [1,2,3],       (optional, filter by result IDs)
        "column_mapping": [          (optional, use DEFAULT_MAPPING if omitted)
            {"excel_col": "Title", "result_field": "title"},
            ...
        ]
    }
    """
    body = request.get_json(force=True) or {}
    search_id = body.get("search_id")
    result_ids = set(body.get("result_ids") or [])
    column_mapping = body.get("column_mapping") or DEFAULT_MAPPING

    if search_id:
        results = get_results(search_id)
    else:
        results = get_all_results(limit=500)

    if result_ids:
        results = [r for r in results if r.get("id") in result_ids]

    if not results:
        return jsonify({"error": "No results to export"}), 400

    # Strip raw_data (JSON string) so it doesn't pollute the sheet
    clean = []
    for r in results:
        c = dict(r)
        c.pop("raw_data", None)
        clean.append(c)

    file_path = export_to_excel(clean, column_mapping)
    return send_file(
        file_path,
        as_attachment=True,
        download_name=os.path.basename(file_path),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ─── Column mapping CRUD ──────────────────────────────────────────────────────

@api.route("/mappings", methods=["GET"])
def list_mappings():
    return jsonify(get_mappings())


@api.route("/mappings", methods=["POST"])
def create_mapping():
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    field_mappings = body.get("field_mappings")
    if not name or not field_mappings:
        return jsonify({"error": "name and field_mappings are required"}), 400
    save_mapping(name, field_mappings)
    return jsonify({"ok": True}), 201


@api.route("/mappings/<int:mapping_id>", methods=["DELETE"])
def remove_mapping(mapping_id):
    delete_mapping(mapping_id)
    return jsonify({"ok": True})


# ─── Metadata / helpers ───────────────────────────────────────────────────────

@api.route("/keywords/defaults", methods=["GET"])
def default_keywords():
    return jsonify(DEFAULT_KEYWORDS)


@api.route("/sources", methods=["GET"])
def list_sources():
    return jsonify([
        {"key": "sam_gov",    "label": "SAM.gov (Federal)"},
        {"key": "web_search", "label": "Web Search (DuckDuckGo)"},
        {"key": "bidnet",     "label": "BidNet Direct"},
    ])


@api.route("/fields", methods=["GET"])
def list_fields():
    """Return the canonical result fields available for column mapping."""
    return jsonify([
        {"key": "title",       "label": "Name / Title"},
        {"key": "number",      "label": "Number"},
        {"key": "site",        "label": "Site"},
        {"key": "description", "label": "Description"},
        {"key": "city",        "label": "City"},
        {"key": "state",       "label": "State"},
        {"key": "company",     "label": "Company / Agency"},
        {"key": "due_date",    "label": "Due Date"},
        {"key": "source_url",  "label": "Source URL"},
        {"key": "source_name", "label": "Source Name"},
    ])
