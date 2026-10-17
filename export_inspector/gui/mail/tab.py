"""The Google Mail tab: load an .mbox or SQLite index, filter it and show messages."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from export_inspector import google_mail
from export_inspector.gui.appearance import use_detail_font
from export_inspector.gui.common import (
    DEFAULT_TIMEZONE,
    dialog_start_path,
    line_edit,
    remember_text,
    settings_text,
)
from export_inspector.gui.mail.convert_mbox import ConvertMboxWidget
from export_inspector.gui.mail.models import (
    GMAIL_RECORD_ROLE,
    GMAIL_SEARCH_ROLE,
    GMAIL_SORT_ROLE,
    GmailFilterProxy,
    GmailRecord,
)


class GoogleMailTab(QWidget):
    """Tab that lists the messages of an .mbox file or SQLite index and shows one in full."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[GmailRecord] = []
        self.selected_record: GmailRecord | None = None
        self.convert_widget: ConvertMboxWidget | None = None

        self.path_edit = line_edit("Mailbox .mbox or SQLite index")
        self.path_edit.setText(settings_text("google_mail/input_path"))
        browse_input = QPushButton("Browse")
        browse_input.clicked.connect(self.pick_input)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self.load_mail)
        self.timezone_edit = line_edit(text=DEFAULT_TIMEZONE)
        self.filter_edit = line_edit("Filter mail")
        self.filter_edit.textChanged.connect(self.apply_filter)
        self.status_label = QLabel("0/0")
        self.index_max_body = QSpinBox()
        self.index_max_body.setRange(1000, 1_000_000)
        self.index_max_body.setValue(google_mail.DEFAULT_MAX_BODY_CHARS)

        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels(["Datetime", "Sender", "Title"])
        self.proxy_model = GmailFilterProxy()
        self.proxy_model.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self.select_mail)

        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        use_detail_font(self.detail_text)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        source_box = QGroupBox("Source")
        source_layout = QGridLayout(source_box)
        source_layout.addWidget(QLabel("Path"), 0, 0)
        source_layout.addWidget(self.path_edit, 0, 1, 1, 2)
        source_layout.addWidget(browse_input, 0, 3)
        source_layout.addWidget(load_button, 0, 4)
        source_layout.addWidget(QLabel("Timezone"), 1, 0)
        source_layout.addWidget(self.timezone_edit, 1, 1)
        source_layout.addWidget(QLabel("Max body chars in SQLite"), 1, 2)
        source_layout.addWidget(self.index_max_body, 1, 3)
        root.addWidget(source_box)

        filter_box = QGroupBox("Filter")
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.addWidget(self.filter_edit)
        filter_layout.addWidget(self.status_label)
        root.addWidget(filter_box)

        table_box = QGroupBox("Mail")
        table_layout = QVBoxLayout(table_box)
        table_layout.addWidget(self.table)
        root.addWidget(table_box, 2)

        detail_box = QGroupBox("Contents")
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.addWidget(self.detail_text)
        root.addWidget(detail_box, 1)

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

    def load_mail(self) -> None:
        """Load the records from the path field, warning in a dialog if loading fails."""
        input_path = self.path_edit.text().strip()
        if not input_path:
            QMessageBox.warning(
                self, "Missing input", "Select an .mbox or .sqlite file first."
            )
            return

        path = Path(input_path).expanduser()
        if not path.exists():
            QMessageBox.warning(self, "Missing input", f"File not found: {path}")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if google_mail.detect_sqlite(path):
                records = self.load_sqlite_records(path)
            else:
                records = self.load_mbox_records(path)
        except (Exception, SystemExit) as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        remember_text("google_mail/input_path", str(path))
        self.records = records
        self.populate_table()
        self.apply_filter()
        if self.proxy_model.rowCount() > 0:
            self.table.selectRow(0)
        else:
            self.selected_record = None
            self.detail_text.setPlainText("No mail found.")

    def open_convert_widget(self) -> None:
        """Show the "Convert mbox" window, creating it on first use."""
        if self.convert_widget is None:
            self.convert_widget = ConvertMboxWidget(self)
        self.convert_widget.refresh_source_path()
        self.convert_widget.show()
        self.convert_widget.raise_()
        self.convert_widget.activateWindow()

    def convert_to_sqlite(self) -> None:
        self.open_convert_widget()

    def convert_mbox_to_sqlite(
        self, mbox_path: Path, convert_widget: ConvertMboxWidget
    ) -> None:
        """Ask where to save the index, then start converting `mbox_path` in `convert_widget`.

        Does nothing (after a dialog) if the file is missing, already SQLite, the save
        dialog is cancelled or the user declines to overwrite an existing index.
        """
        mbox_path = mbox_path.expanduser()
        if not mbox_path.exists():
            QMessageBox.warning(self, "Missing input", f"File not found: {mbox_path}")
            return
        if google_mail.detect_sqlite(mbox_path):
            QMessageBox.information(
                self, "Already SQLite", "The selected source is already a SQLite index."
            )
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save SQLite index",
            dialog_start_path("google_mail/index_output", "gmail_index.sqlite"),
            "SQLite (*.sqlite);;All files (*)",
        )
        if not output_path:
            return

        index_path = Path(output_path).expanduser()
        overwrite = False
        if index_path.exists():
            answer = QMessageBox.question(
                self,
                "Overwrite index?",
                f"Replace existing SQLite index?\n{index_path}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            overwrite = True

        convert_widget.start_conversion(
            mbox_path,
            index_path,
            self.index_max_body.value(),
            overwrite,
        )

    def load_sqlite_records(self, path: Path) -> list[GmailRecord]:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT
                    message_index,
                    date_utc,
                    date_unix,
                    sender,
                    recipients,
                    subject,
                    labels,
                    thread_id,
                    snippet,
                    source_path,
                    source_offset
                FROM messages
                ORDER BY date_unix DESC, message_index DESC
                """
            ).fetchall()
        finally:
            conn.close()

        records: list[GmailRecord] = []
        timezone = self.timezone_edit.text().strip() or DEFAULT_TIMEZONE
        for row in rows:
            date_text = "n/a"
            if row["date_utc"]:
                date_text = google_mail.format_date(
                    datetime.fromisoformat(row["date_utc"]), timezone
                )
            records.append(
                GmailRecord(
                    message_index=int(row["message_index"]),
                    source_path=row["source_path"] or str(path),
                    source_offset=row["source_offset"],
                    date_text=date_text,
                    date_sort=int(row["date_unix"] or 0),
                    sender=row["sender"] or "unknown",
                    recipients=row["recipients"] or "",
                    subject=row["subject"] or "(no subject)",
                    labels=row["labels"] or "",
                    thread_id=row["thread_id"] or "",
                    snippet=row["snippet"] or "",
                )
            )
        return records

    def load_mbox_records(self, path: Path) -> list[GmailRecord]:
        records: list[GmailRecord] = []
        current_header_lines: list[bytes] = []
        current_headers: dict[str, str] = {}
        in_headers = False
        have_message = False
        message_index = 0
        message_start_offset = 0

        def finalize_current() -> None:
            nonlocal message_index, current_headers
            if not have_message:
                return
            if not current_headers and current_header_lines:
                current_headers = google_mail.parse_headers(current_header_lines)
            message_index += 1
            records.append(
                self.record_from_headers(
                    message_index,
                    path,
                    message_start_offset,
                    current_headers,
                )
            )

        with path.open("rb") as handle:
            while True:
                line_offset = handle.tell()
                raw_line = handle.readline()
                if not raw_line:
                    break
                if raw_line.startswith(b"From "):
                    finalize_current()
                    current_header_lines = []
                    current_headers = {}
                    in_headers = True
                    have_message = True
                    message_start_offset = line_offset
                    continue

                if not have_message:
                    continue
                if in_headers:
                    if raw_line in (b"\n", b"\r\n"):
                        current_headers = google_mail.parse_headers(current_header_lines)
                        in_headers = False
                        continue
                    current_header_lines.append(raw_line)

        finalize_current()
        records.sort(
            key=lambda record: (record.date_sort, record.message_index),
            reverse=True,
        )
        return records

    def record_from_headers(
        self,
        message_index: int,
        path: Path,
        source_offset: int,
        headers: dict[str, str],
    ) -> GmailRecord:
        parsed_date = google_mail.parse_date(headers.get("date"))
        if parsed_date is not None:
            date_sort = int(parsed_date.timestamp())
            date_text = google_mail.format_date(
                parsed_date, self.timezone_edit.text().strip() or DEFAULT_TIMEZONE
            )
        else:
            date_sort = 0
            date_text = "n/a"
        return GmailRecord(
            message_index=message_index,
            source_path=str(path),
            source_offset=source_offset,
            date_text=date_text,
            date_sort=date_sort,
            sender=google_mail.decode_header_value(headers.get("from")) or "unknown",
            recipients=google_mail.extract_addresses(
                headers.get("to", ""), headers.get("cc", ""), headers.get("bcc", "")
            ),
            subject=google_mail.decode_header_value(headers.get("subject"))
            or "(no subject)",
            labels=google_mail.decode_header_value(headers.get("x-gmail-labels")),
            thread_id=headers.get("x-gm-thrid", ""),
            snippet="",
        )

    def populate_table(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        for record in self.records:
            row = [
                QStandardItem(record.date_text),
                QStandardItem(record.sender),
                QStandardItem(record.subject),
            ]
            sort_values = [
                record.date_sort,
                record.sender.lower(),
                record.subject.lower(),
            ]
            search_blob = self.record_search_blob(record)
            for column, item in enumerate(row):
                item.setEditable(False)
                item.setData(record, GMAIL_RECORD_ROLE)
                item.setData(search_blob, GMAIL_SEARCH_ROLE)
                item.setData(sort_values[column], GMAIL_SORT_ROLE)
            self.model.appendRow(row)
        self.proxy_model.sort(0, Qt.DescendingOrder)

    def apply_filter(self) -> None:
        self.proxy_model.set_query(self.filter_edit.text())
        self.status_label.setText(f"{self.proxy_model.rowCount()}/{len(self.records)}")

    def select_mail(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self.selected_record = None
            self.detail_text.clear()
            return

        source_index = self.proxy_model.mapToSource(current)
        record = self.model.item(source_index.row(), 0).data(GMAIL_RECORD_ROLE)
        self.selected_record = record
        self.render_mail(record)

    def render_mail(self, record: GmailRecord) -> None:
        source_path = Path(record.source_path).expanduser()
        if not source_path.exists():
            self.detail_text.setPlainText(
                self.record_fallback_text(
                    record, f"Source mbox not found: {source_path}"
                )
            )
            return

        try:
            if record.source_offset is not None:
                headers, body_text = google_mail.load_message_from_offset(
                    source_path, int(record.source_offset)
                )
            else:
                headers, body_text = google_mail.load_message_from_mbox(
                    source_path, record.message_index, show_progress=False
                )
            text = google_mail.format_full_message(
                headers,
                body_text,
                self.timezone_edit.text().strip() or DEFAULT_TIMEZONE,
            )
        except SystemExit as exc:
            text = self.record_fallback_text(record, str(exc))
        except Exception as exc:
            text = self.record_fallback_text(
                record, f"Could not load message body: {exc}"
            )
        self.detail_text.setPlainText(text)

    def record_fallback_text(self, record: GmailRecord, reason: str) -> str:
        lines = [
            f"Date: {record.date_text}",
            f"From: {record.sender}",
        ]
        if record.recipients:
            lines.append(f"To: {record.recipients}")
        lines.append(f"Subject: {record.subject}")
        if record.labels:
            lines.append(f"Labels: {record.labels}")
        if record.thread_id:
            lines.append(f"Thread: {record.thread_id}")
        lines.extend(["", reason])
        if record.snippet:
            lines.extend(["", record.snippet])
        return "\n".join(lines)

    def record_search_blob(self, record: GmailRecord) -> str:
        return "\n".join(
            [
                record.date_text,
                record.sender,
                record.recipients,
                record.subject,
                record.labels,
                record.thread_id,
                record.snippet,
                str(record.message_index),
            ]
        )
