"""The `google-mail` command: info, search, index and show for Gmail / Takeout mbox files."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from export_inspector.gmail.formatting import format_full_message, print_info, print_results
from export_inspector.gmail.mbox import (
    load_message_from_mbox,
    load_message_from_offset,
    scan_mbox_info,
    search_mbox,
)
from export_inspector.gmail.search import (
    detect_sqlite,
    load_sqlite_metadata,
    scan_sqlite_info,
    search_sqlite,
)
from export_inspector.gmail.sqlite_index import (
    DEFAULT_MAX_BODY_CHARS,
    index_mbox,
    open_database,
    write_index_metadata,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect, search, and index Gmail/Google Takeout mailbox exports."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    info_parser = subparsers.add_parser(
        "info", help="Show mailbox stats for a raw .mbox file or SQLite index."
    )
    info_parser.add_argument("input_file", help="Path to the .mbox or .sqlite file.")
    info_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )
    info_parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top senders/subjects to show, default: 10.",
    )
    info_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable periodic progress updates to stderr while scanning raw .mbox input.",
    )

    search_parser = subparsers.add_parser(
        "search", help="Search a raw .mbox file or SQLite mailbox index."
    )
    search_parser.add_argument("input_file", help="Path to the .mbox or .sqlite file.")
    search_parser.add_argument(
        "terms",
        nargs="*",
        help="Case-insensitive search terms. By default all terms must match.",
    )
    search_parser.add_argument(
        "--from",
        dest="from_filter",
        help="Only include messages whose sender contains this text.",
    )
    search_parser.add_argument(
        "--to",
        dest="to_filter",
        help="Only include messages whose recipients contain this text.",
    )
    search_parser.add_argument(
        "--subject",
        dest="subject_filter",
        help="Only include messages whose subject contains this text.",
    )
    search_parser.add_argument(
        "--label",
        dest="label_filter",
        help="Only include messages whose labels contain this text.",
    )
    search_parser.add_argument(
        "--after",
        help="Only include messages on or after this date (YYYY-MM-DD).",
    )
    search_parser.add_argument(
        "--before",
        help="Only include messages before this date (YYYY-MM-DD).",
    )
    search_parser.add_argument(
        "--any",
        action="store_true",
        help="Match if any search term is found instead of requiring all terms.",
    )
    search_parser.add_argument(
        "--headers-only",
        action="store_true",
        help="Search only headers, not message bodies. Supported only for raw .mbox input.",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of results to print, default: 20.",
    )
    search_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )
    search_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable periodic progress updates to stderr while scanning raw .mbox input.",
    )
    search_parser.add_argument(
        "--no-ansi",
        action="store_true",
        help="Disable ANSI highlight output in search results.",
    )

    show_parser = subparsers.add_parser(
        "show", help="Display one full message by message index."
    )
    show_parser.add_argument(
        "input_file",
        help="Path to the .mbox file or .sqlite mailbox index.",
    )
    show_parser.add_argument(
        "message_index",
        type=int,
        help="Message index from search results.",
    )
    show_parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for displayed dates, default: Europe/Stockholm.",
    )
    show_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable periodic progress updates to stderr while scanning raw .mbox input.",
    )

    index_parser = subparsers.add_parser(
        "index", help="Build a SQLite full-text index for a raw .mbox file."
    )
    index_parser.add_argument("mbox_file", help="Path to the source .mbox file.")
    index_parser.add_argument(
        "index_file",
        nargs="?",
        default="gmail_index.sqlite",
        help="Path to the SQLite index to create, default: gmail_index.sqlite.",
    )
    index_parser.add_argument(
        "--max-body-chars",
        type=int,
        default=DEFAULT_MAX_BODY_CHARS,
        help="Maximum body characters to keep per message in the search index.",
    )
    index_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable periodic progress updates to stderr while indexing.",
    )
    index_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output index file if it already exists.",
    )

    return parser.parse_args()


def handle_info(args: argparse.Namespace) -> None:
    path = Path(args.input_file)
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    if detect_sqlite(path):
        (
            stats,
            sender_counts,
            recipient_counts,
            subject_counts,
            has_mime_stats,
        ) = scan_sqlite_info(path)
    else:
        stats, sender_counts, recipient_counts, subject_counts = scan_mbox_info(
            path, show_progress=not args.no_progress
        )
        has_mime_stats = True

    print_info(
        path,
        stats,
        sender_counts,
        recipient_counts,
        subject_counts,
        args.top,
        args.timezone,
        has_mime_stats,
    )


def handle_search(args: argparse.Namespace) -> None:
    if not args.terms and not any(
        [
            args.from_filter,
            args.to_filter,
            args.subject_filter,
            args.label_filter,
            args.after,
            args.before,
        ]
    ):
        raise SystemExit("Provide at least one search term or filter.")

    path = Path(args.input_file)
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    if detect_sqlite(path):
        if args.headers_only:
            raise SystemExit("--headers-only is only supported for raw .mbox input.")
        if not args.no_progress:
            print("Using SQLite index.", file=sys.stderr)
        results = search_sqlite(args)
    else:
        results = search_mbox(args)
    print_results(results)


def handle_index(args: argparse.Namespace) -> None:
    mbox_path = Path(args.mbox_file)
    index_path = Path(args.index_file)
    if not mbox_path.exists():
        raise SystemExit(f"File not found: {mbox_path}")

    conn = open_database(index_path, force=args.force)
    try:
        message_count, stats = index_mbox(
            mbox_path,
            conn,
            max_body_chars=args.max_body_chars,
            show_progress=not args.no_progress,
        )
        write_index_metadata(conn, mbox_path, message_count, args.max_body_chars, stats)
        conn.commit()
    finally:
        conn.close()

    print(f"Index: {index_path}")
    print(f"Source: {mbox_path}")
    print(f"Messages indexed: {message_count}")
    print(f"Max body chars per message: {args.max_body_chars}")


def handle_show(args: argparse.Namespace) -> None:
    input_path = Path(args.input_file)
    if not input_path.exists():
        raise SystemExit(f"File not found: {input_path}")

    source_path = input_path
    source_offset: int | None = None
    if detect_sqlite(input_path):
        metadata = load_sqlite_metadata(input_path)
        source_value = metadata.get("source_path")
        if not source_value:
            raise SystemExit("This SQLite index does not include source_path metadata.")
        source_path = Path(source_value)
        if not source_path.exists():
            raise SystemExit(f"Source mbox from index metadata not found: {source_path}")
        conn = sqlite3.connect(input_path)
        try:
            try:
                row = conn.execute(
                    "SELECT source_offset FROM messages WHERE message_index = ?",
                    (args.message_index,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = ()
        finally:
            conn.close()
        if row is None:
            raise SystemExit(f"Message index not found in index: {args.message_index}")
        if row:
            source_offset = row[0]

    if source_offset is not None:
        headers, body_text = load_message_from_offset(source_path, int(source_offset))
    else:
        headers, body_text = load_message_from_mbox(
            source_path, args.message_index, show_progress=not args.no_progress
        )
    print(format_full_message(headers, body_text, args.timezone))


def main() -> None:
    """Entry point of the `google-mail` script: run the info, search, index or show command."""
    args = parse_args()
    if args.command == "info":
        handle_info(args)
    elif args.command == "search":
        handle_search(args)
    elif args.command == "index":
        handle_index(args)
    elif args.command == "show":
        handle_show(args)
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
