from datetime import datetime

import pytz
from flask import Flask, jsonify, render_template, request

from database import init_db, get_daily_view, get_all_dates

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
