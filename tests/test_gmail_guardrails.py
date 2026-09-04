from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from export_inspector import google_mail
from export_inspector.gmail.models import IndexStats, MailboxStats, SearchResult


FIXTURES = Path(__file__).parent / "fixtures"
GMAIL_MBOX = FIXTURES / "gmail" / "sample.mbox"


def test_gmail_models_remain_import_compatible() -> None:
    assert google_mail.MailboxStats is MailboxStats
    assert google_mail.SearchResult is SearchResult
    assert google_mail.IndexStats is IndexStats


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
    stats, sender_counts, recipient_counts, subject_counts = google_mail.scan_mbox_info(
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
    results = google_mail.search_mbox(
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


def test_gmail_sqlite_index_search_and_show_round_trip(tmp_path, capsys) -> None:
    index_path = tmp_path / "gmail.sqlite"
    progress_calls: list[tuple[int, int, int]] = []

    conn = google_mail.open_database(index_path, force=False)
    try:
        message_count, stats = google_mail.index_mbox(
            GMAIL_MBOX,
            conn,
            max_body_chars=10_000,
            show_progress=False,
            progress_callback=lambda count, current, total: progress_calls.append(
                (count, current, total)
            ),
        )
        google_mail.write_index_metadata(conn, GMAIL_MBOX, message_count, 10_000, stats)
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
