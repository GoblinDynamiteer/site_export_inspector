#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
from export_inspector.gmail.sqlite_index import (
    COMMIT_EVERY,
    finalize_index_message,
    index_mbox,
    load_metadata,
    open_database,
    write_index_metadata,
)


DEFAULT_MAX_BODY_CHARS = 50000
ANSI_RESET = "\033[0m"
ANSI_HIGHLIGHT = "\033[1;30;43m"


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


def detect_sqlite(path: Path) -> bool:
    if path.suffix.lower() in {".sqlite", ".db", ".sqlite3"}:
        return True
    with path.open("rb") as handle:
        return handle.read(16) == b"SQLite format 3\x00"


def load_sqlite_metadata(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(path)
    try:
        return load_metadata(conn)
    finally:
        conn.close()


def scan_sqlite_info(
    path: Path,
) -> tuple[MailboxStats, Counter[str], Counter[str], Counter[str], bool]:
    conn = sqlite3.connect(path)
    metadata = load_metadata(conn)

    sender_counts = Counter(
        {
            sender: count
            for sender, count in conn.execute(
                "SELECT sender, COUNT(*) FROM messages GROUP BY sender"
            )
        }
    )
    recipient_counts = Counter(
        {
            recipient: count
            for recipient, count in conn.execute(
                """
                SELECT trim(value), COUNT(*)
                FROM messages, json_each('["' || replace(replace(recipients, '"', '""'), ', ', '","') || '"]')
                WHERE recipients IS NOT NULL AND recipients != ''
                GROUP BY trim(value)
                """
            )
            if recipient
        }
    )
    subject_counts = Counter(
        {
            subject: count
            for subject, count in conn.execute(
                "SELECT subject, COUNT(*) FROM messages GROUP BY subject"
            )
        }
    )
    row = conn.execute(
        "SELECT MIN(date_utc), MAX(date_utc), COUNT(*) FROM messages"
    ).fetchone()
    conn.close()

    def metadata_int(key: str) -> int:
        value = metadata.get(key)
        return int(value) if value is not None else 0

    first_dt = datetime.fromisoformat(row[0]) if row and row[0] else None
    last_dt = datetime.fromisoformat(row[1]) if row and row[1] else None
    total_messages = int(row[2]) if row and row[2] is not None else 0
    stats = MailboxStats(
        total_messages=total_messages,
        multipart_messages=metadata_int("multipart_messages"),
        attachment_messages=metadata_int("attachment_messages"),
        attachment_files=metadata_int("attachment_files"),
        first_dt=first_dt,
        last_dt=last_dt,
    )
    has_mime_stats = all(
        key in metadata
        for key in ("multipart_messages", "attachment_messages", "attachment_files")
    )
    return stats, sender_counts, recipient_counts, subject_counts, has_mime_stats


def print_info(
    path: Path,
    stats: MailboxStats,
    sender_counts: Counter[str],
    recipient_counts: Counter[str],
    subject_counts: Counter[str],
    top: int,
    timezone: str,
    has_mime_stats: bool,
) -> None:
    print(f"File: {path}")
    print(f"Messages: {stats.total_messages}")
    print(
        f"Date range: {format_date(stats.first_dt, timezone)} to "
        f"{format_date(stats.last_dt, timezone)}"
    )
    if has_mime_stats:
        print(f"Multipart messages: {stats.multipart_messages}")
        print(f"Messages with attachments: {stats.attachment_messages}")
        print(f"Attachment files: {stats.attachment_files}")
    else:
        print("Multipart messages: n/a (not stored in this index)")
        print("Messages with attachments: n/a (not stored in this index)")
        print("Attachment files: n/a (not stored in this index)")

    print()
    print(f"Top senders ({top}):")
    for sender, count in sender_counts.most_common(top):
        print(f"  {count:>6}  {sender}")

    print()
    print(f"Top recipients ({top}):")
    for recipient, count in recipient_counts.most_common(top):
        print(f"  {count:>6}  {recipient}")

    print()
    print(f"Top subjects ({top}):")
    for subject, count in subject_counts.most_common(top):
        print(f"  {count:>6}  {subject}")


def build_fts_query(terms: list[str], match_any: bool) -> str:
    escaped: list[str] = []
    for term in terms:
        term = term.strip()
        if not term:
            continue
        if " " not in term and all(char.isalnum() for char in term):
            escaped.append(f"{term.replace('"', '""')}*")
        else:
            escaped_term = term.replace('"', '""')
            escaped.append(f'"{escaped_term}"')
    if not escaped:
        return ""
    operator = " OR " if match_any else " AND "
    return operator.join(escaped)


def search_sqlite(args: argparse.Namespace) -> list[SearchResult]:
    conn = sqlite3.connect(args.input_file)
    conn.row_factory = sqlite3.Row

    where_clauses: list[str] = []
    params: list[object] = []

    fts_query = build_fts_query(args.terms, args.any)
    from_clause = "messages"
    if fts_query:
        from_clause = "messages JOIN message_fts ON message_fts.rowid = messages.id"
        where_clauses.append("message_fts MATCH ?")
        params.append(fts_query)

    if args.from_filter:
        where_clauses.append("lower(messages.sender) LIKE ?")
        params.append(f"%{args.from_filter.lower()}%")
    if args.to_filter:
        where_clauses.append("lower(messages.recipients) LIKE ?")
        params.append(f"%{args.to_filter.lower()}%")
    if args.subject_filter:
        where_clauses.append("lower(messages.subject) LIKE ?")
        params.append(f"%{args.subject_filter.lower()}%")
    if args.label_filter:
        where_clauses.append("lower(messages.labels) LIKE ?")
        params.append(f"%{args.label_filter.lower()}%")

    after_dt = parse_date_filter(args.after, args.timezone)
    before_dt = parse_date_filter(args.before, args.timezone)
    if after_dt is not None:
        where_clauses.append("messages.date_unix >= ?")
        params.append(int(after_dt.timestamp()))
    if before_dt is not None:
        where_clauses.append("messages.date_unix < ?")
        params.append(int(before_dt.timestamp()))

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    snippet_sql = "messages.snippet"
    if fts_query:
        snippet_sql = "snippet(message_fts, -1, '', '', ' ... ', 18)"

    query = f"""
        SELECT
            messages.message_index,
            messages.date_utc,
            messages.sender,
            messages.recipients,
            messages.subject,
            messages.labels,
            messages.thread_id,
            {snippet_sql} AS snippet
        FROM {from_clause}
        {where_sql}
        ORDER BY messages.date_unix DESC, messages.message_index DESC
        LIMIT ?
    """
    params.append(args.limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    ansi_enabled = use_ansi(args)
    query_terms = [term.lower() for term in args.terms]

    return [
        SearchResult(
            index=row["message_index"],
            date_text=format_date(
                datetime.fromisoformat(row["date_utc"]) if row["date_utc"] else None,
                args.timezone,
            ),
            sender=row["sender"],
            to_text=row["recipients"] or "",
            subject=row["subject"],
            labels=row["labels"] or "",
            thread_id=row["thread_id"] or "",
            snippet=highlight_text(row["snippet"] or "", query_terms, ansi_enabled),
        )
        for row in rows
    ]


def print_results(results: list[SearchResult]) -> None:
    if not results:
        print("No matches found.")
        return
    for result in results:
        print(f"{result.index}. {result.date_text}")
        print(f"   From: {result.sender}")
        if result.to_text:
            print(f"   To: {result.to_text}")
        print(f"   Subject: {result.subject}")
        if result.labels:
            print(f"   Labels: {result.labels}")
        if result.thread_id:
            print(f"   Thread: {result.thread_id}")
        print(f"   Snippet: {result.snippet}")
        print()


def format_full_message(headers: dict[str, str], body_text: str, timezone: str) -> str:
    sender = decode_header_value(headers.get("from")) or "unknown"
    recipients = decode_header_value(headers.get("to"))
    cc_text = decode_header_value(headers.get("cc"))
    subject = decode_header_value(headers.get("subject")) or "(no subject)"
    labels = decode_header_value(headers.get("x-gmail-labels"))
    thread_id = headers.get("x-gm-thrid", "")
    message_id = decode_header_value(headers.get("message-id"))
    parsed_date = parse_date(headers.get("date"))
    lines = [
        f"Date: {format_date(parsed_date, timezone)}",
        f"From: {sender}",
    ]
    if recipients:
        lines.append(f"To: {recipients}")
    if cc_text:
        lines.append(f"Cc: {cc_text}")
    lines.append(f"Subject: {subject}")
    if labels:
        lines.append(f"Labels: {labels}")
    if thread_id:
        lines.append(f"Thread: {thread_id}")
    if message_id:
        lines.append(f"Message-Id: {message_id}")
    lines.append("")
    lines.append(body_text or "(no decoded body text)")
    return "\n".join(lines)


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
