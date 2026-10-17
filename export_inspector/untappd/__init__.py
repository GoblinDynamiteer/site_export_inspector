"""Untappd check-in exports: loading and field helpers (`checkins`) and the CLI (`cli`).

The names below are re-exported so `from export_inspector import untappd` and
`untappd.normalize_text(...)` etc. keep working after the move from `untappd.py`.
"""

from __future__ import annotations

from export_inspector.untappd.checkins import (
    DATE_FORMAT,
    display_rating,
    entry_search_fields,
    format_float,
    load_export,
    normalize_text,
    parse_created_at,
    parse_date_filter,
    parse_rating,
    shorten,
)
# The CLI names resolve lazily, so importing the package (or `checkins`) does not load
# `cli`, and `python -m export_inspector.untappd.cli` runs without a runpy warning.
_CLI_NAMES = frozenset(
    {
        "ANSI_HIGHLIGHT",
        "ANSI_RESET",
        "SearchResult",
        "build_result",
        "entry_matches",
        "handle_info",
        "handle_search",
        "handle_show",
        "highlight_text",
        "main",
        "parse_args",
        "print_focus_info",
        "print_multi_focus_info",
        "render_focus_value",
        "sort_results",
        "use_ansi",
    }
)


def __getattr__(name: str):
    if name in _CLI_NAMES:
        from export_inspector.untappd import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ANSI_HIGHLIGHT",
    "ANSI_RESET",
    "DATE_FORMAT",
    "SearchResult",
    "build_result",
    "display_rating",
    "entry_matches",
    "entry_search_fields",
    "format_float",
    "handle_info",
    "handle_search",
    "handle_show",
    "highlight_text",
    "load_export",
    "main",
    "normalize_text",
    "parse_args",
    "parse_created_at",
    "parse_date_filter",
    "parse_rating",
    "print_focus_info",
    "print_multi_focus_info",
    "render_focus_value",
    "shorten",
    "sort_results",
    "use_ansi",
]
