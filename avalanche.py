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
    # Values may be ints, floats, or strings like "5"
    danger_rose = advisory.get("overall_danger_rose", [])
    if danger_rose:
        numeric_vals = []
        for v in danger_rose:
            try:
                numeric_vals.append(int(v))
            except (TypeError, ValueError):
                pass
        if numeric_vals and max(numeric_vals) > 0:
            level = DANGER_LEVELS.get(max(numeric_vals), None)
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


def _get_issued_date(advisory, data):
    """Extract the date the forecast was issued, using the Unix timestamp.

    Returns a YYYY-MM-DD string in Mountain Time, or None if unparseable.
    """
    # Prefer the Unix timestamp (most reliable)
    ts = advisory.get("date_issued_timestamp") or data.get("date_issued_timestamp")
    if ts:
        try:
            issued_dt = datetime.fromtimestamp(int(ts), tz=MTN_TZ)
            return issued_dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            pass

    # Fallback: parse the human-readable date_issued string
    # Format: "Sunday, March 8, 2026 - 6:22am" or "Saturday, March 7, 2026 at 6:49 AM"
    date_str_raw = advisory.get("date_issued", "") or data.get("date_issued", "")
    if date_str_raw:
        for fmt in ["%A, %B %d, %Y - %I:%M%p", "%A, %B %d, %Y at %I:%M %p"]:
            try:
                issued_dt = datetime.strptime(date_str_raw.strip(), fmt)
                return issued_dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        # Last resort: look for a YYYY pattern and month/day
        m = re.search(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", date_str_raw)
        if m:
            try:
                issued_dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y")
                return issued_dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

    return None


def fetch_avalanche_forecast():
    """Fetch today's avalanche forecast from UAC and save to DB.

    Only saves if the forecast was actually issued today. If the UAC API
    still returns yesterday's forecast (before ~6:30am), we skip saving
    and let the scheduler try again on the next cycle.
    """
    now = datetime.now(MTN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    fetched_at = now.isoformat()

    try:
        resp = requests.get(UAC_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # UAC API structure: {"advisories": [{"advisory": {...}}]}
        # Extract the advisory dict from the nested structure
        advisory = {}
        advisories = data.get("advisories", [])
        if isinstance(advisories, list) and len(advisories) > 0:
            first = advisories[0]
            if isinstance(first, dict):
                advisory = first.get("advisory", first)
        # Fallback: maybe it's data["advisory"] directly
        if not advisory:
            advisory = data.get("advisory", data)

        # Check if the forecast was actually issued today
        issued_date = _get_issued_date(advisory, data)
        if issued_date and issued_date != date_str:
            print(f"[avalanche] Forecast is from {issued_date}, not today ({date_str}). Skipping — UAC hasn't posted yet.", flush=True)
            return False

        # Extract bottom line (HTML content)
        bottom_line = _clean_html(
            advisory.get("bottom_line", "")
            or advisory.get("bottom_line_html", "")
            or data.get("bottom_line", "")
        )

        overall_danger = _parse_overall_danger(advisory)

        # Parse avalanche problems
        problems = _parse_avalanche_problems(advisory)

        # Extract danger rose image URL from HTML img tag
        rose_image_html = advisory.get("overall_danger_rose_image", "")
        rose_image_url = ""
        if rose_image_html:
            match = re.search(r'src="([^"]+)"', rose_image_html)
            if match:
                rose_image_url = match.group(1)

        # Store structured data for frontend
        date_issued_str = advisory.get("date_issued", "") or data.get("date_issued", "")
        stored_data = {
            "overall_danger": overall_danger,
            "bottom_line": bottom_line,
            "danger_rose_image": rose_image_url,
            "problems": problems,
            "forecast_date": date_issued_str,
            "issued_date": issued_date,  # YYYY-MM-DD for easy comparison
        }

        save_avalanche_forecast(
            "salt-lake", date_str, overall_danger, bottom_line,
            json.dumps(stored_data), fetched_at
        )

        print(f"[avalanche] Saved forecast issued {issued_date}. Danger: {overall_danger}, Problems: {len(problems)}, Bottom line: {len(bottom_line)} chars")
        return True

    except Exception as e:
        print(f"[avalanche] Error fetching forecast: {e}")
        return False
