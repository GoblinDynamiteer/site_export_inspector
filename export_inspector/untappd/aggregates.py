"""Group Untappd check-ins by beer, brewery and venue, and the values the views show for them.

Qt-free: the GUI tab builds its tables and filters from these functions. Groups are plain
dicts (see the `build_*_groups` docstrings) so their scalar fields can feed search blobs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from export_inspector.untappd.checkins import (
    display_rating,
    format_float,
    normalize_text,
    parse_created_at,
    parse_rating,
)


def beer_key(entry: dict) -> str:
    """Return a key that identifies the check-in's beer: its `bid`, else brewery + beer name."""
    bid = normalize_text(entry.get("bid"))
    if bid:
        return f"bid:{bid}"
    beer = normalize_text(entry.get("beer_name")).lower()
    brewery = normalize_text(entry.get("brewery_name")).lower()
    return f"name:{brewery}|{beer}"


def brewery_key(entry: dict) -> str:
    """Return a key that identifies the brewery: its id, else country + brewery name."""
    brewery_id = normalize_text(entry.get("brewery_id"))
    if brewery_id:
        return f"brewery:{brewery_id}"
    brewery = normalize_text(entry.get("brewery_name")).lower()
    country = normalize_text(entry.get("brewery_country")).lower()
    return f"name:{country}|{brewery}"


def venue_key(entry: dict) -> str:
    """Return a key for the venue (or purchase venue) with city and country; "" if none."""
    venue = normalize_text(entry.get("venue_name"))
    purchase_venue = normalize_text(entry.get("purchase_venue"))
    if not venue and not purchase_venue:
        return ""
    city = normalize_text(entry.get("venue_city")).lower()
    country = normalize_text(entry.get("venue_country")).lower()
    return f"venue:{country}|{city}|{(venue or purchase_venue).lower()}"


def entry_key(entry: dict) -> str:
    """Return a stable key for the check-in itself: its id, else beer key + created time.

    Used instead of object identity because Qt item data may hand back copies.
    """
    checkin_id = normalize_text(entry.get("checkin_id"))
    if checkin_id:
        return f"checkin:{checkin_id}"
    created = normalize_text(entry.get("created_at"))
    return f"fallback:{beer_key(entry)}|{created}"


def entry_created_dt(entry: dict) -> datetime | None:
    """Return the check-in time, or None if `created_at` is missing or unparsable."""
    created = normalize_text(entry.get("created_at"))
    if not created:
        return None
    try:
        return parse_created_at(created)
    except Exception:
        return None


@dataclass
class HadCounts:
    """Per-beer totals and chronological numbering of the check-ins in one export.

    `checkin_index` numbers every check-in from 1 (oldest first); `had_index` is the
    occurrence number of the beer at that check-in; `had_count` is the beer's total.
    Unknown check-ins and beers count as 0.
    """

    per_beer: dict[str, int] = field(default_factory=dict)
    had_indexes: dict[str, int] = field(default_factory=dict)
    checkin_indexes: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_entries(cls, entries: list[dict]) -> HadCounts:
        counts: dict[str, int] = {}
        indexes: dict[str, int] = {}
        checkin_indexes: dict[str, int] = {}
        sorted_entries = sorted(
            entries,
            key=lambda item: entry_created_dt(item) or datetime.min,
        )
        for checkin_index, entry in enumerate(sorted_entries, start=1):
            key = beer_key(entry)
            counts[key] = counts.get(key, 0) + 1
            indexes[entry_key(entry)] = counts[key]
            checkin_indexes[entry_key(entry)] = checkin_index
        return cls(counts, indexes, checkin_indexes)

    def had_count(self, entry: dict) -> int:
        return self.per_beer.get(beer_key(entry), 0)

    def had_index(self, entry: dict) -> int:
        return self.had_indexes.get(entry_key(entry), 0)

    def checkin_index(self, entry: dict) -> int:
        return self.checkin_indexes.get(entry_key(entry), 0)


def _sorted_by_created(entries: list[dict]) -> list[dict]:
    return sorted(
        entries,
        key=lambda item: entry_created_dt(item) or datetime.min,
    )


