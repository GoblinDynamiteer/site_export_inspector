"""The Runkeeper tab: load ZIP exports, browse activities and show a route map."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import QModelIndex, Qt, QUrl
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWebEngineWidgets import QWebEngineView
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
    QVBoxLayout,
    QWidget,
)

from export_inspector import runkeeper
from export_inspector.runkeeper import details
from export_inspector.runkeeper.ranks import ActivityRanks
from export_inspector.gui.appearance import use_detail_font
from export_inspector.gui.common import (
    DEFAULT_TIMEZONE,
    dialog_start_path,
    line_edit,
    remember_text,
    settings_text,
)
from export_inspector.gui.runkeeper.map_view import build_embedded_runkeeper_map_html
from export_inspector.gui.runkeeper.models import (
    RUNKEEPER_ACTIVITY_ROLE,
    RUNKEEPER_SEARCH_ROLE,
    RUNKEEPER_SORT_ROLE,
    RunkeeperActivityFilterProxy,
)

class RunkeeperTab(QWidget):
    """Tab that loads Runkeeper ZIP exports (a ZIP or a folder of them), lists the
    activities with ranks and details, and shows the selected route on a map."""

    def __init__(self) -> None:
        super().__init__()
        self.activities: list[runkeeper.Activity] = []
        self.measurements: list[dict[str, str]] = []
        self.photos: list[dict[str, str]] = []
        self.route_points_cache: dict[
            tuple[str, str], list[dict[str, float | str | None]]
        ] = {}
        self.ranks = ActivityRanks()
        self.selected_activity: runkeeper.Activity | None = None

        self.path_edit = line_edit("Runkeeper ZIP export or folder of ZIPs")
        self.path_edit.setText(settings_text("runkeeper/input_path"))
        browse_file = QPushButton("Browse ZIP")
        browse_file.clicked.connect(self.pick_input_file)
        browse_directory = QPushButton("Browse Folder")
        browse_directory.clicked.connect(self.pick_input_directory)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self.load_export)

        self.timezone_edit = line_edit(text=DEFAULT_TIMEZONE)
        self.timezone_edit.editingFinished.connect(self.refresh_loaded_display)
        self.filter_edit = line_edit("Filter activities")
        self.filter_edit.textChanged.connect(self.apply_filter)
        self.status_label = QLabel("0/0")

        self.model = QStandardItemModel(0, 4, self)
        self.model.setHorizontalHeaderLabels(
            ["Started", "Type", "Duration", "Distance"]
        )
        self.proxy_model = RunkeeperActivityFilterProxy()
        self.proxy_model.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self.select_activity)

        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        use_detail_font(self.detail_text)

        self.show_map_button = QPushButton("Show Map")
        self.show_map_button.clicked.connect(self.show_map)
        self.show_map_button.setEnabled(False)
        self.map_view: QWebEngineView | None = None
        self.map_layout = QVBoxLayout()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        source_box = QGroupBox("Source")
        source_layout = QGridLayout(source_box)
        source_layout.addWidget(QLabel("Path"), 0, 0)
        source_layout.addWidget(self.path_edit, 0, 1, 1, 2)
        source_layout.addWidget(browse_file, 0, 3)
        source_layout.addWidget(browse_directory, 0, 4)
        source_layout.addWidget(load_button, 0, 5)
        source_layout.addWidget(QLabel("Timezone"), 1, 0)
        source_layout.addWidget(self.timezone_edit, 1, 1, 1, 2)
        root.addWidget(source_box)

        filter_box = QGroupBox("Filter")
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.addWidget(self.filter_edit)
        filter_layout.addWidget(self.status_label)
        root.addWidget(filter_box)

        table_box = QGroupBox("Activities")
        table_layout = QVBoxLayout(table_box)
        table_layout.addWidget(self.table)
        root.addWidget(table_box, 2)

        detail_box = QGroupBox("Details")
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.addWidget(self.detail_text)
        detail_layout.addWidget(self.show_map_button)
        detail_layout.addLayout(self.map_layout)
        root.addWidget(detail_box, 2)

    def pick_input_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Runkeeper ZIP",
            dialog_start_path("runkeeper/input_path"),
            "ZIP Files (*.zip)",
        )
        if path:
            self.path_edit.setText(path)
            remember_text("runkeeper/input_path", path)

    def pick_input_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Runkeeper ZIP folder",
            dialog_start_path("runkeeper/input_path"),
        )
        if path:
            self.path_edit.setText(path)
            remember_text("runkeeper/input_path", path)

    def load_export(self) -> None:
        """Load the ZIP or folder from the path field, warning in a dialog if loading fails."""
        input_path = self.path_edit.text().strip()
        if not input_path:
            QMessageBox.warning(
                self, "Missing input", "Select a Runkeeper ZIP file or folder first."
            )
            return

        try:
            self.activities, self.measurements, self.photos = runkeeper.load_export(
                Path(input_path)
            )
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return

        remember_text("runkeeper/input_path", input_path)

        self.route_points_cache.clear()
        if self.map_view is not None:
            self.map_view.setHtml("<html><body></body></html>")
        self.ranks = ActivityRanks.from_activities(self.activities)
        self.populate_table()
        self.apply_filter()

        if self.proxy_model.rowCount() > 0:
            self.table.selectRow(0)
        else:
            self.selected_activity = None
            self.detail_text.setPlainText("No GPX activities found.")
            self.show_map_button.setEnabled(False)
            if self.map_view is not None:
                self.map_view.setHtml("<html><body></body></html>")

    def populate_table(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        timezone = self.timezone_edit.text().strip() or DEFAULT_TIMEZONE
        for activity in self.activities:
            row = [
                QStandardItem(
                    activity.started_at.astimezone(ZoneInfo(timezone)).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                ),
                QStandardItem(activity.activity_type),
                QStandardItem(runkeeper.format_duration(activity.duration_seconds)),
                QStandardItem(f"{activity.distance_km:.2f} km"),
            ]
            sort_values = [
                activity.started_at.timestamp(),
                activity.activity_type.lower(),
                activity.duration_seconds,
                activity.distance_km,
            ]
            search_blob = details.activity_search_blob(activity, self.ranks, timezone)
            for column, item in enumerate(row):
                item.setEditable(False)
                item.setData(activity, RUNKEEPER_ACTIVITY_ROLE)
                item.setData(search_blob, RUNKEEPER_SEARCH_ROLE)
                item.setData(sort_values[column], RUNKEEPER_SORT_ROLE)
            self.model.appendRow(row)
        self.proxy_model.sort(0, Qt.DescendingOrder)

    def refresh_loaded_display(self) -> None:
        if not self.activities:
            return
        self.populate_table()
        self.apply_filter()
        if self.selected_activity is not None:
            self.render_details(self.selected_activity)

    def apply_filter(self) -> None:
        self.proxy_model.set_query(self.filter_edit.text())
        self.update_status()

    def update_status(self) -> None:
        self.status_label.setText(
            f"{self.proxy_model.rowCount()}/{len(self.activities)}"
        )

    def select_activity(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self.selected_activity = None
            self.detail_text.clear()
            self.show_map_button.setEnabled(False)
            return

        source_index = self.proxy_model.mapToSource(current)
        activity = self.model.item(source_index.row(), 0).data(RUNKEEPER_ACTIVITY_ROLE)
        self.selected_activity = activity
        self.render_details(activity)
        self.show_map_button.setEnabled(True)
        if self.map_view is not None:
            self.map_view.setHtml("<html><body></body></html>")

    def render_details(self, activity: runkeeper.Activity) -> None:
        timezone = self.timezone_edit.text().strip() or DEFAULT_TIMEZONE
        self.detail_text.setPlainText(
            details.activity_details_text(activity, self.ranks, timezone, len(self.photos))
        )

    def show_map(self) -> None:
        """Render the selected activity's route in the embedded map.

        The web view is created on first use. Errors are shown in a dialog.
        """
        if self.selected_activity is None:
            return

        activity = self.selected_activity
        cache_key = (str(activity.archive_path), activity.file_name)
        try:
            points = self.route_points_cache.get(cache_key)
            if points is None:
                points = runkeeper.load_route_points(
                    activity.archive_path, activity.file_name
                )
                self.route_points_cache[cache_key] = points
            map_html = build_embedded_runkeeper_map_html(
                activity,
                points,
                self.timezone_edit.text().strip() or DEFAULT_TIMEZONE,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Map failed", str(exc))
            return

        if self.map_view is None:
            self.map_view = QWebEngineView()
            self.map_view.setMinimumHeight(320)
            self.map_layout.addWidget(self.map_view)

        self.map_view.setHtml(map_html, QUrl("https://carto.com/"))
