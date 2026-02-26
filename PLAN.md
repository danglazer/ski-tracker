# Ski Tracker Feature Plan

## Current State
- Flask + SQLite on Fly.io (1GB shared-cpu, auto-stop)
- Scrapes 4 resorts every 15min (7am-4pm MT): Snowbird, Solitude, Brighton, Snowbasin
- Stores: terrain open/closed status, 24hr snowfall (number only)
- No weather, no text reports, no avalanche, no AI

---

## Feature 1: Weather Forecast on Resort Cards

**Goal:** Show today's weather forecast in each resort card (not the history view).

**Data Source:** NWS api.weather.gov (free, no API key, reliable)
- `GET https://api.weather.gov/points/{lat},{lon}` → returns forecast URL
- `GET {forecast_url}` → returns multi-period text forecast
- Resort coordinates:
  - Snowbird: 40.5830, -111.6556
  - Solitude: 40.6199, -111.5919
  - Brighton: 40.5980, -111.5832
  - Snowbasin: 41.2160, -111.8569

**Implementation:**
1. **New DB table: `weather_forecasts`**
   - `id`, `resort` (TEXT), `date` (TEXT), `forecast_text` (TEXT), `temperature_high` (REAL), `temperature_low` (REAL), `wind` (TEXT), `short_forecast` (TEXT), `fetched_at` (TEXT)
   - UNIQUE on (resort, date)

