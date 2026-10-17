#!/usr/bin/env python3
"""Compatibility wrapper for the old `messenger_chat` module; the code lives in
`export_inspector.messenger` (loader, formatting, search, cli).

Re-exports every old name (the CLI ones lazily) and still runs as a script.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from export_inspector.messenger.formatting import (
    ANSI_HIGHLIGHT,
    ANSI_RESET,
    ATTACHMENT_LABELS,
    DEFAULT_GAP_SECONDS,
    NAME_COLOR_PALETTE,
    build_info_output,
    build_name_colors,
    build_output,
    describe_attachment,
    describe_reactions,
    format_gap,
    format_swedish_datetime,
    highlight_text,
    render_message,
    repair_text,
    rgb_ansi,
    signature_label,
)
from export_inspector.messenger.loader import (
    discover_folder_sources,
    discover_threads,
    is_messenger_thread_json_path,
    load_exports,
    load_json_thread,
    load_zip_thread_members,
    message_dedupe_key,
    message_sort_key,
    normalize_message,
    participant_signature_from_data,
    participant_signature_from_message,
)
from export_inspector.messenger.search import (
    build_message_search_texts,
    filter_messages_from,
    filter_messages_search,
    filter_messages_until,
    parse_from_date,
    parse_until_date,
    term_matches_text,
)

# The CLI names resolve lazily, so importing the package (or a domain module) does not load
# `cli`, and `python -m export_inspector.messenger.cli` runs without a runpy warning.
_CLI_NAMES = frozenset(
    {
        "ANSI_CLEAR_LINE",
        "main",
        "parse_args",
        "read_pager_action",
        "run_pager",
    }
)


def __getattr__(name: str):
    if name in _CLI_NAMES:
        from export_inspector.messenger import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ANSI_HIGHLIGHT",
    "ANSI_RESET",
    "ATTACHMENT_LABELS",
    "DEFAULT_GAP_SECONDS",
    "NAME_COLOR_PALETTE",
    "build_info_output",
    "build_message_search_texts",
    "build_name_colors",
    "build_output",
    "describe_attachment",
    "describe_reactions",
    "discover_folder_sources",
    "discover_threads",
    "filter_messages_from",
    "filter_messages_search",
    "filter_messages_until",
    "format_gap",
    "format_swedish_datetime",
    "highlight_text",
    "is_messenger_thread_json_path",
    "load_exports",
    "load_json_thread",
    "load_zip_thread_members",
    "message_dedupe_key",
    "message_sort_key",
    "normalize_message",
    "parse_from_date",
    "parse_until_date",
    "participant_signature_from_data",
    "participant_signature_from_message",
    "render_message",
    "repair_text",
    "rgb_ansi",
    "signature_label",
    "term_matches_text",
]  # the lazy CLI names (`_CLI_NAMES`) resolve via `__getattr__`


if __name__ == "__main__":
    from export_inspector.messenger.cli import main as _main

    _main()
