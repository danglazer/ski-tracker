"""Combined entry point: runs the scheduler + Flask web app in one process."""

import threading
import time
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import init_db, save_snapshot, update_daily_summary, get_avalanche_forecast
from scraper import scrape_all
from avalanche import fetch_avalanche_forecast
from app import app

MTN_TZ = pytz.timezone("America/Denver")


def run_scrape():
    now = datetime.now(MTN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    scraped_at = now.isoformat()

    print(f"\n[{scraped_at}] Starting scrape...")

    results = scrape_all()

    for resort, data in results.items():
        snow = data.get("snow_24hr", 0.0)
        for t in data.get("terrain", []):
            name = t["name"]
            status = t["status"]
            print(f"  {resort} | {name} | {status}")
            save_snapshot(resort, name, status, scraped_at)
            update_daily_summary(resort, name, date_str, status, snow)

    print(f"[{scraped_at}] Scrape complete.\n")


def run_avalanche():
    """Fetch UAC avalanche forecast (skip if already have today's with image AND correct date)."""
    import json
    today = datetime.now(MTN_TZ).strftime("%Y-%m-%d")
    existing = get_avalanche_forecast("salt-lake", today)
    if existing:
        try:
            fj = json.loads(existing.get("forecast_json", "{}"))
            issued_date = fj.get("issued_date", "")
            if fj.get("danger_rose_image") and issued_date == today:
                print(f"[avalanche] Today's forecast (issued {issued_date}) with rose image exists, skipping")
                return
        except Exception:
            pass
    try:
        fetch_avalanche_forecast()
    except Exception as e:
        print(f"[avalanche] Scheduler error: {e}")


def start_scheduler():
    # Wait for Flask to bind before starting scraper
    time.sleep(3)

    scheduler = BackgroundScheduler(timezone=MTN_TZ)
    terrain_trigger = CronTrigger(hour="8-16", minute="*/15", timezone=MTN_TZ)
    scheduler.add_job(run_scrape, terrain_trigger)

    # Avalanche: every 15min 5am-9am until found, then once at noon
    scheduler.add_job(run_avalanche, CronTrigger(hour="5-9", minute="0,15,30,45", timezone=MTN_TZ))
    scheduler.add_job(run_avalanche, CronTrigger(hour=12, minute=0, timezone=MTN_TZ))

    scheduler.start()
    print("Scheduler started:")
    print("  - Terrain scrape: every 15 min, 8am-4pm Mountain Time")
    print("  - Avalanche: every 15min 5-9am MT + noon")

    print("Running initial fetches in background...")
    threading.Thread(target=run_avalanche, daemon=True).start()
    threading.Thread(target=run_scrape, daemon=True).start()


if __name__ == "__main__":
    init_db()

    # Run scheduler in a background thread
    scraper_thread = threading.Thread(target=start_scheduler, daemon=True)
    scraper_thread.start()

    # Run Flask in the main thread
    app.run(host="0.0.0.0", port=8080, debug=False)
