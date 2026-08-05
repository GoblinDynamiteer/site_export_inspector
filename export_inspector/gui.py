from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from PySide6.QtCore import QDate, QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QAction, QFont, QTextCursor
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
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import show_messenger_chat


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMEZONE = "Europe/Stockholm"


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


def create_date_controls() -> tuple[QCheckBox, QDateEdit]:
    checkbox = QCheckBox("Enable")
    date_edit = QDateEdit()
    date_edit.setCalendarPopup(True)
    date_edit.setDisplayFormat("yyyy-MM-dd")
    date_edit.setDate(QDate.currentDate())
    date_edit.setEnabled(False)
    checkbox.toggled.connect(date_edit.setEnabled)
    return checkbox, date_edit


def messenger_search_blob(message: dict, timezone_name: str) -> str:
    values: list[str] = [
        show_messenger_chat.repair_text(message.get("sender_name", "")),
        show_messenger_chat.repair_text(message.get("content", "")),
        show_messenger_chat.format_swedish_datetime(message["timestamp_ms"], timezone_name),
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
        self.timezone_edit = line_edit(text=DEFAULT_TIMEZONE)
        self.filter_edit = line_edit("Live filter: sender, text, attachment ref, reaction…")
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
        path, _ = QFileDialog.getOpenFileName(self, "Select Messenger JSON", "", "JSON Files (*.json)")
        if path:
            self.path_edit.setText(path)

    def pick_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Messenger Folder")
        if path:
            self.path_edit.setText(path)

    def load_chat(self) -> None:
        raw_path = self.path_edit.text().strip()
        input_path: str | None = raw_path or None

        try:
            self.available_threads = show_messenger_chat.discover_threads(input_path)
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return

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
            self.messages, self.participants, self.paths = show_messenger_chat.load_exports(
                input_path,
                target_signature=signature,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return

        participants_text = " / ".join(self.participants) if self.participants else "(none)"
        self.info_label.setText(
            f"Files: {len(self.paths)}\nParticipants: {participants_text}\nMessages: {len(self.messages)}"
        )
        self.refresh_messages()

    def current_from_timestamp(self) -> int | None:
        if not self.from_enabled.isChecked():
            return None
        try:
            return show_messenger_chat.parse_from_date(iso_date(self.from_date), self.timezone_edit.text().strip() or DEFAULT_TIMEZONE)
        except Exception:
            return None

    def _message_search_blob(self, message: dict) -> str:
        return messenger_search_blob(
            message,
            self.timezone_edit.text().strip() or DEFAULT_TIMEZONE,
        )

    def filtered_messages(self) -> list[dict]:
        timezone_name = self.timezone_edit.text().strip() or DEFAULT_TIMEZONE
        from_timestamp = self.current_from_timestamp()
        filtered = show_messenger_chat.filter_messages_from(self.messages, from_timestamp)
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
                blocks.append(show_messenger_chat.format_gap(previous_timestamp_ms, current_timestamp))
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

    def start_module(self, args: list[str], working_directory: str | None = None) -> None:
        if self.process.state() != QProcess.NotRunning:
            QMessageBox.warning(self, "Busy", "A command is already running in this tab.")
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
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(data)
        self.output.moveCursor(QTextCursor.End)

    def _drain_stderr(self) -> None:
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
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

        self.index_output = line_edit(text="gmail_index.sqlite")
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
            "",
            "Mailbox files (*.mbox *.sqlite *.db *.sqlite3);;All files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def pick_index_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save SQLite index", self.index_output.text(), "SQLite (*.sqlite)")
        if path:
            self.index_output.setText(path)

    def run_current(self) -> None:
        input_path = self.path_edit.text().strip()
        if not input_path:
            QMessageBox.warning(self, "Missing input", "Select an .mbox or .sqlite file first.")
            return

        action = self.action_combo.currentText()
        args = [action, input_path]

        if action == "info":
            args.extend(["--timezone", self.timezone_edit.text().strip() or DEFAULT_TIMEZONE])
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
            args.extend(["--timezone", self.timezone_edit.text().strip() or DEFAULT_TIMEZONE, "--no-progress"])
        elif action == "show":
            args.append(str(self.show_index.value()))
            args.extend(["--timezone", self.timezone_edit.text().strip() or DEFAULT_TIMEZONE, "--no-progress"])
        elif action == "index":
            args.append(self.index_output.text().strip() or "gmail_index.sqlite")
            args.extend(["--max-body-chars", str(self.index_max_body.value()), "--no-progress"])
            if self.index_force.isChecked():
                args.append("--force")

        self.start_module(args)


class UntappdTab(ProcessTab):
    def __init__(self) -> None:
        super().__init__("untappd")
        self.path_edit = line_edit("Untappd export JSON")
        browse_input = QPushButton("Browse")
        browse_input.clicked.connect(self.pick_input)

        self.action_combo = QComboBox()
        self.action_combo.addItems(["info", "search", "show"])
        self.action_stack = QStackedWidget()
        self.action_combo.currentIndexChanged.connect(self.action_stack.setCurrentIndex)

        self.info_top = QSpinBox()
        self.info_top.setRange(1, 500)
        self.info_top.setValue(10)
        self.info_min_rated = QSpinBox()
        self.info_min_rated.setRange(1, 500)
        self.info_min_rated.setValue(3)
        self.info_beer_count = line_edit("Punk IPA")
        self.info_venue_count = line_edit("Ölstugan Gull-Olle")

        self.search_terms = line_edit("stout omnipollo")
        self.search_beer = line_edit()
        self.search_brewery = line_edit()
        self.search_type = line_edit()
        self.search_venue = line_edit()
        self.search_country = line_edit()
        self.search_after_enabled, self.search_after = create_date_controls()
        self.search_before_enabled, self.search_before = create_date_controls()
        self.search_min_rating = QDoubleSpinBox()
        self.search_min_rating.setRange(0.0, 5.0)
        self.search_min_rating.setDecimals(2)
        self.search_min_rating.setSpecialValueText("Any")
        self.search_max_rating = QDoubleSpinBox()
        self.search_max_rating.setRange(0.0, 5.0)
        self.search_max_rating.setDecimals(2)
        self.search_max_rating.setValue(5.0)
        self.search_sort = QComboBox()
        self.search_sort.addItems(["date-desc", "date-asc", "rating-desc", "rating-asc", "beer", "brewery"])
        self.search_any = QCheckBox("Match any term")
        self.search_limit = QSpinBox()
        self.search_limit.setRange(1, 5000)
        self.search_limit.setValue(20)

        self.show_identifier = line_edit("1")

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

        self.build_shell_layout(controls)

    def _build_info_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.addRow("Top rows", self.info_top)
        layout.addRow("Min ratings for top rated", self.info_min_rated)
        layout.addRow("Beer count", self.info_beer_count)
        layout.addRow("Venue count", self.info_venue_count)
        return page

    def _build_search_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.addRow("Terms", self.search_terms)
        layout.addRow("Beer filter", self.search_beer)
        layout.addRow("Brewery filter", self.search_brewery)
        layout.addRow("Type filter", self.search_type)
        layout.addRow("Venue filter", self.search_venue)
        layout.addRow("Country filter", self.search_country)

        after_row = QHBoxLayout()
        after_row.addWidget(self.search_after_enabled)
        after_row.addWidget(self.search_after)
        layout.addRow("After", after_row)

        before_row = QHBoxLayout()
        before_row.addWidget(self.search_before_enabled)
        before_row.addWidget(self.search_before)
        layout.addRow("Before", before_row)

        layout.addRow("Min rating", self.search_min_rating)
        layout.addRow("Max rating", self.search_max_rating)
        layout.addRow("Sort", self.search_sort)
        layout.addRow("Limit", self.search_limit)
        layout.addRow("", self.search_any)
        return page

    def _build_show_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.addRow("Identifier", self.show_identifier)
        return page

    def pick_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Untappd JSON", "", "JSON Files (*.json)")
        if path:
            self.path_edit.setText(path)

    def run_current(self) -> None:
        input_path = self.path_edit.text().strip()
        if not input_path:
            QMessageBox.warning(self, "Missing input", "Select an Untappd export JSON file first.")
            return

        action = self.action_combo.currentText()
        args = [action, input_path]
        if action == "info":
            args.extend(["--top", str(self.info_top.value())])
            args.extend(["--min-ratings-for-top-rated", str(self.info_min_rated.value())])
            beer_value = self.info_beer_count.text().strip()
            venue_value = self.info_venue_count.text().strip()
            if beer_value and venue_value:
                QMessageBox.warning(self, "Choose one", "Use either beer count or venue count, not both.")
                return
            if beer_value:
                args.extend(["--beer-count", beer_value])
            if venue_value:
                args.extend(["--venue-count", venue_value])
        elif action == "search":
            args.extend(split_terms(self.search_terms.text()))
            for flag, value in (
                ("--beer", self.search_beer.text().strip()),
                ("--brewery", self.search_brewery.text().strip()),
                ("--type", self.search_type.text().strip()),
                ("--venue", self.search_venue.text().strip()),
                ("--country", self.search_country.text().strip()),
            ):
                if value:
                    args.extend([flag, value])
            if self.search_after_enabled.isChecked():
                args.extend(["--after", iso_date(self.search_after)])
            if self.search_before_enabled.isChecked():
                args.extend(["--before", iso_date(self.search_before)])
            if self.search_min_rating.value() > 0:
                args.extend(["--min-rating", f"{self.search_min_rating.value():.2f}"])
            if self.search_max_rating.value() < 5.0:
                args.extend(["--max-rating", f"{self.search_max_rating.value():.2f}"])
            if self.search_any.isChecked():
                args.append("--any")
            args.extend(["--limit", str(self.search_limit.value()), "--sort", self.search_sort.currentText()])
        elif action == "show":
            identifier = self.show_identifier.text().strip()
            if not identifier:
                QMessageBox.warning(self, "Missing identifier", "Enter a search-result number or check-in id.")
                return
            args.append(identifier)

        self.start_module(args)


class RunkeeperTab(ProcessTab):
    def __init__(self) -> None:
        super().__init__("runkeeper")
        self.path_edit = line_edit("Runkeeper ZIP export or folder of ZIPs")
        browse_file = QPushButton("Browse ZIP")
        browse_file.clicked.connect(self.pick_input_file)
        browse_directory = QPushButton("Browse Folder")
        browse_directory.clicked.connect(self.pick_input_directory)

        self.action_combo = QComboBox()
        self.action_combo.addItems(["info", "search", "show", "map"])
        self.action_stack = QStackedWidget()
        self.action_combo.currentIndexChanged.connect(self.action_stack.setCurrentIndex)

        self.timezone_edit = line_edit(text=DEFAULT_TIMEZONE)
        self.info_top = QSpinBox()
        self.info_top.setRange(1, 500)
        self.info_top.setValue(10)

        self.search_terms = line_edit("walking")
        self.search_type = line_edit()
        self.search_after_enabled, self.search_after = create_date_controls()
        self.search_before_enabled, self.search_before = create_date_controls()
        self.search_min_distance = QDoubleSpinBox()
        self.search_min_distance.setRange(0.0, 10000.0)
        self.search_min_distance.setSpecialValueText("Any")
        self.search_max_distance = QDoubleSpinBox()
        self.search_max_distance.setRange(0.0, 10000.0)
        self.search_max_distance.setSpecialValueText("Any")
        self.search_sort = QComboBox()
        self.search_sort.addItems([
            "date-desc",
            "date-asc",
            "distance-desc",
            "distance-asc",
            "duration-desc",
            "duration-asc",
            "pace-asc",
            "pace-desc",
            "elevation-desc",
        ])
        self.search_limit = QSpinBox()
        self.search_limit.setRange(1, 5000)
        self.search_limit.setValue(20)

        self.show_identifier = line_edit("1")

        self.map_identifier = line_edit("1")
        self.map_output = line_edit("route.html")
        self.map_serve = QCheckBox("Serve over local HTTP")
        self.map_open = QCheckBox("Open in browser")
        self.map_port = QSpinBox()
        self.map_port.setRange(1024, 65535)
        self.map_port.setValue(8000)
        browse_map_output = QPushButton("Save As…")
        browse_map_output.clicked.connect(self.pick_map_output)

        controls = QVBoxLayout()
        source_box = QGroupBox("Source")
        source_layout = QGridLayout(source_box)
        source_layout.addWidget(QLabel("Path"), 0, 0)
        source_layout.addWidget(self.path_edit, 0, 1, 1, 2)
        source_layout.addWidget(browse_file, 0, 3)
        source_layout.addWidget(browse_directory, 0, 4)
        controls.addWidget(source_box)

        action_box = QGroupBox("Action")
        action_layout = QVBoxLayout(action_box)
        action_layout.addWidget(self.action_combo)
        action_layout.addWidget(self.action_stack)
        controls.addWidget(action_box)

        self.action_stack.addWidget(self._build_info_page())
        self.action_stack.addWidget(self._build_search_page())
        self.action_stack.addWidget(self._build_show_page())
        self.action_stack.addWidget(self._build_map_page(browse_map_output))

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
        layout.addRow("Type filter", self.search_type)

        after_row = QHBoxLayout()
        after_row.addWidget(self.search_after_enabled)
        after_row.addWidget(self.search_after)
        layout.addRow("After", after_row)

        before_row = QHBoxLayout()
        before_row.addWidget(self.search_before_enabled)
        before_row.addWidget(self.search_before)
        layout.addRow("Before", before_row)

        layout.addRow("Min distance km", self.search_min_distance)
        layout.addRow("Max distance km", self.search_max_distance)
        layout.addRow("Sort", self.search_sort)
        layout.addRow("Limit", self.search_limit)
        return page

    def _build_show_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.addRow("Identifier", self.show_identifier)
        return page

    def _build_map_page(self, browse_map_output: QPushButton) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.addRow("Identifier", self.map_identifier)
        output_row = QHBoxLayout()
        output_row.addWidget(self.map_output)
        output_row.addWidget(browse_map_output)
        layout.addRow("Output HTML", output_row)
        layout.addRow("Port", self.map_port)
        layout.addRow("", self.map_serve)
        layout.addRow("", self.map_open)
        return page

    def pick_input_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Runkeeper ZIP", "", "ZIP Files (*.zip)")
        if path:
            self.path_edit.setText(path)

    def pick_input_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Runkeeper ZIP folder")
        if path:
            self.path_edit.setText(path)

    def pick_map_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save route HTML", self.map_output.text(), "HTML Files (*.html)")
        if path:
            self.map_output.setText(path)

    def run_current(self) -> None:
        input_path = self.path_edit.text().strip()
        if not input_path:
            QMessageBox.warning(self, "Missing input", "Select a Runkeeper ZIP file or folder first.")
            return

        action = self.action_combo.currentText()
        args = [action, input_path]
        timezone = self.timezone_edit.text().strip() or DEFAULT_TIMEZONE
        if action == "info":
            args.extend(["--top", str(self.info_top.value()), "--timezone", timezone])
        elif action == "search":
            args.extend(split_terms(self.search_terms.text()))
            if self.search_type.text().strip():
                args.extend(["--type", self.search_type.text().strip()])
            if self.search_after_enabled.isChecked():
                args.extend(["--after", iso_date(self.search_after)])
            if self.search_before_enabled.isChecked():
                args.extend(["--before", iso_date(self.search_before)])
            if self.search_min_distance.value() > 0:
                args.extend(["--min-distance", f"{self.search_min_distance.value():.2f}"])
            if self.search_max_distance.value() > 0:
                args.extend(["--max-distance", f"{self.search_max_distance.value():.2f}"])
            args.extend(["--limit", str(self.search_limit.value()), "--sort", self.search_sort.currentText(), "--timezone", timezone])
        elif action == "show":
            identifier = self.show_identifier.text().strip()
            if not identifier:
                QMessageBox.warning(self, "Missing identifier", "Enter an activity index or GPX file name.")
                return
            args.extend([identifier, "--timezone", timezone])
        elif action == "map":
            identifier = self.map_identifier.text().strip()
            if not identifier:
                QMessageBox.warning(self, "Missing identifier", "Enter an activity index or GPX file name.")
                return
            args.extend([identifier, "--timezone", timezone])
            output_path = self.map_output.text().strip()
            if output_path:
                args.extend(["--output", output_path])
            if self.map_serve.isChecked():
                args.append("--serve")
            if self.map_open.isChecked():
                args.append("--open")
            args.extend(["--port", str(self.map_port.value())])

        self.start_module(args)


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