def _ratings(entries: list[dict]) -> list[float]:
    return [rating for entry in entries if (rating := parse_rating(entry)) is not None]


def _latest_first(groups: list[dict]) -> list[dict]:
    return sorted(
        groups,
        key=lambda item: item["latest_dt"] or datetime.min,
        reverse=True,
    )


def build_beer_groups(entries: list[dict]) -> list[dict]:
    """Group check-ins by `beer_key`, latest-had group first.

    Each group has `key`, `entries` (oldest first), `beer`, `brewery`, `beer_type`,
    `first_dt`, `latest_dt` and `ratings` (the rated check-ins' ratings).
    """
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(beer_key(entry), []).append(entry)

    groups: list[dict] = []
    for key, group_entries in grouped.items():
        sorted_entries = _sorted_by_created(group_entries)
        first = sorted_entries[0]
        latest = sorted_entries[-1]
        groups.append(
            {
                "key": key,
                "entries": sorted_entries,
                "beer": normalize_text(first.get("beer_name")) or "-",
                "brewery": normalize_text(first.get("brewery_name")) or "-",
                "beer_type": normalize_text(first.get("beer_type")) or "-",
                "first_dt": entry_created_dt(first),
                "latest_dt": entry_created_dt(latest),
                "ratings": _ratings(sorted_entries),
            }
        )
    return _latest_first(groups)


def build_brewery_groups(entries: list[dict]) -> list[dict]:
    """Group check-ins by `brewery_key`, latest-had group first.

    Each group has `key`, `entries` (oldest first), `brewery`, `city`, `state`,
    `country`, `first_dt`, `latest_dt`, `ratings` and `unique_beers`.
    """
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(brewery_key(entry), []).append(entry)

    groups: list[dict] = []
    for key, group_entries in grouped.items():
        sorted_entries = _sorted_by_created(group_entries)
        first = sorted_entries[0]
        latest = sorted_entries[-1]
        groups.append(
            {
                "key": key,
                "entries": sorted_entries,
                "brewery": normalize_text(first.get("brewery_name")) or "-",
                "city": normalize_text(first.get("brewery_city")) or "-",
                "state": normalize_text(first.get("brewery_state")) or "-",
                "country": normalize_text(first.get("brewery_country")) or "-",
                "first_dt": entry_created_dt(first),
                "latest_dt": entry_created_dt(latest),
                "ratings": _ratings(sorted_entries),
                "unique_beers": len({beer_key(entry) for entry in group_entries}),
            }
        )
    return _latest_first(groups)


def build_venue_groups(entries: list[dict]) -> list[dict]:
    """Group check-ins by `venue_key` (check-ins without a venue are left out), latest first.

    Each group has `key`, `entries` (oldest first), `venue`, `city`, `state`, `country`,
    `lat`, `lng`, `first_dt`, `latest_dt`, `ratings`, `unique_beers` and
    `unique_breweries`.
    """
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        key = venue_key(entry)
        if key:
            grouped.setdefault(key, []).append(entry)

    groups: list[dict] = []
    for key, group_entries in grouped.items():
        sorted_entries = _sorted_by_created(group_entries)
        first = sorted_entries[0]
        latest = sorted_entries[-1]
        groups.append(
            {
                "key": key,
                "entries": sorted_entries,
                "venue": venue_label(first),
                "city": normalize_text(first.get("venue_city")) or "-",
                "state": normalize_text(first.get("venue_state")) or "-",
                "country": normalize_text(first.get("venue_country")) or "-",
                "lat": normalize_text(first.get("venue_lat")),
                "lng": normalize_text(first.get("venue_lng")),
                "first_dt": entry_created_dt(first),
                "latest_dt": entry_created_dt(latest),
                "ratings": _ratings(sorted_entries),
                "unique_beers": len({beer_key(entry) for entry in group_entries}),
                "unique_breweries": len({brewery_key(entry) for entry in group_entries}),
            }
        )
    return _latest_first(groups)


def venue_label(entry: dict) -> str:
    """Return the venue name, else the purchase venue, else "-"."""
    return (
        normalize_text(entry.get("venue_name"))
        or normalize_text(entry.get("purchase_venue"))
        or "-"
    )


