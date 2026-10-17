"""Plain-text activity details and filter text for the Runkeeper GUI (Qt-free)."""

from __future__ import annotations

from export_inspector.runkeeper.formatting import (
    format_dt,
    format_duration,
    format_pace,
    format_speed,
)
from export_inspector.runkeeper.models import Activity
from export_inspector.runkeeper.ranks import ActivityRanks

PHOTO_NOTE = (
    "Photo note: photos.csv uses activity UUIDs that are not exposed in the GPX file names."
)


def activity_search_blob(activity: Activity, ranks: ActivityRanks, timezone_name: str) -> str:
    """Return the newline-joined text the activity filter matches against."""
    fields = [
        activity.name,
        activity.file_name,
        activity.activity_type,
        format_dt(activity.started_at, timezone_name),
        format_dt(activity.finished_at, timezone_name),
        format_duration(activity.duration_seconds),
        f"{activity.distance_km:.2f} km",
        format_pace(activity.distance_km, activity.duration_seconds),
        format_speed(activity.distance_km, activity.duration_seconds),
        f"{activity.elevation_gain_m:.0f} m",
        str(activity.point_count),
        str(activity.archive_path),
        ranks.distance_label(activity),
        ranks.duration_label(activity),
    ]
    if activity.start_lat is not None and activity.start_lon is not None:
        fields.append(f"{activity.start_lat:.6f}, {activity.start_lon:.6f}")
    if activity.end_lat is not None and activity.end_lon is not None:
        fields.append(f"{activity.end_lat:.6f}, {activity.end_lon:.6f}")
    return "\n".join(fields)


def activity_details_text(
    activity: Activity, ranks: ActivityRanks, timezone_name: str, photo_count: int
) -> str:
    """Return the detail text: times, duration/distance with ranks, pace, speed, elevation,
    points, start/end, archive and the number of photo rows in the loaded export."""
    lines = [
        f"Name: {activity.name}",
        f"File: {activity.file_name}",
        f"Type: {activity.activity_type}",
        f"Started: {format_dt(activity.started_at, timezone_name)}",
        f"Finished: {format_dt(activity.finished_at, timezone_name)}",
        f"Duration: {format_duration(activity.duration_seconds)} ({ranks.duration_label(activity)})",
        f"Distance: {activity.distance_km:.2f} km ({ranks.distance_label(activity)})",
        f"Pace: {format_pace(activity.distance_km, activity.duration_seconds)}",
        f"Speed: {format_speed(activity.distance_km, activity.duration_seconds)}",
        f"Elevation gain: {activity.elevation_gain_m:.0f} m",
        f"Track points: {activity.point_count}",
    ]
    if activity.start_lat is not None and activity.start_lon is not None:
        lines.append(f"Start: {activity.start_lat:.6f}, {activity.start_lon:.6f}")
    if activity.end_lat is not None and activity.end_lon is not None:
        lines.append(f"End: {activity.end_lat:.6f}, {activity.end_lon:.6f}")
    lines.extend(
        [
            f"Archive: {activity.archive_path}",
            f"Photo entries in loaded export data: {photo_count}",
        ]
    )
    if photo_count:
        lines.append(PHOTO_NOTE)
    return "\n".join(lines)
