"""Fetch NWS weather forecasts for each resort."""

import requests
from datetime import datetime
import pytz

from database import save_weather_forecast

MTN_TZ = pytz.timezone("America/Denver")

HEADERS = {"User-Agent": "SkiTracker/1.0 (utah-ski-terrain-tracker)"}

# Resort coordinates
RESORT_COORDS = {
    "snowbird": (40.5830, -111.6556),
    "solitude": (40.6199, -111.5919),
    "brighton": (40.5980, -111.5832),
    "snowbasin": (41.2160, -111.8569),
}

# Cache for forecast URLs (they don't change)
_forecast_urls = {}


def _get_forecast_url(resort, lat, lon):
    """Get the NWS forecast URL for a lat/lon (cached)."""
    if resort in _forecast_urls:
        return _forecast_urls[resort]

    try:
        resp = requests.get(
            f"https://api.weather.gov/points/{lat},{lon}",
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        url = data["properties"]["forecast"]
        _forecast_urls[resort] = url
        return url
    except Exception as e:
        print(f"[weather] Failed to get forecast URL for {resort}: {e}")
        return None


def fetch_all_forecasts():
    """Fetch today's weather forecast for all resorts and save to DB."""
    now = datetime.now(MTN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    fetched_at = now.isoformat()

    for resort, (lat, lon) in RESORT_COORDS.items():
        try:
            forecast_url = _get_forecast_url(resort, lat, lon)
            if not forecast_url:
                continue

            resp = requests.get(forecast_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            periods = data.get("properties", {}).get("periods", [])
            if not periods:
                print(f"[weather] No forecast periods for {resort}")
                continue

            # Get today's daytime period (first period)
            today = periods[0]
            tonight = periods[1] if len(periods) > 1 else None

            temp_high = today.get("temperature")
            temp_low = tonight.get("temperature") if tonight else None
            wind = today.get("windSpeed", "")
            if today.get("windDirection"):
                wind = f"{today['windDirection']} {wind}"
            short_forecast = today.get("shortForecast", "")
            detailed = today.get("detailedForecast", "")

            # Combine today + tonight for full text
            forecast_text = f"Today: {detailed}"
            if tonight:
                forecast_text += f"\nTonight: {tonight.get('detailedForecast', '')}"

            save_weather_forecast(
                resort, date_str, forecast_text,
                temp_high, temp_low, wind, short_forecast, fetched_at
            )
            print(f"[weather] {resort}: {short_forecast}, High {temp_high}F")

        except Exception as e:
            print(f"[weather] Error fetching {resort}: {e}")

    print(f"[weather] Fetch complete for {date_str}")
