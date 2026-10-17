"""Compact route map HTML for the Runkeeper tab's embedded web view (CARTO tiles)."""

from __future__ import annotations

import html
import json

from export_inspector import runkeeper

def build_embedded_runkeeper_map_html(
    activity: runkeeper.Activity,
    points: list[dict[str, float | str | None]],
    timezone_name: str,
) -> str:
    """Return an HTML page that draws the activity's route with Leaflet on CARTO tiles.

    This is the GUI's compact map-only page, deliberately separate from
    `runkeeper.build_map_html()`. Raises ValueError when `points` is empty.
    """
    if not points:
        raise ValueError("This activity has no track points to render.")

    route_coordinates = [[point["lat"], point["lon"]] for point in points]
    color = runkeeper.color_for_activity(activity.activity_type)
    title = html.escape(activity.name)
    activity_type = html.escape(activity.activity_type)
    started = html.escape(runkeeper.format_dt(activity.started_at, timezone_name))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin=""
  >
  <style>
    html, body, #map {{
      height: 100%;
      margin: 0;
    }}
    body {{
      background: #f6f3ec;
      font-family: "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}
    #map {{
      min-height: 320px;
    }}
    .summary {{
      position: absolute;
      left: 12px;
      top: 12px;
      z-index: 700;
      max-width: min(340px, calc(100% - 24px));
      padding: 10px 12px;
      border: 1px solid rgba(20, 33, 61, 0.12);
      border-radius: 6px;
      background: rgba(255, 252, 246, 0.94);
      box-shadow: 0 10px 24px rgba(20, 33, 61, 0.12);
      color: #14213d;
    }}
    .title {{
      margin: 0 0 4px;
      font-weight: 700;
      font-size: 14px;
      line-height: 1.25;
    }}
    .meta {{
      margin: 0;
      color: #5f6b7a;
      font-size: 12px;
      line-height: 1.35;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="summary">
    <p class="title">{title}</p>
    <p class="meta">{activity_type} · {started}</p>
  </div>
  <script
    src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
    crossorigin=""
  ></script>
  <script>
    const route = {json.dumps(route_coordinates, separators=(",", ":"))};
    const map = L.map("map", {{
      zoomControl: true,
      attributionControl: true
    }});

    L.tileLayer("https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png", {{
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors &copy; CARTO"
    }}).addTo(map);

    const routeLine = L.polyline(route, {{
      color: {json.dumps(color)},
      weight: 5,
      opacity: 0.9
    }}).addTo(map);

    L.circleMarker(route[0], {{
      radius: 7,
      color: "#ffffff",
      weight: 2,
      fillColor: "#2a9d8f",
      fillOpacity: 1
    }}).addTo(map).bindPopup("Start");

    L.circleMarker(route[route.length - 1], {{
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
