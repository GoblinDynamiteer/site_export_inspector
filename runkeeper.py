#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import socketserver
import sys
import webbrowser
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import SimpleHTTPRequestHandler
from io import StringIO
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo


DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
ANSI_RESET = "\033[0m"
ANSI_HIGHLIGHT = "\033[1;30;43m"
NS = {"gpx": "http://www.topografix.com/GPX/1/1"}


@dataclass
class Activity:
    index: int
    file_name: str
    name: str
    activity_type: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    distance_km: float
    elevation_gain_m: float
    point_count: int
    start_lat: float | None
    start_lon: float | None
    end_lat: float | None
    end_lon: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect Runkeeper exports with stats, search, and activity details."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    info_parser = subparsers.add_parser("info", help="Show summary stats for a Runkeeper ZIP export.")
    info_parser.add_argument("input_file", help="Path to the Runkeeper export ZIP.")
    info_parser.add_argument("--top", type=int, default=10, help="Top-N lists, default: 10.")
    info_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )

    search_parser = subparsers.add_parser("search", help="Search activities in a Runkeeper ZIP export.")
    search_parser.add_argument("input_file", help="Path to the Runkeeper export ZIP.")
    search_parser.add_argument("terms", nargs="*", help="Search terms for activity name, type, or file name.")
    search_parser.add_argument("--type", dest="type_filter", help="Filter by activity type.")
    search_parser.add_argument("--after", help="Only include activities on or after YYYY-MM-DD.")
    search_parser.add_argument("--from", dest="from_date", help="Alias for --after.")
    search_parser.add_argument("--before", help="Only include activities before YYYY-MM-DD.")
    search_parser.add_argument("--min-distance", type=float, help="Only include activities >= this many km.")
    search_parser.add_argument("--max-distance", type=float, help="Only include activities <= this many km.")
    search_parser.add_argument("--min-duration", type=float, help="Only include activities >= this many minutes.")
    search_parser.add_argument("--max-duration", type=float, help="Only include activities <= this many minutes.")
    search_parser.add_argument(
        "--sort",
        choices=[
            "date-desc",
            "date-asc",
            "distance-desc",
            "distance-asc",
            "duration-desc",
            "duration-asc",
            "pace-asc",
            "pace-desc",
            "elevation-desc",
        ],
        default="date-desc",
        help="Sort order for results, default: date-desc.",
    )
    search_parser.add_argument("--any", action="store_true", help="Match any term instead of all terms.")
    search_parser.add_argument("--limit", type=int, default=20, help="Maximum results, default: 20.")
    search_parser.add_argument("--no-ansi", action="store_true", help="Disable ANSI highlights.")
    search_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )

    show_parser = subparsers.add_parser("show", help="Show one activity in detail.")
    show_parser.add_argument("input_file", help="Path to the Runkeeper export ZIP.")
    show_parser.add_argument(
        "identifier",
        help="Activity file name like 2026-04-22-072752.gpx, or the numeric activity index.",
    )
    show_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )

    map_parser = subparsers.add_parser("map", help="Generate an HTML map for one activity.")
    map_parser.add_argument("input_file", help="Path to the Runkeeper export ZIP.")
    map_parser.add_argument(
        "identifier",
        help="Activity file name like 2026-04-22-072752.gpx, or the numeric activity index.",
    )
    map_parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path. Default: <activity-file>.html in the current directory.",
    )
    map_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )
    map_parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve the generated HTML over local HTTP so map tiles load correctly.",
    )
    map_parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated map in the system default browser. Implies --serve.",
    )
    map_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for --serve, default: 8000.",
    )

    return parser.parse_args()


def parse_date_filter(value: str | None, timezone_name: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=ZoneInfo(timezone_name))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected format: YYYY-MM-DD."
        ) from exc


def format_dt(value: datetime, timezone_name: str) -> str:
    return value.astimezone(ZoneInfo(timezone_name)).strftime(DATE_FORMAT)


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_pace(distance_km: float, duration_seconds: float) -> str:
    if distance_km <= 0 or duration_seconds <= 0:
        return "-"
    pace_seconds = duration_seconds / distance_km
    minutes, seconds = divmod(int(round(pace_seconds)), 60)
    return f"{minutes}:{seconds:02d} /km"


def format_speed(distance_km: float, duration_seconds: float) -> str:
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


