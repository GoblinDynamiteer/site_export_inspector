from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from export_inspector.gmail.mbox import (
    choose_text_candidate,
    consume_body_line,
    decode_header_value,
    extract_addresses,
    parse_date,
    parse_headers,
    shorten,
)
from export_inspector.gmail.models import IndexStats


PROGRESS_EVERY = 10000
COMMIT_EVERY = 1000


def open_database(path: Path, force: bool) -> sqlite3.Connection:
    """Create a fresh Gmail SQLite index database.

    The returned connection has the Gmail message, FTS, and metadata schema
    installed and uses write-optimized pragmas for bulk indexing. If `path`
    exists, `force` controls whether it is unlinked first; without `force`, this
    raises `SystemExit` instead of modifying the existing file.
    """

    if path.exists():
        if not force:
            raise SystemExit(
                f"Index file already exists: {path}. Use --force to overwrite it."
            )
        path.unlink()

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")
    conn.execute("PRAGMA cache_size=-200000")
    conn.executescript(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            message_index INTEGER NOT NULL UNIQUE,
            source_path TEXT NOT NULL,
            source_offset INTEGER,
            thread_id TEXT,
            gmail_message_id TEXT,
            message_id TEXT,
            date_utc TEXT,
            date_unix INTEGER,
            sender TEXT,
            recipients TEXT,
            subject TEXT,
            labels TEXT,
            snippet TEXT
        );

        CREATE VIRTUAL TABLE message_fts USING fts5(
            sender,
            recipients,
            subject,
            labels,
            body
        );

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    return conn


def load_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    """Read Gmail index metadata from an open SQLite connection.

    Older or invalid SQLite files may not have a `metadata` table; in that case
    this returns an empty dictionary instead of failing the caller's info/show
    flow.
    """

    try:
        rows = conn.execute("SELECT key, value FROM metadata").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {key: value for key, value in rows}


def finalize_index_message(
    conn: sqlite3.Connection,
    message_index: int,
    source_path: str,
    source_offset: int,
    headers: dict[str, str],
    body_parts: list[str],
    stats: IndexStats,
) -> None:
    """Insert one parsed Gmail message into the search index.

    The caller owns transaction boundaries. Empty header dictionaries are
    skipped. `stats` is updated in place with multipart and attachment counts
    derived from the message headers.
    """

    if not headers:
        return

    sender = decode_header_value(headers.get("from")) or "unknown"
    recipients = extract_addresses(
        headers.get("to", ""), headers.get("cc", ""), headers.get("bcc", "")
    )
    subject = decode_header_value(headers.get("subject")) or "(no subject)"
    labels = decode_header_value(headers.get("x-gmail-labels"))
    thread_id = headers.get("x-gm-thrid", "")
    gmail_message_id = headers.get("x-gm-msgid", "")
    message_id = decode_header_value(headers.get("message-id"))
    parsed_date = parse_date(headers.get("date"))
    if parsed_date is not None:
        parsed_date = parsed_date.astimezone(UTC)
    date_utc = parsed_date.isoformat() if parsed_date else None
    date_unix = int(parsed_date.timestamp()) if parsed_date else None

    content_type = headers.get("content-type", "").lower()
    if content_type.startswith("multipart/"):
        stats.multipart_messages += 1

    attachment_count = int(headers.get("__attachment_count__", "0") or "0")
    if attachment_count > 0:
        stats.attachment_messages += 1
        stats.attachment_files += attachment_count

    body_text = "\n".join(part for part in body_parts if part)
    snippet = shorten(body_text or subject)

    cursor = conn.execute(
        """
        INSERT INTO messages (
            message_index,
            source_path,
            source_offset,
            thread_id,
            gmail_message_id,
            message_id,
            date_utc,
            date_unix,
            sender,
            recipients,
            subject,
            labels,
            snippet
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_index,
            source_path,
            source_offset,
            thread_id,
            gmail_message_id,
            message_id,
            date_utc,
            date_unix,
            sender,
            recipients,
            subject,
            labels,
            snippet,
        ),
    )
    conn.execute(
        """
        INSERT INTO message_fts(rowid, sender, recipients, subject, labels, body)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (cursor.lastrowid, sender, recipients, subject, labels, body_text),
    )


