from __future__ import annotations

import html
import json
import sys
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import (
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QKeySequence,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from export_inspector import runkeeper
from export_inspector.gui.common import (
    DEFAULT_TIMEZONE,
    dialog_start_path,
    line_edit,
    remember_text,
    settings_text,
)
from export_inspector.gui.appearance import (
    TEXT_SCALE_DEFAULT,
    TEXT_SCALE_MAX,
    TEXT_SCALE_MIN,
    TEXT_SCALE_STEP,
    apply_appearance,
    load_appearance,
    save_appearance,
    system_font,
    use_detail_font,
)
from export_inspector.gui.mail.tab import GoogleMailTab
from export_inspector.gui.messenger.tab import MessengerTab
from export_inspector.gui.settings_dialog import SettingsDialog
from export_inspector.gui.untappd.tab import UntappdTab


def ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def build_embedded_runkeeper_map_html(
    activity: runkeeper.Activity,
    points: list[dict[str, float | str | None]],
    timezone_name: str,
) -> str:
    if not points:
        raise ValueError("This activity has no track points to render.")

    route_coordinates = [[point["lat"], point["lon"]] for point in points]
    color = runkeeper.color_for_activity(activity.activity_type)
    title = html.escape(activity.name)
    activity_type = html.escape(activity.activity_type)
    started = html.escape(runkeeper.format_dt(activity.started_at, timezone_name))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin=""
  >
  <style>
    html, body, #map {{
      height: 100%;
      margin: 0;
    }}
    body {{
      background: #f6f3ec;
      font-family: "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}
    #map {{
      min-height: 320px;
    }}
    .summary {{
      position: absolute;
      left: 12px;
      top: 12px;
      z-index: 700;
      max-width: min(340px, calc(100% - 24px));
      padding: 10px 12px;
      border: 1px solid rgba(20, 33, 61, 0.12);
      border-radius: 6px;
      background: rgba(255, 252, 246, 0.94);
      box-shadow: 0 10px 24px rgba(20, 33, 61, 0.12);
      color: #14213d;
    }}
    .title {{
      margin: 0 0 4px;
      font-weight: 700;
      font-size: 14px;
      line-height: 1.25;
    }}
    .meta {{
      margin: 0;
      color: #5f6b7a;
      font-size: 12px;
      line-height: 1.35;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="summary">
    <p class="title">{title}</p>
    <p class="meta">{activity_type} · {started}</p>
  </div>
  <script
    src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
    crossorigin=""
  ></script>
  <script>
    const route = {json.dumps(route_coordinates, separators=(",", ":"))};
    const map = L.map("map", {{
      zoomControl: true,
      attributionControl: true
    }});

    L.tileLayer("https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png", {{
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors &copy; CARTO"
    }}).addTo(map);

    const routeLine = L.polyline(route, {{
      color: {json.dumps(color)},
      weight: 5,
      opacity: 0.9
    }}).addTo(map);

    L.circleMarker(route[0], {{
      radius: 7,
      color: "#ffffff",
      weight: 2,
      fillColor: "#2a9d8f",
      fillOpacity: 1
    }}).addTo(map).bindPopup("Start");

    L.circleMarker(route[route.length - 1], {{
      radius: 7,
      color: "#ffffff",
      weight: 2,
      fillColor: "#d1495b",
      fillOpacity: 1
    }}).addTo(map).bindPopup("End");

    map.fitBounds(routeLine.getBounds(), {{ padding: [24, 24] }});
  </script>
</body>
</html>
"""


RUNKEEPER_SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
RUNKEEPER_ACTIVITY_ROLE = int(Qt.ItemDataRole.UserRole) + 2
RUNKEEPER_SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 3


class RunkeeperActivityFilterProxy(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.query_terms: list[str] = []

    def set_query(self, query: str) -> None:
        self.query_terms = query.lower().split()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self.query_terms:
            return True
        source_index = self.sourceModel().index(source_row, 0, source_parent)
        search_blob = self.sourceModel().data(source_index, RUNKEEPER_SEARCH_ROLE) or ""
        lowered = str(search_blob).lower()
        return all(term in lowered for term in self.query_terms)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_value = self.sourceModel().data(left, RUNKEEPER_SORT_ROLE)
        right_value = self.sourceModel().data(right, RUNKEEPER_SORT_ROLE)
        if left_value is not None and right_value is not None:
            return left_value < right_value
        return super().lessThan(left, right)


class RunkeeperTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.activities: list[runkeeper.Activity] = []
        self.measurements: list[dict[str, str]] = []
        self.photos: list[dict[str, str]] = []
        self.route_points_cache: dict[
            tuple[str, str], list[dict[str, float | str | None]]
        ] = {}
        self.distance_ranks: dict[int, int] = {}
        self.duration_ranks: dict[int, int] = {}
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
        self.rebuild_ranks()
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

    def rebuild_ranks(self) -> None:
        self.distance_ranks = self.rank_by_type("distance")
        self.duration_ranks = self.rank_by_type("duration")

    def rank_by_type(self, metric: str) -> dict[int, int]:
        ranks: dict[int, int] = {}
        by_type: dict[str, list[runkeeper.Activity]] = {}
        for activity in self.activities:
            by_type.setdefault(activity.activity_type, []).append(activity)

        for activities in by_type.values():
            if metric == "distance":
                values = [activity.distance_km for activity in activities]
                for activity in activities:
                    ranks[activity.index] = 1 + sum(
                        value > activity.distance_km for value in values
                    )
            else:
                values = [activity.duration_seconds for activity in activities]
                for activity in activities:
                    ranks[activity.index] = 1 + sum(
                        value > activity.duration_seconds for value in values
                    )
        return ranks

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
            search_blob = self.activity_search_blob(activity)
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

    def activity_search_blob(self, activity: runkeeper.Activity) -> str:
        timezone = self.timezone_edit.text().strip() or DEFAULT_TIMEZONE
        fields = [
            activity.name,
            activity.file_name,
            activity.activity_type,
            runkeeper.format_dt(activity.started_at, timezone),
            runkeeper.format_dt(activity.finished_at, timezone),
            runkeeper.format_duration(activity.duration_seconds),
            f"{activity.distance_km:.2f} km",
            runkeeper.format_pace(activity.distance_km, activity.duration_seconds),
            runkeeper.format_speed(activity.distance_km, activity.duration_seconds),
            f"{activity.elevation_gain_m:.0f} m",
            str(activity.point_count),
            str(activity.archive_path),
            self.distance_rank_label(activity),
            self.duration_rank_label(activity),
        ]
        if activity.start_lat is not None and activity.start_lon is not None:
            fields.append(f"{activity.start_lat:.6f}, {activity.start_lon:.6f}")
        if activity.end_lat is not None and activity.end_lon is not None:
            fields.append(f"{activity.end_lat:.6f}, {activity.end_lon:.6f}")
        return "\n".join(fields)

    def render_details(self, activity: runkeeper.Activity) -> None:
        timezone = self.timezone_edit.text().strip() or DEFAULT_TIMEZONE
        lines = [
            f"Name: {activity.name}",
            f"File: {activity.file_name}",
            f"Type: {activity.activity_type}",
            f"Started: {runkeeper.format_dt(activity.started_at, timezone)}",
            f"Finished: {runkeeper.format_dt(activity.finished_at, timezone)}",
            f"Duration: {runkeeper.format_duration(activity.duration_seconds)} ({self.duration_rank_label(activity)})",
            f"Distance: {activity.distance_km:.2f} km ({self.distance_rank_label(activity)})",
            f"Pace: {runkeeper.format_pace(activity.distance_km, activity.duration_seconds)}",
            f"Speed: {runkeeper.format_speed(activity.distance_km, activity.duration_seconds)}",
            f"Elevation gain: {activity.elevation_gain_m:.0f} m",
            f"Track points: {activity.point_count}",
        ]
        if activity.start_lat is not None and activity.start_lon is not None:
            lines.append(f"Start: {activity.start_lat:.6f}, {activity.start_lon:.6f}")
        if activity.end_lat is not None and activity.end_lon is not None:
            lines.append(f"End: {activity.end_lat:.6f}, {activity.end_lon:.6f}")
        lines.extend(
            [
                f"Archive: {activity.archive_path}",
                f"Photo entries in loaded export data: {len(self.photos)}",
            ]
        )
        if self.photos:
            lines.append(
                "Photo note: photos.csv uses activity UUIDs that are not exposed in the GPX file names."
            )
        self.detail_text.setPlainText("\n".join(lines))

    def distance_rank_label(self, activity: runkeeper.Activity) -> str:
        rank = self.distance_ranks.get(activity.index)
        if rank is None:
            return f"unranked {activity.activity_type} distance"
        return f"{ordinal(rank)} longest {activity.activity_type} distance"

    def duration_rank_label(self, activity: runkeeper.Activity) -> str:
        rank = self.duration_ranks.get(activity.index)
        if rank is None:
            return f"unranked {activity.activity_type} duration"
        return f"{ordinal(rank)} longest {activity.activity_type} duration"

    def show_map(self) -> None:
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Export Inspector")
        self.resize(1400, 920)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        self.google_mail_tab = GoogleMailTab()
        tabs.addTab(MessengerTab(), "Messenger")
        tabs.addTab(self.google_mail_tab, "Google Mail")
        tabs.addTab(UntappdTab(), "Untappd")
        tabs.addTab(RunkeeperTab(), "Runkeeper")
        self.setCentralWidget(tabs)

        file_menu = self.menuBar().addMenu("File")
        settings_action = QAction("Settings…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.show_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(QApplication.quit)
        file_menu.addAction(quit_action)

        tools_menu = self.menuBar().addMenu("Tools")
        gmail_menu = tools_menu.addMenu("Gmail")
        convert_mbox_action = QAction("Convert mbox", self)
        convert_mbox_action.triggered.connect(self.google_mail_tab.open_convert_widget)
        gmail_menu.addAction(convert_mbox_action)

        about = QAction("About", self)
        about.triggered.connect(self.show_about)
        self.menuBar().addAction(about)

        for shortcuts, delta in (
            ([QKeySequence(QKeySequence.ZoomIn), QKeySequence("Ctrl+=")], TEXT_SCALE_STEP),
            ([QKeySequence(QKeySequence.ZoomOut)], -TEXT_SCALE_STEP),
            ([QKeySequence("Ctrl+0")], 0),
        ):
            action = QAction(self)
            action.setShortcuts(shortcuts)
            action.triggered.connect(lambda _checked=False, d=delta: self.step_text_scale(d))
            self.addAction(action)

    def show_settings(self) -> None:
        SettingsDialog(self).exec()

    def step_text_scale(self, delta: int) -> None:
        """Change the saved text scale by ``delta`` percent (0 resets it) and apply it."""
        appearance = load_appearance()
        if delta:
            scale = max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX, appearance.text_scale + delta))
        else:
            scale = TEXT_SCALE_DEFAULT
        appearance = replace(appearance, text_scale=scale)
        save_appearance(appearance)
        apply_appearance(appearance)

    def show_about(self) -> None:
        QMessageBox.information(
            self,
            "About Export Inspector",
            "Unified desktop wrapper around the Messenger, Google Mail, Untappd, and Runkeeper export tools.",
        )


def main() -> None:
    app = QApplication(sys.argv)
    system_font()
    window = MainWindow()
    apply_appearance(load_appearance())
    window.show()
    sys.exit(app.exec())
