"""Date, duration, pace, speed and text formatting for Runkeeper activities."""

from __future__ import annotations

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from export_inspector.runkeeper.models import DATE_FORMAT


def parse_date_filter(value: str | None, timezone_name: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(
            tzinfo=ZoneInfo(timezone_name)
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected format: YYYY-MM-DD."
        ) from exc


def format_dt(value: datetime, timezone_name: str) -> str:
    """Format a datetime in `timezone_name` as `YYYY-MM-DD HH:MM:SS`."""
    return value.astimezone(ZoneInfo(timezone_name)).strftime(DATE_FORMAT)


def format_duration(seconds: float) -> str:
    """Format seconds as `M:SS`, or `H:MM:SS` from one hour."""
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_pace(distance_km: float, duration_seconds: float) -> str:
    """Format the pace as `M:SS /km`, or "-" without distance or duration."""
    if distance_km <= 0 or duration_seconds <= 0:
        return "-"
    pace_seconds = duration_seconds / distance_km
    minutes, seconds = divmod(int(round(pace_seconds)), 60)
    return f"{minutes}:{seconds:02d} /km"


def format_speed(distance_km: float, duration_seconds: float) -> str:
    """Format the average speed as `N.NN km/h`, or "-" without duration."""
    if duration_seconds <= 0:
        return "-"
    kmh = distance_km / (duration_seconds / 3600)
    return f"{kmh:.2f} km/h"


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def shorten(text: str, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