def use_ansi(args: argparse.Namespace) -> bool:
    return sys.stdout.isatty() and not getattr(args, "no_ansi", False)


def highlight_text(text: str, terms: list[str], ansi_enabled: bool) -> str:
    if not text or not terms:
        return text

    lowered = text.lower()
    matches: list[tuple[int, int]] = []
    for term in sorted({term.lower() for term in terms if term}, key=len, reverse=True):
        for match in re.finditer(re.escape(term), lowered):
            matches.append((match.start(), match.end()))

    if not matches:
        return text

    matches.sort()
    merged: list[tuple[int, int]] = []
    for start, end in matches:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        parts.append(text[cursor:start])
        hit = text[start:end]
        if ansi_enabled:
            parts.append(f"{ANSI_HIGHLIGHT}{hit}{ANSI_RESET}")
        else:
            parts.append(f"[{hit}]")
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def parse_type_from_name(name: str) -> str:
    trimmed = normalize_text(name)
    match = re.match(r"^(.*?)\s+\d{1,2}/\d{1,2}/\d{2}\s+\d{1,2}:\d{2}\s+[ap]m$", trimmed, re.IGNORECASE)
    if match:
        candidate = normalize_text(match.group(1))
        if candidate:
            return candidate
    prefix = trimmed.split(" ", 1)[0]
    return prefix or "Unknown"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def parse_gpx_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def parse_activity(index: int, file_name: str, xml_bytes: bytes) -> Activity:
    root = ET.fromstring(xml_bytes)
    name = normalize_text(root.findtext(".//gpx:trk/gpx:name", default="", namespaces=NS)) or file_name

    points: list[tuple[float, float, float | None, datetime | None]] = []
    for point in root.findall(".//gpx:trkpt", NS):
        lat = float(point.attrib["lat"])
        lon = float(point.attrib["lon"])
        ele_text = point.findtext("gpx:ele", default="", namespaces=NS).strip()
        time_text = point.findtext("gpx:time", default="", namespaces=NS).strip()
        ele = float(ele_text) if ele_text else None
        dt = parse_gpx_datetime(time_text) if time_text else None
        points.append((lat, lon, ele, dt))

    started_at = next((dt for _, _, _, dt in points if dt is not None), None)
    finished_at = next((dt for _, _, _, dt in reversed(points) if dt is not None), None)
    if started_at is None or finished_at is None:
        track_time = normalize_text(root.findtext(".//gpx:trk/gpx:time", default="", namespaces=NS))
        if not track_time:
            raise ValueError(f"Could not find timestamps in {file_name}")
        started_at = finished_at = parse_gpx_datetime(track_time)

    distance_km = 0.0
    elevation_gain_m = 0.0
    for previous, current in zip(points, points[1:]):
        distance_km += haversine_km(previous[0], previous[1], current[0], current[1])
        previous_ele = previous[2]
        current_ele = current[2]
        if previous_ele is not None and current_ele is not None and current_ele > previous_ele:
            elevation_gain_m += current_ele - previous_ele

    start_lat = points[0][0] if points else None
    start_lon = points[0][1] if points else None
    end_lat = points[-1][0] if points else None
    end_lon = points[-1][1] if points else None

    return Activity(
        index=index,
        file_name=file_name,
        name=name,
        activity_type=parse_type_from_name(name),
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=max(0.0, (finished_at - started_at).total_seconds()),
        distance_km=distance_km,
        elevation_gain_m=elevation_gain_m,
        point_count=len(points),
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
    )


def parse_csv_rows(zip_file: zipfile.ZipFile, member_name: str) -> list[dict[str, str]]:
    try:
        raw = zip_file.read(member_name).decode("utf-8-sig")
    except KeyError:
        return []
    reader = csv.DictReader(StringIO(raw))
    return [dict(row) for row in reader]


def load_export(path: Path) -> tuple[list[Activity], list[dict[str, str]], list[dict[str, str]]]:
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    if path.suffix.lower() != ".zip":
        raise SystemExit("Expected a Runkeeper ZIP export.")

    activities: list[Activity] = []
    with zipfile.ZipFile(path) as zip_file:
        gpx_files = sorted(
            name for name in zip_file.namelist() if name.lower().endswith(".gpx")
        )
        for index, member_name in enumerate(gpx_files, start=1):
            activities.append(parse_activity(index, member_name, zip_file.read(member_name)))
        measurements = parse_csv_rows(zip_file, "measurements.csv")
        photos = parse_csv_rows(zip_file, "photos.csv")

    activities.sort(key=lambda item: item.started_at)
    for index, activity in enumerate(activities, start=1):
        activity.index = index
    return activities, measurements, photos


