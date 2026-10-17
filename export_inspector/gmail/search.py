"""Gmail search services: SQLite index detection, info and FTS search.

Raw .mbox search lives in `export_inspector.gmail.mbox` (`search_mbox`); the CLI picks one
of the two with `detect_sqlite`.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from export_inspector.gmail.mbox import (
    format_date,
    highlight_text,
    parse_date_filter,
    use_ansi,
)
from export_inspector.gmail.models import MailboxStats, SearchResult
from export_inspector.gmail.sqlite_index import load_metadata


def detect_sqlite(path: Path) -> bool:
    """True for a .sqlite/.db/.sqlite3 path or a file with the SQLite header, else False
    (treated as raw .mbox)."""
    if path.suffix.lower() in {".sqlite", ".db", ".sqlite3"}:
        return True
    with path.open("rb") as handle:
        return handle.read(16) == b"SQLite format 3\x00"


def load_sqlite_metadata(path: Path) -> dict[str, str]:
    """Return the metadata table of a SQLite index (source path, counts, ...)."""
    conn = sqlite3.connect(path)
    try:
        return load_metadata(conn)
    finally:
        conn.close()


def scan_sqlite_info(
    path: Path,
) -> tuple[MailboxStats, Counter[str], Counter[str], Counter[str], bool]:
    """Return (stats, senders, recipients, subjects, has_mime_stats) for a SQLite index.

    `has_mime_stats` is False for indexes built before the multipart/attachment counts
    were stored; those counts are then 0.
    """
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


def build_fts_query(terms: list[str], match_any: bool) -> str:
    """Build an FTS5 MATCH expression: plain alphanumeric terms become prefix matches,
    others quoted phrases, joined with AND (or OR for `match_any`); "" without terms."""
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
    """Search a SQLite index with the `search` command's arguments (terms via FTS, sender/
    recipient/subject/label substrings, date range), newest first, up to `args.limit`."""
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
