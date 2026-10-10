from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from tests.gui_snapshot import Snapshot  # noqa: E402


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        help="Rewrite tests/golden/*.txt from the current GUI output instead of comparing.",
    )


@pytest.fixture
def make_snapshot(request):
    """Return a factory for ``Snapshot`` objects that honours ``--update-golden``."""
    update = request.config.getoption("--update-golden")

    def factory(name: str, replacements: dict[str, str] | None = None) -> Snapshot:
        return Snapshot(name, replacements, update=update)

    return factory


@pytest.fixture
def qt_app(tmp_path):
    """Offscreen QApplication with QSettings redirected to a temporary directory.

    Uses IniFormat because ``QSettings.setPath`` only affects NativeFormat on Unix; on
    Windows and macOS the tests would otherwise touch the real registry/preferences.
    """
    from export_inspector import gui
    from export_inspector.gui import common

    settings_dir = tmp_path / "settings"
    previous_format = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(settings_dir))
    assert common.app_settings().fileName().startswith(str(settings_dir))
    application = QApplication.instance() or QApplication([])
    original = gui.system_font()
    yield application
    QApplication.setFont(original)
    QSettings.setDefaultFormat(previous_format)


@pytest.fixture
def message_boxes(monkeypatch):
    """Replace modal QMessageBox calls: errors and warnings fail the test, others are recorded."""
    calls: list[tuple[str, str, str]] = []

    def fail(kind):
        def handler(_parent, title, text, *args, **kwargs):
            pytest.fail(f"Unexpected QMessageBox.{kind}: {title}: {text}")

        return handler

    def record(kind, answer=None):
        def handler(_parent, title, text, *args, **kwargs):
            calls.append((kind, title, text))
            return answer

        return handler

    monkeypatch.setattr(QMessageBox, "critical", fail("critical"))
    monkeypatch.setattr(QMessageBox, "warning", fail("warning"))
    monkeypatch.setattr(QMessageBox, "information", record("information"))
    monkeypatch.setattr(QMessageBox, "question", record("question", QMessageBox.No))
    return calls