def sort_activities(activities: Iterable[Activity], sort_key: str) -> list[Activity]:
    items = list(activities)
    if sort_key == "date-asc":
        return sorted(items, key=lambda item: item.started_at)
    if sort_key == "date-desc":
        return sorted(items, key=lambda item: item.started_at, reverse=True)
    if sort_key == "distance-desc":
        return sorted(items, key=lambda item: (item.distance_km, item.started_at), reverse=True)
    if sort_key == "distance-asc":
        return sorted(items, key=lambda item: (item.distance_km, item.started_at))
    if sort_key == "duration-desc":
        return sorted(items, key=lambda item: (item.duration_seconds, item.started_at), reverse=True)
    if sort_key == "duration-asc":
        return sorted(items, key=lambda item: (item.duration_seconds, item.started_at))
    if sort_key == "pace-asc":
        return sorted(items, key=lambda item: pace_sort_value(item))
    if sort_key == "pace-desc":
        return sorted(items, key=lambda item: pace_sort_value(item), reverse=True)
    if sort_key == "elevation-desc":
        return sorted(items, key=lambda item: (item.elevation_gain_m, item.started_at), reverse=True)
    raise ValueError(f"Unsupported sort key: {sort_key}")


def pace_sort_value(activity: Activity) -> float:
    if activity.distance_km <= 0 or activity.duration_seconds <= 0:
        return float("inf")
    return activity.duration_seconds / activity.distance_km


def activity_matches(activity: Activity, args: argparse.Namespace) -> bool:
    if args.type_filter and args.type_filter.lower() not in activity.activity_type.lower():
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
    if args.min_duration is not None and activity.duration_seconds < args.min_duration * 60:
        return False
    if args.max_duration is not None and activity.duration_seconds > args.max_duration * 60:
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


def print_counter(title: str, counter: Counter[str], limit: int) -> None:
    print(f"{title} ({min(limit, len(counter))}):")
    for key, value in counter.most_common(limit):
        label = key or "(unknown)"
        print(f"{value:8d}  {label}")
    if not counter:
        print("       0  (none)")
    print()


def print_activity_leaderboard(title: str, activities: list[Activity], timezone_name: str, limit: int) -> None:
    print(f"{title} ({min(limit, len(activities))}):")
    for activity in activities[:limit]:
        print(
            f"{activity.distance_km:8.2f} km  {format_dt(activity.started_at, timezone_name)}  "
            f"{activity.activity_type}  {format_duration(activity.duration_seconds)}"
        )
    if not activities:
        print("       0  (none)")
    print()


