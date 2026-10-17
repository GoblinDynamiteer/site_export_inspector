"""The Untappd tab: load a check-in export and browse check-ins, beers, breweries and venues."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt, QUrl
from PySide6.QtGui import QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from export_inspector import untappd
from export_inspector.untappd import aggregates, details
from export_inspector.gui.appearance import use_detail_font
from export_inspector.gui.common import (
    dialog_start_path,
    line_edit,
    remember_text,
    settings_text,
)
from export_inspector.gui.untappd.models import (
    UNTAPPD_BEER_ROLE,
    UNTAPPD_ENTRY_ROLE,
    UNTAPPD_SEARCH_ROLE,
    UNTAPPD_SORT_ROLE,
    UntappdEntryFilterProxy,
)
from export_inspector.gui.untappd.photo import PhotoPreviewLabel, pixmap_from_image_data

class UntappdTab(QWidget):
    """Tab that loads an Untappd JSON export and browses check-ins, beers, breweries
    and venues, with details and the check-in photo."""

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict] = []
        self.beer_groups: list[dict] = []
        self.brewery_groups: list[dict] = []
        self.venue_groups: list[dict] = []
        self.had = aggregates.HadCounts()
        self.selected_entry: dict | None = None
        self.selected_beer: dict | None = None
        self.selected_brewery: dict | None = None
        self.selected_venue: dict | None = None
        self.photo_cache: dict[str, QPixmap] = {}
        self.pending_photo_urls: set[str] = set()

        self.path_edit = line_edit("Untappd export JSON")
        self.path_edit.setText(settings_text("untappd/input_path"))
        browse_input = QPushButton("Browse")
        browse_input.clicked.connect(self.pick_input)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self.load_export)

        self.filter_edit = line_edit("Filter check-ins")
        self.filter_edit.textChanged.connect(self.apply_filter)
        self.status_label = QLabel("0/0")
        self.beer_filter_edit = line_edit("Filter beers")
        self.beer_filter_edit.textChanged.connect(self.apply_beer_filter)
        self.beer_status_label = QLabel("0/0")
        self.brewery_filter_edit = line_edit("Filter breweries")
        self.brewery_filter_edit.textChanged.connect(self.apply_brewery_filter)
        self.brewery_status_label = QLabel("0/0")
        self.venue_filter_edit = line_edit("Filter venues")
        self.venue_filter_edit.textChanged.connect(self.apply_venue_filter)
        self.venue_status_label = QLabel("0/0")

        self.model = QStandardItemModel(0, 8, self)
        self.model.setHorizontalHeaderLabels(
            ["Date", "Check-in", "Brewery", "Beer", "ABV", "Type", "Rating", "Had"]
        )
        self.proxy_model = UntappdEntryFilterProxy()
        self.proxy_model.setSourceModel(self.model)
        self.beer_model = QStandardItemModel(0, 8, self)
        self.beer_model.setHorizontalHeaderLabels(
            [
                "Brewery",
                "Beer",
                "Date First Had",
                "Date Latest Had",
                "ABV",
                "Type",
                "Rating",
                "Total Had",
            ]
        )
        self.beer_proxy_model = UntappdEntryFilterProxy()
        self.beer_proxy_model.setSourceModel(self.beer_model)
        self.brewery_model = QStandardItemModel(0, 7, self)
        self.brewery_model.setHorizontalHeaderLabels(
            [
                "Brewery",
                "Country",
                "Date First Had",
                "Date Latest Had",
                "Rating",
                "Unique Beers",
                "Total Had",
            ]
        )
        self.brewery_proxy_model = UntappdEntryFilterProxy()
        self.brewery_proxy_model.setSourceModel(self.brewery_model)
        self.venue_model = QStandardItemModel(0, 8, self)
        self.venue_model.setHorizontalHeaderLabels(
            [
                "Venue",
                "City",
                "Country",
                "Date First Had",
                "Date Latest Had",
                "Rating",
                "Unique Beers",
                "Total Had",
            ]
        )
        self.venue_proxy_model = UntappdEntryFilterProxy()
        self.venue_proxy_model.setSourceModel(self.venue_model)

        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self.select_entry)
        self.beer_table = QTableView()
        self.beer_table.setModel(self.beer_proxy_model)
        self.beer_table.setSortingEnabled(True)
        self.beer_table.setSelectionBehavior(QTableView.SelectRows)
        self.beer_table.setSelectionMode(QTableView.SingleSelection)
        self.beer_table.setAlternatingRowColors(True)
        self.beer_table.verticalHeader().setVisible(False)
        self.beer_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.beer_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.beer_table.selectionModel().currentRowChanged.connect(self.select_beer)
        self.brewery_table = self.build_aggregate_table(self.brewery_proxy_model)
        self.brewery_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.brewery_table.selectionModel().currentRowChanged.connect(
            self.select_brewery
        )
        self.venue_table = self.build_aggregate_table(self.venue_proxy_model)
        self.venue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.venue_table.selectionModel().currentRowChanged.connect(self.select_venue)

        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        use_detail_font(self.detail_text)
        self.photo_label = PhotoPreviewLabel()
        self.beer_detail_text = QPlainTextEdit()
        self.beer_detail_text.setReadOnly(True)
        self.beer_detail_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        use_detail_font(self.beer_detail_text)
        self.brewery_detail_text = QPlainTextEdit()
        self.brewery_detail_text.setReadOnly(True)
        self.brewery_detail_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        use_detail_font(self.brewery_detail_text)
        self.venue_detail_text = QPlainTextEdit()
        self.venue_detail_text.setReadOnly(True)
        self.venue_detail_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        use_detail_font(self.venue_detail_text)
        self.network_manager = QNetworkAccessManager(self)
        self.network_manager.finished.connect(self.photo_download_finished)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        source_box = QGroupBox("Source")
        source_layout = QGridLayout(source_box)
        source_layout.addWidget(QLabel("Path"), 0, 0)
        source_layout.addWidget(self.path_edit, 0, 1, 1, 2)
        source_layout.addWidget(browse_input, 0, 3)
        source_layout.addWidget(load_button, 0, 4)
        root.addWidget(source_box)

        views = QTabWidget()
        views.addTab(self.build_checkins_page(), "Check-ins")
        views.addTab(self.build_beers_page(), "Beers")
        views.addTab(self.build_breweries_page(), "Breweries")
        views.addTab(self.build_venues_page(), "Venues")
        root.addWidget(views, 1)

    def build_aggregate_table(self, model: QSortFilterProxyModel) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QTableView.SelectRows)
        table.setSelectionMode(QTableView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        return table

    def build_checkins_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        filter_box = QGroupBox("Filter")
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.addWidget(self.filter_edit)
        filter_layout.addWidget(self.status_label)
        layout.addWidget(filter_box)

        table_box = QGroupBox("Check-ins")
        table_layout = QVBoxLayout(table_box)
        table_layout.addWidget(self.table)
        layout.addWidget(table_box, 2)

        detail_box = QGroupBox("Details")
        detail_layout = QHBoxLayout(detail_box)
        detail_layout.addWidget(self.detail_text, 2)
        detail_layout.addWidget(self.photo_label, 1)
        layout.addWidget(detail_box, 1)
        return page

    def build_beers_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        filter_box = QGroupBox("Filter")
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.addWidget(self.beer_filter_edit)
        filter_layout.addWidget(self.beer_status_label)
        layout.addWidget(filter_box)

        table_box = QGroupBox("Beers")
        table_layout = QVBoxLayout(table_box)
        table_layout.addWidget(self.beer_table)
        layout.addWidget(table_box, 2)

        detail_box = QGroupBox("Details")
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.addWidget(self.beer_detail_text)
        layout.addWidget(detail_box, 1)
        return page

    def build_breweries_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        filter_box = QGroupBox("Filter")
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.addWidget(self.brewery_filter_edit)
        filter_layout.addWidget(self.brewery_status_label)
        layout.addWidget(filter_box)

        table_box = QGroupBox("Breweries")
        table_layout = QVBoxLayout(table_box)
        table_layout.addWidget(self.brewery_table)
        layout.addWidget(table_box, 2)

        detail_box = QGroupBox("Details")
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.addWidget(self.brewery_detail_text)
        layout.addWidget(detail_box, 1)
        return page

    def build_venues_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        filter_box = QGroupBox("Filter")
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.addWidget(self.venue_filter_edit)
        filter_layout.addWidget(self.venue_status_label)
        layout.addWidget(filter_box)

        table_box = QGroupBox("Venues")
        table_layout = QVBoxLayout(table_box)
        table_layout.addWidget(self.venue_table)
        layout.addWidget(table_box, 2)

        detail_box = QGroupBox("Details")
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.addWidget(self.venue_detail_text)
        layout.addWidget(detail_box, 1)
        return page

    def pick_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Untappd JSON",
            dialog_start_path("untappd/input_path"),
            "JSON Files (*.json)",
        )
        if path:
            self.path_edit.setText(path)
            remember_text("untappd/input_path", path)

    def load_export(self) -> None:
        """Load the export from the path field, warning in a dialog if loading fails."""
        input_path = self.path_edit.text().strip()
        if not input_path:
            QMessageBox.warning(
                self, "Missing input", "Select an Untappd export JSON file first."
            )
            return

        try:
            self.entries = untappd.load_export(Path(input_path))
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return

        remember_text("untappd/input_path", input_path)
        self.had = aggregates.HadCounts.from_entries(self.entries)
        self.populate_table()
        self.populate_beer_table()
        self.populate_brewery_table()
        self.populate_venue_table()
        self.apply_filter()
        self.apply_beer_filter()
        self.apply_brewery_filter()
        self.apply_venue_filter()

        if self.proxy_model.rowCount() > 0:
            self.table.selectRow(0)
        else:
            self.selected_entry = None
            self.detail_text.setPlainText("No check-ins found.")
            self.photo_label.set_photo(None)
        if self.beer_proxy_model.rowCount() > 0:
            self.beer_table.selectRow(0)
        else:
            self.selected_beer = None
            self.beer_detail_text.setPlainText("No beers found.")
        if self.brewery_proxy_model.rowCount() > 0:
            self.brewery_table.selectRow(0)
        else:
            self.selected_brewery = None
            self.brewery_detail_text.setPlainText("No breweries found.")
        if self.venue_proxy_model.rowCount() > 0:
            self.venue_table.selectRow(0)
        else:
            self.selected_venue = None
            self.venue_detail_text.setPlainText("No venues found.")

    def populate_table(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        for entry in self.entries:
            created_dt = aggregates.entry_created_dt(entry)
            created_text = created_dt.strftime("%Y-%m-%d %H:%M") if created_dt else "-"
            rating_value = untappd.parse_rating(entry)
            had_index = self.had.had_index(entry)
            checkin_index = self.had.checkin_index(entry)
            row = [
                QStandardItem(created_text),
                QStandardItem(str(checkin_index)),
                QStandardItem(untappd.normalize_text(entry.get("brewery_name")) or "-"),
                QStandardItem(untappd.normalize_text(entry.get("beer_name")) or "-"),
                QStandardItem(aggregates.abv_table_text(entry)),
                QStandardItem(untappd.normalize_text(entry.get("beer_type")) or "-"),
                QStandardItem(untappd.display_rating(entry)),
                QStandardItem(str(had_index)),
            ]
            sort_values = [
                created_dt.timestamp() if created_dt else 0,
                checkin_index,
                untappd.normalize_text(entry.get("brewery_name")).lower(),
                untappd.normalize_text(entry.get("beer_name")).lower(),
                aggregates.abv_sort_value(entry),
                untappd.normalize_text(entry.get("beer_type")).lower(),
                rating_value if rating_value is not None else -1,
                had_index,
            ]
            search_blob = aggregates.entry_search_blob(entry, self.had)
            for column, item in enumerate(row):
                item.setEditable(False)
                item.setData(entry, UNTAPPD_ENTRY_ROLE)
                item.setData(search_blob, UNTAPPD_SEARCH_ROLE)
                item.setData(sort_values[column], UNTAPPD_SORT_ROLE)
            self.model.appendRow(row)
        self.proxy_model.sort(0, Qt.DescendingOrder)

    def apply_filter(self) -> None:
        self.proxy_model.set_query(self.filter_edit.text())
        self.status_label.setText(f"{self.proxy_model.rowCount()}/{len(self.entries)}")

    def populate_beer_table(self) -> None:
        self.beer_groups = aggregates.build_beer_groups(self.entries)
        self.beer_model.removeRows(0, self.beer_model.rowCount())
        for group in self.beer_groups:
            first_dt = group["first_dt"]
            latest_dt = group["latest_dt"]
            row = [
                QStandardItem(group["brewery"]),
                QStandardItem(group["beer"]),
                QStandardItem(first_dt.strftime("%Y-%m-%d %H:%M") if first_dt else "-"),
                QStandardItem(
                    latest_dt.strftime("%Y-%m-%d %H:%M") if latest_dt else "-"
                ),
                QStandardItem(aggregates.abv_table_text(group["entries"][0])),
                QStandardItem(group["beer_type"]),
                QStandardItem(aggregates.mean_rating_text(group["ratings"])),
                QStandardItem(str(len(group["entries"]))),
            ]
            sort_values = [
                group["brewery"].lower(),
                group["beer"].lower(),
                first_dt.timestamp() if first_dt else 0,
                latest_dt.timestamp() if latest_dt else 0,
                aggregates.abv_sort_value(group["entries"][0]),
                group["beer_type"].lower(),
                aggregates.mean_rating_value(group["ratings"]),
                len(group["entries"]),
            ]
            search_blob = aggregates.beer_search_blob(group)
            for column, item in enumerate(row):
                item.setEditable(False)
                item.setData(group, UNTAPPD_BEER_ROLE)
                item.setData(search_blob, UNTAPPD_SEARCH_ROLE)
                item.setData(sort_values[column], UNTAPPD_SORT_ROLE)
            self.beer_model.appendRow(row)
        self.beer_proxy_model.sort(3, Qt.DescendingOrder)

    def apply_beer_filter(self) -> None:
        self.beer_proxy_model.set_query(self.beer_filter_edit.text())
        self.beer_status_label.setText(
            f"{self.beer_proxy_model.rowCount()}/{len(self.beer_groups)}"
        )

    def populate_brewery_table(self) -> None:
        self.brewery_groups = aggregates.build_brewery_groups(self.entries)
        self.brewery_model.removeRows(0, self.brewery_model.rowCount())
        for group in self.brewery_groups:
            first_dt = group["first_dt"]
            latest_dt = group["latest_dt"]
            row = [
                QStandardItem(group["brewery"]),
                QStandardItem(group["country"]),
                QStandardItem(first_dt.strftime("%Y-%m-%d %H:%M") if first_dt else "-"),
                QStandardItem(
                    latest_dt.strftime("%Y-%m-%d %H:%M") if latest_dt else "-"
                ),
                QStandardItem(aggregates.mean_rating_text(group["ratings"])),
                QStandardItem(str(group["unique_beers"])),
                QStandardItem(str(len(group["entries"]))),
            ]
            sort_values = [
                group["brewery"].lower(),
                group["country"].lower(),
                first_dt.timestamp() if first_dt else 0,
                latest_dt.timestamp() if latest_dt else 0,
                aggregates.mean_rating_value(group["ratings"]),
                group["unique_beers"],
                len(group["entries"]),
            ]
            self.add_group_row(self.brewery_model, row, sort_values, group)
        self.brewery_proxy_model.sort(3, Qt.DescendingOrder)

    def apply_brewery_filter(self) -> None:
        self.brewery_proxy_model.set_query(self.brewery_filter_edit.text())
        self.brewery_status_label.setText(
            f"{self.brewery_proxy_model.rowCount()}/{len(self.brewery_groups)}"
        )

    def populate_venue_table(self) -> None:
        self.venue_groups = aggregates.build_venue_groups(self.entries)
        self.venue_model.removeRows(0, self.venue_model.rowCount())
        for group in self.venue_groups:
            first_dt = group["first_dt"]
            latest_dt = group["latest_dt"]
            row = [
                QStandardItem(group["venue"]),
                QStandardItem(group["city"]),
                QStandardItem(group["country"]),
                QStandardItem(first_dt.strftime("%Y-%m-%d %H:%M") if first_dt else "-"),
                QStandardItem(
                    latest_dt.strftime("%Y-%m-%d %H:%M") if latest_dt else "-"
                ),
                QStandardItem(aggregates.mean_rating_text(group["ratings"])),
                QStandardItem(str(group["unique_beers"])),
                QStandardItem(str(len(group["entries"]))),
            ]
            sort_values = [
                group["venue"].lower(),
                group["city"].lower(),
                group["country"].lower(),
                first_dt.timestamp() if first_dt else 0,
                latest_dt.timestamp() if latest_dt else 0,
                aggregates.mean_rating_value(group["ratings"]),
                group["unique_beers"],
                len(group["entries"]),
            ]
            self.add_group_row(self.venue_model, row, sort_values, group)
        self.venue_proxy_model.sort(4, Qt.DescendingOrder)

    def apply_venue_filter(self) -> None:
        self.venue_proxy_model.set_query(self.venue_filter_edit.text())
        self.venue_status_label.setText(
            f"{self.venue_proxy_model.rowCount()}/{len(self.venue_groups)}"
        )

    def add_group_row(
        self,
        model: QStandardItemModel,
        row: list[QStandardItem],
        sort_values: list[object],
        group: dict,
    ) -> None:
        search_blob = aggregates.aggregate_search_blob(group)
        for column, item in enumerate(row):
            item.setEditable(False)
            item.setData(group, UNTAPPD_BEER_ROLE)
            item.setData(search_blob, UNTAPPD_SEARCH_ROLE)
            item.setData(sort_values[column], UNTAPPD_SORT_ROLE)
        model.appendRow(row)

    def select_entry(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self.selected_entry = None
            self.detail_text.clear()
            self.photo_label.set_photo(None)
            return

        source_index = self.proxy_model.mapToSource(current)
        entry = self.model.item(source_index.row(), 0).data(UNTAPPD_ENTRY_ROLE)
        self.selected_entry = entry
        self.render_details(entry)
        self.update_photo(entry)

    def select_beer(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self.selected_beer = None
            self.beer_detail_text.clear()
            return

        source_index = self.beer_proxy_model.mapToSource(current)
        group = self.beer_model.item(source_index.row(), 0).data(UNTAPPD_BEER_ROLE)
        self.selected_beer = group
        self.render_beer_details(group)

    def select_brewery(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self.selected_brewery = None
            self.brewery_detail_text.clear()
            return

        source_index = self.brewery_proxy_model.mapToSource(current)
        group = self.brewery_model.item(source_index.row(), 0).data(UNTAPPD_BEER_ROLE)
        self.selected_brewery = group
        self.render_brewery_details(group)

    def select_venue(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self.selected_venue = None
            self.venue_detail_text.clear()
            return

        source_index = self.venue_proxy_model.mapToSource(current)
        group = self.venue_model.item(source_index.row(), 0).data(UNTAPPD_BEER_ROLE)
        self.selected_venue = group
        self.render_venue_details(group)

    def render_details(self, entry: dict) -> None:
        self.detail_text.setPlainText(
            details.checkin_details_text(entry, self.entries, self.had)
        )

    def render_beer_details(self, group: dict) -> None:
        self.beer_detail_text.setPlainText(details.beer_details_text(group, self.had))

    def render_brewery_details(self, group: dict) -> None:
        self.brewery_detail_text.setPlainText(details.brewery_details_text(group, self.had))

    def render_venue_details(self, group: dict) -> None:
        self.venue_detail_text.setPlainText(details.venue_details_text(group, self.had))

    def photo_url(self, entry: dict) -> str:
        return untappd.normalize_text(entry.get("photo_url"))

    def update_photo(self, entry: dict) -> None:
        url = self.photo_url(entry)
        if not url:
            self.photo_label.set_photo(None)
            return
        if url in self.photo_cache:
            self.photo_label.set_photo(self.photo_cache[url])
            return
        self.photo_label.set_photo(None, "Loading photo...")
        if url in self.pending_photo_urls:
            return

        self.pending_photo_urls.add(url)
        request = QNetworkRequest(QUrl(url))
        reply = self.network_manager.get(request)
        reply.setProperty("photo_url", url)

    def photo_download_finished(self, reply: QNetworkReply) -> None:
        url = str(reply.property("photo_url") or "")
        if url:
            self.pending_photo_urls.discard(url)

        if reply.error() != QNetworkReply.NetworkError.NoError:
            if (
                self.selected_entry is not None
                and self.photo_url(self.selected_entry) == url
            ):
                self.photo_label.set_photo(None, "Photo failed to load")
            reply.deleteLater()
            return

        pixmap = pixmap_from_image_data(bytes(reply.readAll()))
        if url and not pixmap.isNull():
            self.photo_cache[url] = pixmap
            if (
                self.selected_entry is not None
                and self.photo_url(self.selected_entry) == url
            ):
                self.photo_label.set_photo(pixmap)
        elif (
            self.selected_entry is not None
            and self.photo_url(self.selected_entry) == url
        ):
            self.photo_label.set_photo(None, "Photo failed to load")

        reply.deleteLater()
