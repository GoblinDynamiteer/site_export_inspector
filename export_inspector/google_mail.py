#!/usr/bin/env python3
"""Compatibility wrapper for the old `google_mail` module; the code lives in
`export_inspector.gmail` (models, mbox, sqlite_index, search, formatting, cli).

Re-exports every old name (the CLI ones lazily) and still runs as a script.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from export_inspector.gmail.formatting import (
    ANSI_HIGHLIGHT,
    ANSI_RESET,
    format_full_message,
    print_info,
    print_results,
)
from export_inspector.gmail.mbox import (
    BASE64_CHARS,
    PROGRESS_EVERY,
    SNIPPET_LIMIT,
    build_header_search_fields,
    choose_text_candidate,
    collect_message_body_text,
    consume_body_line,
    decode_payload,
    decode_header_value,
    extract_addresses,
    extract_message_body,
    extract_people,
    finalize_info_message,
    finalize_search_message,
    format_date,
    highlight_text,
    html_to_text,
    line_text_candidates,
    load_message_from_mbox,
    load_message_from_offset,
    looks_like_encoded_blob,
    message_passes_filters,
    parse_date,
    parse_date_filter,
    parse_headers,
    parse_message_bytes,
    scan_mbox_info,
    search_mbox,
    shorten,
    term_matches_text,
    terms_match_in_texts,
    update_date_range,
    use_ansi,
)
from export_inspector.gmail.models import IndexStats, MailboxStats, SearchResult
from export_inspector.gmail.search import (
    build_fts_query,
    detect_sqlite,
    load_sqlite_metadata,
    scan_sqlite_info,
    search_sqlite,
)
from export_inspector.gmail.sqlite_index import (
    COMMIT_EVERY,
    DEFAULT_MAX_BODY_CHARS,
    finalize_index_message,
    index_mbox,
    load_metadata,
    open_database,
    write_index_metadata,
)

# The CLI names resolve lazily, so importing this module does not load
# `export_inspector.gmail.cli`.
_CLI_NAMES = frozenset(
    {
        "handle_index",
        "handle_info",
        "handle_search",
        "handle_show",
        "main",
        "parse_args",
    }
)


def __getattr__(name: str):
    if name in _CLI_NAMES:
        from export_inspector.gmail import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ANSI_HIGHLIGHT",
    "ANSI_RESET",
    "BASE64_CHARS",
    "COMMIT_EVERY",
    "DEFAULT_MAX_BODY_CHARS",
    "IndexStats",
    "MailboxStats",
    "PROGRESS_EVERY",
    "SNIPPET_LIMIT",
    "SearchResult",
    "build_fts_query",
    "build_header_search_fields",
    "choose_text_candidate",
    "collect_message_body_text",
    "consume_body_line",
    "decode_header_value",
    "decode_payload",
    "detect_sqlite",
    "extract_addresses",
    "extract_message_body",
    "extract_people",
    "finalize_index_message",
    "finalize_info_message",
    "finalize_search_message",
    "format_date",
    "format_full_message",
    "highlight_text",
    "html_to_text",
    "index_mbox",
    "line_text_candidates",
    "load_message_from_mbox",
    "load_message_from_offset",
    "load_metadata",
    "load_sqlite_metadata",
    "looks_like_encoded_blob",
    "message_passes_filters",
    "open_database",
    "parse_date",
    "parse_date_filter",
    "parse_headers",
    "parse_message_bytes",
    "print_info",
    "print_results",
    "scan_mbox_info",
    "scan_sqlite_info",
    "search_mbox",
    "search_sqlite",
    "shorten",
    "term_matches_text",
    "terms_match_in_texts",
    "update_date_range",
    "use_ansi",
    "write_index_metadata",
]  # the lazy CLI names (`_CLI_NAMES`) resolve via `__getattr__`


if __name__ == "__main__":
    from export_inspector.gmail.cli import main as _main

    _main()
