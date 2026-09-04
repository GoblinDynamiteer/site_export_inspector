from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MailboxStats:
    """Aggregate mailbox counts and date bounds produced by Gmail scans."""

    total_messages: int = 0
    multipart_messages: int = 0
    attachment_messages: int = 0
    attachment_files: int = 0
    first_dt: datetime | None = None
    last_dt: datetime | None = None


@dataclass
class SearchResult:
    """One Gmail search hit with enough metadata for CLI and GUI rendering."""

    index: int
    date_text: str
    sender: str
    to_text: str
    subject: str
    labels: str
    thread_id: str
    snippet: str


@dataclass
class IndexStats:
    """Counts collected while building a SQLite Gmail index."""

    multipart_messages: int = 0
    attachment_messages: int = 0
    attachment_files: int = 0
