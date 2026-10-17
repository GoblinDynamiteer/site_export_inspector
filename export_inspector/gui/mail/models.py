"""Gmail table record and filter/sort proxy for the Google Mail tab."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt


GMAIL_SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 21
GMAIL_RECORD_ROLE = int(Qt.ItemDataRole.UserRole) + 22
GMAIL_SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 23


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


class GmailFilterProxy(QSortFilterProxyModel):
    """Filters rows on all query terms (case-insensitive) and sorts on GMAIL_SORT_ROLE."""

    def __init__(self) -> None:
        super().__init__()
        self.query_terms: list[str] = []

    def set_query(self, query: str) -> None:
        """Keep only rows whose search blob contains every whitespace-separated term."""
        self.query_terms = query.lower().split()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self.query_terms:
            return True
        source_index = self.sourceModel().index(source_row, 0, source_parent)
        search_blob = self.sourceModel().data(source_index, GMAIL_SEARCH_ROLE) or ""
        lowered = str(search_blob).lower()
        return all(term in lowered for term in self.query_terms)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_value = self.sourceModel().data(left, GMAIL_SORT_ROLE)
        right_value = self.sourceModel().data(right, GMAIL_SORT_ROLE)
        if left_value is not None and right_value is not None:
            return left_value < right_value
        return super().lessThan(left, right)
