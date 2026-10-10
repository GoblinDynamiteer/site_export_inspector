"""Helpers shared by the GUI tabs: settings storage, remembered paths and line edits.

Keep this module free of imports from the rest of ``export_inspector.gui`` so every
other GUI module can import it without cycles.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLineEdit

DEFAULT_TIMEZONE = "Europe/Stockholm"
SETTINGS_ORG = "jk"
SETTINGS_APP = "export_inspector"


def line_edit(placeholder: str = "", text: str = "") -> QLineEdit:
    """Return a ``QLineEdit`` with an optional placeholder and initial text."""
    widget = QLineEdit()
    widget.setPlaceholderText(placeholder)
    if text:
        widget.setText(text)
    return widget


def app_settings() -> QSettings:
    """Return the application's ``QSettings`` (org ``jk``, app ``export_inspector``)."""
    # defaultFormat() is NativeFormat unless changed, which tests do to isolate settings.
    return QSettings(QSettings.defaultFormat(), QSettings.UserScope, SETTINGS_ORG, SETTINGS_APP)


def settings_text(key: str, default: str = "") -> str:
    """Return a saved setting as text, or ``default`` when it is missing."""
    value = app_settings().value(key, default)
    return str(value) if value is not None else default


def remember_text(key: str, value: str) -> None:
    """Save ``value`` stripped under ``key``; blank values leave the old setting alone."""
    text = value.strip()
    if text:
        app_settings().setValue(key, text)


def dialog_start_path(key: str, fallback: str = "") -> str:
    """Return a start directory for a file dialog from the path saved under ``key``.

    A saved folder is used as is, and a saved file gives its parent folder. When neither
    exists, ``fallback`` is returned; an empty saved value (and no fallback) gives "".
    """
    saved = settings_text(key, fallback).strip()
    if not saved:
        return ""
    path = Path(saved).expanduser()
    if path.is_dir():
        return str(path)
    if path.parent.exists():
        return str(path.parent)
    return fallback