def mean_rating_value(ratings: list[float]) -> float:
    """Return the mean rating, or -1.0 (sorts below every rating) when there are none."""
    if not ratings:
        return -1.0
    return sum(ratings) / len(ratings)


def mean_rating_text(ratings: list[float]) -> str:
    """Return the mean rating with at most two decimals and no trailing zeros, or "-"."""
    if not ratings:
        return "-"
    return f"{mean_rating_value(ratings):.2f}".rstrip("0").rstrip(".")


def top_counts(
    entries: list[dict], labeler: Callable[[dict], str], limit: int = 8
) -> list[tuple[str, int]]:
    """Count `labeler(entry)` values; return the `limit` most common (ties by name)."""
    counts: dict[str, int] = {}
    for entry in entries:
        label = labeler(entry)
        counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:limit]


def format_abv(value: str) -> str:
    """Format an ABV value with one decimal, falling back to `format_float` if not numeric."""
    try:
        return f"{float(value):.1f}"
    except ValueError:
        return format_float(value)


def abv_table_text(entry: dict) -> str:
    """Return the beer's ABV as table text, e.g. "5.5%", or "-" if missing."""
    abv = normalize_text(entry.get("beer_abv"))
    if not abv:
        return "-"
    return f"{format_abv(abv)}%"


def abv_sort_value(entry: dict) -> float:
    """Return the ABV as a number for sorting, -1.0 if missing or not numeric."""
    try:
        return float(normalize_text(entry.get("beer_abv")))
    except ValueError:
        return -1.0


def entry_search_blob(entry: dict, had: HadCounts) -> str:
    """Return the newline-joined text the check-ins filter matches against."""
    fields = [
        normalize_text(entry.get("created_at")),
        str(had.checkin_index(entry)),
        normalize_text(entry.get("beer_name")),
        abv_table_text(entry),
        normalize_text(entry.get("brewery_name")),
        normalize_text(entry.get("beer_type")),
        display_rating(entry),
        str(had.had_count(entry)),
        str(had.had_index(entry)),
        normalize_text(entry.get("venue_name")),
        normalize_text(entry.get("purchase_venue")),
        normalize_text(entry.get("brewery_country")),
        normalize_text(entry.get("venue_country")),
        normalize_text(entry.get("comment")),
        normalize_text(entry.get("flavor_profiles")),
        normalize_text(entry.get("serving_type")),
        normalize_text(entry.get("tagged_friends")),
        normalize_text(entry.get("checkin_id")),
    ]
    return "\n".join(field for field in fields if field)


def beer_search_blob(group: dict) -> str:
    """Return the text the beers filter matches against for a `build_beer_groups` group."""
    fields = [
        group["brewery"],
        group["beer"],
        group["beer_type"],
        abv_table_text(group["entries"][0]),
        mean_rating_text(group["ratings"]),
        str(len(group["entries"])),
    ]
    for entry in group["entries"]:
        fields.extend(
            [
                normalize_text(entry.get("created_at")),
                normalize_text(entry.get("venue_name")),
                normalize_text(entry.get("purchase_venue")),
                normalize_text(entry.get("venue_country")),
                normalize_text(entry.get("brewery_country")),
                normalize_text(entry.get("comment")),
                normalize_text(entry.get("flavor_profiles")),
            ]
        )
    return "\n".join(field for field in fields if field)


def aggregate_search_blob(group: dict) -> str:
    """Return the filter text for a brewery or venue group: its scalar fields plus each
    check-in's beer, brewery, style, rating, venue and comment."""
    fields = [
        str(value)
        for key, value in group.items()
        if key not in {"entries", "ratings"} and value not in (None, "")
    ]
    for entry in group["entries"]:
        fields.extend(
            [
                normalize_text(entry.get("created_at")),
                normalize_text(entry.get("beer_name")),
                normalize_text(entry.get("brewery_name")),
                normalize_text(entry.get("beer_type")),
                display_rating(entry),
                normalize_text(entry.get("venue_name")),
                normalize_text(entry.get("purchase_venue")),
                normalize_text(entry.get("comment")),
            ]
        )
    return "\n".join(field for field in fields if field)
