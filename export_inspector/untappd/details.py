"""Plain-text detail views for an Untappd check-in, beer, brewery or venue (Qt-free).

The GUI shows these strings in its detail panes. Groups come from
`export_inspector.untappd.aggregates`, and `had` numbers the check-ins of the whole export.
"""

from __future__ import annotations

from datetime import datetime

from export_inspector.untappd.aggregates import (
    HadCounts,
    abv_table_text,
    beer_key,
    entry_created_dt,
    mean_rating_text,
    top_counts,
    venue_label,
)
from export_inspector.untappd.checkins import display_rating, format_float, normalize_text

CHECKIN_DETAIL_FIELDS: list[tuple[str, str | None]] = [
    ("Beer", "beer_name"),
    ("Brewery", "brewery_name"),
    ("Type", "beer_type"),
    ("Check-in", None),
    ("Total had with this check-in", None),
    ("Total Had", None),
    ("Your rating", "rating_score"),
    ("Global rating", "global_rating_score"),
    ("Weighted global rating", "global_weighted_rating_score"),
    ("ABV", "beer_abv"),
    ("IBU", "beer_ibu"),
    ("Created at", "created_at"),
    ("Venue", "venue_name"),
    ("Venue city", "venue_city"),
    ("Venue state", "venue_state"),
    ("Venue country", "venue_country"),
    ("Purchase venue", "purchase_venue"),
    ("Serving type", "serving_type"),
    ("Flavor profiles", "flavor_profiles"),
    ("Tagged friends", "tagged_friends"),
    ("Toasts", "total_toasts"),
    ("Comments", "total_comments"),
    ("Brewery city", "brewery_city"),
    ("Brewery state", "brewery_state"),
    ("Brewery country", "brewery_country"),
    ("Venue lat", "venue_lat"),
    ("Venue lng", "venue_lng"),
    ("Check-in ID", "checkin_id"),
    ("Beer ID", "bid"),
    ("Brewery ID", "brewery_id"),
    ("Check-in URL", "checkin_url"),
    ("Beer URL", "beer_url"),
    ("Brewery URL", "brewery_url"),
    ("Photo URL", "photo_url"),
]


def _latest_first(entries: list[dict]) -> list[dict]:
    return sorted(
        entries,
        key=lambda item: entry_created_dt(item) or datetime.min,
        reverse=True,
    )


def _first_and_latest_lines(group: dict) -> list[str]:
    lines = []
    if group["first_dt"] is not None:
        lines.append(f"Date First Had: {group['first_dt'].strftime('%Y-%m-%d %H:%M')}")
    if group["latest_dt"] is not None:
        lines.append(f"Date Latest Had: {group['latest_dt'].strftime('%Y-%m-%d %H:%M')}")
    return lines


def _top_lines(title: str, entries: list[dict], labeler, limit: int = 8) -> list[str]:
    counts = top_counts(entries, labeler, limit)
    return ["", title, *(f"{count}  {name}" for name, count in counts)]


def checkin_details_text(entry: dict, entries: list[dict], had: HadCounts) -> str:
    """Return the check-in detail text: its fields, comment and, if the beer was had more
    than once in `entries`, all dates it was had (newest first)."""
    lines: list[str] = []
    for label, key in CHECKIN_DETAIL_FIELDS:
        if key is None:
            if label == "Check-in":
                lines.append(f"{label}: {had.checkin_index(entry)}")
            elif label == "Total had with this check-in":
                lines.append(f"{label}: {had.had_index(entry)}")
            else:
                lines.append(f"{label}: {had.had_count(entry)}")
            continue
        value = entry.get(key)
        if value in (None, ""):
            continue
        lines.append(f"{label}: {format_float(value)}")

    comment = normalize_text(entry.get("comment"))
    if comment:
        lines.extend(["", "Comment:", comment])

    previous_dates = [
        normalize_text(candidate.get("created_at"))
        for candidate in entries
        if beer_key(candidate) == beer_key(entry)
    ]
    if len(previous_dates) > 1:
        lines.extend(["", "Had dates:", *sorted(previous_dates, reverse=True)])

    return "\n".join(lines)


def _checkin_parts(entry: dict, had: HadCounts, *, with_beer: bool) -> str:
    parts = [normalize_text(entry.get("created_at")) or "-"]
    if with_beer:
        parts.extend(
            [
                f"beer={normalize_text(entry.get('beer_name')) or '-'}",
                f"brewery={normalize_text(entry.get('brewery_name')) or '-'}",
            ]
        )
    parts.extend(
        [
            f"venue={venue_label(entry)}",
            f"rating={display_rating(entry)}",
            f"check-in={had.checkin_index(entry)}",
            f"had={had.had_index(entry)}",
        ]
    )
    serving = normalize_text(entry.get("serving_type"))
    if serving:
        parts.append(f"serving={serving}")
    toasts = normalize_text(entry.get("total_toasts"))
    if toasts:
        parts.append(f"toasts={toasts}")
    comment = normalize_text(entry.get("comment"))
    if comment:
        parts.append(f"comment={comment}")
    return " | ".join(parts)


