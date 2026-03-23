# Bids Agent — Lead Generation

A web-based visual agent that searches for government bids, RFPs, RFQs, and
RFIs using configurable keywords and exports the results to Excel.

## Features

- **Visual browser interface** — runs in any modern browser
- **Keyword search** — pre-loaded with language-access keywords
  (Translation, Interpreting, Language Access, OPI, VRI, …) plus custom input
- **Multiple data sources**
  - SAM.gov (US Federal Opportunities API)
  - Web Search via DuckDuckGo (no API key required)
  - BidNet Direct
- **Document type filters** — Bid, RFP, RFQ, RFI
- **Results table** — view Name, Number, Site, Description, City, State,
  Company/Agency, Due Date with clickable links
- **Column Mapper** — drag-and-drop editor lets you map any result field to
  any Excel column name; save named mappings for re-use
- **Excel export** — styled .xlsx with auto-filter, frozen header, hyperlinks
- **Search History** — all searches and results stored locally in SQLite

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
python main.py

# 3. Open in your browser
# http://localhost:5000
```

## Project Structure

```
Bids-Agent/
├── main.py               # Flask entry point
├── requirements.txt
├── app/
│   ├── database.py       # SQLite storage
│   ├── export.py         # Excel export (openpyxl)
│   ├── routes.py         # REST API endpoints
│   └── scrapers/
│       ├── base_scraper.py
│       ├── sam_gov.py    # SAM.gov Opportunities API
│       ├── web_search.py # DuckDuckGo HTML scraping
│       └── bid_sites.py  # BidNet Direct + generic
├── templates/
│   └── index.html        # Single-page application shell
├── static/
│   ├── css/style.css
│   └── js/app.js
└── data/                 # SQLite DB + exported .xlsx files (git-ignored)
```

## Usage

1. **Search** — select keywords (click presets or type custom), choose
   document types and sources, then click **Search**.
2. **Review** — a preview table appears immediately. Switch to the
   **Results** tab for the full list.
3. **Map columns** — click **Customize…** to open the column mapper. Drag
   field chips onto column slots or use the dropdowns. Save as a named
   mapping for future use.
4. **Export** — click **Export All** or select specific rows and click
   **Export Selected**. A styled `.xlsx` file is downloaded automatically.
5. **History** — the **History** tab shows all past searches. Click **Load**
   to reload results or **Export** to re-export any past search.
 
