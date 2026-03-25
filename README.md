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
# 1. Install dependencies (includes Playwright for BidNet Direct)
pip install -r requirements.txt

# 2. Install the Playwright browser binary (one-time, ~300 MB)
playwright install chromium

# 3. Run the app
python main.py

# 4. Open in your browser
# http://localhost:5000
```

> **Why is `playwright install chromium` needed?**
> BidNet Direct is a JavaScript-rendered website (AngularJS SPA). A plain HTTP
> request returns only an empty HTML shell — no results. Playwright launches a
> real headless Chromium browser that executes JavaScript just like your browser
> does, so it can see and extract the actual search results.

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

## Optional: SAM.gov API Key

Without an API key the SAM.gov free tier allows only ~10 requests per day.
If you hit that limit the scraper returns a `403 Forbidden` error.

To get a free API key:
1. Log in at [sam.gov](https://sam.gov) (free registration)
2. Go to **My SAM → System Account** and create a public-access key
3. Set the environment variable before starting the app:

```bash
# macOS / Linux
export SAM_GOV_API_KEY=your_key_here
python main.py

# Windows
set SAM_GOV_API_KEY=your_key_here
python main.py
```

The app detects the key automatically — no other configuration needed.

