from __future__ import annotations

import importlib


def test_gui_module_imports_with_offscreen_platform(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    gui = importlib.import_module("export_inspector.gui")

    assert callable(gui.main)
    common = importlib.import_module("export_inspector.gui.common")
    assert common.SETTINGS_ORG == "jk"
    assert common.SETTINGS_APP == "export_inspector"
