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
HEADERS = {
    "User-Agent": "SkiTerrainTracker/1.0 (https://github.com/utah-ski-tracker; ski-terrain-tracker@example.com)"
}

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


def _parse_overall_danger(advisory):
    """Extract the highest danger level from the advisory data.

    The UAC API nests forecast data inside an 'advisory' object.
    The overall_danger_rose array contains numeric danger values for
    each aspect/elevation segment — the max value gives the overall rating.
    """
    # Try the danger rose array first (primary method)
    danger_rose = advisory.get("overall_danger_rose", [])
    if danger_rose and any(v > 0 for v in danger_rose if isinstance(v, (int, float))):
        max_val = max(v for v in danger_rose if isinstance(v, (int, float)))
        level = DANGER_LEVELS.get(int(max_val), None)
        if level:
            return level

    # Try overall_danger as a direct string field
    overall_str = advisory.get("overall_danger", "")
    if isinstance(overall_str, str) and overall_str.strip():
        clean = overall_str.strip().title()
        if clean in DANGER_COLORS:
            return clean

    return "No Rating"


def _parse_avalanche_problems(advisory):
    """Extract avalanche problems from the advisory data."""
    problems = []
    for i in range(1, 4):  # Up to 3 problems
        problem_key = f"avalanche_problem_{i}"
        if problem_key in advisory and advisory[problem_key]:
            problem = advisory[problem_key]
            if isinstance(problem, dict) and problem.get("type"):
                problems.append({
                    "type": problem.get("type", "Unknown"),
                    "likelihood": problem.get("likelihood", ""),
                    "size": problem.get("size", ""),
                })
    return problems


def _clean_html(html_str):
    """Strip HTML tags and normalize whitespace."""
    if not html_str:
        return ""
    text = BS(html_str, "html.parser").get_text(separator=" ").strip()
    return re.sub(r"\s+", " ", text).strip()


def fetch_avalanche_forecast():
    """Fetch today's avalanche forecast from UAC and save to DB."""
    now = datetime.now(MTN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    fetched_at = now.isoformat()

    try:
        resp = requests.get(UAC_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # UAC API nests everything inside "advisory" — but handle both
        # structures for robustness
        advisory = data.get("advisory", data)
        if not isinstance(advisory, dict):
            advisory = data

        # Extract bottom line (HTML content)
        bottom_line = _clean_html(
            advisory.get("bottom_line", "")
            or advisory.get("bottom_line_html", "")
            or data.get("bottom_line", "")
        )

        overall_danger = _parse_overall_danger(advisory)

        # Parse avalanche problems
        problems = _parse_avalanche_problems(advisory)

        # Store structured data for frontend
        stored_data = {
            "overall_danger": overall_danger,
            "bottom_line": bottom_line,
            "danger_rose": advisory.get("overall_danger_rose", []),
            "problems": problems,
            "forecast_date": advisory.get("date_issued", "") or data.get("date_issued", ""),
        }

        save_avalanche_forecast(
            "salt-lake", date_str, overall_danger, bottom_line,
            json.dumps(stored_data), fetched_at
        )

        print(f"[avalanche] Danger: {overall_danger}, Problems: {len(problems)}, Bottom line: {len(bottom_line)} chars")
        return True

    except Exception as e:
        print(f"[avalanche] Error fetching forecast: {e}")
        return False
