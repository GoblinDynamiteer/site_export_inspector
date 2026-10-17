"""The main window: one tab per export source, plus the File/Tools menus and shortcuts."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QTabWidget

from export_inspector.gui.appearance import (
    TEXT_SCALE_DEFAULT,
    TEXT_SCALE_MAX,
    TEXT_SCALE_MIN,
    TEXT_SCALE_STEP,
    apply_appearance,
    load_appearance,
    save_appearance,
)
from export_inspector.gui.mail.tab import GoogleMailTab
from export_inspector.gui.messenger.tab import MessengerTab
from export_inspector.gui.runkeeper.tab import RunkeeperTab
from export_inspector.gui.settings_dialog import SettingsDialog
from export_inspector.gui.untappd.tab import UntappdTab


class MainWindow(QMainWindow):
    """Top-level window with the Messenger, Google Mail, Untappd and Runkeeper tabs,
    the File (Settings, Quit), Tools (Gmail → Convert mbox) and About menus, and the
    Ctrl++ / Ctrl+- / Ctrl+0 text scale shortcuts."""

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
