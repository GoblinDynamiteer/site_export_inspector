from __future__ import annotations

import html
import json
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QDate,
    QIODevice,
    QPoint,
    QModelIndex,
    QProcess,
    QProcessEnvironment,
    QSettings,
    QSortFilterProxyModel,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QFont,
    QImageReader,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
    QTextCursor,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import runkeeper
import show_messenger_chat
import untappd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMEZONE = "Europe/Stockholm"
SETTINGS_ORG = "jk"
SETTINGS_APP = "export_inspector"


def split_terms(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    return shlex.split(text)


def iso_date(date_edit: QDateEdit) -> str:
    return date_edit.date().toString("yyyy-MM-dd")


def make_env() -> QProcessEnvironment:
    env = QProcessEnvironment.systemEnvironment()
    current = env.value("PYTHONPATH", "")
    root = str(PROJECT_ROOT)
    env.insert("PYTHONPATH", f"{root}{os.pathsep + current if current else ''}")
    return env


def line_edit(placeholder: str = "", text: str = "") -> QLineEdit:
    widget = QLineEdit()
    widget.setPlaceholderText(placeholder)
    if text:
        widget.setText(text)
    return widget


def app_settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def settings_text(key: str, default: str = "") -> str:
    value = app_settings().value(key, default)
    return str(value) if value is not None else default


def remember_text(key: str, value: str) -> None:
    text = value.strip()
    if text:
        app_settings().setValue(key, text)


def dialog_start_path(key: str, fallback: str = "") -> str:
    saved = settings_text(key, fallback).strip()
    if not saved:
        return ""
    path = Path(saved).expanduser()
    if path.is_dir():
        return str(path)
    if path.parent.exists():
        return str(path.parent)
    return fallback


def create_date_controls() -> tuple[QCheckBox, QDateEdit]:
    checkbox = QCheckBox("Enable")
    date_edit = QDateEdit()
    date_edit.setCalendarPopup(True)
    date_edit.setDisplayFormat("yyyy-MM-dd")
    date_edit.setDate(QDate.currentDate())
    date_edit.setEnabled(False)
    checkbox.toggled.connect(date_edit.setEnabled)
    return checkbox, date_edit


def ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def pixmap_from_image_data(data: bytes) -> QPixmap:
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        return pixmap
    return QPixmap.fromImage(image)


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


def messenger_search_blob(message: dict, timezone_name: str) -> str:
    values: list[str] = [
        show_messenger_chat.repair_text(message.get("sender_name", "")),
        show_messenger_chat.repair_text(message.get("content", "")),
        show_messenger_chat.format_swedish_datetime(
            message["timestamp_ms"], timezone_name
        ),
    ]
    values.extend(show_messenger_chat.describe_attachment(message))
    reactions = show_messenger_chat.describe_reactions(message)
    if reactions:
        values.append(reactions)
    return "\n".join(values).lower()


def render_message_block(message: dict, timezone_name: str) -> str:
    return "\n".join(show_messenger_chat.render_message(message, timezone_name, {}))


class MessengerTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[dict] = []
        self.participants: list[str] = []
        self.paths: list[str] = []
        self.thread_signatures: list[tuple[str, ...]] = []
        self.available_threads: list[tuple[tuple[str, ...], list[str]]] = []

        self.path_edit = line_edit("JSON file or folder with message_*.json files")
        self.path_edit.setText(settings_text("messenger/input_path"))
        self.timezone_edit = line_edit(text=DEFAULT_TIMEZONE)
        self.filter_edit = line_edit(
            "Live filter: sender, text, attachment ref, reaction…"
        )
        self.filter_edit.textChanged.connect(self.refresh_messages)
        self.from_enabled, self.from_date = create_date_controls()
        self.from_enabled.toggled.connect(self.refresh_messages)
        self.from_date.dateChanged.connect(self.refresh_messages)
        self.show_latest = QCheckBox("Show latest messages")
        self.show_latest.setChecked(True)
        self.show_latest.toggled.connect(self.refresh_messages)
        self.render_limit = QSpinBox()
        self.render_limit.setRange(50, 100000)
        self.render_limit.setValue(100000)
        self.render_limit.valueChanged.connect(self.refresh_messages)
        self.status_label = QLabel("No chat loaded.")
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.thread_list = QListWidget()
        self.thread_list.currentRowChanged.connect(self.select_thread)
        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.Monospace)
        self.viewer.setFont(mono)

        browse_file = QPushButton("Browse File")
        browse_dir = QPushButton("Browse Folder")
        browse_file.clicked.connect(self.pick_file)
        browse_dir.clicked.connect(self.pick_directory)
        load_button = QPushButton("Load Chat")
        load_button.clicked.connect(self.load_chat)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        source_box = QGroupBox("Source")
        source_layout = QGridLayout(source_box)
        source_layout.addWidget(QLabel("Path"), 0, 0)
        source_layout.addWidget(self.path_edit, 0, 1, 1, 3)
        source_layout.addWidget(browse_file, 1, 1)
        source_layout.addWidget(browse_dir, 1, 2)
        source_layout.addWidget(load_button, 1, 3)
        root.addWidget(source_box)

        filter_box = QGroupBox("Filter")
        filter_layout = QFormLayout(filter_box)
        filter_layout.addRow("Timezone", self.timezone_edit)
        filter_layout.addRow("Live text", self.filter_edit)
        from_row = QHBoxLayout()
        from_row.addWidget(self.from_enabled)
        from_row.addWidget(self.from_date)
        filter_layout.addRow("From date", from_row)
        filter_layout.addRow("", self.show_latest)
        filter_layout.addRow("Render limit", self.render_limit)
        root.addWidget(filter_box)

        summary_box = QGroupBox("Summary")
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.addWidget(self.status_label)
        summary_layout.addWidget(self.info_label)
        root.addWidget(summary_box)

        thread_box = QGroupBox("Chats")
        thread_layout = QVBoxLayout(thread_box)
        thread_layout.addWidget(self.thread_list)
        root.addWidget(thread_box)

        messages_box = QGroupBox("Messages")
        messages_layout = QVBoxLayout(messages_box)
        messages_layout.addWidget(self.viewer)
        root.addWidget(messages_box, 1)

    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Messenger JSON",
            dialog_start_path("messenger/input_path"),
            "JSON Files (*.json)",
        )
        if path:
            self.path_edit.setText(path)
            remember_text("messenger/input_path", path)

    def pick_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Messenger Folder",
            dialog_start_path("messenger/input_path"),
        )
        if path:
            self.path_edit.setText(path)
            remember_text("messenger/input_path", path)

    def load_chat(self) -> None:
        raw_path = self.path_edit.text().strip()
        input_path: str | None = raw_path or None

        try:
            self.available_threads = show_messenger_chat.discover_threads(input_path)
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return

        if raw_path:
            remember_text("messenger/input_path", raw_path)

        self.thread_list.clear()
        self.thread_signatures = []

        if not self.available_threads:
            self.messages = []
            self.participants = []
            self.paths = []
            self.viewer.clear()
            self.status_label.setText("No chats found.")
            self.info_label.setText("")
            return

        for signature, sources in self.available_threads:
            self.thread_signatures.append(signature)
            self.thread_list.addItem(
                f"{show_messenger_chat.signature_label(signature)}  ({len(sources)} source{'s' if len(sources) != 1 else ''})"
            )

        self.status_label.setText(f"Found {len(self.available_threads)} chats.")
        self.thread_list.setCurrentRow(0)

    def select_thread(self, row: int) -> None:
        if row < 0 or row >= len(self.thread_signatures):
            return

        raw_path = self.path_edit.text().strip()
        input_path: str | None = raw_path or None
        signature = self.thread_signatures[row]

        try:
            self.messages, self.participants, self.paths = (
                show_messenger_chat.load_exports(
                    input_path,
                    target_signature=signature,
                )
            )
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return

        participants_text = (
            " / ".join(self.participants) if self.participants else "(none)"
        )
        self.info_label.setText(
            f"Files: {len(self.paths)}\nParticipants: {participants_text}\nMessages: {len(self.messages)}"
        )
        self.refresh_messages()

    def current_from_timestamp(self) -> int | None:
        if not self.from_enabled.isChecked():
            return None
        try:
            return show_messenger_chat.parse_from_date(
                iso_date(self.from_date),
                self.timezone_edit.text().strip() or DEFAULT_TIMEZONE,
            )
        except Exception:
            return None

    def _message_search_blob(self, message: dict) -> str:
        return messenger_search_blob(
            message,
            self.timezone_edit.text().strip() or DEFAULT_TIMEZONE,
        )

    def filtered_messages(self) -> list[dict]:
        from_timestamp = self.current_from_timestamp()
        filtered = show_messenger_chat.filter_messages_from(
            self.messages, from_timestamp
        )
        query = self.filter_edit.text().strip().lower()
        if not query:
            return filtered
        terms = query.split()
        matches: list[dict] = []
        for message in filtered:
            blob = self._message_search_blob(message)
            if all(term in blob for term in terms):
                matches.append(message)
        return matches

    def refresh_messages(self) -> None:
        if not self.messages:
            self.viewer.clear()
            if self.thread_signatures:
                self.status_label.setText("Selected chat has no messages.")
            else:
                self.status_label.setText("No chat loaded.")
            return

        timezone_name = self.timezone_edit.text().strip() or DEFAULT_TIMEZONE
        filtered = self.filtered_messages()
        limit = self.render_limit.value()
        if self.show_latest.isChecked():
            visible = filtered[-limit:]
        else:
            visible = filtered[:limit]

        blocks: list[str] = []
        previous_timestamp_ms: int | None = None
        for message in visible:
            current_timestamp = message["timestamp_ms"]
            if (
                previous_timestamp_ms is not None
                and current_timestamp - previous_timestamp_ms
                >= show_messenger_chat.DEFAULT_GAP_SECONDS * 1000
            ):
                blocks.append(
                    show_messenger_chat.format_gap(
                        previous_timestamp_ms, current_timestamp
                    )
                )
                blocks.append("")

            blocks.append(render_message_block(message, timezone_name))
            blocks.append("")
            previous_timestamp_ms = current_timestamp

        self.viewer.setPlainText("\n".join(blocks).rstrip())

        rendered_text = f"Showing {len(visible)} of {len(filtered)} matching messages"
        if len(filtered) > limit:
            edge = "latest" if self.show_latest.isChecked() else "earliest"
            rendered_text += f"  (render limit {limit}, {edge} slice)"
        self.status_label.setText(rendered_text)


