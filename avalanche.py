"""Fetch Utah Avalanche Center forecast."""

import json
import requests
from datetime import datetime
import pytz

from database import save_avalanche_forecast

MTN_TZ = pytz.timezone("America/Denver")

UAC_URL = "https://utahavalanchecenter.org/forecast/salt-lake/json"
HEADERS = {"User-Agent": "SkiTracker/1.0 (utah-ski-terrain-tracker)"}

# Map numeric danger values to human-readable levels
DANGER_LEVELS = {
    0: "No Rating",
    1: "Low",
    2: "Low",
    3: "Moderate",
    4: "Moderate",
    5: "Considerable",
    6: "Considerable",
    7: "High",
    8: "High",
    9: "Extreme",
    10: "Extreme",
}

DANGER_COLORS = {
    "Low": "green",
    "Moderate": "yellow",
    "Considerable": "orange",
    "High": "red",
    "Extreme": "black",
    "No Rating": "gray",
}


def _parse_overall_danger(danger_rose):
    """Extract the highest danger level from the danger rose array."""
    if not danger_rose:
        return "No Rating"
    max_val = max(danger_rose) if danger_rose else 0
    return DANGER_LEVELS.get(max_val, "No Rating")


def _parse_avalanche_problems(data):
    """Extract avalanche problems from the forecast data."""
    problems = []
    for i in range(1, 4):  # Up to 3 problems
        problem_key = f"avalanche_problem_{i}"
        if problem_key in data and data[problem_key]:
            problem = data[problem_key]
            if isinstance(problem, dict) and problem.get("type"):
                problems.append({
                    "type": problem.get("type", "Unknown"),
                    "likelihood": problem.get("likelihood", ""),
                    "size": problem.get("size", ""),
                })
    # Also check for advisory/problems in the main data
    if "advisories" in data:
        for adv in data["advisories"]:
            if isinstance(adv, dict):
                problems.append({"type": adv.get("advisory", ""), "likelihood": "", "size": ""})
    return problems


def fetch_avalanche_forecast():
    """Fetch today's avalanche forecast from UAC and save to DB."""
    now = datetime.now(MTN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    fetched_at = now.isoformat()

    try:
        resp = requests.get(UAC_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Extract key fields
        bottom_line = data.get("bottom_line", "")
        # Clean HTML tags from bottom_line
        if bottom_line:
            import re
            bottom_line = re.sub(r"<[^>]+>", "", bottom_line).strip()

        danger_rose = data.get("overall_danger_rose", [])
        overall_danger = _parse_overall_danger(danger_rose)

        # Parse avalanche problems
        problems = _parse_avalanche_problems(data)

        # Store full response for reference, but trim large fields
        stored_data = {
            "overall_danger": overall_danger,
            "bottom_line": bottom_line,
            "danger_rose": danger_rose,
            "problems": problems,
            "forecast_date": data.get("date_issued", ""),
        }

        save_avalanche_forecast(
            "salt-lake", date_str, overall_danger, bottom_line,
            json.dumps(stored_data), fetched_at
        )

        print(f"[avalanche] Danger: {overall_danger}, Problems: {len(problems)}")
        return True

    except Exception as e:
        print(f"[avalanche] Error fetching forecast: {e}")
        return False
