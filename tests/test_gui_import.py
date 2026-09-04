from __future__ import annotations

import importlib


def test_gui_module_imports_with_offscreen_platform(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    gui = importlib.import_module("export_inspector.gui")

    assert callable(gui.main)
    assert gui.SETTINGS_ORG == "jk"
    assert gui.SETTINGS_APP == "export_inspector"
