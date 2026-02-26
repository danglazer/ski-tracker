from datetime import datetime

import pytz
from flask import Flask, jsonify, render_template, request

from database import (
    init_db, get_daily_view, get_all_dates, get_full_history, get_terrain_history,
    get_resort_snow_history, get_snow_report, get_all_weather_forecasts,
    get_avalanche_forecast, get_daily_digest,
)

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
    for resort, terrain_list in view.items():
        snow = terrain_list[0]["snowfall_24hr"] if terrain_list else 0.0
        resort_data = {
            "snow_24hr": snow,
            "terrain": [
                {
                    "name": t["terrain_name"],
                    "ever_opened": bool(t["ever_opened"]),
                    "closed_streak": t["closed_streak"],
                }
                for t in terrain_list
            ],
        }
        if resort in weather:
            resort_data["weather"] = weather[resort]
        response[resort] = resort_data

    return jsonify(response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
