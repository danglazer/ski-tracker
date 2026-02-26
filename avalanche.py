"""Fetch Utah Avalanche Center forecast."""

import json
import re
import requests
from datetime import datetime
import pytz
from bs4 import BeautifulSoup as BS

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


def _parse_overall_danger(data):
    """Extract the highest danger level from the forecast data.

    Tries multiple fields: overall_danger_rose, danger[], and
    advisory.overall_danger as fallbacks.
    """
    # Try the danger rose array first
    danger_rose = data.get("overall_danger_rose", [])
    if danger_rose and any(v > 0 for v in danger_rose if isinstance(v, (int, float))):
        max_val = max(v for v in danger_rose if isinstance(v, (int, float)))
        level = DANGER_LEVELS.get(int(max_val), None)
        if level:
            return level

    # Try danger[] array (each entry has an elevation + danger level)
    danger_list = data.get("danger", [])
    if isinstance(danger_list, list):
        for entry in danger_list:
            if isinstance(entry, dict):
                val = entry.get("danger")
                if isinstance(val, (int, float)) and val > 0:
                    level = DANGER_LEVELS.get(int(val), None)
                    if level:
                        return level

    # Try overall_danger as a string
    overall_str = data.get("overall_danger", "")
    if isinstance(overall_str, str) and overall_str.strip():
        clean = overall_str.strip().title()
        if clean in DANGER_COLORS:
            return clean

    # Try advisory.overall_danger
    advisory = data.get("advisory", {})
    if isinstance(advisory, dict):
        adv_danger = advisory.get("overall_danger", "")
        if isinstance(adv_danger, str) and adv_danger.strip():
            clean = adv_danger.strip().title()
            if clean in DANGER_COLORS:
                return clean

    return "No Rating"


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

        # Extract key fields — try multiple possible keys
        bottom_line = data.get("bottom_line", "") or data.get("bottom_line_html", "") or ""
        # Clean HTML tags and normalize whitespace
        if bottom_line:
            bottom_line = BS(bottom_line, "html.parser").get_text(separator=" ").strip()
            # Collapse multiple spaces/newlines
            bottom_line = re.sub(r"\s+", " ", bottom_line).strip()
        # If still empty, try the forecast_summary or hazard_discussion
        if not bottom_line:
            bottom_line = data.get("forecast_summary", "") or data.get("hazard_discussion", "") or ""
            if bottom_line:
                bottom_line = BS(bottom_line, "html.parser").get_text(separator=" ").strip()
                bottom_line = re.sub(r"\s+", " ", bottom_line).strip()

        overall_danger = _parse_overall_danger(data)

        # Parse avalanche problems
        problems = _parse_avalanche_problems(data)

        # Store full response for reference, but trim large fields
        stored_data = {
            "overall_danger": overall_danger,
            "bottom_line": bottom_line,
            "danger_rose": data.get("overall_danger_rose", []),
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
