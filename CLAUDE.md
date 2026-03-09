# Utah Ski Terrain Tracker

Tracks terrain open/closed status at 4 Utah resorts: Snowbird, Solitude, Brighton, Snowbasin.
Scrapes resort websites for real-time terrain status + 24hr snowfall.

# Tech Stack

- Flask + SQLite + APScheduler
- Playwright/Chromium (Snowbird, Brighton, Solitude) + BeautifulSoup (Snowbasin)
- Single-page frontend (vanilla JS, dark theme default)

# Key Files

- `start.py` — Entry point, scheduler + Flask startup
- `app.py` — Flask routes (`/api/status`, `/api/history`, `/api/dates`, etc.)
- `scraper.py` — Per-resort scrapers, Chromium lifecycle
- `database.py` — SQLite schema (terrain_snapshots, daily_summary)
- `scheduler.py` — Backup scheduler (start.py is the actual entry point)
- `templates/index.html` — Single-page frontend

# Schedule (Mountain Time)

- Terrain scrape: every 15 min, 8am–4pm

# Git Workflow

After making code changes:
1. Commit to a feature branch
2. Push to remote
3. Create a PR to merge into main
4. Merge the PR (squash)
5. Tell me to run `git pull origin main && fly deploy` when ready to deploy

# Deployment

- Hosted on Fly.io as `resort-terrain-tracker`
- Deploy directory: ~/ski-tracker
- VM: shared-cpu-1x, 1024MB memory
- Persistent volume mounted at /data
- DB path: /data/terrain.db (production), ./data/terrain.db (local)

# Common Commands

- Run locally: `python start.py`
- Check logs: `fly logs -a resort-terrain-tracker`
