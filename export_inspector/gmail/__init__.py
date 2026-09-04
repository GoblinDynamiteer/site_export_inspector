"""Shared Gmail domain services for CLI and GUI entry points."""

from export_inspector.gmail.models import IndexStats, MailboxStats, SearchResult
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
    "open_database",
    "write_index_metadata",
]
