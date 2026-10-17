"""Load Gmail messages as lightweight table records from an .mbox file or SQLite index.

Qt-free: the GUI's mail table is built from these records, and the full message is
loaded later from `source_path` (at `source_offset` when known).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from export_inspector.gmail.mbox import (
    decode_header_value,
    extract_addresses,
    format_date,
    parse_date,
    parse_headers,
)
from export_inspector.gmail.search import detect_sqlite


@dataclass
class GmailRecord:
    """One row of the mail table: display fields plus where to load the full message.

    `source_offset` is the byte offset of the message's `From ` line in `source_path`,
    or None when the message must be found by `message_index` instead.
    """

    message_index: int
    source_path: str
    source_offset: int | None
    date_text: str
    date_sort: int
    sender: str
    recipients: str
    subject: str
    labels: str
    thread_id: str
    snippet: str


def load_records(path: Path, timezone: str) -> list[GmailRecord]:
    """Load records from a SQLite index or a raw .mbox (see `detect_sqlite`), newest first."""
    if detect_sqlite(path):
        return load_sqlite_records(path, timezone)
    return load_mbox_records(path, timezone)


def load_sqlite_records(path: Path, timezone: str) -> list[GmailRecord]:
    """Load every indexed message, newest first, with dates formatted in `timezone`.

    Messages without a stored source path point at `path` itself.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                message_index,
                date_utc,
                date_unix,
                sender,
                recipients,
                subject,
                labels,
                thread_id,
                snippet,
                source_path,
                source_offset
            FROM messages
            ORDER BY date_unix DESC, message_index DESC
            """
        ).fetchall()
    finally:
        conn.close()

    records: list[GmailRecord] = []
    for row in rows:
        date_text = "n/a"
        if row["date_utc"]:
            date_text = format_date(datetime.fromisoformat(row["date_utc"]), timezone)
        records.append(
            GmailRecord(
                message_index=int(row["message_index"]),
                source_path=row["source_path"] or str(path),
                source_offset=row["source_offset"],
                date_text=date_text,
                date_sort=int(row["date_unix"] or 0),
                sender=row["sender"] or "unknown",
                recipients=row["recipients"] or "",
                subject=row["subject"] or "(no subject)",
                labels=row["labels"] or "",
                thread_id=row["thread_id"] or "",
                snippet=row["snippet"] or "",
            )
        )
    return records


def load_mbox_records(path: Path, timezone: str) -> list[GmailRecord]:
    """Scan a raw .mbox for message headers only (no bodies), newest first.

    Messages are numbered from 1 in file order and keep the offset of their `From ` line.
    """
    records: list[GmailRecord] = []
    current_header_lines: list[bytes] = []
    current_headers: dict[str, str] = {}
    in_headers = False
    have_message = False
    message_index = 0
    message_start_offset = 0

    def finalize_current() -> None:
        nonlocal message_index, current_headers
        if not have_message:
            return
        if not current_headers and current_header_lines:
            current_headers = parse_headers(current_header_lines)
        message_index += 1
        records.append(
            record_from_headers(
                message_index,
                path,
                message_start_offset,
                current_headers,
                timezone,
            )
        )

    with path.open("rb") as handle:
        while True:
            line_offset = handle.tell()
            raw_line = handle.readline()
            if not raw_line:
                break
            if raw_line.startswith(b"From "):
                finalize_current()
                current_header_lines = []
                current_headers = {}
                in_headers = True
                have_message = True
                message_start_offset = line_offset
                continue

            if not have_message:
                continue
            if in_headers:
                if raw_line in (b"\n", b"\r\n"):
                    current_headers = parse_headers(current_header_lines)
                    in_headers = False
                    continue
                current_header_lines.append(raw_line)

    finalize_current()
    records.sort(
        key=lambda record: (record.date_sort, record.message_index),
        reverse=True,
    )
    return records


def record_from_headers(
    message_index: int,
    path: Path,
    source_offset: int,
    headers: dict[str, str],
    timezone: str,
) -> GmailRecord:
    """Build a record from parsed headers ("n/a" date, "unknown" sender and "(no subject)"
    when missing). Raw mbox records have no snippet."""
    parsed_date = parse_date(headers.get("date"))
    if parsed_date is not None:
        date_sort = int(parsed_date.timestamp())
        date_text = format_date(parsed_date, timezone)
    else:
        date_sort = 0
        date_text = "n/a"
    return GmailRecord(
        message_index=message_index,
        source_path=str(path),
        source_offset=source_offset,
        date_text=date_text,
        date_sort=date_sort,
        sender=decode_header_value(headers.get("from")) or "unknown",
        recipients=extract_addresses(
            headers.get("to", ""), headers.get("cc", ""), headers.get("bcc", "")
        ),
        subject=decode_header_value(headers.get("subject")) or "(no subject)",
        labels=decode_header_value(headers.get("x-gmail-labels")),
        thread_id=headers.get("x-gm-thrid", ""),
        snippet="",
    )


def record_fallback_text(record: GmailRecord, reason: str) -> str:
    """Return the record's header fields, `reason` and its snippet, for when the full
    message can't be loaded."""
    lines = [
        f"Date: {record.date_text}",
        f"From: {record.sender}",
    ]
    if record.recipients:
        lines.append(f"To: {record.recipients}")
    lines.append(f"Subject: {record.subject}")
    if record.labels:
        lines.append(f"Labels: {record.labels}")
    if record.thread_id:
        lines.append(f"Thread: {record.thread_id}")
    lines.extend(["", reason])
    if record.snippet:
        lines.extend(["", record.snippet])
    return "\n".join(lines)


def record_search_blob(record: GmailRecord) -> str:
    """Return the newline-joined text the mail filter matches against."""
    return "\n".join(
        [
            record.date_text,
            record.sender,
            record.recipients,
            record.subject,
            record.labels,
            record.thread_id,
            record.snippet,
            str(record.message_index),
        ]
    )
