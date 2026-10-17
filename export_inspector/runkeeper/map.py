"""The standalone route map page for the CLI and the browser (OSM tiles, served over local HTTP)."""

from __future__ import annotations

import html
import json
from pathlib import Path

from export_inspector.runkeeper.formatting import (
    format_dt,
    format_duration,
    format_pace,
    format_speed,
)
from export_inspector.runkeeper.models import Activity


def color_for_activity(activity_type: str) -> str:
    """Return the route colour for an activity type (run, cycling, walk, other)."""
    lowered = activity_type.lower()
    if "run" in lowered:
        return "#d1495b"
    if "cycl" in lowered:
        return "#00798c"
    if "walk" in lowered:
        return "#2a9d8f"
    return "#264653"


def default_map_output_path(activity_file_name: str) -> Path:
    return Path(Path(activity_file_name).name).with_suffix(".html")


def build_map_html(
    activity: Activity, points: list[dict[str, float | str | None]], timezone_name: str
) -> str:
    """Return the standalone route page (Leaflet over OpenStreetMap tiles, with stats).

    Meant to be served over local HTTP; the GUI uses its own compact CARTO page instead.
    """
    if not points:
        raise SystemExit("This activity has no track points to render.")

    route_coordinates = [[point["lat"], point["lon"]] for point in points]
    color = color_for_activity(activity.activity_type)

    started = html.escape(format_dt(activity.started_at, timezone_name))
    finished = html.escape(format_dt(activity.finished_at, timezone_name))
    title = html.escape(activity.name)
    activity_type = html.escape(activity.activity_type)
    file_name = html.escape(activity.file_name)

    summary_rows = [
        ("Type", activity_type),
        ("Started", started),
        ("Finished", finished),
        ("Distance", f"{activity.distance_km:.2f} km"),
        ("Duration", format_duration(activity.duration_seconds)),
        ("Pace", format_pace(activity.distance_km, activity.duration_seconds)),
        ("Speed", format_speed(activity.distance_km, activity.duration_seconds)),
        ("Elevation gain", f"{activity.elevation_gain_m:.0f} m"),
        ("Track points", str(activity.point_count)),
        ("File", file_name),
    ]
    stats_html = "\n".join(
        f'<div class="stat"><span class="label">{html.escape(label)}</span><span class="value">{html.escape(value)}</span></div>'
        for label, value in summary_rows
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin=""
  >
  <style>
    :root {{
      --bg: #f7f3ea;
      --paper: rgba(255, 252, 246, 0.94);
      --ink: #14213d;
      --muted: #5f6b7a;
      --accent: {color};
      --line: #d9d0c1;
      --shadow: 0 24px 60px rgba(20, 33, 61, 0.15);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(42, 157, 143, 0.12), transparent 32%),
        radial-gradient(circle at top right, rgba(209, 73, 91, 0.10), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, var(--bg) 100%);
    }}

    .page {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(280px, 360px) 1fr;
      gap: 20px;
      padding: 20px;
    }}

    .panel {{
      background: var(--paper);
      border: 1px solid rgba(20, 33, 61, 0.08);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(8px);
    }}

    .sidebar {{
      padding: 24px 22px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}

    .eyebrow {{
      margin: 0;
      font: 600 0.78rem/1.2 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    h1 {{
      margin: 0;
      font-size: clamp(1.9rem, 2.5vw, 2.8rem);
      line-height: 0.98;
    }}

    .lede {{
      margin: 0;
      color: var(--muted);
      font: 500 1rem/1.5 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}

    .stats {{
      display: grid;
      gap: 10px;
    }}

    .stat {{
      display: grid;
      gap: 2px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--line);
    }}

    .label {{
      font: 600 0.72rem/1.2 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .value {{
      font: 500 1.02rem/1.35 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
      word-break: break-word;
    }}

    .note {{
      margin: 0;
      color: var(--muted);
      font: 500 0.92rem/1.45 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}

    .warning {{
      margin: 0;
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(209, 73, 91, 0.10);
      color: #7f1d1d;
      font: 600 0.92rem/1.45 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}

    .map-panel {{
      position: relative;
      overflow: hidden;
      min-height: 72vh;
    }}

    #map {{
      width: 100%;
      height: 100%;
      min-height: 72vh;
    }}

    .legend {{
      position: absolute;
      right: 16px;
      bottom: 16px;
      z-index: 700;
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(255, 252, 246, 0.92);
      box-shadow: 0 12px 30px rgba(20, 33, 61, 0.12);
      font: 600 0.88rem/1.3 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}

    .swatch {{
      display: inline-block;
      width: 12px;
      height: 12px;
      border-radius: 999px;
      margin-right: 8px;
      background: var(--accent);
      vertical-align: middle;
    }}

    @media (max-width: 900px) {{
      .page {{
        grid-template-columns: 1fr;
      }}

      .map-panel,
      #map {{
        min-height: 60vh;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <aside class="panel sidebar">
      <p class="eyebrow">Runkeeper Route</p>
      <h1>{title}</h1>
      <p class="lede">{activity_type} tracked in Runkeeper, rendered over OpenStreetMap tiles.</p>
      <p id="protocol-warning" class="warning" hidden>
        This file is opened directly from disk. OpenStreetMap tiles may be blocked without a Referer. Serve this HTML over local HTTP instead.
      </p>
      <div class="stats">
        {stats_html}
      </div>
      <p class="note">This HTML uses Leaflet and OpenStreetMap tiles, so the browser needs internet access when you open it.</p>
    </aside>
    <section class="panel map-panel">
      <div id="map"></div>
      <div class="legend"><span class="swatch"></span>{activity_type}</div>
    </section>
  </div>

  <script
    src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
    crossorigin=""
  ></script>
  <script>
    if (window.location.protocol === "file:") {{
      document.getElementById("protocol-warning").hidden = false;
    }}

    const route = {json.dumps(route_coordinates, separators=(",", ":"))};
    const map = L.map("map", {{
      zoomControl: true,
      attributionControl: true
    }});

    L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors"
    }}).addTo(map);

    const routeLine = L.polyline(route, {{
      color: {json.dumps(color)},
      weight: 5,
      opacity: 0.9
    }}).addTo(map);

    const start = route[0];
    const end = route[route.length - 1];

    L.circleMarker(start, {{
      radius: 7,
      color: "#ffffff",
      weight: 2,
      fillColor: "#2a9d8f",
      fillOpacity: 1
    }}).addTo(map).bindPopup("Start");

    L.circleMarker(end, {{
      radius: 7,
      color: "#ffffff",
      weight: 2,
      fillColor: "#d1495b",
      fillOpacity: 1
    }}).addTo(map).bindPopup("End");

    map.fitBounds(routeLine.getBounds(), {{ padding: [24, 24] }});
  </script>
</body>
</html>
"""
