from __future__ import annotations

import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from export_inspector import google_mail
from export_inspector.gmail import mbox
from export_inspector.gmail import sqlite_index
from export_inspector.gmail.models import IndexStats, MailboxStats, SearchResult


FIXTURES = Path(__file__).parent / "fixtures"
GMAIL_MBOX = FIXTURES / "gmail" / "sample.mbox"


def test_gmail_models_remain_import_compatible() -> None:
    assert google_mail.MailboxStats is MailboxStats
    assert google_mail.SearchResult is SearchResult
    assert google_mail.IndexStats is IndexStats


def test_gmail_sqlite_service_remains_import_compatible() -> None:
    assert google_mail.open_database is sqlite_index.open_database
    assert google_mail.index_mbox is sqlite_index.index_mbox
    assert google_mail.write_index_metadata is sqlite_index.write_index_metadata
    assert google_mail.load_metadata is sqlite_index.load_metadata


def test_gmail_mbox_service_remains_import_compatible() -> None:
    assert google_mail.scan_mbox_info is mbox.scan_mbox_info
    assert google_mail.search_mbox is mbox.search_mbox
    assert google_mail.load_message_from_mbox is mbox.load_message_from_mbox
    assert google_mail.load_message_from_offset is mbox.load_message_from_offset
    assert google_mail.parse_headers is mbox.parse_headers


def test_google_mail_script_help_works_without_installed_package() -> None:
    script_path = Path(google_mail.__file__).resolve()

    result = subprocess.run(
        [sys.executable, "-S", str(script_path), "--help"],
        cwd="/tmp",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Inspect, search, and index Gmail" in result.stdout


def search_args(input_file: Path, terms: list[str] | None = None, **overrides) -> Namespace:
    values = {
        "input_file": str(input_file),
        "terms": terms or [],
        "from_filter": None,
        "to_filter": None,
        "subject_filter": None,
        "label_filter": None,
        "after": None,
        "before": None,
        "any": False,
        "headers_only": False,
        "limit": 20,
        "timezone": "UTC",
        "no_progress": True,
        "no_ansi": True,
    }
    values.update(overrides)
    return Namespace(**values)


def test_scan_mbox_info_reads_synthetic_gmail_fixture() -> None:
    stats, sender_counts, recipient_counts, subject_counts = mbox.scan_mbox_info(
        GMAIL_MBOX,
        show_progress=False,
    )

    assert stats.total_messages == 2
    assert stats.first_dt is not None
    assert stats.last_dt is not None
    assert sender_counts["alice@example.com"] == 1
    assert recipient_counts["alice@example.com"] == 1
    assert subject_counts["Hiking Plans"] == 1


def test_raw_mbox_search_filters_and_returns_message_indexes() -> None:
    results = mbox.search_mbox(
        search_args(
            GMAIL_MBOX,
            ["fika"],
            from_filter="alice",
            subject_filter="hiking",
            limit=5,
        )
    )

    assert [result.index for result in results] == [1]
    assert results[0].sender == "Alice Example <alice@example.com>"
    assert results[0].subject == "Hiking Plans"
    assert "fika" in results[0].snippet


def test_gmail_mbox_message_loader_reads_decoded_body() -> None:
    headers, body_text = mbox.load_message_from_mbox(
        GMAIL_MBOX,
        target_index=2,
        show_progress=False,
    )

    assert headers["subject"] == "Re: Hiking Plans"
    assert "I will bring coffee" in body_text


def test_gmail_sqlite_index_search_and_show_round_trip(tmp_path, capsys) -> None:
    index_path = tmp_path / "gmail.sqlite"
    progress_calls: list[tuple[int, int, int]] = []

    conn = sqlite_index.open_database(index_path, force=False)
    try:
        message_count, stats = sqlite_index.index_mbox(
            GMAIL_MBOX,
            conn,
            max_body_chars=10_000,
            show_progress=False,
            progress_callback=lambda count, current, total: progress_calls.append(
                (count, current, total)
            ),
        )
        sqlite_index.write_index_metadata(
            conn,
            GMAIL_MBOX,
            message_count,
            10_000,
            stats,
        )
        conn.commit()
    finally:
        conn.close()

    assert message_count == 2
    assert progress_calls[-1][0] == 2
    assert google_mail.detect_sqlite(index_path)

    indexed_results = google_mail.search_sqlite(search_args(index_path, ["coffee"]))
    assert [result.index for result in indexed_results] == [2]
    assert indexed_results[0].labels == "Sent"

    google_mail.handle_show(
        Namespace(
            input_file=str(index_path),
            message_index=1,
            timezone="UTC",
            no_progress=True,
        )
    )
    output = capsys.readouterr().out
    assert "Subject: Hiking Plans" in output
    assert "trail schedule includes fika" in output
