"""Combined entry point: runs the scheduler + Flask web app in one process."""

import threading
import time
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import (
    init_db, save_snapshot, update_daily_summary, save_snow_report,
    backfill_open_times, backfill_daily_from_snapshots,
    get_daily_digest, get_avalanche_forecast, get_daily_view,
    get_snow_report,
)
from scraper import scrape_all, TRACKED
from weather import fetch_all_forecasts
from avalanche import fetch_avalanche_forecast
from digest import generate_digest, summarize_snow_report
from app import app

MTN_TZ = pytz.timezone("America/Denver")

SCRAPE_TIMEOUT = 10 * 60  # 10 minutes max per scrape cycle



def run_scrape():
    now = datetime.now(MTN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    scraped_at = now.isoformat()

    # Use a threading.Timer as a watchdog instead of signal.SIGALRM
    # (signals only work in the main thread)
    timed_out = threading.Event()

    def _watchdog():
        timed_out.set()
        print(f"[{scraped_at}] Scrape timed out after {SCRAPE_TIMEOUT}s.\n", flush=True)

    watchdog = threading.Timer(SCRAPE_TIMEOUT, _watchdog)
    watchdog.daemon = True
    watchdog.start()

    try:
        print(f"\n[{scraped_at}] Starting scrape...", flush=True)

        try:
            results = scrape_all()
        except Exception as e:
            print(f"[scraper] FATAL: scrape_all() crashed: {e}", flush=True)
            return

        if timed_out.is_set():
            return


        saved_count = 0
        for resort, data in results.items():
            if timed_out.is_set():
                print(f"[scraper] Timeout reached, stopping save loop.", flush=True)
                break

            snow = data.get("snow_24hr", 0.0)
            terrain = data.get("terrain", [])
            if not terrain:
                print(f"  [scraper] WARNING: {resort} returned no terrain data", flush=True)
            for t in terrain:
                name = t["name"]
                status = t["status"]
                print(f"  {resort} | {name} | {status}", flush=True)
                try:
                    save_snapshot(resort, name, status, scraped_at)
                    update_daily_summary(resort, name, date_str, status, snow, scraped_at)
                    saved_count += 1
                except Exception as e:
                    print(f"  [scraper] ERROR saving {resort}/{name}: {e}", flush=True)

            # Summarize raw page text into a snow report via Claude API
            try:
                raw_text = data.get("raw_report_text", "")
                if raw_text and len(raw_text.strip()) > 50:
                    summary = summarize_snow_report(resort, raw_text)
                    if summary:
                        save_snow_report(resort, date_str, summary, scraped_at)
            except Exception as e:
                print(f"  [scraper] ERROR summarizing {resort} snow report: {e}", flush=True)

        print(f"[{scraped_at}] Scrape complete. Saved {saved_count} terrain entries.\n", flush=True)
    except Exception as e:
        print(f"[{scraped_at}] Scrape error: {e}\n", flush=True)
    finally:
        watchdog.cancel()

    # Check if we can generate today's digest now
    maybe_generate_digest()


def run_weather():
    """Fetch NWS weather forecasts for all resorts."""
    try:
        fetch_all_forecasts()
    except Exception as e:
        print(f"[weather] Scheduler error: {e}")


def run_avalanche():
    """Fetch UAC avalanche forecast (skip if already have today's with image)."""
    today = datetime.now(MTN_TZ).strftime("%Y-%m-%d")
    existing = get_avalanche_forecast("salt-lake", today)
    if existing:
        try:
            import json
            fj = json.loads(existing.get("forecast_json", "{}"))
            if fj.get("danger_rose_image"):
                print(f"[avalanche] Forecast with rose image exists for {today}, skipping")
                return
        except Exception:
            pass
    try:
        fetch_avalanche_forecast()
    except Exception as e:
        print(f"[avalanche] Scheduler error: {e}")

    # Check if we can generate today's digest now
    maybe_generate_digest()


def run_digest():
    """Generate AI daily digest."""
    try:
        generate_digest()
    except Exception as e:
        print(f"[digest] Scheduler error: {e}")


def maybe_generate_digest(force=False):
    """Generate digest only when avalanche report AND mountain reports are ready.

    Requires:
    - Avalanche forecast with danger rose image (confirms UAC published)
    - Terrain data from at least 3 resorts (guards against partial scrape failures)
    - At least 1 snow report for today (confirms mountain reports are in)

    Args:
        force: If True, regenerate even if today's digest already exists.
               Data quality checks still apply.
    """
    try:
        import json

        now = datetime.now(MTN_TZ)
        today_str = now.strftime("%Y-%m-%d")

        # Don't run before 6am
        if now.hour < 6:
            return

        # Already have today's digest?
        if not force:
            existing = get_daily_digest(today_str)
            if existing and existing.get("digest_text"):
                return

        # Need avalanche forecast with danger rose image (confirms UAC actually published)
        avy = get_avalanche_forecast("salt-lake", today_str)
        if not avy:
            print(f"[digest-trigger] No avalanche forecast yet for {today_str}, waiting...", flush=True)
            return
        try:
            fj = json.loads(avy.get("forecast_json", "{}"))
            if not fj.get("danger_rose_image"):
                print(f"[digest-trigger] Avalanche forecast missing danger rose image, waiting...", flush=True)
                return
        except Exception:
            print(f"[digest-trigger] Could not parse avalanche forecast JSON, waiting...", flush=True)
            return

        # Need terrain data from at least 3 resorts (out of 5 tracked)
        view = get_daily_view(today_str)
        if not view:
            print(f"[digest-trigger] No terrain data yet for {today_str}, waiting...", flush=True)
            return
        resorts_with_data = len(view)
        if resorts_with_data < 3:
            print(f"[digest-trigger] Only {resorts_with_data}/5 resorts have terrain data, waiting...", flush=True)
            return

        # Need at least 1 snow report (confirms mountain report summaries are in)
        has_snow_report = False
        for resort in TRACKED:
            if get_snow_report(resort, today_str):
                has_snow_report = True
                break
        if not has_snow_report:
            print(f"[digest-trigger] No snow reports yet for {today_str}, waiting...", flush=True)
            return

        print(f"[digest-trigger] All data ready ({resorts_with_data} resorts, avy rose, snow reports), generating digest...", flush=True)
        run_digest()
    except Exception as e:
        print(f"[digest-trigger] Error: {e}", flush=True)


def start_scheduler():
    # Wait for Flask to bind before starting scraper
    time.sleep(3)

    scheduler = BackgroundScheduler(timezone=MTN_TZ)

    # Terrain scraping: every 15min, 6am-4pm MT
    scheduler.add_job(run_scrape, CronTrigger(hour="6-16", minute="0,15,30,45", timezone=MTN_TZ))

    # Weather: once daily at 6:30am MT
    scheduler.add_job(run_weather, CronTrigger(hour=6, minute=30, timezone=MTN_TZ))

    # Avalanche: every 15min 5am-9am until found, then once at noon
    scheduler.add_job(run_avalanche, CronTrigger(hour="5-9", minute="0,15,30,45", timezone=MTN_TZ))
    scheduler.add_job(run_avalanche, CronTrigger(hour=12, minute=0, timezone=MTN_TZ))

    # Digest: triggered automatically after both avalanche + terrain data arrive
    # Fallback at 10am — still checks data quality, but will regenerate if stale
    scheduler.add_job(lambda: maybe_generate_digest(force=True), CronTrigger(hour=10, minute=0, timezone=MTN_TZ))

    scheduler.start()
    print("Scheduler started:")
    print("  - Terrain scrape: every 15min, 6am-4pm MT")
    print("  - Weather: daily at 6:30am MT")
    print("  - Avalanche: every 15min 5-9am MT + noon")
    print("  - Digest: auto after avy rose+terrain+snow reports ready, fallback 10am MT")

    # Run initial fetches in background
    print("Running initial fetches...")
    threading.Thread(target=run_weather, daemon=True).start()
    threading.Thread(target=run_avalanche, daemon=True).start()
    threading.Thread(target=run_scrape, daemon=True).start()


if __name__ == "__main__":
    init_db()
    backfill_open_times()

    # Backfill daily_summary from snapshots for any recent dates that may have gaps
    from datetime import timedelta
    today = datetime.now(MTN_TZ)
    for days_ago in range(7):
        d = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        count = backfill_daily_from_snapshots(d)
        if count > 0:
            print(f"[startup] Backfilled {count} terrain entries for {d}", flush=True)

    # Run scheduler in a background thread
    scraper_thread = threading.Thread(target=start_scheduler, daemon=True)
    scraper_thread.start()

    # Run Flask in the main thread
    app.run(host="0.0.0.0", port=8080, debug=False)
