# Utah Ski Terrain Tracker

Tracks whether specific terrain areas at Utah ski resorts ever opened on a given day. Designed for powder hunting — if it snowed but terrain never opened, that's potential untracked powder for tomorrow.

**Live at:** [resort-terrain-tracker.fly.dev](https://resort-terrain-tracker.fly.dev)

## What It Tracks

| Resort | Terrain |
|---|---|
| Snowbird | Mineral Basin, Cirque Traverse, High Baldy |
| Solitude | Honeycomb Canyon, Summit Express, Highway to Heaven, Fantasy Ridge, Evergreen Peak |
| Brighton | Milly Bowl, Snake Bowl |
| Snowbasin | Allen Peak Tram, Strawberry Gondola, Middle Bowl Cirque Gate, Upper Mt Ogden Bowl Gate |
| Powder Mountain | James Peak |

Scrapes every 15 minutes from 6am–4pm Mountain Time. Records terrain open/close status, exact opening times, and 24hr snowfall.

## Features

- **Daily terrain status** — See which terrain opened or stayed closed each day, with exact opening times (e.g., "Opened 9:30 AM"). Gold highlight when snow fell but terrain never opened = potential powder tomorrow.
- **History views** — Spreadsheet and calendar views to browse terrain open/close history over time.
- **Snow calendar** — Per-resort snowfall calendar showing daily totals with color-coded intensity.
- **AI snow reports** — Claude-generated summaries of each resort's daily conditions page.
- **Weather forecasts** — NWS weather forecasts for each resort, fetched daily at 6:30am MT.
- **Avalanche forecast** — Utah Avalanche Center danger ratings and avalanche problems for the Salt Lake mountains. Fetched every 15min from 5–9am MT.
- **AI daily digest** — Claude-powered daily briefing with yesterday recap, today's outlook, and pattern notes. Auto-generates as soon as both avalanche and terrain data are available.
- **Collapsible digest** — Click to expand/collapse the daily digest.
- **Dark/light theme** — Toggle between dark and light modes.

## Architecture

- **Flask** web app with single-page frontend
- **APScheduler** for background cron jobs (terrain scraping, weather, avalanche, digest)
- **Playwright/Chromium** for JS-rendered resort sites (Snowbird, Brighton, Solitude, Powder Mountain)
- **Requests + BeautifulSoup** for server-rendered sites (Snowbasin)
- **SQLite** database with persistent volume on Fly.io (`/data/terrain.db`)
- **Claude API** for snow report summaries and daily digest generation

## Schedule

| Job | Schedule (Mountain Time) |
|---|---|
| Terrain scrape | Every 15min, 6am–4pm |
| Weather forecast | Daily at 6:30am |
| Avalanche forecast | Every 15min 5–9am + noon |
| Daily digest | Auto after avalanche + terrain data arrive, fallback 10am |

## Deployment (Fly.io)

Hosted on Fly.io as `resort-terrain-tracker` with a persistent SQLite volume.

```bash
# Deploy
cd ~/ski-tracker-deploy
git pull origin main
fly deploy --app resort-terrain-tracker

# Check logs
fly logs --app resort-terrain-tracker

# Trigger manual scrape
curl -X POST https://resort-terrain-tracker.fly.dev/api/scrape

# Trigger manual digest
curl -X POST https://resort-terrain-tracker.fly.dev/api/generate-digest
```

### Environment Variables

Set on Fly.io:
- `ANTHROPIC_API_KEY` — Required for AI snow reports and daily digest

### VM Specs

- `shared-cpu-1x`, 1024MB memory (Chromium needs ~800MB)
- Persistent volume `ski_data` mounted at `/data`

## Local Development

```bash
pip3 install -r requirements.txt
playwright install chromium
export ANTHROPIC_API_KEY="your-key-here"  # optional, for AI features
python3 start.py
```

Open `http://localhost:8080`. The app runs the scheduler and web server in one process.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/status?date=YYYY-MM-DD` | GET | Current terrain status + weather for all resorts |
| `/api/history` | GET | Full terrain history across all dates |
| `/api/dates` | GET | List of dates with data |
| `/api/terrain-calendar?resort=X&terrain=Y` | GET | Open/close calendar for a specific terrain |
| `/api/snow-calendar?resort=X` | GET | Snowfall history for a resort |
| `/api/snow-report?resort=X&date=YYYY-MM-DD` | GET | AI snow report for a resort/date |
| `/api/weather?date=YYYY-MM-DD` | GET | Weather forecasts for all resorts |
| `/api/avalanche?date=YYYY-MM-DD` | GET | Avalanche forecast |
| `/api/digest?date=YYYY-MM-DD` | GET | AI daily digest |
| `/api/scrape` | POST | Trigger manual scrape |
| `/api/generate-digest` | POST | Trigger manual digest generation |
| `/api/last-scrape` | GET | Last scrape timestamp + dates with data |
| `/api/backfill` | POST | Backfill daily_summary from snapshots |