2. **New file: `weather.py`** — fetches NWS forecast for each resort
   - Cache the forecast URL (it doesn't change) so we only call `/points` once
   - Fetch once per morning (~6:30am MT), retry if it fails
   - Parse the first 2 forecast periods (today + tonight)
   - Store in DB

3. **Schedule:** Run once daily at 6:30am MT (before first terrain scrape at 7am)

4. **API endpoint:** Add weather data to existing `/api/status` response per resort

5. **Frontend:** Add a weather summary row in each resort card header, below the snow badge:
   - "Today: 28°F, Snow likely, W 10mph" style compact display
   - Light styling, doesn't dominate the card

---

## Feature 2: Daily Snow Report Text

**Goal:** Capture and store the narrative morning snow report from each resort. Display in a popup modal when clicking "Snow Report" link.

**Data Source:** Scrape from the same pages we already visit (no new page loads needed for most resorts). The narrative text is on:
- **Snowbird:** `snowbird.com/the-mountain/mountain-report/current-conditions-weather/` (already visited for snowfall)
- **Brighton:** `brightonresort.com/conditions` (already visited)
- **Snowbasin:** `snowbasin.com/the-mountain/mountain-report/` (already visited)
- **Solitude:** `solitudemountain.com/mountain-and-village/conditions-and-maps` (already visited)

**Implementation:**
1. **New DB table: `snow_reports`**
   - `id`, `resort` (TEXT), `date` (TEXT), `report_text` (TEXT), `fetched_at` (TEXT)
   - UNIQUE on (resort, date)
   - Only save once per day (first non-empty scrape of the day)

2. **Scraper changes:** In each resort's scraper function, extract the narrative text section (in addition to what we already extract). Return it as `"report_text"` in the result dict.
   - Snowbird: Look for the morning report / conditions narrative block
   - Brighton: Extract the reporter's comments / conditions text
   - Snowbasin: Extract the mountain report narrative text
   - Solitude: Extract the conditions description text

3. **New DB function:** `save_snow_report(resort, date, text)` — only inserts if no report exists for that day yet (first report wins, since morning report is what we want)

4. **New DB function:** `get_snow_report(resort, date)` — returns the report text for a specific day

5. **New API endpoint:** `GET /api/snow-report?resort=X&date=YYYY-MM-DD`

6. **Frontend:**
   - Add a "Snow Report" link/button in each resort card header
   - Clicking opens a modal showing the narrative text for that date
   - In the history/calendar view, clicking a day should also show that day's report
   - Modal includes date and resort name in header

---

## Feature 3: Avalanche Forecast Section

**Goal:** New section on the page showing today's UAC Salt Lake avalanche forecast summary.

**Data Source:** UAC JSON API
- `GET https://utahavalanchecenter.org/forecast/salt-lake/json`
- Requires custom User-Agent (e.g., `SkiTracker/1.0 (contact@email.com)`)
- Returns: danger ratings, bottom_line text, avalanche problems, danger_rose values
- Published daily between 5-8am MT

**Implementation:**
1. **New DB table: `avalanche_forecasts`**
   - `id`, `region` (TEXT), `date` (TEXT), `overall_danger` (TEXT), `bottom_line` (TEXT), `forecast_json` (TEXT — full JSON blob for reference), `fetched_at` (TEXT)
   - UNIQUE on (region, date)

2. **New file: `avalanche.py`** — fetches and parses UAC forecast
   - Extract: overall danger rating, bottom_line summary, avalanche problems
   - Map danger_rose values to human-readable danger levels (Low/Moderate/Considerable/High/Extreme)
   - Store in DB

3. **Schedule:** Check every 15min between 5am-9am MT until forecast is found for today, then once more at noon as a backup check

4. **New API endpoint:** `GET /api/avalanche?date=YYYY-MM-DD`
   - Returns danger level, bottom_line text, problems list

5. **Frontend:** New section between the resort cards and the history spreadsheet:
   - Card-style display: "Avalanche Forecast — Salt Lake Mountains"
   - Danger level badge (color-coded: green/yellow/orange/red/black for the 5 levels)
   - Bottom line text summary
   - Collapsible section for detailed avalanche problems
   - Date shown; links to full UAC forecast page

---

## Feature 4: Daily Digest (Claude API)

**Goal:** AI-generated daily briefing that recaps yesterday and recommends today's skiing. Improves over time as it spots patterns in historical data.

**Data Sources (all already in DB by the time digest runs):**
- Yesterday's terrain status (what opened/closed, when things opened)
- Yesterday's snowfall per resort
- Today's weather forecast (from Feature 1)
- Today's avalanche forecast (from Feature 3)
- Historical patterns (from daily_summary table)

**Implementation:**
1. **New DB table: `daily_digests`**
   - `id`, `date` (TEXT), `digest_text` (TEXT), `generated_at` (TEXT)
   - UNIQUE on (date)

2. **Terrain open times:** To know WHEN terrain opened (not just if), we need to query `terrain_snapshots` for the first "open" status for each terrain on the previous day. This data already exists in the raw snapshots table.

3. **New DB function:** `get_terrain_open_times(date)` — for each terrain, find the earliest snapshot where status="open" on that date. Returns dict like `{"snowbird|Mineral Basin": "2025-02-20T10:15:00", ...}`

4. **New file: `digest.py`**
   - `generate_digest(date)` function that:
     a. Gathers yesterday's data (terrain, snow, open times)
     b. Gathers today's weather + avalanche forecast
     c. Gathers historical patterns (last 30 days of terrain/snow data)
     d. Calls Claude API with a structured prompt to generate the digest
     e. Saves to DB

5. **Claude API prompt structure:**
   ```
   You are a ski conditions analyst for Utah resorts (Snowbird, Solitude, Brighton, Snowbasin).

   YESTERDAY'S DATA:
   - Terrain status: [open/closed for each area, with first-open times]
   - Snowfall: [24hr totals per resort]

   TODAY'S CONDITIONS:
   - Weather forecast: [NWS data per resort]
   - Avalanche forecast: [UAC danger + bottom line]

   HISTORICAL CONTEXT (last 30 days):
   - [terrain open/closed + snowfall data to spot patterns]

   Generate a daily digest with:
   1. YESTERDAY RECAP: What happened with snow and terrain
   2. TODAY'S OUTLOOK: Where to ski and why, based on conditions
   3. PATTERN NOTES: Any trends you notice (e.g., terrain opening patterns after storms)
   ```

6. **Schedule:** Run once daily at ~8:15am MT (after weather + avalanche data are fetched, before most people check)
   - Retry at 9am if avalanche forecast wasn't available yet

7. **New API endpoint:** `GET /api/digest?date=YYYY-MM-DD`

8. **Frontend:** New section at the top of the page (below controls, above resort cards):
   - "Daily Digest — Feb 26, 2026" header
   - Formatted text from Claude
   - Sections for Yesterday Recap, Today's Outlook, Pattern Notes
   - Past digests viewable by changing the date picker

9. **Pattern learning over time:**
   - The prompt includes historical data, so Claude can spot patterns each time
   - As the season progresses and more data accumulates, the patterns section gets richer
   - We pass the last 3 digests' "Pattern Notes" sections as context so insights compound
   - Future enhancement: could store identified patterns in a separate table

**Dependencies:** Requires `anthropic` Python package and an `ANTHROPIC_API_KEY` environment variable (set as Fly.io secret).

---

## Execution Order

The features build on each other, so the recommended order is:

1. **Feature 2 (Snow Reports)** — Smallest change, just extends existing scrapers + adds modal
2. **Feature 1 (Weather)** — New data source, new scraper, adds to cards
3. **Feature 3 (Avalanche)** — New data source, new section
4. **Feature 4 (Digest)** — Depends on Features 1 + 3 being in place, plus Claude API

## Architecture Notes

- All new tables go in `database.py` `init_db()`
- All new scheduled jobs go in `start.py` `start_scheduler()`
- Keep the single-file HTML approach (no build step) — add new modals/sections inline
- NWS and UAC fetches use `requests` (no Playwright needed — both are JSON APIs)
- Claude API calls use the `anthropic` Python SDK
- New env var needed: `ANTHROPIC_API_KEY` (Fly.io secret)
- RAM impact should be minimal (just HTTP calls + text storage, no new browser instances)

## New Dependencies
- `anthropic` (Claude API SDK)
- No other new packages needed (`requests` already installed)
