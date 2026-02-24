from datetime import datetime

import pytz
from flask import Flask, jsonify, render_template, request

from database import init_db, get_daily_view, get_all_dates, get_full_history, get_terrain_history, get_resort_snow_history

app = Flask(__name__)
MTN_TZ = pytz.timezone("America/Denver")

init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    date_str = request.args.get("date")
    if not date_str:
        date_str = datetime.now(MTN_TZ).strftime("%Y-%m-%d")

    view = get_daily_view(date_str)

    response = {}
    for resort, terrain_list in view.items():
        snow = terrain_list[0]["snowfall_24hr"] if terrain_list else 0.0
        response[resort] = {
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

    return jsonify(response)


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
