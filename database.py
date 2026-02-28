import sqlite3
import os
from datetime import datetime, timedelta

# Use /data on Fly.io (persistent volume), or ./data locally
if os.path.isdir("/data") and os.environ.get("FLY_APP_NAME"):
    DB_DIR = "/data"
else:
    DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "terrain.db")


def _connect():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS terrain_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resort TEXT NOT NULL,
            terrain_name TEXT NOT NULL,
            status TEXT NOT NULL,
            scraped_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resort TEXT NOT NULL,
            terrain_name TEXT NOT NULL,
            date TEXT NOT NULL,
            ever_opened INTEGER NOT NULL DEFAULT 0,
            snowfall_24hr REAL NOT NULL DEFAULT 0.0,
            UNIQUE(resort, terrain_name, date)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS snow_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resort TEXT NOT NULL,
            date TEXT NOT NULL,
            report_text TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(resort, date)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS weather_forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resort TEXT NOT NULL,
            date TEXT NOT NULL,
            forecast_text TEXT NOT NULL,
            temperature_high REAL,
            temperature_low REAL,
            wind TEXT,
            short_forecast TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(resort, date)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS avalanche_forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT NOT NULL,
            date TEXT NOT NULL,
            overall_danger TEXT,
            bottom_line TEXT,
            forecast_json TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(region, date)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            digest_text TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            UNIQUE(date)
        )
    """)
    conn.commit()
    conn.close()


def save_snapshot(resort, terrain_name, status, scraped_at):
    conn = _connect()
    conn.execute(
        "INSERT INTO terrain_snapshots (resort, terrain_name, status, scraped_at) VALUES (?, ?, ?, ?)",
        (resort, terrain_name, status, scraped_at),
    )
    conn.commit()
    conn.close()


def update_daily_summary(resort, terrain_name, date_str, status, snowfall_24hr):
    conn = _connect()
    c = conn.cursor()

    new_ever_opened = 1 if status == "open" else 0

    c.execute(
        "SELECT ever_opened FROM daily_summary WHERE resort = ? AND terrain_name = ? AND date = ?",
        (resort, terrain_name, date_str),
    )
    row = c.fetchone()

    if row is None:
        c.execute(
            "INSERT INTO daily_summary (resort, terrain_name, date, ever_opened, snowfall_24hr) VALUES (?, ?, ?, ?, ?)",
            (resort, terrain_name, date_str, new_ever_opened, snowfall_24hr),
        )
    else:
        existing = row["ever_opened"]
        final_opened = 1 if existing == 1 else new_ever_opened
        c.execute(
            "UPDATE daily_summary SET ever_opened = ?, snowfall_24hr = ? WHERE resort = ? AND terrain_name = ? AND date = ?",
            (final_opened, snowfall_24hr, resort, terrain_name, date_str),
        )

    conn.commit()
    conn.close()


def get_closed_streak(resort, terrain_name, date_str):
    conn = _connect()
    c = conn.cursor()

    # Check if today is closed
    c.execute(
        "SELECT ever_opened FROM daily_summary WHERE resort = ? AND terrain_name = ? AND date = ?",
        (resort, terrain_name, date_str),
    )
    today_row = c.fetchone()
    if not today_row or today_row["ever_opened"] == 1:
        conn.close()
        return 0

    # Count consecutive closed days going back from yesterday
    streak = 1  # today counts as day 1
    current = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)

    while True:
        d = current.strftime("%Y-%m-%d")
        c.execute(
            "SELECT ever_opened FROM daily_summary WHERE resort = ? AND terrain_name = ? AND date = ?",
            (resort, terrain_name, d),
        )
        row = c.fetchone()
        if row is None or row["ever_opened"] == 1:
            break
        streak += 1
        current -= timedelta(days=1)

    conn.close()
    return streak


def get_daily_view(date_str):
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "SELECT resort, terrain_name, ever_opened, snowfall_24hr FROM daily_summary WHERE date = ?",
        (date_str,),
    )
    rows = c.fetchall()
    conn.close()

    result = {}
    for row in rows:
        resort = row["resort"]
        if resort not in result:
            result[resort] = []
        result[resort].append({
            "terrain_name": row["terrain_name"],
            "ever_opened": row["ever_opened"],
            "snowfall_24hr": row["snowfall_24hr"],
            "closed_streak": get_closed_streak(resort, row["terrain_name"], date_str),
        })

    return result


def get_all_dates():
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT DISTINCT date FROM daily_summary ORDER BY date DESC")
    dates = [row["date"] for row in c.fetchall()]
    conn.close()
    return dates


def get_full_history():
    """Returns all terrain open/closed data across all dates for the spreadsheet view."""
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        SELECT resort, terrain_name, date, ever_opened, snowfall_24hr
        FROM daily_summary
        ORDER BY date ASC
    """)
    rows = c.fetchall()
    conn.close()

    dates = []
    date_set = set()
    terrain_map = {}
    snow_map = {}  # {resort: {date: snowfall_24hr}}

    for row in rows:
        d = row["date"]
        resort = row["resort"]
        if d not in date_set:
            date_set.add(d)
            dates.append(d)
        key = f'{resort}|{row["terrain_name"]}'
        if key not in terrain_map:
            terrain_map[key] = {}
        terrain_map[key][d] = row["ever_opened"]

        # Track snow per resort per date (all terrain rows share same value)
        if resort not in snow_map:
            snow_map[resort] = {}
        if d not in snow_map[resort]:
            snow_map[resort][d] = row["snowfall_24hr"]

    return {"dates": dates, "terrain": terrain_map, "snow": snow_map}


