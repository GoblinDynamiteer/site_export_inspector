"""Load Runkeeper ZIP exports (one ZIP or a folder of them): GPX activities, CSV data, route points."""

from __future__ import annotations

import csv
import math
import re
import zipfile
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree as ET

from export_inspector.runkeeper.formatting import normalize_text
from export_inspector.runkeeper.models import Activity, NS


def parse_type_from_name(name: str) -> str:
    trimmed = normalize_text(name)
    match = re.match(
        r"^(.*?)\s+\d{1,2}/\d{1,2}/\d{2}\s+\d{1,2}:\d{2}\s+[ap]m$",
        trimmed,
        re.IGNORECASE,
    )
    if match:
        candidate = normalize_text(match.group(1))
        if candidate:
            return candidate
    prefix = trimmed.split(" ", 1)[0]
    return prefix or "Unknown"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def parse_gpx_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def parse_activity(
    index: int, archive_path: Path, file_name: str, xml_bytes: bytes
) -> Activity:
    root = ET.fromstring(xml_bytes)
    name = (
        normalize_text(root.findtext(".//gpx:trk/gpx:name", default="", namespaces=NS))
        or file_name
    )

    points: list[tuple[float, float, float | None, datetime | None]] = []
    for point in root.findall(".//gpx:trkpt", NS):
        lat = float(point.attrib["lat"])
        lon = float(point.attrib["lon"])
        ele_text = point.findtext("gpx:ele", default="", namespaces=NS).strip()
        time_text = point.findtext("gpx:time", default="", namespaces=NS).strip()
        ele = float(ele_text) if ele_text else None
        dt = parse_gpx_datetime(time_text) if time_text else None
        points.append((lat, lon, ele, dt))

    started_at = next((dt for _, _, _, dt in points if dt is not None), None)
    finished_at = next((dt for _, _, _, dt in reversed(points) if dt is not None), None)
    if started_at is None or finished_at is None:
        track_time = normalize_text(
            root.findtext(".//gpx:trk/gpx:time", default="", namespaces=NS)
        )
        if not track_time:
            raise ValueError(f"Could not find timestamps in {file_name}")
        started_at = finished_at = parse_gpx_datetime(track_time)

    distance_km = 0.0
    elevation_gain_m = 0.0
    for previous, current in zip(points, points[1:]):
        distance_km += haversine_km(previous[0], previous[1], current[0], current[1])
        previous_ele = previous[2]
        current_ele = current[2]
        if (
            previous_ele is not None
            and current_ele is not None
            and current_ele > previous_ele
        ):
            elevation_gain_m += current_ele - previous_ele

    start_lat = points[0][0] if points else None
    start_lon = points[0][1] if points else None
    end_lat = points[-1][0] if points else None
    end_lon = points[-1][1] if points else None

    return Activity(
        index=index,
        archive_path=archive_path,
        file_name=file_name,
        name=name,
        activity_type=parse_type_from_name(name),
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=max(0.0, (finished_at - started_at).total_seconds()),
        distance_km=distance_km,
        elevation_gain_m=elevation_gain_m,
        point_count=len(points),
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
    )


def parse_csv_rows(zip_file: zipfile.ZipFile, member_name: str) -> list[dict[str, str]]:
    try:
        raw = zip_file.read(member_name).decode("utf-8-sig")
    except KeyError:
        return []
    reader = csv.DictReader(StringIO(raw))
    return [dict(row) for row in reader]


def discover_zip_paths(path: Path) -> list[Path]:
    """Return the ZIP itself, or every `*.zip` under a directory (recursive, sorted).

    Raises SystemExit for a missing path, a non-ZIP file or a directory without ZIPs.
    """
    if not path.exists():
        raise SystemExit(f"Path not found: {path}")
    if path.is_dir():
        zip_paths = sorted(item for item in path.rglob("*.zip") if item.is_file())
        if not zip_paths:
            raise SystemExit(f"No ZIP files found in directory: {path}")
        return zip_paths
    if path.suffix.lower() != ".zip":
        raise SystemExit("Expected a Runkeeper ZIP export or a directory of ZIP files.")
    return [path]


def load_export(
    path: Path,
) -> tuple[list[Activity], list[dict[str, str]], list[dict[str, str]]]:
    """Load one ZIP export or a folder of them: (activities, measurements, photos).

    Activities are sorted by start time and numbered from 1; the CSV rows of all ZIPs
    are concatenated. Raises SystemExit like `discover_zip_paths`.
    """
    zip_paths = discover_zip_paths(path)

    activities: list[Activity] = []
    measurements: list[dict[str, str]] = []
    photos: list[dict[str, str]] = []
    for zip_path in zip_paths:
        with zipfile.ZipFile(zip_path) as zip_file:
            gpx_files = sorted(
                name for name in zip_file.namelist() if name.lower().endswith(".gpx")
            )
            for member_name in gpx_files:
                activities.append(
                    parse_activity(
                        len(activities) + 1,
                        zip_path,
                        member_name,
                        zip_file.read(member_name),
                    )
                )
            measurements.extend(parse_csv_rows(zip_file, "measurements.csv"))
            photos.extend(parse_csv_rows(zip_file, "photos.csv"))

    activities.sort(key=lambda item: item.started_at)
    for index, activity in enumerate(activities, start=1):
        activity.index = index
    return activities, measurements, photos


def load_route_points(
    zip_path: Path, member_name: str
) -> list[dict[str, float | str | None]]:
    """Return the track points (`lat`, `lon`, `ele`, `time`) of one GPX in a ZIP."""
    with zipfile.ZipFile(zip_path) as zip_file:
        root = ET.fromstring(zip_file.read(member_name))

    points: list[dict[str, float | str | None]] = []
    for point in root.findall(".//gpx:trkpt", NS):
        ele_text = point.findtext("gpx:ele", default="", namespaces=NS).strip()
        time_text = point.findtext("gpx:time", default="", namespaces=NS).strip()
        points.append(
            {
                "lat": float(point.attrib["lat"]),
                "lon": float(point.attrib["lon"]),
                "ele": float(ele_text) if ele_text else None,
                "time": time_text or None,
            }
        )
    return points
