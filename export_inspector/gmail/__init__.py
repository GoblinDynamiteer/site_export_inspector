"""Shared Gmail domain services for CLI and GUI entry points."""

from export_inspector.gmail.models import IndexStats, MailboxStats, SearchResult

__all__ = [
    "IndexStats",
    "MailboxStats",
    "SearchResult",
]
