from __future__ import annotations

import zipfile
from pathlib import Path

from export_inspector import messenger_chat, runkeeper, untappd


FIXTURES = Path(__file__).parent / "fixtures"


def test_messenger_fixture_loads_normalized_thread() -> None:
    messages, participants = messenger_chat.load_json_thread(
        FIXTURES / "messenger" / "message_1.json"
    )

    assert participants == ("Alice Example", "Bob Example")
    assert [message["sender_name"] for message in messages] == [
        "Alice Example",
        "Bob Example",
    ]
    assert messenger_chat.build_message_search_texts(messages[0], "UTC")


def test_untappd_fixture_loads_json_array() -> None:
    entries = untappd.load_export(FIXTURES / "untappd" / "checkins.json")

    assert len(entries) == 1
    assert entries[0]["beer_name"] == "Sample Pale Ale"
    assert untappd.parse_created_at(entries[0]["created_at"]).year == 2022
    assert untappd.display_rating(entries[0]) == "4"


def test_runkeeper_fixture_loads_zip_export(tmp_path) -> None:
    zip_path = tmp_path / "runkeeper-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(FIXTURES / "runkeeper" / "activity.gpx", "activity.gpx")
        archive.write(FIXTURES / "runkeeper" / "measurements.csv", "measurements.csv")
        archive.write(FIXTURES / "runkeeper" / "photos.csv", "photos.csv")

    activities, measurements, photos = runkeeper.load_export(zip_path)

    assert len(activities) == 1
    assert activities[0].name == "Running sample"
    assert activities[0].point_count == 2
    assert measurements[0]["Type"] == "Weight"
    assert photos[0]["uri"] == "photos/sample.jpg"