def get_resort_snow_history(resort):
    """Returns daily snowfall history for a resort (one value per date)."""
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        SELECT date, snowfall_24hr
        FROM daily_summary
        WHERE resort = ?
        GROUP BY date
        ORDER BY date ASC
    """, (resort,))
    rows = c.fetchall()
    conn.close()
    return {row["date"]: row["snowfall_24hr"] for row in rows}


def get_terrain_history(resort, terrain_name):
    """Returns one terrain's full open/closed history for the calendar view."""
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        SELECT date, ever_opened
        FROM daily_summary
        WHERE resort = ? AND terrain_name = ?
        ORDER BY date ASC
    """, (resort, terrain_name))
    rows = c.fetchall()
    conn.close()
    return {row["date"]: row["ever_opened"] for row in rows}


# ─── Snow Reports ───

def save_snow_report(resort, date_str, report_text, fetched_at):
    """Save or update a snow report for the day."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO snow_reports (resort, date, report_text, fetched_at) VALUES (?, ?, ?, ?)",
            (resort, date_str, report_text, fetched_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_snow_report(resort, date_str):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT report_text FROM snow_reports WHERE resort = ? AND date = ?", (resort, date_str))
    row = c.fetchone()
    conn.close()
    return row["report_text"] if row else None


# ─── Weather Forecasts ───

def save_weather_forecast(resort, date_str, forecast_text, temp_high, temp_low, wind, short_forecast, fetched_at):
    conn = _connect()
    conn.execute(
        """INSERT OR REPLACE INTO weather_forecasts
           (resort, date, forecast_text, temperature_high, temperature_low, wind, short_forecast, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (resort, date_str, forecast_text, temp_high, temp_low, wind, short_forecast, fetched_at),
    )
    conn.commit()
    conn.close()


def get_weather_forecast(resort, date_str):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT * FROM weather_forecasts WHERE resort = ? AND date = ?", (resort, date_str))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "forecast_text": row["forecast_text"],
        "temperature_high": row["temperature_high"],
        "temperature_low": row["temperature_low"],
        "wind": row["wind"],
        "short_forecast": row["short_forecast"],
    }


def get_all_weather_forecasts(date_str):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT * FROM weather_forecasts WHERE date = ?", (date_str,))
    rows = c.fetchall()
    conn.close()
    result = {}
    for row in rows:
        result[row["resort"]] = {
            "forecast_text": row["forecast_text"],
            "temperature_high": row["temperature_high"],
            "temperature_low": row["temperature_low"],
            "wind": row["wind"],
            "short_forecast": row["short_forecast"],
        }
    return result


# ─── Avalanche Forecasts ───

def save_avalanche_forecast(region, date_str, overall_danger, bottom_line, forecast_json, fetched_at):
    conn = _connect()
    conn.execute(
        """INSERT OR REPLACE INTO avalanche_forecasts
           (region, date, overall_danger, bottom_line, forecast_json, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (region, date_str, overall_danger, bottom_line, forecast_json, fetched_at),
    )
    conn.commit()
    conn.close()


def get_avalanche_forecast(region, date_str):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT * FROM avalanche_forecasts WHERE region = ? AND date = ?", (region, date_str))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "overall_danger": row["overall_danger"],
        "bottom_line": row["bottom_line"],
        "forecast_json": row["forecast_json"],
    }


# ─── Daily Digests ───

def save_daily_digest(date_str, digest_text, generated_at):
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO daily_digests (date, digest_text, generated_at) VALUES (?, ?, ?)",
        (date_str, digest_text, generated_at),
    )
    conn.commit()
    conn.close()


def get_daily_digest(date_str):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT digest_text, generated_at FROM daily_digests WHERE date = ?", (date_str,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"digest_text": row["digest_text"], "generated_at": row["generated_at"]}


# ─── Terrain Open Times (for digest) ───

def get_terrain_open_times(date_str):
    """For each terrain, find the earliest snapshot where status='open' on that date."""
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        SELECT resort, terrain_name, MIN(scraped_at) as first_open
        FROM terrain_snapshots
        WHERE status = 'open' AND scraped_at LIKE ?
        GROUP BY resort, terrain_name
    """, (date_str + "%",))
    rows = c.fetchall()
    conn.close()
    return {f'{row["resort"]}|{row["terrain_name"]}': row["first_open"] for row in rows}


def get_recent_daily_summaries(days=30):
    """Get last N days of daily summary data for digest context."""
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        SELECT resort, terrain_name, date, ever_opened, snowfall_24hr
        FROM daily_summary
        ORDER BY date DESC
        LIMIT ?
    """, (days * 20,))  # ~20 terrain entries per day
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_recent_digests(n=3):
    """Get the last N digests for pattern compounding."""
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT date, digest_text FROM daily_digests ORDER BY date DESC LIMIT ?", (n,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]
