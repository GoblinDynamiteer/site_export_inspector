"""Untappd check-in export loading and per-check-in field helpers (no CLI, no Qt)."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def load_export(path: Path) -> list[dict[str, Any]]:
    """Load an Untappd JSON export as its list of check-in dicts, in file order.

    Raises SystemExit if the file is missing or the JSON is not an array.
    """
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("Expected the Untappd export to be a JSON array.")
    return data


def parse_created_at(value: str) -> datetime:
    """Parse a check-in `created_at` (`YYYY-MM-DD HH:MM:SS`) as Europe/Stockholm time."""
    return datetime.strptime(value, DATE_FORMAT).replace(tzinfo=ZoneInfo("Europe/Stockholm"))


def parse_date_filter(value: str | None) -> datetime | None:
    """Parse a `YYYY-MM-DD` date filter as Stockholm midnight; None for an empty value.

    Raises argparse.ArgumentTypeError for any other format.
    """
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Europe/Stockholm"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected format: YYYY-MM-DD."
        ) from exc


def normalize_text(value: Any) -> str:
    """Return `value` as a stripped string, or "" for None."""
    if value is None:
        return ""
    return str(value).strip()


def parse_rating(entry: dict[str, Any]) -> float | None:
    """Return the check-in's own rating (`rating_score`), or None if unrated or invalid."""
    value = entry.get("rating_score")
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def display_rating(entry: dict[str, Any]) -> str:
    """Return the rating with at most two decimals and no trailing zeros, or "-"."""
    rating = parse_rating(entry)
    if rating is None:
        return "-"
    return f"{rating:.2f}".rstrip("0").rstrip(".")


def shorten(text: str, limit: int = 220) -> str:
    """Collapse whitespace and cut to `limit` characters, ending in "..." if cut."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def entry_search_fields(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the (label, text) fields that text search looks in, in display order."""
    return [
        ("Beer", normalize_text(entry.get("beer_name"))),
        ("Brewery", normalize_text(entry.get("brewery_name"))),
        ("Type", normalize_text(entry.get("beer_type"))),
        ("Comment", normalize_text(entry.get("comment"))),
        ("Venue", normalize_text(entry.get("venue_name"))),
        ("Purchase venue", normalize_text(entry.get("purchase_venue"))),
        ("Flavor", normalize_text(entry.get("flavor_profiles"))),
        ("Serving", normalize_text(entry.get("serving_type"))),
        ("Brewery country", normalize_text(entry.get("brewery_country"))),
        ("Venue country", normalize_text(entry.get("venue_country"))),
        ("Tagged friends", normalize_text(entry.get("tagged_friends"))),
    ]


def format_float(value: Any) -> str:
    """Format a raw export value: floats with at most four decimals, "-" for empty or
    non-finite values, anything else via str()."""
    if value is None or value == "":
        return "-"
    if isinstance(value, float):
        if math.isfinite(value):
            return f"{value:.4f}".rstrip("0").rstrip(".")
        return "-"
    return str(value)
