# Utah Ski Terrain Tracker

Tracks whether specific terrain areas at Snowbird, Solitude, Brighton, and Snowbasin ever opened on a given day. Designed for powder hunting — if it snowed but terrain never opened, that's potential untracked powder for tomorrow.

## What It Tracks

| Resort | Terrain |
|---|---|
| Snowbird | Mineral Basin, Cirque Traverse, High Baldy |
| Solitude | Honeycomb Canyon, Summit Express, Highway to Heaven, Fantasy Ridge, Evergreen Peak |
| Brighton | Milly Bowl, Snake Bowl |
| Snowbasin | Allen Peak Tram, Strawberry Gondola, Middle Bowl Cirque Gate, Upper Mt Ogden Bowl Gate |

Scrapes every hour from 9am–4pm Mountain Time. Shows one result per terrain per day (opened = green, never opened = red). Highlights terrain in gold when it snowed but the area stayed closed all day = potential powder tomorrow.

## Features

- **Daily terrain status** — See which terrain opened or stayed closed each day, with powder alerts when snow fell but terrain never opened.
- **History views** — Spreadsheet and calendar views to browse terrain open/close history over time. Click any terrain to see a calendar of when it was open vs. closed.
- **Snow calendar** — Per-resort snowfall calendar showing daily totals with color-coded intensity.
- **Weather forecasts** — NWS weather forecasts for each resort, fetched and stored daily.
- **Avalanche forecast** — Utah Avalanche Center danger ratings, avalanche problems, and bottom-line summary for the Salt Lake mountains.
- **AI daily digest** — Claude-powered daily briefing with a yesterday recap, today's outlook, and pattern notes (requires `ANTHROPIC_API_KEY`).
- **Dark/light theme** — Toggle between dark and light modes.

---

## Setup (one time)

### Step 1 — Check if Python is installed

Open Terminal (press `Cmd + Space`, type "Terminal", press Enter). Type:

```
python3 --version
```

If you see a version number (like `Python 3.11.0`), you're good. If you get an error, download Python from https://www.python.org/downloads/ and install it.

### Step 2 — Install dependencies

In Terminal, type these commands one at a time (press Enter after each):

```
cd ~/Desktop/ski-tracker
pip3 install -r requirements.txt
playwright install chromium
```

This may take a few minutes. That's normal.

### Step 3 (optional) — AI daily digest

To enable the AI-generated daily digest, set your Anthropic API key:

```
export ANTHROPIC_API_KEY="your-key-here"
```

Without this, everything else works fine — you just won't get the digest.

---

## Running the App

You need two Terminal windows running at the same time.

### Terminal window 1 — Start the scraper (runs hourly)

```
cd ~/Desktop/ski-tracker
python3 scheduler.py
```

Leave this running. It will scrape terrain status every hour between 9am and 4pm Mountain Time. It also runs once immediately when you start it. The scheduler also fetches weather forecasts, avalanche data, and generates the daily digest.

### Terminal window 2 — Start the web app

```
cd ~/Desktop/ski-tracker
python3 app.py
```

Leave this running too.

### Open the app

Open your web browser and go to:

```
http://localhost:5050
```

You'll see the terrain tracker. Pick a date to see what was open that day.

---

## Stopping the App

Press `Ctrl + C` in each Terminal window to stop them.

---

## Tips

- **First run:** The scraper runs immediately on startup, so you'll have data within a minute or two.
- **Gold highlight** = It snowed today AND that terrain never opened = likely untracked powder tomorrow.
- **"X days closed"** badge = how many consecutive days that terrain has been closed. Longer streak after snowfall = more potential powder.
- The app only collects data while `scheduler.py` is running (9am–4pm). If your Mac is asleep, it won't scrape.
- All data is stored in `data/terrain.db` on your computer — nothing is sent anywhere.

---

## Troubleshooting

**"No data for this date"** — Either the scraper hasn't run yet today, or it wasn't running during 9am–4pm. Start `scheduler.py` and wait a minute.

**Scraper errors in Terminal** — Resort websites sometimes change their layout. Check that the resort's website is working, then let me know and I can update the scraper.

**Solitude not loading** — The Solitude scraper uses a headless browser (playwright). Make sure you ran `playwright install chromium` during setup.
