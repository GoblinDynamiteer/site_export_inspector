"""Offscreen behaviour tests for the GUI tabs.

Each test loads synthetic fixtures through the real tab widgets and compares the visible
text (status labels, tables, detail panes) with a golden snapshot in ``tests/golden/``
(``pytest --update-golden`` rewrites them after an intended change).
Tabs are reached through ``MainWindow`` by title, so these tests keep working while the
tab classes move between modules.
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile

import pytest
from PySide6.QtCore import QElapsedTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QTabWidget, QWidget

from export_inspector import google_mail, gui
from tests.gui_snapshot import FIXTURES, Snapshot, each_row_detail

TAB_TITLES = ["Messenger", "Google Mail", "Untappd", "Runkeeper"]

SECOND_GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="export-inspector-test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Running evening sample</name>
    <trkseg>
      <trkpt lat="59.3293" lon="18.0686"><ele>10.0</ele><time>2022-01-03T18:00:00Z</time></trkpt>
      <trkpt lat="59.3350" lon="18.0750"><ele>12.0</ele><time>2022-01-03T18:04:00Z</time></trkpt>
      <trkpt lat="59.3400" lon="18.0800"><ele>15.0</ele><time>2022-01-03T18:09:00Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


@pytest.fixture
def window(qt_app, message_boxes):
    main_window = gui.MainWindow()
    yield main_window
    main_window.close()
    main_window.deleteLater()


def tab(window, title: str) -> QWidget:
    tabs = window.centralWidget()
    assert isinstance(tabs, QTabWidget)
    for index in range(tabs.count()):
        if tabs.tabText(index) == title:
            return tabs.widget(index)
    raise AssertionError(f"No tab titled {title!r}")


def module_of(widget: QWidget):
    """Return the module defining the widget's class, wherever it currently lives."""
    return sys.modules[type(widget).__module__]


def wait_until(condition, timeout_ms: int = 10000) -> None:
    timer = QElapsedTimer()
    timer.start()
    while not condition():
        assert timer.elapsed() < timeout_ms, "Timed out waiting for the GUI"
        QApplication.processEvents()


def test_main_window_has_all_tabs(window) -> None:
    tabs = window.centralWidget()
    assert [tabs.tabText(i) for i in range(tabs.count())] == TAB_TITLES
    menus = [action.text() for action in window.menuBar().actions()]
    assert menus == ["File", "Tools", "About"]


def test_messenger_tab_loads_threads_and_filters(window, make_snapshot, tmp_path) -> None:
    source = tmp_path / "messenger"
    (source / "alice").mkdir(parents=True)
    (source / "carol").mkdir()
    shutil.copy(FIXTURES / "messenger" / "message_1.json", source / "alice" / "message_1.json")
    (source / "carol" / "message_1.json").write_text(
        json.dumps(
            {
                "participants": [{"name": "Carol Example"}, {"name": "Alice Example"}],
                "messages": [
                    {"sender_name": "Carol Example", "timestamp_ms": 1641200000000, "content": "Morning coffee?"},
                    {"sender_name": "Alice Example", "timestamp_ms": 1641240000000, "content": "Sorry, saw this late"},
                ],
            }
        ),
        encoding="utf-8",
    )
    messenger = tab(window, "Messenger")
    snapshot = make_snapshot("messenger", {str(tmp_path): "<TMP>"})

    messenger.path_edit.setText(str(source))
    messenger.load_chat()
    snapshot.add("status", messenger.status_label.text())
    snapshot.add(
        "threads",
        "\n".join(messenger.thread_list.item(i).text() for i in range(messenger.thread_list.count())),
    )
    for row in range(messenger.thread_list.count()):
        messenger.thread_list.setCurrentRow(row)
        snapshot.add(f"thread {row} info", messenger.info_label.text())
        snapshot.add(f"thread {row} status", messenger.status_label.text())
        snapshot.add(f"thread {row} messages", messenger.viewer.toPlainText())

    messenger.thread_list.setCurrentRow(0)
    messenger.filter_edit.setText("confirmed")
    snapshot.add("filtered status", messenger.status_label.text())
    snapshot.add("filtered messages", messenger.viewer.toPlainText())
    snapshot.assert_matches()


def check_gmail_tab(gmail, snapshot: Snapshot) -> None:
    snapshot.add("status", gmail.status_label.text())
    snapshot.add_table("table", gmail.table)
    for row, text in enumerate(each_row_detail(gmail.table, gmail.detail_text)):
        snapshot.add(f"detail {row}", text)
    gmail.filter_edit.setText("coffee")
    snapshot.add("filtered status", gmail.status_label.text())
    snapshot.add_table("filtered table", gmail.table)
    gmail.filter_edit.setText("")


def test_gmail_tab_loads_mbox(window, make_snapshot) -> None:
    gmail = tab(window, "Google Mail")
    snapshot = make_snapshot("gmail_mbox")

    gmail.path_edit.setText(str(FIXTURES / "gmail" / "sample.mbox"))
    gmail.load_mail()
    check_gmail_tab(gmail, snapshot)
    snapshot.assert_matches()


