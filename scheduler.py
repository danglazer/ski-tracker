import time
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import init_db, save_snapshot, update_daily_summary
from scraper import scrape_all

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


def main():
    init_db()

    print("Running initial scrape on startup...")
    run_scrape()

    scheduler = BackgroundScheduler(timezone=MTN_TZ)
    trigger = CronTrigger(hour="9-16", minute=0, timezone=MTN_TZ)
    scheduler.add_job(run_scrape, trigger)
    scheduler.start()

    print("Scheduler started. Scraping hourly 9am-4pm Mountain Time. Press Ctrl+C to exit.")

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down scheduler...")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
