from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTableView

from export_inspector import gui
from export_inspector.gui import common


@pytest.fixture
def app(qt_app):
    return qt_app


def test_load_appearance_defaults_and_clamps(app) -> None:
    assert gui.load_appearance() == gui.AppearanceSettings()

    settings = common.app_settings()
    settings.setValue("appearance/text_scale", 999)
    settings.setValue("appearance/detail_point_size", "not a number")
    settings.setValue("appearance/detail_family", "DejaVu Sans Mono")
    settings.sync()

    loaded = gui.load_appearance()
    assert loaded.text_scale == gui.TEXT_SCALE_MAX
    assert loaded.detail_point_size == 0
    assert loaded.detail_family == "DejaVu Sans Mono"


def test_save_appearance_round_trip(app) -> None:
    appearance = gui.AppearanceSettings(text_scale=150, detail_family="Mono X", detail_point_size=14)
    gui.save_appearance(appearance)
    assert gui.load_appearance() == appearance


def test_interface_and_detail_fonts_scale(app) -> None:
    base = gui.system_font().pointSizeF()
    scaled = gui.AppearanceSettings(text_scale=150)

    assert gui.interface_font(scaled).pointSizeF() == pytest.approx(base * 1.5)
    assert gui.detail_font(scaled).pointSizeF() == pytest.approx(base * 1.5)

    fixed = gui.AppearanceSettings(text_scale=150, detail_family="Mono X", detail_point_size=14)
    assert gui.detail_font(fixed).pointSize() == 14
    assert gui.detail_font(fixed).family() == "Mono X"


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

    monkeypatch.setattr(gui, "QFontDatabase", FakeFontDatabase)

    assert gui.monospace_families() == ["Alpha Mono", "Zeta Mono"]


def test_apply_appearance_updates_app_detail_panes_and_tables(app) -> None:
    detail = QPlainTextEdit()
    gui.use_detail_font(detail)
    table = QTableView()
    base = gui.system_font().pointSizeF()

    gui.apply_appearance(gui.AppearanceSettings(text_scale=200, detail_point_size=20))

    assert QApplication.font().pointSizeF() == pytest.approx(base * 2)
    assert detail.font().pointSize() == 20
    expected_rows = gui.QFontMetrics(QApplication.font()).height() + 10
    assert table.verticalHeader().defaultSectionSize() >= expected_rows


def test_settings_dialog_apply_saves_and_applies(app) -> None:
    dialog = gui.SettingsDialog()
    assert [dialog.categories.item(i).text() for i in range(dialog.categories.count())] == [
        "Appearance",
        "Detail panes",
    ]

    dialog.scale_slider.setValue(130)
    dialog.detail_size.setValue(16)
    assert gui.load_appearance() == gui.AppearanceSettings()

    dialog.apply()
    assert gui.load_appearance() == gui.AppearanceSettings(text_scale=130, detail_point_size=16)
    base = gui.system_font().pointSizeF()
    assert QApplication.font().pointSizeF() == pytest.approx(base * 1.3)

    dialog.restore_defaults()
    assert dialog.pending() == gui.AppearanceSettings()


def test_main_window_text_scale_steps(app) -> None:
    window = gui.MainWindow()

    window.step_text_scale(gui.TEXT_SCALE_STEP)
    assert gui.load_appearance().text_scale == gui.TEXT_SCALE_DEFAULT + gui.TEXT_SCALE_STEP

    for _ in range(50):
        window.step_text_scale(gui.TEXT_SCALE_STEP)
    assert gui.load_appearance().text_scale == gui.TEXT_SCALE_MAX

    window.step_text_scale(0)
    assert gui.load_appearance().text_scale == gui.TEXT_SCALE_DEFAULT
