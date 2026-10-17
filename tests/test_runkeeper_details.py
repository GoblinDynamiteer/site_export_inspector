from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from export_inspector.runkeeper import details, formatting
from export_inspector.runkeeper.models import Activity
from export_inspector.runkeeper.ranks import ActivityRanks, rank_by_type


def activity(index: int, activity_type: str, km: float, seconds: float, **extra) -> Activity:
    started = datetime(2022, 1, index, 10, 0, tzinfo=UTC)
    values = dict(
        index=index,
        archive_path=Path("export.zip"),
        file_name=f"{index}.gpx",
        name=f"{activity_type} {index}",
        activity_type=activity_type,
        started_at=started,
        finished_at=started.replace(hour=11),
        duration_seconds=seconds,
        distance_km=km,
        elevation_gain_m=12.4,
        point_count=3,
        start_lat=59.0,
        start_lon=18.0,
        end_lat=59.5,
        end_lon=18.5,
    )
    values.update(extra)
    return Activity(**values)


ACTIVITIES = [
    activity(1, "Running", 5.0, 1800),
    activity(2, "Running", 10.0, 1500),
    activity(3, "Running", 5.0, 3600),
    activity(4, "Cycling", 30.0, 3600),
]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (10, "10th"),
        (11, "11th"), (12, "12th"), (13, "13th"), (20, "20th"), (21, "21st"),
        (22, "22nd"), (23, "23rd"), (101, "101st"), (111, "111th"), (112, "112th"),
    ],
)
def test_ordinal(value: int, expected: str) -> None:
    assert formatting.ordinal(value) == expected


def test_rank_by_type_ranks_within_each_type_and_shares_ties() -> None:
    assert rank_by_type(ACTIVITIES, "distance") == {1: 2, 2: 1, 3: 2, 4: 1}
    assert rank_by_type(ACTIVITIES, "duration") == {1: 2, 2: 3, 3: 1, 4: 1}


def test_rank_labels() -> None:
    ranks = ActivityRanks.from_activities(ACTIVITIES)
    assert ranks.distance_label(ACTIVITIES[1]) == "1st longest Running distance"
    assert ranks.duration_label(ACTIVITIES[1]) == "3rd longest Running duration"
    assert ActivityRanks().distance_label(ACTIVITIES[3]) == "unranked Cycling distance"


def test_activity_details_text() -> None:
    ranks = ActivityRanks.from_activities(ACTIVITIES)
    text = details.activity_details_text(ACTIVITIES[1], ranks, "UTC", photo_count=0)
    assert text.split("\n") == [
        "Name: Running 2",
        "File: 2.gpx",
        "Type: Running",
        "Started: 2022-01-02 10:00:00",
        "Finished: 2022-01-02 11:00:00",
        "Duration: 25:00 (3rd longest Running duration)",
        "Distance: 10.00 km (1st longest Running distance)",
        "Pace: 2:30 /km",
        "Speed: 24.00 km/h",
        "Elevation gain: 12 m",
        "Track points: 3",
        "Start: 59.000000, 18.000000",
        "End: 59.500000, 18.500000",
        "Archive: export.zip",
        "Photo entries in loaded export data: 0",
    ]
    with_photos = details.activity_details_text(ACTIVITIES[1], ranks, "Europe/Stockholm", 2)
    assert "Started: 2022-01-02 11:00:00" in with_photos
    assert with_photos.endswith("Photo entries in loaded export data: 2\n" + details.PHOTO_NOTE)

    no_coordinates = activity(5, "Walking", 1.0, 600, start_lat=None, end_lon=None)
    text = details.activity_details_text(no_coordinates, ranks, "UTC", 0)
    assert "Start:" not in text and "End:" not in text


def test_activity_search_blob() -> None:
    ranks = ActivityRanks.from_activities(ACTIVITIES)
    blob = details.activity_search_blob(ACTIVITIES[3], ranks, "UTC").split("\n")
    assert blob[:3] == ["Cycling 4", "4.gpx", "Cycling"]
    assert "1st longest Cycling distance" in blob
    assert blob[-2:] == ["59.000000, 18.000000", "59.500000, 18.500000"]


@pytest.mark.parametrize("module", ["ranks", "details", "formatting"])
def test_runkeeper_logic_modules_do_not_import_qt(module: str) -> None:
    path = Path(details.__file__).with_name(f"{module}.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {name for name in imported if name and name.startswith("PySide6")}
    assert "export_inspector.runkeeper.cli" not in imported
