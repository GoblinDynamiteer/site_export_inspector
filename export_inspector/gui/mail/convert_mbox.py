"""The Gmail "Convert mbox" window: index an .mbox file into SQLite in a worker thread."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from export_inspector import google_mail
from export_inspector.gui.common import (
    dialog_start_path,
    line_edit,
    remember_text,
    settings_text,
)

if TYPE_CHECKING:
    from export_inspector.gui import GoogleMailTab


@dataclass
class MboxConversionResult:
    mbox_path: Path
    index_path: Path
    message_count: int


class MboxConversionThread(QThread):
    progress_changed = Signal(int, int)
    conversion_finished = Signal(object)
    conversion_failed = Signal(str)

    def __init__(
        self,
        mbox_path: Path,
        index_path: Path,
        max_body_chars: int,
        overwrite: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mbox_path = mbox_path
        self.index_path = index_path
        self.max_body_chars = max_body_chars
        self.overwrite = overwrite

    def run(self) -> None:
        try:
            conn = google_mail.open_database(self.index_path, force=self.overwrite)
            try:
                message_count, stats = google_mail.index_mbox(
                    self.mbox_path,
                    conn,
                    max_body_chars=self.max_body_chars,
                    show_progress=False,
                    progress_callback=self.update_progress,
                )
                google_mail.write_index_metadata(
                    conn,
                    self.mbox_path,
                    message_count,
                    self.max_body_chars,
                    stats,
                )
                conn.commit()
            finally:
                conn.close()
        except (Exception, SystemExit) as exc:
            self.conversion_failed.emit(str(exc))
            return

        self.conversion_finished.emit(
            MboxConversionResult(self.mbox_path, self.index_path, message_count)
        )

    def update_progress(
        self, message_count: int, processed_bytes: int, total_bytes: int
    ) -> None:
        if total_bytes <= 0:
            progress_value = 1000
        else:
            progress_value = int((processed_bytes / total_bytes) * 1000)
        self.progress_changed.emit(message_count, min(progress_value, 1000))


class ConvertMboxWidget(QWidget):
    def __init__(self, gmail_tab: "GoogleMailTab") -> None:
        super().__init__(gmail_tab.window(), Qt.Window)
        self.gmail_tab = gmail_tab
        self.conversion_thread: MboxConversionThread | None = None
        self.setWindowTitle("Convert mbox")
        self.setMinimumWidth(620)

        self.path_edit = line_edit("Mailbox .mbox file")
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.pick_mbox)
        self.browse_button = browse_button

        convert_button = QPushButton("Convert")
        convert_button.clicked.connect(self.convert)
        self.convert_button = convert_button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        self.close_button = close_button

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_label = QLabel()
        self.status_label.setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        source_box = QGroupBox("Source")
        source_layout = QGridLayout(source_box)
        source_layout.addWidget(QLabel("Mbox file"), 0, 0)
        source_layout.addWidget(self.path_edit, 0, 1)
        source_layout.addWidget(browse_button, 0, 2)
        root.addWidget(source_box)
        root.addWidget(self.progress_bar)
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(close_button)
        actions.addWidget(convert_button)
        root.addLayout(actions)

        self.refresh_source_path()

    def refresh_source_path(self) -> None:
        source_path = self.gmail_tab.path_edit.text().strip()
        if not source_path:
            source_path = settings_text(
                "google_mail/convert_mbox_path",
                settings_text("google_mail/input_path"),
            )
        self.path_edit.setText(source_path)

    def pick_mbox(self) -> None:
        start_path = dialog_start_path("google_mail/convert_mbox_path")
        current_path = self.path_edit.text().strip()
        if current_path:
            path = Path(current_path).expanduser()
            if path.is_dir():
                start_path = str(path)
            elif path.parent.exists():
                start_path = str(path.parent)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select mbox file",
            start_path,
            "Mailbox files (*.mbox);;All files (*)",
        )
        if path:
            self.path_edit.setText(path)
            remember_text("google_mail/convert_mbox_path", path)

    def selected_mbox_path(self) -> Path | None:
        input_path = self.path_edit.text().strip()
        if not input_path:
            return None
        return Path(input_path).expanduser()

    def convert(self) -> None:
        mbox_path = self.selected_mbox_path()
        if mbox_path is None:
            QMessageBox.warning(self, "Missing input", "Select an .mbox file first.")
            return
        remember_text("google_mail/convert_mbox_path", str(mbox_path))
        self.gmail_tab.convert_mbox_to_sqlite(mbox_path, self)

    def start_conversion(
        self,
        mbox_path: Path,
        index_path: Path,
        max_body_chars: int,
        overwrite: bool,
    ) -> None:
        self.path_edit.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.convert_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Starting conversion...")
        self.status_label.setVisible(True)

        thread = MboxConversionThread(
            mbox_path,
            index_path,
            max_body_chars,
            overwrite,
            self,
        )
        thread.progress_changed.connect(self.update_progress)
        thread.conversion_finished.connect(self.finish_conversion)
        thread.conversion_failed.connect(self.fail_conversion)
        thread.finished.connect(thread.deleteLater)
        self.conversion_thread = thread
        thread.start()

    def update_progress(self, message_count: int, progress_value: int) -> None:
        self.progress_bar.setValue(progress_value)
        self.status_label.setText(f"Indexed {message_count} messages...")

    def finish_conversion(self, result: MboxConversionResult) -> None:
        self.conversion_thread = None
        self.reset_controls()
        remember_text("google_mail/convert_mbox_path", str(result.mbox_path))
        remember_text("google_mail/index_output", str(result.index_path))
        self.gmail_tab.path_edit.setText(str(result.index_path))
        remember_text("google_mail/input_path", str(result.index_path))
        QMessageBox.information(
            self,
            "Conversion complete",
            f"Indexed {result.message_count} messages into:\n{result.index_path}",
        )
        self.gmail_tab.load_mail()
        self.close()

    def fail_conversion(self, message: str) -> None:
        self.conversion_thread = None
        self.reset_controls()
        QMessageBox.critical(self, "Conversion failed", message)

    def reset_controls(self) -> None:
        self.path_edit.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.convert_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)

    def closeEvent(self, event: object) -> None:
        if self.conversion_thread is not None:
            QMessageBox.information(
                self,
                "Conversion running",
                "Wait for the conversion to finish before closing this window.",
            )
            event.ignore()
            return
        super().closeEvent(event)
