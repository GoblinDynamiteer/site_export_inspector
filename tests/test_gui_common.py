"""Unit tests for the small GUI helpers shared by the tabs."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QDate

from export_inspector import gui
from export_inspector.gui import common


def test_settings_constants_and_location(qt_app, tmp_path) -> None:
    settings = common.app_settings()
    assert common.SETTINGS_ORG == "jk"
    assert common.SETTINGS_APP == "export_inspector"
    assert settings.organizationName() == "jk"
    assert settings.applicationName() == "export_inspector"
    assert settings.fileName().startswith(str(tmp_path))
    assert common.DEFAULT_TIMEZONE == "Europe/Stockholm"


def test_line_edit_sets_placeholder_and_text(qt_app) -> None:
    empty = common.line_edit("Filter mail")
    assert empty.placeholderText() == "Filter mail"
    assert empty.text() == ""

    filled = common.line_edit(text="Europe/Stockholm")
    assert filled.placeholderText() == ""
    assert filled.text() == "Europe/Stockholm"


def test_remember_and_read_text(qt_app) -> None:
    assert common.settings_text("tab/input_path") == ""
    assert common.settings_text("tab/input_path", "fallback") == "fallback"

    common.remember_text("tab/input_path", "  /data/export.json  ")
    assert common.settings_text("tab/input_path") == "/data/export.json"

    common.remember_text("tab/input_path", "   ")
    assert common.settings_text("tab/input_path") == "/data/export.json"


def test_dialog_start_path(qt_app, tmp_path) -> None:
    folder = tmp_path / "exports"
    folder.mkdir()
    file_path = folder / "checkins.json"
    file_path.write_text("[]", encoding="utf-8")

    assert common.dialog_start_path("missing/key") == ""

    common.remember_text("saved/dir", str(folder))
    assert common.dialog_start_path("saved/dir") == str(folder)

    common.remember_text("saved/file", str(file_path))
    assert common.dialog_start_path("saved/file") == str(folder)

    common.remember_text("saved/gone", str(tmp_path / "gone" / "deeper" / "x.json"))
    assert common.dialog_start_path("saved/gone", "fallback") == "fallback"

    # Current behaviour, pinned for the move: a bare file name fallback resolves to its
    # parent directory ".", not to the file name itself.
    assert common.dialog_start_path("missing/key", "gmail_index.sqlite") == "."


def test_date_controls_toggle_and_format(qt_app) -> None:
    checkbox, date_edit = gui.create_date_controls()
    assert checkbox.text() == "Enable"
    assert not checkbox.isChecked()
    assert not date_edit.isEnabled()
    assert date_edit.date() == QDate.currentDate()

    checkbox.setChecked(True)
    assert date_edit.isEnabled()
    date_edit.setDate(QDate(2022, 3, 4))
    assert gui.iso_date(date_edit) == "2022-03-04"
    checkbox.setChecked(False)
    assert not date_edit.isEnabled()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (10, "10th"),
        (11, "11th"), (12, "12th"), (13, "13th"), (20, "20th"), (21, "21st"),
        (22, "22nd"), (23, "23rd"), (101, "101st"), (111, "111th"), (112, "112th"),
    ],
)
def test_ordinal(value: int, expected: str) -> None:
    assert gui.ordinal(value) == expected


def test_common_does_not_import_other_gui_modules() -> None:
    """gui/common.py is the base every GUI module imports, so it must not import them back."""
    tree = ast.parse(Path(common.__file__).read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }
    assert not {name for name in imported if name and name.startswith("export_inspector")}