def test_gmail_tab_loads_sqlite_index(window, make_snapshot, tmp_path) -> None:
    mbox_path = FIXTURES / "gmail" / "sample.mbox"
    index_path = tmp_path / "index.sqlite"
    conn = google_mail.open_database(index_path, force=False)
    count, stats = google_mail.index_mbox(mbox_path, conn, max_body_chars=4000, show_progress=False)
    google_mail.write_index_metadata(conn, mbox_path, count, 4000, stats)
    conn.commit()
    conn.close()
    gmail = tab(window, "Google Mail")
    snapshot = make_snapshot("gmail_sqlite", {str(tmp_path): "<TMP>"})

    gmail.path_edit.setText(str(index_path))
    gmail.load_mail()
    check_gmail_tab(gmail, snapshot)
    snapshot.assert_matches()


def test_gmail_convert_widget_indexes_and_loads(window, message_boxes, monkeypatch, tmp_path) -> None:
    gmail = tab(window, "Google Mail")
    index_path = tmp_path / "converted.sqlite"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(index_path), "")
    )
    gmail.path_edit.setText(str(FIXTURES / "gmail" / "sample.mbox"))

    gmail.open_convert_widget()
    widget = gmail.convert_widget
    assert widget.path_edit.text() == str(FIXTURES / "gmail" / "sample.mbox")
    widget.convert()
    wait_until(lambda: widget.conversion_thread is None and not widget.isVisible())

    assert index_path.exists()
    assert gmail.path_edit.text() == str(index_path)
    assert gmail.status_label.text() == "2/2"
    assert message_boxes == [
        ("information", "Conversion complete", f"Indexed 2 messages into:\n{index_path}")
    ]


def test_untappd_tab_loads_all_views(window, make_snapshot) -> None:
    untappd_tab = tab(window, "Untappd")
    snapshot = make_snapshot("untappd")

    untappd_tab.path_edit.setText(str(FIXTURES / "untappd" / "checkins_multi.json"))
    untappd_tab.load_export()
    snapshot.add("status", untappd_tab.status_label.text())
    views = [
        ("check-ins", untappd_tab.table, untappd_tab.detail_text, untappd_tab.filter_edit),
        ("beers", untappd_tab.beer_table, untappd_tab.beer_detail_text, untappd_tab.beer_filter_edit),
        ("breweries", untappd_tab.brewery_table, untappd_tab.brewery_detail_text, untappd_tab.brewery_filter_edit),
        ("venues", untappd_tab.venue_table, untappd_tab.venue_detail_text, untappd_tab.venue_filter_edit),
    ]
    for name, table, detail, _filter in views:
        snapshot.add_table(f"{name} table", table)
        for row, text in enumerate(each_row_detail(table, detail)):
            snapshot.add(f"{name} detail {row}", text)
    for name, table, _detail, filter_edit in views:
        filter_edit.setText("stout")
        snapshot.add_table(f"{name} filtered 'stout'", table)
        filter_edit.setText("")
    snapshot.add("status after filters", untappd_tab.status_label.text())
    snapshot.assert_matches()


def test_runkeeper_tab_loads_activities_and_map(window, make_snapshot, monkeypatch, tmp_path) -> None:
    zip_path = tmp_path / "runkeeper-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(FIXTURES / "runkeeper" / "activity.gpx", "activity.gpx")
        archive.writestr("evening.gpx", SECOND_GPX)
        archive.write(FIXTURES / "runkeeper" / "measurements.csv", "measurements.csv")
        archive.write(FIXTURES / "runkeeper" / "photos.csv", "photos.csv")
    runkeeper_tab = tab(window, "Runkeeper")
    snapshot = make_snapshot("runkeeper", {str(tmp_path): "<TMP>"})

    class FakeWebView(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.html = ""
            self.base_url = None

        def setHtml(self, html: str, base_url=None) -> None:
            self.html = html
            self.base_url = base_url

    monkeypatch.setattr(module_of(runkeeper_tab), "QWebEngineView", FakeWebView)

    runkeeper_tab.path_edit.setText(str(zip_path))
    runkeeper_tab.load_export()
    snapshot.add("status", runkeeper_tab.status_label.text())
    snapshot.add_table("table", runkeeper_tab.table)
    for row, text in enumerate(each_row_detail(runkeeper_tab.table, runkeeper_tab.detail_text)):
        snapshot.add(f"detail {row}", text)
    runkeeper_tab.filter_edit.setText("evening")
    snapshot.add("filtered status", runkeeper_tab.status_label.text())
    snapshot.add_table("filtered table", runkeeper_tab.table)

    runkeeper_tab.table.selectRow(0)
    assert runkeeper_tab.show_map_button.isEnabled()
    runkeeper_tab.show_map()
    view = runkeeper_tab.map_view
    assert isinstance(view, FakeWebView)
    assert view.base_url.toString() == "https://carto.com/"
    assert "basemaps.cartocdn.com" in view.html
    assert "tile.openstreetmap.org" not in view.html
    snapshot.add("map html", view.html)
    snapshot.assert_matches()


def test_loading_remembers_input_paths(window, tmp_path) -> None:
    untappd_tab = tab(window, "Untappd")
    untappd_tab.path_edit.setText(str(FIXTURES / "untappd" / "checkins_multi.json"))
    untappd_tab.load_export()
    gmail = tab(window, "Google Mail")
    gmail.path_edit.setText(str(FIXTURES / "gmail" / "sample.mbox"))
    gmail.load_mail()

    assert gui.settings_text("untappd/input_path") == str(FIXTURES / "untappd" / "checkins_multi.json")
    assert gui.settings_text("google_mail/input_path") == str(FIXTURES / "gmail" / "sample.mbox")
