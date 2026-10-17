from __future__ import annotations

import ast
from pathlib import Path

import pytest

from export_inspector.gmail import records, sqlite_index


FIXTURES = Path(__file__).parent / "fixtures"
GMAIL_MBOX = FIXTURES / "gmail" / "sample.mbox"


@pytest.fixture
def index_path(tmp_path) -> Path:
    path = tmp_path / "gmail.sqlite"
    conn = sqlite_index.open_database(path, force=False)
    try:
        count, stats = sqlite_index.index_mbox(
            GMAIL_MBOX, conn, max_body_chars=10_000, show_progress=False
        )
        sqlite_index.write_index_metadata(conn, GMAIL_MBOX, count, 10_000, stats)
        conn.commit()
    finally:
        conn.close()
    return path


def test_mbox_records_are_header_only_and_newest_first() -> None:
    loaded = records.load_mbox_records(GMAIL_MBOX, "UTC")

    assert [record.message_index for record in loaded] == [2, 1]
    assert [record.source_offset for record in loaded] == [382, 0]
    newest = loaded[0]
    assert newest.source_path == str(GMAIL_MBOX)
    assert newest.date_text == "2022-01-02 11:30:00"
    assert newest.date_sort == 1641123000
    assert newest.sender == "Bob Example <bob@example.com>"
    assert newest.recipients == "alice@example.com"
    assert newest.subject == "Re: Hiking Plans"
    assert newest.labels == "Sent"
    assert newest.thread_id == "1001"
    assert newest.snippet == ""


def test_sqlite_records_match_the_mbox_and_add_snippets(index_path) -> None:
    from_index = records.load_sqlite_records(index_path, "Europe/Stockholm")
    from_mbox = records.load_mbox_records(GMAIL_MBOX, "Europe/Stockholm")

    def comparable(record):
        return (record.message_index, record.date_text, record.sender, record.subject, record.labels)

    assert [comparable(r) for r in from_index] == [comparable(r) for r in from_mbox]
    assert from_index[0].date_text == "2022-01-02 12:30:00"
    assert all(record.snippet for record in from_index)
    assert [record.source_offset for record in from_index] == [382, 0]


def test_load_records_picks_the_loader_by_file_type(index_path) -> None:
    assert records.load_records(GMAIL_MBOX, "UTC") == records.load_mbox_records(GMAIL_MBOX, "UTC")
    assert records.load_records(index_path, "UTC") == records.load_sqlite_records(index_path, "UTC")


def test_record_from_headers_fills_defaults() -> None:
    record = records.record_from_headers(7, Path("x.mbox"), 123, {}, "UTC")
    assert record == records.GmailRecord(
        message_index=7,
        source_path="x.mbox",
        source_offset=123,
        date_text="n/a",
        date_sort=0,
        sender="unknown",
        recipients="",
        subject="(no subject)",
        labels="",
        thread_id="",
        snippet="",
    )


def test_record_texts() -> None:
    record = records.load_mbox_records(GMAIL_MBOX, "UTC")[1]
    assert records.record_fallback_text(record, "Source mbox not found: x") == (
        "Date: 2022-01-01 10:00:00\n"
        "From: Alice Example <alice@example.com>\n"
        "To: bob@example.com\n"
        "Subject: Hiking Plans\n"
        "Labels: Inbox\n"
        "Thread: 1001\n"
        "\n"
        "Source mbox not found: x"
    )
    assert records.record_search_blob(record).split("\n") == [
        "2022-01-01 10:00:00",
        "Alice Example <alice@example.com>",
        "bob@example.com",
        "Hiking Plans",
        "Inbox",
        "1001",
        "",
        "1",
    ]

    bare = records.record_from_headers(3, Path("x.mbox"), 0, {}, "UTC")
    assert records.record_fallback_text(bare, "why") == (
        "Date: n/a\nFrom: unknown\nSubject: (no subject)\n\nwhy"
    )


def test_records_module_does_not_import_qt_or_the_cli() -> None:
    tree = ast.parse(Path(records.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {name for name in imported if name and name.startswith("PySide6")}
    assert not imported & {"export_inspector.gmail.cli", "export_inspector.google_mail"}
