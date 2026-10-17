"""Appearance settings: text scale and detail pane font, saved in QSettings.

Imports only ``gui.common`` from the GUI package, so tabs and dialogs can use it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
from PySide6.QtWidgets import QApplication, QTableView, QWidget

from export_inspector.gui.common import app_settings

TEXT_SCALE_DEFAULT = 100
TEXT_SCALE_MIN = 50
TEXT_SCALE_MAX = 250
TEXT_SCALE_STEP = 10
DETAIL_POINT_SIZE_MAX = 72
DETAIL_PANE_PROPERTY = "exportInspectorDetailPane"
_system_font: QFont | None = None


@dataclass(frozen=True)
class AppearanceSettings:
    """GUI text settings, persisted in QSettings under ``appearance/``.

    ``text_scale`` is a percentage of the system default font size. ``detail_family``
    is the monospace font for detail panes ("" means the system monospace font), and
    ``detail_point_size`` its size in points (0 follows the interface text size).
    """

    text_scale: int = TEXT_SCALE_DEFAULT
    detail_family: str = ""
    detail_point_size: int = 0


def _settings_int(settings: QSettings, key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(settings.value(key, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def load_appearance() -> AppearanceSettings:
    """Read the saved appearance settings, falling back to defaults for bad values."""
    settings = app_settings()
    return AppearanceSettings(
        text_scale=_settings_int(
            settings, "appearance/text_scale", TEXT_SCALE_DEFAULT, TEXT_SCALE_MIN, TEXT_SCALE_MAX
        ),
        detail_family=str(settings.value("appearance/detail_family", "") or ""),
        detail_point_size=_settings_int(
            settings, "appearance/detail_point_size", 0, 0, DETAIL_POINT_SIZE_MAX
        ),
    )


def save_appearance(appearance: AppearanceSettings) -> None:
    """Persist appearance settings. Does not apply them; see ``apply_appearance``."""
    settings = app_settings()
    settings.setValue("appearance/text_scale", appearance.text_scale)
    settings.setValue("appearance/detail_family", appearance.detail_family)
    settings.setValue("appearance/detail_point_size", appearance.detail_point_size)


def system_font() -> QFont:
    """Return the application font as it was before any text scaling was applied."""
    global _system_font
    if _system_font is None:
        _system_font = QFont(QApplication.font())
    return QFont(_system_font)


def interface_font(appearance: AppearanceSettings) -> QFont:
    """Return the system font scaled by ``appearance.text_scale``."""
    font = system_font()
    factor = appearance.text_scale / 100
    if font.pointSizeF() > 0:
        font.setPointSizeF(font.pointSizeF() * factor)
    else:
        font.setPixelSize(max(1, round(font.pixelSize() * factor)))
    return font


def detail_font(appearance: AppearanceSettings) -> QFont:
    """Return the monospace font for detail panes."""
    font = QFont(appearance.detail_family or "Monospace")
    font.setStyleHint(QFont.Monospace)
    if appearance.detail_point_size:
        font.setPointSize(appearance.detail_point_size)
        return font
    interface = interface_font(appearance)
    if interface.pointSizeF() > 0:
        font.setPointSizeF(interface.pointSizeF())
    else:
        font.setPixelSize(interface.pixelSize())
    return font


def monospace_families() -> list[str]:
    """Return the selectable fixed-pitch font families, sorted by name.

    Private system families are excluded, as Qt requires for font-selection controls.
    """
    return sorted(
        family
        for family in QFontDatabase.families()
        if QFontDatabase.isFixedPitch(family) and not QFontDatabase.isPrivateFamily(family)
    )


def use_detail_font(widget: QWidget) -> None:
    """Give a detail pane the detail font and keep it in sync with later changes."""
    widget.setProperty(DETAIL_PANE_PROPERTY, True)
    widget.setFont(detail_font(load_appearance()))


def apply_appearance(appearance: AppearanceSettings) -> None:
    """Apply appearance settings to the running application without saving them.

    Sets the application font, refreshes every detail pane registered with
    ``use_detail_font`` and grows table rows so the scaled text fits.
    """
    font = interface_font(appearance)
    QApplication.setFont(font)
    mono = detail_font(appearance)
    row_height = QFontMetrics(font).height() + 10
    for widget in QApplication.allWidgets():
        if widget.property(DETAIL_PANE_PROPERTY):
            widget.setFont(mono)
        elif isinstance(widget, QTableView):
            header = widget.verticalHeader()
            header.resetDefaultSectionSize()
            header.setDefaultSectionSize(max(header.defaultSectionSize(), row_height))
