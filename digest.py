"""Generate daily AI digest using Claude API."""

import os
import json
from datetime import datetime, timedelta
import pytz

from database import (
    get_daily_view, get_terrain_open_times, get_all_weather_forecasts,
    get_avalanche_forecast, get_recent_daily_summaries, get_recent_digests,
    save_daily_digest, get_snow_report,
)

MTN_TZ = pytz.timezone("America/Denver")


def _format_terrain_summary(date_str, open_times):
    """Format yesterday's terrain data for the prompt."""
    view = get_daily_view(date_str)
    if not view:
        return "No terrain data available."

    lines = []
    for resort, terrain_list in sorted(view.items()):
        snow = terrain_list[0]["snowfall_24hr"] if terrain_list else 0
        lines.append(f"\n{resort.title()} (24hr snow: {snow}\")")
        for t in terrain_list:
            status = "OPENED" if t["ever_opened"] else "CLOSED"
            key = f"{resort}|{t['terrain_name']}"
            open_time = open_times.get(key, "")
            time_str = ""
            if open_time:
                try:
                    dt = datetime.fromisoformat(open_time)
                    time_str = f" (first opened at {dt.strftime('%I:%M %p')})"
                except Exception:
                    pass
            lines.append(f"  - {t['terrain_name']}: {status}{time_str}")

    return "\n".join(lines)


def _format_weather(date_str):
    """Format today's weather forecasts for the prompt."""
    forecasts = get_all_weather_forecasts(date_str)
    if not forecasts:
        return "No weather forecast data available."

    lines = []
    for resort, wx in sorted(forecasts.items()):
        high = wx.get("temperature_high", "?")
        short = wx.get("short_forecast", "")
        wind = wx.get("wind", "")
        lines.append(f"  {resort.title()}: {short}, High {high}F, Wind {wind}")

    return "\n".join(lines)


def _format_avalanche(date_str):
    """Format today's avalanche forecast for the prompt."""
    avy = get_avalanche_forecast("salt-lake", date_str)
    if not avy:
        return "No avalanche forecast available."

    parts = [f"  Danger Level: {avy['overall_danger']}"]
    if avy.get("bottom_line"):
        parts.append(f"  Summary: {avy['bottom_line'][:500]}")

    if avy.get("forecast_json"):
        try:
            data = json.loads(avy["forecast_json"])
            problems = data.get("problems", [])
            if problems:
                parts.append("  Problems:")
                for p in problems:
                    parts.append(f"    - {p.get('type', 'Unknown')}")
        except Exception:
            pass

    return "\n".join(parts)


def _format_historical(summaries):
    """Format recent historical data for the prompt."""
    if not summaries:
        return "No historical data available."

    # Group by date
    by_date = {}
    for row in summaries:
        d = row["date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(row)

    lines = []
    for date in sorted(by_date.keys())[-14:]:  # Last 14 days
        entries = by_date[date]
        snow_vals = set()
        open_count = 0
        total = 0
        for e in entries:
            snow_vals.add(e["snowfall_24hr"])
            if e["ever_opened"]:
                open_count += 1
            total += 1
        max_snow = max(snow_vals) if snow_vals else 0
        lines.append(f"  {date}: {max_snow}\" snow, {open_count}/{total} terrain opened")

    return "\n".join(lines)


def _format_snow_reports(date_str):
    """Format yesterday's snow reports for the prompt."""
    reports = []
    for resort in ["snowbird", "solitude", "brighton", "snowbasin"]:
        text = get_snow_report(resort, date_str)
        if text:
            reports.append(f"  {resort.title()}: {text[:300]}")
    return "\n".join(reports) if reports else "No snow reports available."


def generate_digest():
    """Generate today's daily digest."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[digest] No ANTHROPIC_API_KEY set, skipping digest generation")
        return False

    try:
        import anthropic
    except ImportError:
        print("[digest] anthropic package not installed, skipping digest generation")
        return False

    now = datetime.now(MTN_TZ)
    today_str = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    # Gather data
    open_times = get_terrain_open_times(yesterday)
    terrain_summary = _format_terrain_summary(yesterday, open_times)
    weather_text = _format_weather(today_str)
    avalanche_text = _format_avalanche(today_str)
    historical = _format_historical(get_recent_daily_summaries(30))
    snow_reports = _format_snow_reports(yesterday)

    # Get recent digest pattern notes for compounding
    recent = get_recent_digests(3)
    pattern_context = ""
    if recent:
        pattern_context = "\n\nPREVIOUS PATTERN NOTES (for reference, build on these):\n"
        for d in recent:
            pattern_context += f"\n--- {d['date']} ---\n{d['digest_text'][:500]}\n"

    prompt = f"""You are a ski conditions analyst for Utah resorts (Snowbird, Solitude, Brighton, Snowbasin).
Generate a concise daily briefing for powder hunters. Be direct and practical.

YESTERDAY ({yesterday}) TERRAIN & SNOW:
{terrain_summary}

YESTERDAY'S SNOW REPORTS:
{snow_reports}

TODAY ({today_str}) WEATHER FORECAST:
{weather_text}

TODAY'S AVALANCHE FORECAST (Salt Lake mountains):
{avalanche_text}

RECENT HISTORY (last 14 days):
{historical}
{pattern_context}

Generate a daily digest with these sections:

## Yesterday Recap
What happened with snow and terrain yesterday. Note any terrain that opened or stayed closed despite snow.

## Today's Outlook
Where to ski today and why, based on weather, avalanche conditions, and likely terrain openings.

## Pattern Notes
Any trends you notice — terrain opening patterns after storms, resorts that tend to open backcountry faster, etc.

Keep it concise (under 400 words total). Use bullet points. Be opinionated about where to ski."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )

        digest_text = message.content[0].text
        save_daily_digest(today_str, digest_text, now.isoformat())
        print(f"[digest] Generated digest for {today_str} ({len(digest_text)} chars)")
        return True

    except Exception as e:
        print(f"[digest] Error generating digest: {e}")
        return False
