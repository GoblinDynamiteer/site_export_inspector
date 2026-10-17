"""The Messenger tab: load chat exports, pick a thread, filter and render its messages."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from export_inspector import messenger_chat
from export_inspector.gui.appearance import use_detail_font
from export_inspector.gui.common import (
    DEFAULT_TIMEZONE,
    dialog_start_path,
    line_edit,
    remember_text,
    settings_text,
)


def iso_date(date_edit: QDateEdit) -> str:
    """Return the date edit's date as `YYYY-MM-DD`."""
    return date_edit.date().toString("yyyy-MM-dd")


def create_date_controls() -> tuple[QCheckBox, QDateEdit]:
    """Return an "Enable" checkbox and a date edit (today) that the checkbox enables."""
    checkbox = QCheckBox("Enable")
    date_edit = QDateEdit()
    date_edit.setCalendarPopup(True)
    date_edit.setDisplayFormat("yyyy-MM-dd")
    date_edit.setDate(QDate.currentDate())
    date_edit.setEnabled(False)
    checkbox.toggled.connect(date_edit.setEnabled)
    return checkbox, date_edit


def messenger_search_blob(message: dict, timezone_name: str) -> str:
    """Return the lowercased text a filter matches against: sender, content, time,
    attachments and reactions."""
    values: list[str] = [
        messenger_chat.repair_text(message.get("sender_name", "")),
        messenger_chat.repair_text(message.get("content", "")),
        messenger_chat.format_swedish_datetime(
            message["timestamp_ms"], timezone_name
        ),
    ]
    values.extend(messenger_chat.describe_attachment(message))
    reactions = messenger_chat.describe_reactions(message)
    if reactions:
        values.append(reactions)
    return "\n".join(values).lower()


def render_message_block(message: dict, timezone_name: str) -> str:
    """Render one message as plain text with `messenger_chat.render_message` (no name
    colours or search highlighting)."""
    return "\n".join(messenger_chat.render_message(message, timezone_name, {}))


class MessengerTab(QWidget):
    """Tab that loads Messenger JSON exports, lists their threads and shows one filtered thread."""

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
        use_detail_font(self.viewer)

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
            self.available_threads = messenger_chat.discover_threads(input_path)
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
                f"{messenger_chat.signature_label(signature)}  ({len(sources)} source{'s' if len(sources) != 1 else ''})"
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
                messenger_chat.load_exports(
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
            return messenger_chat.parse_from_date(
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
        filtered = messenger_chat.filter_messages_from(
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
                >= messenger_chat.DEFAULT_GAP_SECONDS * 1000
            ):
                blocks.append(
                    messenger_chat.format_gap(
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
