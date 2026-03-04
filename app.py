from datetime import datetime

import pytz
from flask import Flask, jsonify, render_template, request

from database import (
    init_db, get_daily_view, get_all_dates, get_full_history, get_terrain_history,
    get_resort_snow_history, get_snow_report, get_all_weather_forecasts,
    get_avalanche_forecast, get_daily_digest, get_last_scrape_time,
    backfill_daily_from_snapshots,
)

from scraper import TRACKED

app = Flask(__name__)
MTN_TZ = pytz.timezone("America/Denver")

init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/dates")
def api_dates():
    return jsonify(get_all_dates())


@app.route("/api/history")
def api_history():
    data = get_full_history()
    return jsonify(data)


@app.route("/api/terrain-calendar")
def api_terrain_calendar():
    resort = request.args.get("resort")
    terrain = request.args.get("terrain")
    if not resort or not terrain:
        return jsonify({"error": "resort and terrain required"}), 400
    days = get_terrain_history(resort, terrain)
    return jsonify({"resort": resort, "terrain": terrain, "days": days})


@app.route("/api/snow-calendar")
def api_snow_calendar():
    resort = request.args.get("resort")
    if not resort:
        return jsonify({"error": "resort required"}), 400
    days = get_resort_snow_history(resort)
    return jsonify({"resort": resort, "days": days})


@app.route("/api/snow-report")
def api_snow_report():
    resort = request.args.get("resort")
    date_str = request.args.get("date")
    if not resort or not date_str:
        return jsonify({"error": "resort and date required"}), 400
    text = get_snow_report(resort, date_str)
    return jsonify({"resort": resort, "date": date_str, "report_text": text})


@app.route("/api/weather")
def api_weather():
    date_str = request.args.get("date")
    if not date_str:
        date_str = datetime.now(MTN_TZ).strftime("%Y-%m-%d")
    forecasts = get_all_weather_forecasts(date_str)
    return jsonify(forecasts)


@app.route("/api/avalanche")
def api_avalanche():
    date_str = request.args.get("date")
    if not date_str:
        date_str = datetime.now(MTN_TZ).strftime("%Y-%m-%d")
    forecast = get_avalanche_forecast("salt-lake", date_str)
    return jsonify(forecast or {})


@app.route("/api/digest")
def api_digest():
    date_str = request.args.get("date")
    if not date_str:
        date_str = datetime.now(MTN_TZ).strftime("%Y-%m-%d")
    digest = get_daily_digest(date_str)
    return jsonify(digest or {})


# Add weather data to status endpoint
@app.route("/api/status")
def api_status():
    date_str = request.args.get("date")
    if not date_str:
        date_str = datetime.now(MTN_TZ).strftime("%Y-%m-%d")

    view = get_daily_view(date_str)
    weather = get_all_weather_forecasts(date_str)

    response = {}
    # Always include all tracked resorts so cards render even without terrain data
    for resort, terrain_names in TRACKED.items():
        terrain_list = view.get(resort, [])
        snow = terrain_list[0]["snowfall_24hr"] if terrain_list else 0.0
        resort_data = {
            "snow_24hr": snow,
            "terrain": [
                {
                    "name": t["terrain_name"],
                    "ever_opened": bool(t["ever_opened"]),
                    "first_opened_at": t.get("first_opened_at"),
                    "closed_streak": t["closed_streak"],
                }
                for t in terrain_list
            ],
        }
        if resort in weather:
            resort_data["weather"] = weather[resort]
        response[resort] = resort_data

    return jsonify(response)


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Manually trigger a full scrape cycle."""
    import threading
    from scraper import scrape_all
    from database import save_snapshot, update_daily_summary, save_snow_report
    from digest import summarize_snow_report

    def do_scrape():
        now = datetime.now(MTN_TZ)
        date_str = now.strftime("%Y-%m-%d")
        scraped_at = now.isoformat()
        results = scrape_all()
        for resort, data in results.items():
            snow = data.get("snow_24hr", 0.0)
            for t in data.get("terrain", []):
                save_snapshot(resort, t["name"], t["status"], scraped_at)
                update_daily_summary(resort, t["name"], date_str, t["status"], snow, scraped_at)
            raw_text = data.get("raw_report_text", "")
            if raw_text and len(raw_text.strip()) > 50:
                summary = summarize_snow_report(resort, raw_text)
                if summary:
                    save_snow_report(resort, date_str, summary, scraped_at)

    threading.Thread(target=do_scrape, daemon=True).start()
    return jsonify({"status": "scrape started"}), 202


@app.route("/api/last-scrape")
def api_last_scrape():
    """Return the timestamp of the most recent scrape and dates with data."""
    last = get_last_scrape_time()
    dates = get_all_dates()
    return jsonify({"last_scrape": last, "dates_with_data": dates})


@app.route("/api/backfill", methods=["POST"])
def api_backfill():
    """Backfill daily_summary from terrain_snapshots for specific dates."""
    dates = request.json.get("dates", []) if request.is_json else []
    if not dates:
        return jsonify({"error": "provide dates array in JSON body"}), 400
    results = {}
    for d in dates:
        count = backfill_daily_from_snapshots(d)
        results[d] = count
    return jsonify({"backfilled": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
