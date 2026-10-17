"""Facebook Messenger exports: loading threads, formatting, search and the CLI.

The names below are re-exported (as they are from the old `messenger_chat` module)
so `messenger.load_exports(...)` etc. work from the package too.
"""

from __future__ import annotations

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
    "ANSI_CLEAR_LINE",
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
    "main",
    "message_dedupe_key",
    "message_sort_key",
    "normalize_message",
    "parse_args",
    "parse_from_date",
    "parse_until_date",
    "participant_signature_from_data",
    "participant_signature_from_message",
    "read_pager_action",
    "render_message",
    "repair_text",
    "rgb_ansi",
    "run_pager",
    "signature_label",
    "term_matches_text",
]
