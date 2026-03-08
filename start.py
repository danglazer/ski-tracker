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

    # Acquire scrape lock to prevent concurrent scrapes (OOM risk on 1GB VM)
    if not app.scrape_lock.acquire(blocking=False):
        print(f"[{scraped_at}] Scrape already running, skipping.", flush=True)
        return

    try:
        # Determine if we can do terrain-only mode.
        # Check which resorts already have snow reports for today.
        resorts_needing_reports = []
        for resort in TRACKED:
            if not get_snow_report(resort, date_str):
                resorts_needing_reports.append(resort)

        terrain_only = len(resorts_needing_reports) == 0
        if terrain_only:
            print(f"\n[{scraped_at}] All snow reports in, running terrain-only scrape.", flush=True)
        else:
            print(f"\n[{scraped_at}] Starting full scrape (need reports for: {resorts_needing_reports})...", flush=True)

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
            try:
                results = scrape_all(terrain_only=terrain_only)
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

                terrain = data.get("terrain", [])
                if not terrain:
                    print(f"  [scraper] WARNING: {resort} returned no terrain data, skipping save", flush=True)
                    continue

                snow = data.get("snow_24hr")  # None in terrain-only mode
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
                # Only for resorts that don't have a report yet today
                if not terrain_only and resort in resorts_needing_reports:
                    try:
                        raw_text = data.get("raw_report_text", "")
                        if raw_text and len(raw_text.strip()) > 50:
                            # Double-check in case another scrape cycle already saved it
                            if not get_snow_report(resort, date_str):
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
    finally:
        app.scrape_lock.release()


def run_weather():
    """Fetch NWS weather forecasts for all resorts."""
    try:
        fetch_all_forecasts()
    except Exception as e:
        print(f"[weather] Scheduler error: {e}")


def run_avalanche():
    """Fetch UAC avalanche forecast (skip if already have today's with image AND correct date)."""
    today = datetime.now(MTN_TZ).strftime("%Y-%m-%d")
    existing = get_avalanche_forecast("salt-lake", today)
    if existing:
        try:
            import json
            fj = json.loads(existing.get("forecast_json", "{}"))
            issued_date = fj.get("issued_date", "")
            # Only skip if forecast has a rose image AND was actually issued today
            # (prevents caching yesterday's stale forecast as today's)
            if fj.get("danger_rose_image") and issued_date == today:
                print(f"[avalanche] Today's forecast (issued {issued_date}) with rose image exists, skipping")
                return
            elif fj.get("danger_rose_image") and issued_date != today:
                print(f"[avalanche] Existing forecast was issued {issued_date}, not today ({today}). Re-fetching...")
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
    """Generate digest only when ALL required data is in the database.

    Requires:
    - Avalanche forecast with danger rose image
    - Terrain data from ALL 5 resorts
    - Snow reports from ALL 5 resorts

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

        # 1. Need avalanche forecast with danger rose image, issued today
        avy = get_avalanche_forecast("salt-lake", today_str)
        if not avy:
            print(f"[digest-trigger] Waiting: no avalanche forecast for {today_str}", flush=True)
            return
        try:
            fj = json.loads(avy.get("forecast_json", "{}"))
            if not fj.get("danger_rose_image"):
                print(f"[digest-trigger] Waiting: avalanche forecast missing danger rose image", flush=True)
                return
            issued_date = fj.get("issued_date", "")
            if issued_date and issued_date != today_str:
                print(f"[digest-trigger] Waiting: avalanche forecast is from {issued_date}, not today ({today_str})", flush=True)
                return
        except Exception:
            print(f"[digest-trigger] Waiting: could not parse avalanche forecast JSON", flush=True)
            return

        # 2. Need terrain data from ALL 5 resorts
        view = get_daily_view(today_str)
        if not view:
            print(f"[digest-trigger] Waiting: no terrain data for {today_str}", flush=True)
            return
        missing_terrain = [r for r in TRACKED if r not in view]
        if missing_terrain:
            print(f"[digest-trigger] Waiting: terrain data missing for {missing_terrain}", flush=True)
            return

        # 3. Need snow reports from ALL 5 resorts
        missing_reports = []
        for resort in TRACKED:
            if not get_snow_report(resort, today_str):
                missing_reports.append(resort)
        if missing_reports:
            print(f"[digest-trigger] Waiting: snow reports missing for {missing_reports}", flush=True)
            return

        print(f"[digest-trigger] All data ready (5/5 resorts, avy rose, all snow reports), generating digest...", flush=True)
        run_digest()
    except Exception as e:
        print(f"[digest-trigger] Error: {e}", flush=True)


def start_scheduler():
    # Wait for Flask to bind before starting scraper
    time.sleep(3)

    scheduler = BackgroundScheduler(timezone=MTN_TZ)

    # Terrain scraping: every 15min, 6am-4pm MT
    # max_instances=1 prevents overlapping scrapes if one runs long
    scheduler.add_job(run_scrape, CronTrigger(hour="6-16", minute="0,15,30,45", timezone=MTN_TZ), max_instances=1)

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
    print("  - Terrain scrape: every 15min, 6am-4pm MT (max_instances=1)")
    print("  - Weather: daily at 6:30am MT")
    print("  - Avalanche: every 15min 5-9am MT + noon")
    print("  - Digest: auto after avy rose + all 5 resort terrain + all 5 snow reports ready, fallback 10am MT")

    # Run initial fetches in background
    print("Running initial fetches...")
    threading.Thread(target=run_weather, daemon=True).start()
    threading.Thread(target=run_avalanche, daemon=True).start()
    threading.Thread(target=run_scrape, daemon=True).start()

    # After startup, wait 2 min then check if digest was missed (e.g., VM restart mid-morning)
    def _startup_digest_check():
        time.sleep(120)
        print("[startup] Checking if digest was missed...", flush=True)
        maybe_generate_digest()

    threading.Thread(target=_startup_digest_check, daemon=True).start()


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
