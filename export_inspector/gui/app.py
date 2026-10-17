"""GUI startup: create the QApplication, apply the saved appearance and show the window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from export_inspector.gui.appearance import apply_appearance, load_appearance, system_font
from export_inspector.gui.main_window import MainWindow


def main() -> None:
    """Run the GUI until the window closes, then exit the process with Qt's exit code."""
    app = QApplication(sys.argv)
    system_font()
    window = MainWindow()
    apply_appearance(load_appearance())
    window.show()
    sys.exit(app.exec())
