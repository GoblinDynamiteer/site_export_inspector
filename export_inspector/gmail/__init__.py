"""Shared Gmail domain services for CLI and GUI entry points."""

from export_inspector.gmail.models import IndexStats, MailboxStats, SearchResult
from export_inspector.gmail.mbox import (
    load_message_from_mbox,
    load_message_from_offset,
    scan_mbox_info,
    search_mbox,
)
from export_inspector.gmail.sqlite_index import (
    index_mbox,
    load_metadata,
    open_database,
    write_index_metadata,
)

__all__ = [
    "IndexStats",
    "MailboxStats",
    "SearchResult",
    "index_mbox",
    "load_metadata",
    "load_message_from_mbox",
    "load_message_from_offset",
    "open_database",
    "scan_mbox_info",
    "search_mbox",
    "write_index_metadata",
]
