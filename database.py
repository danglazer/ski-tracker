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