def run_info(args: argparse.Namespace) -> None:
    activities, measurements, photos = load_export(Path(args.input_file))
    if not activities:
        raise SystemExit("No GPX activities found in the ZIP export.")

    total_distance = sum(activity.distance_km for activity in activities)
    total_duration = sum(activity.duration_seconds for activity in activities)
    total_elevation = sum(activity.elevation_gain_m for activity in activities)
    timezone_name = args.timezone

    print(f"Activities: {len(activities)}")
    print(f"Date range: {format_dt(activities[0].started_at, timezone_name)} to {format_dt(activities[-1].started_at, timezone_name)}")
    print(f"Total distance: {total_distance:.2f} km")
    print(f"Total duration: {format_duration(total_duration)}")
    print(f"Total elevation gain: {total_elevation:.0f} m")
    print(f"Average distance: {total_distance / len(activities):.2f} km")
    print(f"Average duration: {format_duration(total_duration / len(activities))}")
    print(f"Average pace: {format_pace(total_distance, total_duration)}")
    print(f"Photos in export: {len(photos)}")
    print(f"Measurements in export: {len(measurements)}")
    print()

    type_counter = Counter(activity.activity_type for activity in activities)
    year_counter = Counter(str(activity.started_at.astimezone(ZoneInfo(timezone_name)).year) for activity in activities)
    weekday_counter = Counter(activity.started_at.astimezone(ZoneInfo(timezone_name)).strftime("%A") for activity in activities)
    measurement_counter = Counter(normalize_text(row.get("Type")) or "(unknown)" for row in measurements)

    distance_by_type = defaultdict(float)
    duration_by_type = defaultdict(float)
    for activity in activities:
        distance_by_type[activity.activity_type] += activity.distance_km
        duration_by_type[activity.activity_type] += activity.duration_seconds

    print_counter("Activity types", type_counter, args.top)
    print_counter("Years", year_counter, args.top)
    print_counter("Weekdays", weekday_counter, args.top)
    print_counter("Measurement types", measurement_counter, args.top)

    print(f"Distance by type ({min(args.top, len(distance_by_type))}):")
    for activity_type, distance_km in sorted(distance_by_type.items(), key=lambda item: item[1], reverse=True)[: args.top]:
        print(
            f"{distance_km:8.2f} km  {activity_type}  "
            f"avg pace={format_pace(distance_km, duration_by_type[activity_type])}"
        )
    print()

    print_activity_leaderboard(
        "Longest activities",
        sort_activities(activities, "distance-desc"),
        timezone_name,
        args.top,
    )
    print_activity_leaderboard(
        "Longest duration activities",
        sort_activities(activities, "duration-desc"),
        timezone_name,
        args.top,
    )

    fastest = [activity for activity in activities if activity.distance_km >= 1 and activity.duration_seconds > 0]
    fastest = sorted(fastest, key=pace_sort_value)
    print(f"Fastest activities ({min(args.top, len(fastest))}):")
    for activity in fastest[: args.top]:
        print(
            f"{format_pace(activity.distance_km, activity.duration_seconds):>10}  "
            f"{format_dt(activity.started_at, timezone_name)}  {activity.activity_type}  "
            f"{activity.distance_km:.2f} km"
        )
    if not fastest:
        print("       0  (none)")
    print()


def run_search(args: argparse.Namespace) -> None:
    activities, _, _ = load_export(Path(args.input_file))
    matches = [activity for activity in activities if activity_matches(activity, args)]
    matches = sort_activities(matches, args.sort)

    if not matches:
        print("No matches found.")
        return

    ansi_enabled = use_ansi(args)
    terms = [term.lower() for term in args.terms]
    for activity in matches[: args.limit]:
        snippet = " | ".join(
            [
                activity.name,
                activity.activity_type,
                activity.file_name,
            ]
        )
        print(f"{activity.index}. {format_dt(activity.started_at, args.timezone)}")
        print(f"   Name: {highlight_text(activity.name, terms, ansi_enabled)}")
        print(f"   Type: {highlight_text(activity.activity_type, terms, ansi_enabled)}")
        print(f"   Distance: {activity.distance_km:.2f} km")
        print(f"   Duration: {format_duration(activity.duration_seconds)}")
        print(f"   Pace: {format_pace(activity.distance_km, activity.duration_seconds)}")
        print(f"   Elevation gain: {activity.elevation_gain_m:.0f} m")
        print(f"   File: {highlight_text(activity.file_name, terms, ansi_enabled)}")
        print(f"   Match: {highlight_text(shorten(snippet), terms, ansi_enabled)}")
        print()


def resolve_activity(activities: list[Activity], identifier: str) -> Activity:
    if identifier.isdigit():
        index = int(identifier)
        for activity in activities:
            if activity.index == index:
                return activity
        raise SystemExit(f"No activity with index {index}.")

    normalized = identifier.strip()
    for activity in activities:
        if activity.file_name == normalized or Path(activity.file_name).name == normalized:
            return activity
    raise SystemExit(f"No activity found for identifier: {identifier}")


def color_for_activity(activity_type: str) -> str:
    lowered = activity_type.lower()
    if "run" in lowered:
        return "#d1495b"
    if "cycl" in lowered:
        return "#00798c"
    if "walk" in lowered:
        return "#2a9d8f"
    return "#264653"


def load_route_points(zip_path: Path, member_name: str) -> list[dict[str, float | str | None]]:
    with zipfile.ZipFile(zip_path) as zip_file:
        root = ET.fromstring(zip_file.read(member_name))

    points: list[dict[str, float | str | None]] = []
    for point in root.findall(".//gpx:trkpt", NS):
        ele_text = point.findtext("gpx:ele", default="", namespaces=NS).strip()
        time_text = point.findtext("gpx:time", default="", namespaces=NS).strip()
        points.append(
            {
                "lat": float(point.attrib["lat"]),
                "lon": float(point.attrib["lon"]),
                "ele": float(ele_text) if ele_text else None,
                "time": time_text or None,
            }
        )
    return points


