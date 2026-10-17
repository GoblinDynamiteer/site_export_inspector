"""Sort, filter and look up Runkeeper activities."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from export_inspector.runkeeper.formatting import parse_date_filter
from export_inspector.runkeeper.models import Activity


def sort_activities(activities: Iterable[Activity], sort_key: str) -> list[Activity]:
    """Sort by a `--sort` key (`date-asc`, `distance-desc`, `pace-asc`, ...).

    Raises ValueError for an unknown key.
    """
    items = list(activities)
    if sort_key == "date-asc":
        return sorted(items, key=lambda item: item.started_at)
    if sort_key == "date-desc":
        return sorted(items, key=lambda item: item.started_at, reverse=True)
    if sort_key == "distance-desc":
        return sorted(
            items, key=lambda item: (item.distance_km, item.started_at), reverse=True
        )
    if sort_key == "distance-asc":
        return sorted(items, key=lambda item: (item.distance_km, item.started_at))
    if sort_key == "duration-desc":
        return sorted(
            items,
            key=lambda item: (item.duration_seconds, item.started_at),
            reverse=True,
        )
    if sort_key == "duration-asc":
        return sorted(items, key=lambda item: (item.duration_seconds, item.started_at))
    if sort_key == "pace-asc":
        return sorted(items, key=lambda item: pace_sort_value(item))
    if sort_key == "pace-desc":
        return sorted(items, key=lambda item: pace_sort_value(item), reverse=True)
    if sort_key == "elevation-desc":
        return sorted(
            items,
            key=lambda item: (item.elevation_gain_m, item.started_at),
            reverse=True,
        )
    raise ValueError(f"Unsupported sort key: {sort_key}")


def pace_sort_value(activity: Activity) -> float:
    if activity.distance_km <= 0 or activity.duration_seconds <= 0:
        return float("inf")
    return activity.duration_seconds / activity.distance_km


def activity_matches(activity: Activity, args: argparse.Namespace) -> bool:
    if (
        args.type_filter
        and args.type_filter.lower() not in activity.activity_type.lower()
    ):
        return False

    after_dt = parse_date_filter(args.from_date or args.after, args.timezone)
    before_dt = parse_date_filter(args.before, args.timezone)
    local_started = activity.started_at.astimezone(ZoneInfo(args.timezone))
    if after_dt and local_started < after_dt:
        return False
    if before_dt and local_started >= before_dt:
        return False

    if args.min_distance is not None and activity.distance_km < args.min_distance:
        return False
    if args.max_distance is not None and activity.distance_km > args.max_distance:
        return False
    if (
        args.min_duration is not None
        and activity.duration_seconds < args.min_duration * 60
    ):
        return False
    if (
        args.max_duration is not None
        and activity.duration_seconds > args.max_duration * 60
    ):
        return False

    terms = [term.lower() for term in args.terms]
    if not terms:
        return True

    haystacks = [
        activity.name.lower(),
        activity.activity_type.lower(),
        activity.file_name.lower(),
    ]
    if args.any:
        return any(term in haystack for term in terms for haystack in haystacks)
    return all(any(term in haystack for haystack in haystacks) for term in terms)


def resolve_activity(activities: list[Activity], identifier: str) -> Activity:
    """Find an activity by its index or its GPX file name; raises SystemExit if none."""
    if identifier.isdigit():
        index = int(identifier)
        for activity in activities:
            if activity.index == index:
                return activity
        raise SystemExit(f"No activity with index {index}.")

    normalized = identifier.strip()
    for activity in activities:
        if (
            activity.file_name == normalized
            or Path(activity.file_name).name == normalized
        ):
            return activity
    raise SystemExit(f"No activity found for identifier: {identifier}")
