"""The `runkeeper-export` command: info, search, show and map over Runkeeper exports."""

from __future__ import annotations

import argparse
import re
import socketserver
import sys
import webbrowser
from collections import Counter, defaultdict
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from export_inspector.runkeeper.formatting import (
    format_dt,
    format_duration,
    format_pace,
    format_speed,
    normalize_text,
    shorten,
)
from export_inspector.runkeeper.loader import load_export, load_route_points
from export_inspector.runkeeper.map import build_map_html, default_map_output_path
from export_inspector.runkeeper.models import Activity
from export_inspector.runkeeper.search import (
    activity_matches,
    pace_sort_value,
    resolve_activity,
    sort_activities,
)


ANSI_RESET = "\033[0m"
ANSI_HIGHLIGHT = "\033[1;30;43m"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect Runkeeper exports with stats, search, and activity details."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    info_parser = subparsers.add_parser(
        "info", help="Show summary stats for Runkeeper ZIP exports."
    )
    info_parser.add_argument(
        "input_file", help="Path to a Runkeeper export ZIP or a directory of ZIPs."
    )
    info_parser.add_argument(
        "--top", type=int, default=10, help="Top-N lists, default: 10."
    )
    info_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )

    search_parser = subparsers.add_parser(
        "search", help="Search activities in Runkeeper ZIP exports."
    )
    search_parser.add_argument(
        "input_file", help="Path to a Runkeeper export ZIP or a directory of ZIPs."
    )
    search_parser.add_argument(
        "terms", nargs="*", help="Search terms for activity name, type, or file name."
    )
    search_parser.add_argument(
        "--type", dest="type_filter", help="Filter by activity type."
    )
    search_parser.add_argument(
        "--after", help="Only include activities on or after YYYY-MM-DD."
    )
    search_parser.add_argument("--from", dest="from_date", help="Alias for --after.")
    search_parser.add_argument(
        "--before", help="Only include activities before YYYY-MM-DD."
    )
    search_parser.add_argument(
        "--min-distance", type=float, help="Only include activities >= this many km."
    )
    search_parser.add_argument(
        "--max-distance", type=float, help="Only include activities <= this many km."
    )
    search_parser.add_argument(
        "--min-duration",
        type=float,
        help="Only include activities >= this many minutes.",
    )
    search_parser.add_argument(
        "--max-duration",
        type=float,
        help="Only include activities <= this many minutes.",
    )
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
    search_parser.add_argument(
        "--any", action="store_true", help="Match any term instead of all terms."
    )
    search_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum results, default: 20."
    )
    search_parser.add_argument(
        "--no-ansi", action="store_true", help="Disable ANSI highlights."
    )
    search_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )

    show_parser = subparsers.add_parser("show", help="Show one activity in detail.")
    show_parser.add_argument(
        "input_file", help="Path to a Runkeeper export ZIP or a directory of ZIPs."
    )
    show_parser.add_argument(
        "identifier",
        help="Activity file name like 2026-04-22-072752.gpx, or the numeric activity index.",
    )
    show_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )

    map_parser = subparsers.add_parser(
        "map", help="Generate an HTML map for one activity."
    )
    map_parser.add_argument(
        "input_file", help="Path to a Runkeeper export ZIP or a directory of ZIPs."
    )
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


def print_counter(title: str, counter: Counter[str], limit: int) -> None:
    print(f"{title} ({min(limit, len(counter))}):")
    for key, value in counter.most_common(limit):
        label = key or "(unknown)"
        print(f"{value:8d}  {label}")
    if not counter:
        print("       0  (none)")
    print()


def print_activity_leaderboard(
    title: str, activities: list[Activity], timezone_name: str, limit: int
) -> None:
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
    print(
        f"Date range: {format_dt(activities[0].started_at, timezone_name)} to {format_dt(activities[-1].started_at, timezone_name)}"
    )
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
    year_counter = Counter(
        str(activity.started_at.astimezone(ZoneInfo(timezone_name)).year)
        for activity in activities
    )
    weekday_counter = Counter(
        activity.started_at.astimezone(ZoneInfo(timezone_name)).strftime("%A")
        for activity in activities
    )
    measurement_counter = Counter(
        normalize_text(row.get("Type")) or "(unknown)" for row in measurements
    )

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
    for activity_type, distance_km in sorted(
        distance_by_type.items(), key=lambda item: item[1], reverse=True
    )[: args.top]:
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

    fastest = [
        activity
        for activity in activities
        if activity.distance_km >= 1 and activity.duration_seconds > 0
    ]
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
        print(
            f"   Pace: {format_pace(activity.distance_km, activity.duration_seconds)}"
        )
        print(f"   Elevation gain: {activity.elevation_gain_m:.0f} m")
        print(f"   File: {highlight_text(activity.file_name, terms, ansi_enabled)}")
        print(f"   Match: {highlight_text(shorten(snippet), terms, ansi_enabled)}")
        print()


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return


def serve_directory(
    directory: Path, file_name: str, port: int, open_browser: bool
) -> None:
    handler = partial(QuietHandler, directory=str(directory))
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
    print(f"Photo entries in loaded export data: {len(photos)}")
    if photos:
        print(
            "Photo note: photos.csv uses activity UUIDs that are not exposed in the GPX file names."
        )


def run_map(args: argparse.Namespace) -> None:
    activities, _, _ = load_export(Path(args.input_file))
    activity = resolve_activity(activities, args.identifier)
    points = load_route_points(activity.archive_path, activity.file_name)

    output_path = (
        Path(args.output)
        if args.output
        else default_map_output_path(activity.file_name)
    )
    output_path.write_text(
        build_map_html(activity, points, args.timezone), encoding="utf-8"
    )
    print(output_path)

    should_serve = args.serve or args.open
    if should_serve:
        print("Serving over local HTTP so map tiles load correctly.")
        serve_directory(
            output_path.resolve().parent, output_path.name, args.port, args.open
        )
        return

    print("Open this over local HTTP if map tiles are blocked when using file://")
    print(f"Example: python3 -m http.server {args.port}")


def main() -> None:
    """Entry point of the `runkeeper-export` script: run the info, search, show or map command."""
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
