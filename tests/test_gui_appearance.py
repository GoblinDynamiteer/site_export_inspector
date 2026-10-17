from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTableView

from export_inspector import gui
from export_inspector.gui import appearance, common
from export_inspector.gui.appearance import (
    TEXT_SCALE_DEFAULT,
    TEXT_SCALE_MAX,
    TEXT_SCALE_STEP,
    AppearanceSettings,
    apply_appearance,
    detail_font,
    interface_font,
    load_appearance,
    monospace_families,
    save_appearance,
    system_font,
    use_detail_font,
)
from export_inspector.gui.settings_dialog import SettingsDialog


@pytest.fixture
def app(qt_app):
    return qt_app


def test_load_appearance_defaults_and_clamps(app) -> None:
    assert load_appearance() == AppearanceSettings()

    settings = common.app_settings()
    settings.setValue("appearance/text_scale", 999)
    settings.setValue("appearance/detail_point_size", "not a number")
    settings.setValue("appearance/detail_family", "DejaVu Sans Mono")
    settings.sync()

    loaded = load_appearance()
    assert loaded.text_scale == TEXT_SCALE_MAX
    assert loaded.detail_point_size == 0
    assert loaded.detail_family == "DejaVu Sans Mono"


def test_save_appearance_round_trip(app) -> None:
    appearance = AppearanceSettings(text_scale=150, detail_family="Mono X", detail_point_size=14)
    save_appearance(appearance)
    assert load_appearance() == appearance


def test_interface_and_detail_fonts_scale(app) -> None:
    base = system_font().pointSizeF()
    scaled = AppearanceSettings(text_scale=150)

    assert interface_font(scaled).pointSizeF() == pytest.approx(base * 1.5)
    assert detail_font(scaled).pointSizeF() == pytest.approx(base * 1.5)

    fixed = AppearanceSettings(text_scale=150, detail_family="Mono X", detail_point_size=14)
    assert detail_font(fixed).pointSize() == 14
    assert detail_font(fixed).family() == "Mono X"


def test_monospace_families_skip_proportional_and_private(app, monkeypatch) -> None:
    class FakeFontDatabase:
        @staticmethod
        def families() -> list[str]:
            return ["Zeta Mono", "Proportional Sans", ".Private Mono", "Alpha Mono"]

        @staticmethod
        def isFixedPitch(family: str) -> bool:
            return "Mono" in family

        @staticmethod
        def isPrivateFamily(family: str) -> bool:
            return family.startswith(".")

    monkeypatch.setattr(appearance, "QFontDatabase", FakeFontDatabase)

    assert monospace_families() == ["Alpha Mono", "Zeta Mono"]


def test_apply_appearance_updates_app_detail_panes_and_tables(app) -> None:
    detail = QPlainTextEdit()
    use_detail_font(detail)
    table = QTableView()
    base = system_font().pointSizeF()

    apply_appearance(AppearanceSettings(text_scale=200, detail_point_size=20))

    assert QApplication.font().pointSizeF() == pytest.approx(base * 2)
    assert detail.font().pointSize() == 20
    expected_rows = QFontMetrics(QApplication.font()).height() + 10
    assert table.verticalHeader().defaultSectionSize() >= expected_rows


def test_settings_dialog_apply_saves_and_applies(app) -> None:
    dialog = SettingsDialog()
    assert [dialog.categories.item(i).text() for i in range(dialog.categories.count())] == [
        "Appearance",
        "Detail panes",
    ]

    dialog.scale_slider.setValue(130)
    dialog.detail_size.setValue(16)
    assert load_appearance() == AppearanceSettings()

    dialog.apply()
    assert load_appearance() == AppearanceSettings(text_scale=130, detail_point_size=16)
    base = system_font().pointSizeF()
    assert QApplication.font().pointSizeF() == pytest.approx(base * 1.3)

    dialog.restore_defaults()
    assert dialog.pending() == AppearanceSettings()


def test_main_window_text_scale_steps(app) -> None:
    window = gui.MainWindow()

    window.step_text_scale(TEXT_SCALE_STEP)
    assert load_appearance().text_scale == TEXT_SCALE_DEFAULT + TEXT_SCALE_STEP

    for _ in range(50):
        window.step_text_scale(TEXT_SCALE_STEP)
    assert load_appearance().text_scale == TEXT_SCALE_MAX

    window.step_text_scale(0)
    assert load_appearance().text_scale == TEXT_SCALE_DEFAULT


def test_appearance_imports_only_common_from_gui() -> None:
    """Tabs and dialogs import gui/appearance.py, so it may only build on gui/common.py."""
    tree = ast.parse(Path(appearance.__file__).read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }
    assert {name for name in imported if name and name.startswith("export_inspector")} == {
        "export_inspector.gui.common"
    }