def default_map_output_path(activity_file_name: str) -> Path:
    return Path(Path(activity_file_name).name).with_suffix(".html")


def build_map_html(
    activity: Activity, points: list[dict[str, float | str | None]], timezone_name: str
) -> str:
    if not points:
        raise SystemExit("This activity has no track points to render.")

    route_coordinates = [[point["lat"], point["lon"]] for point in points]
    color = color_for_activity(activity.activity_type)

    started = html.escape(format_dt(activity.started_at, timezone_name))
    finished = html.escape(format_dt(activity.finished_at, timezone_name))
    title = html.escape(activity.name)
    activity_type = html.escape(activity.activity_type)
    file_name = html.escape(activity.file_name)

    summary_rows = [
        ("Type", activity_type),
        ("Started", started),
        ("Finished", finished),
        ("Distance", f"{activity.distance_km:.2f} km"),
        ("Duration", format_duration(activity.duration_seconds)),
        ("Pace", format_pace(activity.distance_km, activity.duration_seconds)),
        ("Speed", format_speed(activity.distance_km, activity.duration_seconds)),
        ("Elevation gain", f"{activity.elevation_gain_m:.0f} m"),
        ("Track points", str(activity.point_count)),
        ("File", file_name),
    ]
    stats_html = "\n".join(
        f"<div class=\"stat\"><span class=\"label\">{html.escape(label)}</span><span class=\"value\">{html.escape(value)}</span></div>"
        for label, value in summary_rows
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin=""
  >
  <style>
    :root {{
      --bg: #f7f3ea;
      --paper: rgba(255, 252, 246, 0.94);
      --ink: #14213d;
      --muted: #5f6b7a;
      --accent: {color};
      --line: #d9d0c1;
      --shadow: 0 24px 60px rgba(20, 33, 61, 0.15);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(42, 157, 143, 0.12), transparent 32%),
        radial-gradient(circle at top right, rgba(209, 73, 91, 0.10), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, var(--bg) 100%);
    }}

    .page {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(280px, 360px) 1fr;
      gap: 20px;
      padding: 20px;
    }}

    .panel {{
      background: var(--paper);
      border: 1px solid rgba(20, 33, 61, 0.08);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(8px);
    }}

    .sidebar {{
      padding: 24px 22px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}

    .eyebrow {{
      margin: 0;
      font: 600 0.78rem/1.2 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    h1 {{
      margin: 0;
      font-size: clamp(1.9rem, 2.5vw, 2.8rem);
      line-height: 0.98;
    }}

    .lede {{
      margin: 0;
      color: var(--muted);
      font: 500 1rem/1.5 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}

    .stats {{
      display: grid;
      gap: 10px;
    }}

    .stat {{
      display: grid;
      gap: 2px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--line);
    }}

    .label {{
      font: 600 0.72rem/1.2 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .value {{
      font: 500 1.02rem/1.35 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
      word-break: break-word;
    }}

    .note {{
      margin: 0;
      color: var(--muted);
      font: 500 0.92rem/1.45 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}

    .warning {{
      margin: 0;
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(209, 73, 91, 0.10);
      color: #7f1d1d;
      font: 600 0.92rem/1.45 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}

    .map-panel {{
      position: relative;
      overflow: hidden;
      min-height: 72vh;
    }}

    #map {{
      width: 100%;
      height: 100%;
      min-height: 72vh;
    }}

    .legend {{
      position: absolute;
      right: 16px;
      bottom: 16px;
      z-index: 700;
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(255, 252, 246, 0.92);
      box-shadow: 0 12px 30px rgba(20, 33, 61, 0.12);
      font: 600 0.88rem/1.3 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}

    .swatch {{
      display: inline-block;
      width: 12px;
      height: 12px;
      border-radius: 999px;
      margin-right: 8px;
      background: var(--accent);
      vertical-align: middle;
    }}

    @media (max-width: 900px) {{
      .page {{
        grid-template-columns: 1fr;
      }}

      .map-panel,
      #map {{
        min-height: 60vh;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <aside class="panel sidebar">
      <p class="eyebrow">Runkeeper Route</p>
      <h1>{title}</h1>
      <p class="lede">{activity_type} tracked in Runkeeper, rendered over OpenStreetMap tiles.</p>
      <p id="protocol-warning" class="warning" hidden>
        This file is opened directly from disk. OpenStreetMap tiles may be blocked without a Referer. Serve this HTML over local HTTP instead.
      </p>
      <div class="stats">
        {stats_html}
      </div>
      <p class="note">This HTML uses Leaflet and OpenStreetMap tiles, so the browser needs internet access when you open it.</p>
    </aside>
    <section class="panel map-panel">
      <div id="map"></div>
      <div class="legend"><span class="swatch"></span>{activity_type}</div>
    </section>
  </div>

  <script
    src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
    crossorigin=""
  ></script>
  <script>
    if (window.location.protocol === "file:") {{
      document.getElementById("protocol-warning").hidden = false;
    }}

    const route = {json.dumps(route_coordinates, separators=(",", ":"))};
    const map = L.map("map", {{
      zoomControl: true,
      attributionControl: true
    }});

    L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors"
    }}).addTo(map);

    const routeLine = L.polyline(route, {{
      color: {json.dumps(color)},
      weight: 5,
      opacity: 0.9
    }}).addTo(map);

    const start = route[0];
    const end = route[route.length - 1];

    L.circleMarker(start, {{
      radius: 7,
      color: "#ffffff",
      weight: 2,
      fillColor: "#2a9d8f",
      fillOpacity: 1
    }}).addTo(map).bindPopup("Start");

    L.circleMarker(end, {{
      radius: 7,
      color: "#ffffff",
      weight: 2,
      fillColor: "#d1495b",
      fillOpacity: 1
    }}).addTo(map).bindPopup("End");

    map.fitBounds(routeLine.getBounds(), {{ padding: [24, 24] }});
  </script>
</body>
</html>
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return


def serve_directory(directory: Path, file_name: str, port: int, open_browser: bool) -> None:
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(directory), **kwargs)
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://127.0.0.1:{port}/{file_name}"
        print(url)
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def run_show(args: argparse.Namespace) -> None:
    activities, _, photos = load_export(Path(args.input_file))
    activity = resolve_activity(activities, args.identifier)

    print(f"Index: {activity.index}")
    print(f"File: {activity.file_name}")
    print(f"Name: {activity.name}")
    print(f"Type: {activity.activity_type}")
    print(f"Started: {format_dt(activity.started_at, args.timezone)}")
    print(f"Finished: {format_dt(activity.finished_at, args.timezone)}")
    print(f"Duration: {format_duration(activity.duration_seconds)}")
    print(f"Distance: {activity.distance_km:.2f} km")
    print(f"Pace: {format_pace(activity.distance_km, activity.duration_seconds)}")
    print(f"Speed: {format_speed(activity.distance_km, activity.duration_seconds)}")
    print(f"Elevation gain: {activity.elevation_gain_m:.0f} m")
    print(f"Track points: {activity.point_count}")
    if activity.start_lat is not None and activity.start_lon is not None:
        print(f"Start: {activity.start_lat:.6f}, {activity.start_lon:.6f}")
    if activity.end_lat is not None and activity.end_lon is not None:
        print(f"End: {activity.end_lat:.6f}, {activity.end_lon:.6f}")
    print(f"Photo entries elsewhere in archive: {len(photos)}")
    if photos:
        print("Photo note: photos.csv uses activity UUIDs that are not exposed in the GPX file names.")


def run_map(args: argparse.Namespace) -> None:
    zip_path = Path(args.input_file)
    activities, _, _ = load_export(zip_path)
    activity = resolve_activity(activities, args.identifier)
    points = load_route_points(zip_path, activity.file_name)

    output_path = Path(args.output) if args.output else default_map_output_path(activity.file_name)
    output_path.write_text(build_map_html(activity, points, args.timezone), encoding="utf-8")
    print(output_path)

    should_serve = args.serve or args.open
    if should_serve:
        print("Serving over local HTTP so map tiles load correctly.")
        serve_directory(output_path.resolve().parent, output_path.name, args.port, args.open)
        return

    print("Open this over local HTTP if map tiles are blocked when using file://")
    print(f"Example: python3 -m http.server {args.port}")


def main() -> None:
    args = parse_args()
    if args.command == "info":
        run_info(args)
        return
    if args.command == "search":
        run_search(args)
        return
    if args.command == "show":
        run_show(args)
        return
    if args.command == "map":
        run_map(args)
        return
    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