class ProcessTab(QWidget):
    def __init__(self, module_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.module_name = module_name
        self.process = QProcess(self)
        self.process.setProcessEnvironment(make_env())
        self.process.readyReadStandardOutput.connect(self._drain_stdout)
        self.process.readyReadStandardError.connect(self._drain_stderr)
        self.process.started.connect(self._on_started)
        self.process.finished.connect(self._on_finished)

        self.run_button = QPushButton("Run")
        self.stop_button = QPushButton("Stop")
        self.clear_button = QPushButton("Clear Output")
        self.status_label = QLabel("Idle")
        self.command_label = QLabel("")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)

        mono = QFont("Monospace")
        mono.setStyleHint(QFont.Monospace)
        self.output.setFont(mono)
        self.command_label.setFont(mono)
        self.command_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.command_label.setWordWrap(True)

        self.run_button.clicked.connect(self.run_current)
        self.stop_button.clicked.connect(self.stop_process)
        self.clear_button.clicked.connect(self.output.clear)
        self.stop_button.setEnabled(False)

    def build_shell_layout(self, controls_layout: QVBoxLayout) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        root.addLayout(controls_layout)

        action_row = QHBoxLayout()
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.clear_button)
        action_row.addStretch(1)
        action_row.addWidget(self.status_label)
        root.addLayout(action_row)

        command_box = QGroupBox("Command")
        command_layout = QVBoxLayout(command_box)
        command_layout.addWidget(self.command_label)
        root.addWidget(command_box)

        output_box = QGroupBox("Output")
        output_layout = QVBoxLayout(output_box)
        output_layout.addWidget(self.output)
        root.addWidget(output_box, 1)

    def run_current(self) -> None:
        raise NotImplementedError

    def start_module(
        self, args: list[str], working_directory: str | None = None
    ) -> None:
        if self.process.state() != QProcess.NotRunning:
            QMessageBox.warning(
                self, "Busy", "A command is already running in this tab."
            )
            return

        self.output.clear()
        if working_directory:
            self.process.setWorkingDirectory(working_directory)
        else:
            self.process.setWorkingDirectory(str(PROJECT_ROOT))

        command = [sys.executable, "-m", self.module_name, *args]
        self.command_label.setText(" ".join(shlex.quote(part) for part in command))
        self.status_label.setText("Starting…")
        self.process.start(sys.executable, ["-m", self.module_name, *args])

    def stop_process(self) -> None:
        if self.process.state() == QProcess.NotRunning:
            return
        self.process.terminate()
        if not self.process.waitForFinished(1500):
            self.process.kill()

    def _drain_stdout(self) -> None:
        data = bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(data)
        self.output.moveCursor(QTextCursor.End)

    def _drain_stderr(self) -> None:
        data = bytes(self.process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(data)
        self.output.moveCursor(QTextCursor.End)

    def _on_started(self) -> None:
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Running")

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if exit_status == QProcess.NormalExit:
            self.status_label.setText(f"Finished ({exit_code})")
        else:
            self.status_label.setText("Crashed")


class GoogleMailTab(ProcessTab):
    def __init__(self) -> None:
        super().__init__("google_mail")
        self.path_edit = line_edit("Mailbox .mbox or SQLite index")
        self.path_edit.setText(settings_text("google_mail/input_path"))
        browse_input = QPushButton("Browse")
        browse_input.clicked.connect(self.pick_input)

        self.action_combo = QComboBox()
        self.action_combo.addItems(["info", "search", "show", "index"])
        self.action_stack = QStackedWidget()
        self.action_combo.currentIndexChanged.connect(self.action_stack.setCurrentIndex)

        self.timezone_edit = line_edit(text=DEFAULT_TIMEZONE)

        self.info_top = QSpinBox()
        self.info_top.setRange(1, 500)
        self.info_top.setValue(10)

        self.search_terms = line_edit("order receipt sofa")
        self.search_from = line_edit("sender contains…")
        self.search_to = line_edit("recipient contains…")
        self.search_subject = line_edit("subject contains…")
        self.search_label = line_edit("label contains…")
        self.search_after_enabled, self.search_after = create_date_controls()
        self.search_before_enabled, self.search_before = create_date_controls()
        self.search_any = QCheckBox("Match any term")
        self.search_headers_only = QCheckBox("Headers only")
        self.search_limit = QSpinBox()
        self.search_limit.setRange(1, 5000)
        self.search_limit.setValue(20)

        self.show_index = QSpinBox()
        self.show_index.setRange(1, 50_000_000)
        self.show_index.setValue(1)

        self.index_output = line_edit(
            text=settings_text("google_mail/index_output", "gmail_index.sqlite")
        )
        self.index_max_body = QSpinBox()
        self.index_max_body.setRange(1000, 1_000_000)
        self.index_max_body.setValue(50_000)
        self.index_force = QCheckBox("Overwrite if it exists")
        browse_index = QPushButton("Save As…")
        browse_index.clicked.connect(self.pick_index_output)

        controls = QVBoxLayout()
        source_box = QGroupBox("Source")
        source_layout = QGridLayout(source_box)
        source_layout.addWidget(QLabel("Path"), 0, 0)
        source_layout.addWidget(self.path_edit, 0, 1, 1, 2)
        source_layout.addWidget(browse_input, 0, 3)
        controls.addWidget(source_box)

        action_box = QGroupBox("Action")
        action_layout = QVBoxLayout(action_box)
        action_layout.addWidget(self.action_combo)
        action_layout.addWidget(self.action_stack)
        controls.addWidget(action_box)

        self.action_stack.addWidget(self._build_info_page())
        self.action_stack.addWidget(self._build_search_page())
        self.action_stack.addWidget(self._build_show_page())
        self.action_stack.addWidget(self._build_index_page(browse_index))

        self.build_shell_layout(controls)

    def _build_info_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.addRow("Top rows", self.info_top)
        return page

    def _build_search_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.addRow("Terms", self.search_terms)
        layout.addRow("From filter", self.search_from)
        layout.addRow("To filter", self.search_to)
        layout.addRow("Subject filter", self.search_subject)
        layout.addRow("Label filter", self.search_label)

        after_row = QHBoxLayout()
        after_row.addWidget(self.search_after_enabled)
        after_row.addWidget(self.search_after)
        layout.addRow("After", after_row)

        before_row = QHBoxLayout()
        before_row.addWidget(self.search_before_enabled)
        before_row.addWidget(self.search_before)
        layout.addRow("Before", before_row)

        layout.addRow("Limit", self.search_limit)
        layout.addRow("", self.search_any)
        layout.addRow("", self.search_headers_only)
        return page

    def _build_show_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.addRow("Message index", self.show_index)
        return page

    def _build_index_page(self, browse_index: QPushButton) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        output_row = QHBoxLayout()
        output_row.addWidget(self.index_output)
        output_row.addWidget(browse_index)
        layout.addRow("Index file", output_row)
        layout.addRow("Max body chars", self.index_max_body)
        layout.addRow("", self.index_force)
        return page

    def pick_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select mailbox or index",
            dialog_start_path("google_mail/input_path"),
            "Mailbox files (*.mbox *.sqlite *.db *.sqlite3);;All files (*)",
        )
        if path:
            self.path_edit.setText(path)
            remember_text("google_mail/input_path", path)

    def pick_index_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save SQLite index",
            dialog_start_path("google_mail/index_output", self.index_output.text()),
            "SQLite (*.sqlite)",
        )
        if path:
            self.index_output.setText(path)
            remember_text("google_mail/index_output", path)

    def run_current(self) -> None:
        input_path = self.path_edit.text().strip()
        if not input_path:
            QMessageBox.warning(
                self, "Missing input", "Select an .mbox or .sqlite file first."
            )
            return

        remember_text("google_mail/input_path", input_path)

        action = self.action_combo.currentText()
        args = [action, input_path]

        if action == "info":
            args.extend(
                ["--timezone", self.timezone_edit.text().strip() or DEFAULT_TIMEZONE]
            )
            args.extend(["--top", str(self.info_top.value()), "--no-progress"])
        elif action == "search":
            args.extend(split_terms(self.search_terms.text()))
            if self.search_from.text().strip():
                args.extend(["--from", self.search_from.text().strip()])
            if self.search_to.text().strip():
                args.extend(["--to", self.search_to.text().strip()])
            if self.search_subject.text().strip():
                args.extend(["--subject", self.search_subject.text().strip()])
            if self.search_label.text().strip():
                args.extend(["--label", self.search_label.text().strip()])
            if self.search_after_enabled.isChecked():
                args.extend(["--after", iso_date(self.search_after)])
            if self.search_before_enabled.isChecked():
                args.extend(["--before", iso_date(self.search_before)])
            if self.search_any.isChecked():
                args.append("--any")
            if self.search_headers_only.isChecked():
                args.append("--headers-only")
            args.extend(["--limit", str(self.search_limit.value())])
            args.extend(
                [
                    "--timezone",
                    self.timezone_edit.text().strip() or DEFAULT_TIMEZONE,
                    "--no-progress",
                ]
            )
        elif action == "show":
            args.append(str(self.show_index.value()))
            args.extend(
                [
                    "--timezone",
                    self.timezone_edit.text().strip() or DEFAULT_TIMEZONE,
                    "--no-progress",
                ]
            )
        elif action == "index":
            output_path = self.index_output.text().strip() or "gmail_index.sqlite"
            remember_text("google_mail/index_output", output_path)
            args.append(output_path)
            args.extend(
                ["--max-body-chars", str(self.index_max_body.value()), "--no-progress"]
            )
            if self.index_force.isChecked():
                args.append("--force")

        self.start_module(args)


