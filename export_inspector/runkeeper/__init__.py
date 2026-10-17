"""Runkeeper ZIP exports: models, loading, formatting, search, route maps and the CLI.

The names below are re-exported so `from export_inspector import runkeeper` and
`runkeeper.load_export(...)` etc. keep working after the move from `runkeeper.py`.
"""

from __future__ import annotations

from export_inspector.runkeeper.formatting import (
    format_dt,
    format_duration,
    format_pace,
    format_speed,
    normalize_text,
    parse_date_filter,
    shorten,
)
from export_inspector.runkeeper.loader import (
    discover_zip_paths,
    haversine_km,
    load_export,
    load_route_points,
    parse_activity,
    parse_csv_rows,
    parse_gpx_datetime,
    parse_type_from_name,
)
from export_inspector.runkeeper.map import (
    build_map_html,
    color_for_activity,
    default_map_output_path,
)
from export_inspector.runkeeper.models import (
    Activity,
    DATE_FORMAT,
    NS,
)
from export_inspector.runkeeper.search import (
    activity_matches,
    pace_sort_value,
    resolve_activity,
    sort_activities,
)

# The CLI names resolve lazily, so importing the package (or a domain module) does not load
# `cli`, and `python -m export_inspector.runkeeper.cli` runs without a runpy warning.
_CLI_NAMES = frozenset(
    {
        "ANSI_HIGHLIGHT",
        "ANSI_RESET",
        "QuietHandler",
        "highlight_text",
        "main",
        "parse_args",
        "print_activity_leaderboard",
        "print_counter",
        "run_info",
        "run_map",
        "run_search",
        "run_show",
        "serve_directory",
        "use_ansi",
    }
)


def __getattr__(name: str):
    if name in _CLI_NAMES:
        from export_inspector.runkeeper import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ANSI_HIGHLIGHT",
    "ANSI_RESET",
    "Activity",
    "DATE_FORMAT",
    "NS",
    "QuietHandler",
    "activity_matches",
    "build_map_html",
    "color_for_activity",
    "default_map_output_path",
    "discover_zip_paths",
    "format_dt",
    "format_duration",
    "format_pace",
    "format_speed",
    "haversine_km",
    "highlight_text",
    "load_export",
    "load_route_points",
    "main",
    "normalize_text",
    "pace_sort_value",
    "parse_activity",
    "parse_args",
    "parse_csv_rows",
    "parse_date_filter",
    "parse_gpx_datetime",
    "parse_type_from_name",
    "print_activity_leaderboard",
    "print_counter",
    "resolve_activity",
    "run_info",
    "run_map",
    "run_search",
    "run_show",
    "serve_directory",
    "shorten",
    "sort_activities",
    "use_ansi",
]
