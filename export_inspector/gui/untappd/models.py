"""Untappd item roles and the check-in table's filter/sort proxy."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt


UNTAPPD_SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 11
UNTAPPD_ENTRY_ROLE = int(Qt.ItemDataRole.UserRole) + 12
UNTAPPD_SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 13
UNTAPPD_BEER_ROLE = int(Qt.ItemDataRole.UserRole) + 14


class UntappdEntryFilterProxy(QSortFilterProxyModel):
    """Filters rows on all query terms (case-insensitive) and sorts on UNTAPPD_SORT_ROLE."""

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
        search_blob = self.sourceModel().data(source_index, UNTAPPD_SEARCH_ROLE) or ""
        lowered = str(search_blob).lower()
        return all(term in lowered for term in self.query_terms)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_value = self.sourceModel().data(left, UNTAPPD_SORT_ROLE)
        right_value = self.sourceModel().data(right, UNTAPPD_SORT_ROLE)
        if left_value is not None and right_value is not None:
            return left_value < right_value
        return super().lessThan(left, right)
