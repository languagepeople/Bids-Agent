"""
Excel export using openpyxl.

The caller supplies:
  - results : list of result dicts
  - column_mapping : ordered list of {"excel_col": "Title", "result_field": "title"} dicts
  - file_path : destination path for the .xlsx file
"""

import os
from datetime import datetime
from typing import List, Dict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# Default mapping if the user hasn't customised one
DEFAULT_MAPPING = [
    {"excel_col": "Name / Title",    "result_field": "title"},
    {"excel_col": "Number",          "result_field": "number"},
    {"excel_col": "Site",            "result_field": "site"},
    {"excel_col": "Description",     "result_field": "description"},
    {"excel_col": "City",            "result_field": "city"},
    {"excel_col": "State",           "result_field": "state"},
    {"excel_col": "Company / Agency","result_field": "company"},
    {"excel_col": "Due Date",        "result_field": "due_date"},
    {"excel_col": "Source URL",      "result_field": "source_url"},
]


def export_to_excel(
    results: List[Dict],
    column_mapping: List[Dict] = None,
    file_path: str = None,
) -> str:
    """
    Write results to an .xlsx file.

    Returns the absolute path of the created file.
    """
    if column_mapping is None:
        column_mapping = DEFAULT_MAPPING

    if file_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", f"bids_export_{ts}.xlsx"
        )

    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bids & RFPs"

    # ── Header row ───────────────────────────────────────────────────────────
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    for col_idx, mapping in enumerate(column_mapping, start=1):
        cell = ws.cell(row=1, column=col_idx, value=mapping["excel_col"])
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = thin_border

    ws.row_dimensions[1].height = 30

    # ── Data rows ────────────────────────────────────────────────────────────
    alt_fill = PatternFill("solid", fgColor="D6E4F0")
    data_align = Alignment(vertical="top", wrap_text=True)

    for row_idx, result in enumerate(results, start=2):
        fill = alt_fill if row_idx % 2 == 0 else PatternFill()
        for col_idx, mapping in enumerate(column_mapping, start=1):
            value = result.get(mapping["result_field"]) or ""
            cell = ws.cell(row=row_idx, column=col_idx, value=str(value))
            cell.fill = fill
            cell.alignment = data_align
            cell.border = thin_border

            # Make URL columns clickable (value is already str-converted above)
            if mapping["result_field"] in ("source_url", "site") and value.startswith("http"):
                cell.hyperlink = value
                cell.font = Font(color="0563C1", underline="single")

    # ── Column widths ────────────────────────────────────────────────────────
    col_widths = {
        "Name / Title": 40,
        "Number": 20,
        "Site": 30,
        "Description": 60,
        "City": 18,
        "State": 18,
        "Company / Agency": 35,
        "Due Date": 15,
        "Source URL": 50,
    }
    for col_idx, mapping in enumerate(column_mapping, start=1):
        width = col_widths.get(mapping["excel_col"], 20)
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # ── Freeze header row ────────────────────────────────────────────────────
    ws.freeze_panes = "A2"

    # ── Auto-filter ──────────────────────────────────────────────────────────
    last_col = get_column_letter(len(column_mapping))
    ws.auto_filter.ref = f"A1:{last_col}{len(results) + 1}"

    wb.save(file_path)
    return file_path