def index_mbox(
    mbox_path: Path,
    conn: sqlite3.Connection,
    max_body_chars: int,
    show_progress: bool,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> tuple[int, IndexStats]:
    """Index a raw Gmail Takeout `.mbox` file into an open SQLite connection.

    The caller must provide a connection created by `open_database` and remains
    responsible for closing it. This function manages indexing transactions,
    emits optional stderr progress, and calls `progress_callback` as
    `(message_count, processed_bytes, total_bytes)` after commit batches and at
    completion.
    """

    current_header_lines: list[bytes] = []
    current_headers: dict[str, str] = {}
    current_body_parts: list[str] = []
    current_body_chars = 0
    in_headers = False
    have_message = False
    message_index = 0
    message_start_offset = 0
    attachment_count = 0
    pending_disposition = b""
    pending_attachment_counted = False
    pending_qp_line = b""
    stats = IndexStats()
    total_bytes = mbox_path.stat().st_size

    conn.execute("BEGIN")
    with mbox_path.open("rb") as handle:
        while True:
            line_offset = handle.tell()
            raw_line = handle.readline()
            if not raw_line:
                break
            if raw_line.startswith(b"From "):
                if have_message:
                    message_index += 1
                    current_headers["__attachment_count__"] = str(attachment_count)
                    finalize_index_message(
                        conn,
                        message_index,
                        str(mbox_path),
                        message_start_offset,
                        current_headers,
                        current_body_parts,
                        stats,
                    )
                    if message_index % COMMIT_EVERY == 0:
                        conn.commit()
                        conn.execute("BEGIN")
                    if show_progress and message_index % PROGRESS_EVERY == 0:
                        print(
                            f"Indexed {message_index} messages...",
                            file=sys.stderr,
                            flush=True,
                        )
                    if (
                        progress_callback is not None
                        and message_index % COMMIT_EVERY == 0
                    ):
                        progress_callback(message_index, line_offset, total_bytes)

                current_header_lines = []
                current_headers = {}
                current_body_parts = []
                current_body_chars = 0
                message_start_offset = line_offset
                attachment_count = 0
                pending_disposition = b""
                pending_attachment_counted = False
                pending_qp_line = b""
                in_headers = True
                have_message = True
                continue

            if not have_message:
                continue

            if in_headers:
                if raw_line in (b"\n", b"\r\n"):
                    current_headers = parse_headers(current_header_lines)
                    in_headers = False
                    continue
                current_header_lines.append(raw_line)
                continue

            lower_line = raw_line.lower().rstrip(b"\r\n")
            if lower_line.startswith(b"content-disposition:"):
                pending_disposition = lower_line
                pending_attachment_counted = False
                if b"attachment" in pending_disposition:
                    attachment_count += 1
                    pending_attachment_counted = True
                continue

            if pending_disposition and raw_line[:1] in (b" ", b"\t"):
                pending_disposition += b" " + lower_line.lstrip()
                if (
                    b"attachment" in pending_disposition
                    and not pending_attachment_counted
                ):
                    attachment_count += 1
                    pending_attachment_counted = True
                continue

            pending_disposition = b""
            pending_attachment_counted = False

            if current_body_chars >= max_body_chars:
                continue

            candidates, pending_qp_line = consume_body_line(raw_line, pending_qp_line)
            text = choose_text_candidate(candidates)
            if not text:
                continue
            remaining = max_body_chars - current_body_chars
            clipped = text[:remaining]
            if clipped:
                current_body_parts.append(clipped)
                current_body_chars += len(clipped)

    if have_message:
        message_index += 1
        current_headers["__attachment_count__"] = str(attachment_count)
        finalize_index_message(
            conn,
            message_index,
            str(mbox_path),
            message_start_offset,
            current_headers,
            current_body_parts,
            stats,
        )
    conn.commit()
    if progress_callback is not None:
        progress_callback(message_index, total_bytes, total_bytes)
    return message_index, stats


def write_index_metadata(
    conn: sqlite3.Connection,
    mbox_path: Path,
    message_count: int,
    max_body_chars: int,
    stats: IndexStats,
) -> None:
    """Write source and indexing statistics metadata into a Gmail index.

    The caller owns the transaction and final commit. Metadata values are stored
    as text so CLI and GUI callers can read them without schema-specific type
    handling.
    """

    metadata = {
        "source_path": str(mbox_path),
        "source_size_bytes": str(mbox_path.stat().st_size),
        "indexed_at_utc": datetime.now(UTC).isoformat(),
        "message_count": str(message_count),
        "max_body_chars": str(max_body_chars),
        "multipart_messages": str(stats.multipart_messages),
        "attachment_messages": str(stats.attachment_messages),
        "attachment_files": str(stats.attachment_files),
    }
    conn.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        metadata.items(),
    )
