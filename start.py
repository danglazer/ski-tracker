"""Combined entry point: runs the scheduler + Flask web app in one process."""

import threading
import time
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import init_db, save_snapshot, update_daily_summary, save_snow_report
from scraper import scrape_all
from weather import fetch_all_forecasts
from avalanche import fetch_avalanche_forecast
from digest import generate_digest
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

        # Save snow report text (first non-empty of the day wins)
        report_text = data.get("report_text", "")
        if report_text and len(report_text.strip()) > 20:
            save_snow_report(resort, date_str, report_text.strip(), scraped_at)

    print(f"[{scraped_at}] Scrape complete.\n")


def run_weather():
    """Fetch NWS weather forecasts for all resorts."""
    try:
        fetch_all_forecasts()
    except Exception as e:
        print(f"[weather] Scheduler error: {e}")


def run_avalanche():
    """Fetch UAC avalanche forecast."""
    try:
        fetch_avalanche_forecast()
    except Exception as e:
        print(f"[avalanche] Scheduler error: {e}")


def run_digest():
    """Generate AI daily digest."""
    try:
        generate_digest()
    except Exception as e:
        print(f"[digest] Scheduler error: {e}")


def start_scheduler():
    # Wait for Flask to bind before starting scraper
    time.sleep(3)

    scheduler = BackgroundScheduler(timezone=MTN_TZ)

    # Terrain scraping: every 15min, 7am-4pm MT
    scheduler.add_job(run_scrape, CronTrigger(hour="7-16", minute="0,15,30,45", timezone=MTN_TZ))

    # Weather: once daily at 6:30am MT
    scheduler.add_job(run_weather, CronTrigger(hour=6, minute=30, timezone=MTN_TZ))

    # Avalanche: every 15min 5am-9am until found, then once at noon
    scheduler.add_job(run_avalanche, CronTrigger(hour="5-9", minute="0,15,30,45", timezone=MTN_TZ))
    scheduler.add_job(run_avalanche, CronTrigger(hour=12, minute=0, timezone=MTN_TZ))

    # Daily digest: once at 8:15am MT (after weather + avalanche fetched)
    scheduler.add_job(run_digest, CronTrigger(hour=8, minute=15, timezone=MTN_TZ))
    # Retry at 9am in case avalanche wasn't available
    scheduler.add_job(run_digest, CronTrigger(hour=9, minute=0, timezone=MTN_TZ))

    scheduler.start()
    print("Scheduler started:")
    print("  - Terrain scrape: every 15min, 7am-4pm MT")
    print("  - Weather: daily at 6:30am MT")
    print("  - Avalanche: every 15min 5-9am MT + noon")
    print("  - Digest: 8:15am + 9am MT")

    # Run initial fetches in background
    print("Running initial fetches...")
    threading.Thread(target=run_weather, daemon=True).start()
    threading.Thread(target=run_avalanche, daemon=True).start()
    threading.Thread(target=run_scrape, daemon=True).start()


if __name__ == "__main__":
    init_db()

    # Run scheduler in a background thread
    scraper_thread = threading.Thread(target=start_scheduler, daemon=True)
    scraper_thread.start()

    # Run Flask in the main thread
    app.run(host="0.0.0.0", port=8080, debug=False)