def checkin_summary_line(entry: dict, had: HadCounts) -> str:
    """Return a one-line check-in summary (date, beer, brewery, venue, rating, numbering,
    and serving/toasts/comment when present), as listed under brewery and venue details."""
    return _checkin_parts(entry, had, with_beer=True)


def beer_details_text(group: dict, had: HadCounts) -> str:
    """Return the detail text for a `build_beer_groups` group."""
    entries = group["entries"]
    first = entries[0]
    lines = [
        f"Beer: {group['beer']}",
        f"Brewery: {group['brewery']}",
        f"Type: {group['beer_type']}",
        f"ABV: {abv_table_text(first)}",
        f"IBU: {format_float(first.get('beer_ibu'))}",
        f"Average rating: {mean_rating_text(group['ratings'])}",
        f"Rated check-ins: {len(group['ratings'])}",
        f"Total Had: {len(entries)}",
        *_first_and_latest_lines(group),
    ]
    for label, key in (
        ("Global rating", "global_rating_score"),
        ("Weighted global rating", "global_weighted_rating_score"),
        ("Brewery city", "brewery_city"),
        ("Brewery state", "brewery_state"),
        ("Brewery country", "brewery_country"),
        ("Beer URL", "beer_url"),
        ("Brewery URL", "brewery_url"),
    ):
        value = first.get(key)
        if value not in (None, ""):
            lines.append(f"{label}: {format_float(value)}")

    lines.extend(_top_lines("Top venues:", entries, venue_label, limit=5))

    lines.extend(["", "Check-ins:"])
    lines.extend(_checkin_parts(entry, had, with_beer=False) for entry in _latest_first(entries))
    return "\n".join(lines)


def brewery_details_text(group: dict, had: HadCounts) -> str:
    """Return the detail text for a `build_brewery_groups` group."""
    entries = group["entries"]
    lines = [
        f"Brewery: {group['brewery']}",
        f"City: {group['city']}",
        f"State: {group['state']}",
        f"Country: {group['country']}",
        f"Average rating: {mean_rating_text(group['ratings'])}",
        f"Rated check-ins: {len(group['ratings'])}",
        f"Unique beers: {group['unique_beers']}",
        f"Total Had: {len(entries)}",
        *_first_and_latest_lines(group),
    ]
    brewery_url = normalize_text(entries[0].get("brewery_url"))
    if brewery_url:
        lines.append(f"Brewery URL: {brewery_url}")

    lines.extend(
        _top_lines(
            "Top beers:", entries, lambda entry: normalize_text(entry.get("beer_name")) or "(unknown)"
        )
    )
    lines.extend(
        _top_lines(
            "Top styles:", entries, lambda entry: normalize_text(entry.get("beer_type")) or "(unknown)"
        )
    )
    lines.extend(_top_lines("Top venues:", entries, venue_label))

    lines.extend(["", "Check-ins:"])
    lines.extend(checkin_summary_line(entry, had) for entry in _latest_first(entries))
    return "\n".join(lines)


def venue_details_text(group: dict, had: HadCounts) -> str:
    """Return the detail text for a `build_venue_groups` group."""
    entries = group["entries"]
    lines = [
        f"Venue: {group['venue']}",
        f"City: {group['city']}",
        f"State: {group['state']}",
        f"Country: {group['country']}",
        f"Average rating: {mean_rating_text(group['ratings'])}",
        f"Rated check-ins: {len(group['ratings'])}",
        f"Unique beers: {group['unique_beers']}",
        f"Unique breweries: {group['unique_breweries']}",
        f"Total Had: {len(entries)}",
        *_first_and_latest_lines(group),
    ]
    if group["lat"] and group["lng"]:
        lines.append(f"Location: {group['lat']}, {group['lng']}")

    lines.extend(
        _top_lines(
            "Top beers:", entries, lambda entry: normalize_text(entry.get("beer_name")) or "(unknown)"
        )
    )
    lines.extend(
        _top_lines(
            "Top breweries:",
            entries,
            lambda entry: normalize_text(entry.get("brewery_name")) or "(unknown)",
        )
    )
    lines.extend(
        _top_lines(
            "Top styles:", entries, lambda entry: normalize_text(entry.get("beer_type")) or "(unknown)"
        )
    )

    lines.extend(["", "Check-ins:"])
    lines.extend(checkin_summary_line(entry, had) for entry in _latest_first(entries))
    return "\n".join(lines)
