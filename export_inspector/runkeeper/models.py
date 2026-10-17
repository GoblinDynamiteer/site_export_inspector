"""The Runkeeper activity model and shared constants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
NS = {"gpx": "http://www.topografix.com/GPX/1/1"}


@dataclass
class Activity:
    """One GPX activity from an export. `index` is its 1-based position by start time
    across everything loaded; `archive_path` + `file_name` locate the GPX for map rendering."""

    index: int
    archive_path: Path
    file_name: str
    name: str
    activity_type: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    distance_km: float
    elevation_gain_m: float
    point_count: int
    start_lat: float | None
    start_lon: float | None
    end_lat: float | None
    end_lon: float | None