UNTAPPD_SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 11
UNTAPPD_ENTRY_ROLE = int(Qt.ItemDataRole.UserRole) + 12
UNTAPPD_SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 13
UNTAPPD_BEER_ROLE = int(Qt.ItemDataRole.UserRole) + 14


class UntappdEntryFilterProxy(QSortFilterProxyModel):
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
        search_blob = self.sourceModel().data(source_index, UNTAPPD_SEARCH_ROLE) or ""
        lowered = str(search_blob).lower()
        return all(term in lowered for term in self.query_terms)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_value = self.sourceModel().data(left, UNTAPPD_SORT_ROLE)
        right_value = self.sourceModel().data(right, UNTAPPD_SORT_ROLE)
        if left_value is not None and right_value is not None:
            return left_value < right_value
        return super().lessThan(left, right)


class PhotoPreviewLabel(QLabel):
    def __init__(self) -> None:
        super().__init__("No photo")
        self.original_pixmap: QPixmap | None = None
        self.overlay: QLabel | None = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 260)
        self.setWordWrap(True)

    def set_photo(self, pixmap: QPixmap | None, empty_text: str = "No photo") -> None:
        self.original_pixmap = pixmap
        if pixmap is None or pixmap.isNull():
            self.setText(empty_text)
            self.setPixmap(QPixmap())
            self.close_overlay()
            return
        self.setText("")
        self.update_scaled_pixmap()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_scaled_pixmap()

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.original_pixmap is not None
            and not self.original_pixmap.isNull()
        ):
            self.show_overlay(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.close_overlay()
        super().mouseReleaseEvent(event)

    def update_scaled_pixmap(self) -> None:
        if self.original_pixmap is None or self.original_pixmap.isNull():
            return
        scaled = self.original_pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def show_overlay(self, position: QPoint) -> None:
        self.close_overlay()
        if self.original_pixmap is None:
            return
        screen = QApplication.screenAt(position) or self.screen()
        available = screen.availableGeometry() if screen else None
        pixmap = self.original_pixmap
        if available is not None:
            max_size = available.size() * 0.95
            if pixmap.width() > max_size.width() or pixmap.height() > max_size.height():
                pixmap = pixmap.scaled(
                    max_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )

        overlay = QLabel()
        overlay.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        overlay.setAttribute(Qt.WA_DeleteOnClose)
        overlay.setPixmap(pixmap)
        overlay.adjustSize()
        overlay_position = position + QPoint(12, 12)
        if available is not None:
            overlay_position.setX(
                min(
                    max(overlay_position.x(), available.left()),
                    available.right() - overlay.width() + 1,
                )
            )
            overlay_position.setY(
                min(
                    max(overlay_position.y(), available.top()),
                    available.bottom() - overlay.height() + 1,
                )
            )
        overlay.move(overlay_position)
        overlay.mouseReleaseEvent = lambda event: overlay.close()
        overlay.show()
        self.overlay = overlay

    def close_overlay(self) -> None:
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None


class UntappdTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict] = []
        self.beer_groups: list[dict] = []
        self.brewery_groups: list[dict] = []
        self.venue_groups: list[dict] = []
        self.had_counts: dict[str, int] = {}
        self.had_indexes: dict[str, int] = {}
        self.checkin_indexes: dict[str, int] = {}
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
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.Monospace)
        self.detail_text.setFont(mono)
        self.photo_label = PhotoPreviewLabel()
        self.beer_detail_text = QPlainTextEdit()
        self.beer_detail_text.setReadOnly(True)
        self.beer_detail_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.beer_detail_text.setFont(mono)
        self.brewery_detail_text = QPlainTextEdit()
        self.brewery_detail_text.setReadOnly(True)
        self.brewery_detail_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.brewery_detail_text.setFont(mono)
        self.venue_detail_text = QPlainTextEdit()
        self.venue_detail_text.setReadOnly(True)
        self.venue_detail_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.venue_detail_text.setFont(mono)
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
        self.rebuild_had_counts()
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

    def rebuild_had_counts(self) -> None:
        counts: dict[str, int] = {}
        indexes: dict[str, int] = {}
        checkin_indexes: dict[str, int] = {}
        sorted_entries = sorted(
            self.entries,
            key=lambda item: self.entry_created_dt(item) or datetime.min,
        )
        for checkin_index, entry in enumerate(sorted_entries, start=1):
            key = self.beer_key(entry)
            counts[key] = counts.get(key, 0) + 1
            indexes[self.entry_key(entry)] = counts[key]
            checkin_indexes[self.entry_key(entry)] = checkin_index
        self.had_counts = counts
        self.had_indexes = indexes
        self.checkin_indexes = checkin_indexes

    def populate_table(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        for entry in self.entries:
            created_dt = self.entry_created_dt(entry)
            created_text = created_dt.strftime("%Y-%m-%d %H:%M") if created_dt else "-"
            rating_value = untappd.parse_rating(entry)
            had_index = self.had_index(entry)
            checkin_index = self.checkin_index(entry)
            row = [
                QStandardItem(created_text),
                QStandardItem(str(checkin_index)),
                QStandardItem(untappd.normalize_text(entry.get("brewery_name")) or "-"),
                QStandardItem(untappd.normalize_text(entry.get("beer_name")) or "-"),
                QStandardItem(self.abv_table_text(entry)),
                QStandardItem(untappd.normalize_text(entry.get("beer_type")) or "-"),
                QStandardItem(untappd.display_rating(entry)),
                QStandardItem(str(had_index)),
            ]
            sort_values = [
                created_dt.timestamp() if created_dt else 0,
                checkin_index,
                untappd.normalize_text(entry.get("brewery_name")).lower(),
                untappd.normalize_text(entry.get("beer_name")).lower(),
                self.abv_sort_value(entry),
                untappd.normalize_text(entry.get("beer_type")).lower(),
                rating_value if rating_value is not None else -1,
                had_index,
            ]
            search_blob = self.entry_search_blob(entry)
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
        self.beer_groups = self.build_beer_groups()
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
                QStandardItem(self.abv_table_text(group["entries"][0])),
                QStandardItem(group["beer_type"]),
                QStandardItem(self.mean_rating_text(group["ratings"])),
                QStandardItem(str(len(group["entries"]))),
            ]
            sort_values = [
                group["brewery"].lower(),
                group["beer"].lower(),
                first_dt.timestamp() if first_dt else 0,
                latest_dt.timestamp() if latest_dt else 0,
                self.abv_sort_value(group["entries"][0]),
                group["beer_type"].lower(),
                self.mean_rating_value(group["ratings"]),
                len(group["entries"]),
            ]
            search_blob = self.beer_search_blob(group)
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
        self.brewery_groups = self.build_brewery_groups()
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
                QStandardItem(self.mean_rating_text(group["ratings"])),
                QStandardItem(str(group["unique_beers"])),
                QStandardItem(str(len(group["entries"]))),
            ]
            sort_values = [
                group["brewery"].lower(),
                group["country"].lower(),
                first_dt.timestamp() if first_dt else 0,
                latest_dt.timestamp() if latest_dt else 0,
                self.mean_rating_value(group["ratings"]),
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
        self.venue_groups = self.build_venue_groups()
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
                QStandardItem(self.mean_rating_text(group["ratings"])),
                QStandardItem(str(group["unique_beers"])),
                QStandardItem(str(len(group["entries"]))),
            ]
            sort_values = [
                group["venue"].lower(),
                group["city"].lower(),
                group["country"].lower(),
                first_dt.timestamp() if first_dt else 0,
                latest_dt.timestamp() if latest_dt else 0,
                self.mean_rating_value(group["ratings"]),
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
        search_blob = self.aggregate_search_blob(group)
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

    def beer_key(self, entry: dict) -> str:
        bid = untappd.normalize_text(entry.get("bid"))
        if bid:
            return f"bid:{bid}"
        beer = untappd.normalize_text(entry.get("beer_name")).lower()
        brewery = untappd.normalize_text(entry.get("brewery_name")).lower()
        return f"name:{brewery}|{beer}"

    def brewery_key(self, entry: dict) -> str:
        brewery_id = untappd.normalize_text(entry.get("brewery_id"))
        if brewery_id:
            return f"brewery:{brewery_id}"
        brewery = untappd.normalize_text(entry.get("brewery_name")).lower()
        country = untappd.normalize_text(entry.get("brewery_country")).lower()
        return f"name:{country}|{brewery}"

    def venue_key(self, entry: dict) -> str:
        venue = untappd.normalize_text(entry.get("venue_name"))
        purchase_venue = untappd.normalize_text(entry.get("purchase_venue"))
        if not venue and not purchase_venue:
            return ""
        city = untappd.normalize_text(entry.get("venue_city")).lower()
        country = untappd.normalize_text(entry.get("venue_country")).lower()
        return f"venue:{country}|{city}|{(venue or purchase_venue).lower()}"

    def entry_key(self, entry: dict) -> str:
        checkin_id = untappd.normalize_text(entry.get("checkin_id"))
        if checkin_id:
            return f"checkin:{checkin_id}"
        created = untappd.normalize_text(entry.get("created_at"))
        return f"fallback:{self.beer_key(entry)}|{created}"

    def had_count(self, entry: dict) -> int:
        return self.had_counts.get(self.beer_key(entry), 0)

    def had_index(self, entry: dict) -> int:
        return self.had_indexes.get(self.entry_key(entry), 0)

    def checkin_index(self, entry: dict) -> int:
        return self.checkin_indexes.get(self.entry_key(entry), 0)

    def build_beer_groups(self) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for entry in self.entries:
            grouped.setdefault(self.beer_key(entry), []).append(entry)

        groups: list[dict] = []
        for key, entries in grouped.items():
            sorted_entries = sorted(
                entries,
                key=lambda item: self.entry_created_dt(item) or datetime.min,
            )
            first = sorted_entries[0]
            latest = sorted_entries[-1]
            ratings = [
                rating
                for entry in sorted_entries
                if (rating := untappd.parse_rating(entry)) is not None
            ]
            groups.append(
                {
                    "key": key,
                    "entries": sorted_entries,
                    "beer": untappd.normalize_text(first.get("beer_name")) or "-",
                    "brewery": untappd.normalize_text(first.get("brewery_name")) or "-",
                    "beer_type": untappd.normalize_text(first.get("beer_type")) or "-",
                    "first_dt": self.entry_created_dt(first),
                    "latest_dt": self.entry_created_dt(latest),
                    "ratings": ratings,
                }
            )
        return sorted(
            groups,
            key=lambda item: item["latest_dt"] or datetime.min,
            reverse=True,
        )

    def build_brewery_groups(self) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for entry in self.entries:
            grouped.setdefault(self.brewery_key(entry), []).append(entry)

        groups: list[dict] = []
        for key, entries in grouped.items():
            sorted_entries = sorted(
                entries,
                key=lambda item: self.entry_created_dt(item) or datetime.min,
            )
            first = sorted_entries[0]
            latest = sorted_entries[-1]
            ratings = [
                rating
                for entry in sorted_entries
                if (rating := untappd.parse_rating(entry)) is not None
            ]
            groups.append(
                {
                    "key": key,
                    "entries": sorted_entries,
                    "brewery": untappd.normalize_text(first.get("brewery_name")) or "-",
                    "city": untappd.normalize_text(first.get("brewery_city")) or "-",
                    "state": untappd.normalize_text(first.get("brewery_state")) or "-",
                    "country": untappd.normalize_text(first.get("brewery_country"))
                    or "-",
                    "first_dt": self.entry_created_dt(first),
                    "latest_dt": self.entry_created_dt(latest),
                    "ratings": ratings,
                    "unique_beers": len({self.beer_key(entry) for entry in entries}),
                }
            )
        return sorted(
            groups,
            key=lambda item: item["latest_dt"] or datetime.min,
            reverse=True,
        )

    def build_venue_groups(self) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for entry in self.entries:
            key = self.venue_key(entry)
            if key:
                grouped.setdefault(key, []).append(entry)

        groups: list[dict] = []
        for key, entries in grouped.items():
            sorted_entries = sorted(
                entries,
                key=lambda item: self.entry_created_dt(item) or datetime.min,
            )
            first = sorted_entries[0]
            latest = sorted_entries[-1]
            ratings = [
                rating
                for entry in sorted_entries
                if (rating := untappd.parse_rating(entry)) is not None
            ]
            groups.append(
                {
                    "key": key,
                    "entries": sorted_entries,
                    "venue": (
                        untappd.normalize_text(first.get("venue_name"))
                        or untappd.normalize_text(first.get("purchase_venue"))
                        or "-"
                    ),
                    "city": untappd.normalize_text(first.get("venue_city")) or "-",
                    "state": untappd.normalize_text(first.get("venue_state")) or "-",
                    "country": untappd.normalize_text(first.get("venue_country"))
                    or "-",
                    "lat": untappd.normalize_text(first.get("venue_lat")),
                    "lng": untappd.normalize_text(first.get("venue_lng")),
                    "first_dt": self.entry_created_dt(first),
                    "latest_dt": self.entry_created_dt(latest),
                    "ratings": ratings,
                    "unique_beers": len({self.beer_key(entry) for entry in entries}),
                    "unique_breweries": len(
                        {self.brewery_key(entry) for entry in entries}
                    ),
                }
            )
        return sorted(
            groups,
            key=lambda item: item["latest_dt"] or datetime.min,
            reverse=True,
        )

    def mean_rating_value(self, ratings: list[float]) -> float:
        if not ratings:
            return -1.0
        return sum(ratings) / len(ratings)

    def mean_rating_text(self, ratings: list[float]) -> str:
        if not ratings:
            return "-"
        return f"{self.mean_rating_value(ratings):.2f}".rstrip("0").rstrip(".")

    def beer_search_blob(self, group: dict) -> str:
        fields = [
            group["brewery"],
            group["beer"],
            group["beer_type"],
            self.abv_table_text(group["entries"][0]),
            self.mean_rating_text(group["ratings"]),
            str(len(group["entries"])),
        ]
        for entry in group["entries"]:
            fields.extend(
                [
                    untappd.normalize_text(entry.get("created_at")),
                    untappd.normalize_text(entry.get("venue_name")),
                    untappd.normalize_text(entry.get("purchase_venue")),
                    untappd.normalize_text(entry.get("venue_country")),
                    untappd.normalize_text(entry.get("brewery_country")),
                    untappd.normalize_text(entry.get("comment")),
                    untappd.normalize_text(entry.get("flavor_profiles")),
                ]
            )
        return "\n".join(field for field in fields if field)

    def aggregate_search_blob(self, group: dict) -> str:
        fields = [
            str(value)
            for key, value in group.items()
            if key not in {"entries", "ratings"} and value not in (None, "")
        ]
        for entry in group["entries"]:
            fields.extend(
                [
                    untappd.normalize_text(entry.get("created_at")),
                    untappd.normalize_text(entry.get("beer_name")),
                    untappd.normalize_text(entry.get("brewery_name")),
                    untappd.normalize_text(entry.get("beer_type")),
                    untappd.display_rating(entry),
                    untappd.normalize_text(entry.get("venue_name")),
                    untappd.normalize_text(entry.get("purchase_venue")),
                    untappd.normalize_text(entry.get("comment")),
                ]
            )
        return "\n".join(field for field in fields if field)

    def abv_table_text(self, entry: dict) -> str:
        abv = untappd.normalize_text(entry.get("beer_abv"))
        if not abv:
            return "-"
        return f"{self.format_abv(abv)}%"

    def format_abv(self, value: str) -> str:
        try:
            return f"{float(value):.1f}"
        except ValueError:
            return untappd.format_float(value)

    def abv_sort_value(self, entry: dict) -> float:
        try:
            return float(untappd.normalize_text(entry.get("beer_abv")))
        except ValueError:
            return -1.0

    def entry_created_dt(self, entry: dict) -> datetime | None:
        created = untappd.normalize_text(entry.get("created_at"))
        if not created:
            return None
        try:
            return untappd.parse_created_at(created)
        except Exception:
            return None

    def entry_search_blob(self, entry: dict) -> str:
        fields = [
            untappd.normalize_text(entry.get("created_at")),
            str(self.checkin_index(entry)),
            untappd.normalize_text(entry.get("beer_name")),
            self.abv_table_text(entry),
            untappd.normalize_text(entry.get("brewery_name")),
            untappd.normalize_text(entry.get("beer_type")),
            untappd.display_rating(entry),
            str(self.had_count(entry)),
            str(self.had_index(entry)),
            untappd.normalize_text(entry.get("venue_name")),
            untappd.normalize_text(entry.get("purchase_venue")),
            untappd.normalize_text(entry.get("brewery_country")),
            untappd.normalize_text(entry.get("venue_country")),
            untappd.normalize_text(entry.get("comment")),
            untappd.normalize_text(entry.get("flavor_profiles")),
            untappd.normalize_text(entry.get("serving_type")),
            untappd.normalize_text(entry.get("tagged_friends")),
            untappd.normalize_text(entry.get("checkin_id")),
        ]
        return "\n".join(field for field in fields if field)

    def render_details(self, entry: dict) -> None:
        ordered_fields = [
            ("Beer", "beer_name"),
            ("Brewery", "brewery_name"),
            ("Type", "beer_type"),
            ("Check-in", None),
            ("Total had with this check-in", None),
            ("Total Had", None),
            ("Your rating", "rating_score"),
            ("Global rating", "global_rating_score"),
            ("Weighted global rating", "global_weighted_rating_score"),
            ("ABV", "beer_abv"),
            ("IBU", "beer_ibu"),
            ("Created at", "created_at"),
            ("Venue", "venue_name"),
            ("Venue city", "venue_city"),
            ("Venue state", "venue_state"),
            ("Venue country", "venue_country"),
            ("Purchase venue", "purchase_venue"),
            ("Serving type", "serving_type"),
            ("Flavor profiles", "flavor_profiles"),
            ("Tagged friends", "tagged_friends"),
            ("Toasts", "total_toasts"),
            ("Comments", "total_comments"),
            ("Brewery city", "brewery_city"),
            ("Brewery state", "brewery_state"),
            ("Brewery country", "brewery_country"),
            ("Venue lat", "venue_lat"),
            ("Venue lng", "venue_lng"),
            ("Check-in ID", "checkin_id"),
            ("Beer ID", "bid"),
            ("Brewery ID", "brewery_id"),
            ("Check-in URL", "checkin_url"),
            ("Beer URL", "beer_url"),
            ("Brewery URL", "brewery_url"),
            ("Photo URL", "photo_url"),
        ]

        lines: list[str] = []
        for label, key in ordered_fields:
            if key is None:
                if label == "Check-in":
                    lines.append(f"{label}: {self.checkin_index(entry)}")
                elif label == "Total had with this check-in":
                    lines.append(f"{label}: {self.had_index(entry)}")
                else:
                    lines.append(f"{label}: {self.had_count(entry)}")
                continue
            value = entry.get(key)
            if value in (None, ""):
                continue
            lines.append(f"{label}: {untappd.format_float(value)}")

        comment = untappd.normalize_text(entry.get("comment"))
        if comment:
            lines.extend(["", "Comment:", comment])

        previous_dates = [
            untappd.normalize_text(candidate.get("created_at"))
            for candidate in self.entries
            if self.beer_key(candidate) == self.beer_key(entry)
        ]
        if len(previous_dates) > 1:
            lines.extend(
                [
                    "",
                    "Had dates:",
                    *sorted(previous_dates, reverse=True),
                ]
            )

        self.detail_text.setPlainText("\n".join(lines))

    def render_beer_details(self, group: dict) -> None:
        entries = group["entries"]
        first = entries[0]
        lines = [
            f"Beer: {group['beer']}",
            f"Brewery: {group['brewery']}",
            f"Type: {group['beer_type']}",
            f"ABV: {self.abv_table_text(first)}",
            f"IBU: {untappd.format_float(first.get('beer_ibu'))}",
            f"Average rating: {self.mean_rating_text(group['ratings'])}",
            f"Rated check-ins: {len(group['ratings'])}",
            f"Total Had: {len(entries)}",
        ]
        if group["first_dt"] is not None:
            lines.append(
                f"Date First Had: {group['first_dt'].strftime('%Y-%m-%d %H:%M')}"
            )
        if group["latest_dt"] is not None:
            lines.append(
                f"Date Latest Had: {group['latest_dt'].strftime('%Y-%m-%d %H:%M')}"
            )
        for label, key in (
            ("Global rating", "global_rating_score"),
            ("Weighted global rating", "global_weighted_rating_score"),
            ("Brewery city", "brewery_city"),
            ("Brewery state", "brewery_state"),
            ("Brewery country", "brewery_country"),
            ("Beer URL", "beer_url"),
            ("Brewery URL", "brewery_url"),
        ):
            value = first.get(key)
            if value not in (None, ""):
                lines.append(f"{label}: {untappd.format_float(value)}")

        venue_counts: dict[str, int] = {}
        for entry in entries:
            venue = (
                untappd.normalize_text(entry.get("venue_name"))
                or untappd.normalize_text(entry.get("purchase_venue"))
                or "-"
            )
            venue_counts[venue] = venue_counts.get(venue, 0) + 1
        if venue_counts:
            top_venues = sorted(
                venue_counts.items(),
                key=lambda item: (-item[1], item[0].lower()),
            )[:5]
            lines.extend(
                [
                    "",
                    "Top venues:",
                    *[f"{count}  {venue}" for venue, count in top_venues],
                ]
            )

        lines.extend(["", "Check-ins:"])
        for entry in sorted(
            entries,
            key=lambda item: self.entry_created_dt(item) or datetime.min,
            reverse=True,
        ):
            venue = (
                untappd.normalize_text(entry.get("venue_name"))
                or untappd.normalize_text(entry.get("purchase_venue"))
                or "-"
            )
            parts = [
                untappd.normalize_text(entry.get("created_at")) or "-",
                f"venue={venue}",
                f"rating={untappd.display_rating(entry)}",
                f"check-in={self.checkin_index(entry)}",
                f"had={self.had_index(entry)}",
            ]
            serving = untappd.normalize_text(entry.get("serving_type"))
            if serving:
                parts.append(f"serving={serving}")
            toasts = untappd.normalize_text(entry.get("total_toasts"))
            if toasts:
                parts.append(f"toasts={toasts}")
            comment = untappd.normalize_text(entry.get("comment"))
            if comment:
                parts.append(f"comment={comment}")
            lines.append(" | ".join(parts))

        self.beer_detail_text.setPlainText("\n".join(lines))

    def top_counts(
        self, entries: list[dict], labeler, limit: int = 8
    ) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for entry in entries:
            label = labeler(entry)
            counts[label] = counts.get(label, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[
            :limit
        ]

    def checkin_summary_line(self, entry: dict) -> str:
        venue = (
            untappd.normalize_text(entry.get("venue_name"))
            or untappd.normalize_text(entry.get("purchase_venue"))
            or "-"
        )
        parts = [
            untappd.normalize_text(entry.get("created_at")) or "-",
            f"beer={untappd.normalize_text(entry.get('beer_name')) or '-'}",
            f"brewery={untappd.normalize_text(entry.get('brewery_name')) or '-'}",
            f"venue={venue}",
            f"rating={untappd.display_rating(entry)}",
            f"check-in={self.checkin_index(entry)}",
            f"had={self.had_index(entry)}",
        ]
        serving = untappd.normalize_text(entry.get("serving_type"))
        if serving:
            parts.append(f"serving={serving}")
        toasts = untappd.normalize_text(entry.get("total_toasts"))
        if toasts:
            parts.append(f"toasts={toasts}")
        comment = untappd.normalize_text(entry.get("comment"))
        if comment:
            parts.append(f"comment={comment}")
        return " | ".join(parts)

    def render_brewery_details(self, group: dict) -> None:
        entries = group["entries"]
        lines = [
            f"Brewery: {group['brewery']}",
            f"City: {group['city']}",
            f"State: {group['state']}",
            f"Country: {group['country']}",
            f"Average rating: {self.mean_rating_text(group['ratings'])}",
            f"Rated check-ins: {len(group['ratings'])}",
            f"Unique beers: {group['unique_beers']}",
            f"Total Had: {len(entries)}",
        ]
        if group["first_dt"] is not None:
            lines.append(
                f"Date First Had: {group['first_dt'].strftime('%Y-%m-%d %H:%M')}"
            )
        if group["latest_dt"] is not None:
            lines.append(
                f"Date Latest Had: {group['latest_dt'].strftime('%Y-%m-%d %H:%M')}"
            )
        first = entries[0]
        brewery_url = untappd.normalize_text(first.get("brewery_url"))
        if brewery_url:
            lines.append(f"Brewery URL: {brewery_url}")

        lines.extend(["", "Top beers:"])
        lines.extend(
            f"{count}  {name}"
            for name, count in self.top_counts(
                entries,
                lambda entry: (
                    untappd.normalize_text(entry.get("beer_name")) or "(unknown)"
                ),
            )
        )
        lines.extend(["", "Top styles:"])
        lines.extend(
            f"{count}  {name}"
            for name, count in self.top_counts(
                entries,
                lambda entry: (
                    untappd.normalize_text(entry.get("beer_type")) or "(unknown)"
                ),
            )
        )
        lines.extend(["", "Top venues:"])
        lines.extend(
            f"{count}  {name}"
            for name, count in self.top_counts(
                entries,
                lambda entry: (
                    untappd.normalize_text(entry.get("venue_name"))
                    or untappd.normalize_text(entry.get("purchase_venue"))
                    or "-"
                ),
            )
        )

        lines.extend(["", "Check-ins:"])
        for entry in sorted(
            entries,
            key=lambda item: self.entry_created_dt(item) or datetime.min,
            reverse=True,
        ):
            lines.append(self.checkin_summary_line(entry))
        self.brewery_detail_text.setPlainText("\n".join(lines))

    def render_venue_details(self, group: dict) -> None:
        entries = group["entries"]
        lines = [
            f"Venue: {group['venue']}",
            f"City: {group['city']}",
            f"State: {group['state']}",
            f"Country: {group['country']}",
            f"Average rating: {self.mean_rating_text(group['ratings'])}",
            f"Rated check-ins: {len(group['ratings'])}",
            f"Unique beers: {group['unique_beers']}",
            f"Unique breweries: {group['unique_breweries']}",
            f"Total Had: {len(entries)}",
        ]
        if group["first_dt"] is not None:
            lines.append(
                f"Date First Had: {group['first_dt'].strftime('%Y-%m-%d %H:%M')}"
            )
        if group["latest_dt"] is not None:
            lines.append(
                f"Date Latest Had: {group['latest_dt'].strftime('%Y-%m-%d %H:%M')}"
            )
        if group["lat"] and group["lng"]:
            lines.append(f"Location: {group['lat']}, {group['lng']}")

        lines.extend(["", "Top beers:"])
        lines.extend(
            f"{count}  {name}"
            for name, count in self.top_counts(
                entries,
                lambda entry: (
                    untappd.normalize_text(entry.get("beer_name")) or "(unknown)"
                ),
            )
        )
        lines.extend(["", "Top breweries:"])
        lines.extend(
            f"{count}  {name}"
            for name, count in self.top_counts(
                entries,
                lambda entry: (
                    untappd.normalize_text(entry.get("brewery_name")) or "(unknown)"
                ),
            )
        )
        lines.extend(["", "Top styles:"])
        lines.extend(
            f"{count}  {name}"
            for name, count in self.top_counts(
                entries,
                lambda entry: (
                    untappd.normalize_text(entry.get("beer_type")) or "(unknown)"
                ),
            )
        )

        lines.extend(["", "Check-ins:"])
        for entry in sorted(
            entries,
            key=lambda item: self.entry_created_dt(item) or datetime.min,
            reverse=True,
        ):
            lines.append(self.checkin_summary_line(entry))
        self.venue_detail_text.setPlainText("\n".join(lines))

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
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.Monospace)
        self.detail_text.setFont(mono)

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
        tabs.addTab(MessengerTab(), "Messenger")
        tabs.addTab(GoogleMailTab(), "Google Mail")
        tabs.addTab(UntappdTab(), "Untappd")
        tabs.addTab(RunkeeperTab(), "Runkeeper")
        self.setCentralWidget(tabs)

        about = QAction("About", self)
        about.triggered.connect(self.show_about)
        self.menuBar().addAction(about)

    def show_about(self) -> None:
        QMessageBox.information(
            self,
            "About Export Inspector",
            "Unified desktop wrapper around the Messenger, Google Mail, Untappd, and Runkeeper export tools.",
        )


def apply_style(app: QApplication) -> None:
    app.setStyleSheet(
        """
        QWidget {
          background: #f6f3ec;
          color: #1f2933;
          font-size: 13px;
        }
        QMainWindow, QTabWidget::pane, QGroupBox {
          background: #f6f3ec;
        }
        QGroupBox {
          border: 1px solid #d9d1c4;
          border-radius: 8px;
          margin-top: 10px;
          padding-top: 10px;
        }
        QGroupBox::title {
          subcontrol-origin: margin;
          left: 10px;
          padding: 0 4px;
          color: #6b7280;
        }
        QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
          background: #fffdf8;
          border: 1px solid #c9c0b2;
          border-radius: 6px;
          padding: 6px 8px;
        }
        QPushButton {
          background: #173f5f;
          color: white;
          border: none;
          border-radius: 6px;
          padding: 7px 12px;
        }
        QPushButton:hover {
          background: #215676;
        }
        QPushButton:disabled {
          background: #9ca3af;
        }
        QTabBar::tab {
          background: #ebe5da;
          border: 1px solid #d9d1c4;
          padding: 8px 14px;
          margin-right: 4px;
          border-top-left-radius: 6px;
          border-top-right-radius: 6px;
        }
        QTabBar::tab:selected {
          background: #fffdf8;
        }
        QLabel {
          background: transparent;
        }
        """
    )


def main() -> None:
    app = QApplication(sys.argv)
    apply_style(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
