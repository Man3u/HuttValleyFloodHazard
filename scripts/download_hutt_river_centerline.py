"""
Download the real Hutt River centerline (OpenStreetMap, public, no login/key
needed) to validate the DEM-derived stream network against.

Run this on your own machine (same reason as download_hutt_dem.py -- the
sandbox couldn't reach the Overpass API reliably: timeouts on one mirror,
rate-limited on another):

    python3 scripts/download_hutt_river_centerline.py

Writes data/hutt_river_osm.geojson.
"""

import json
import os
import urllib.request

# Bounding box covering the Hutt Valley (south, west, north, east in lat/lon)
BBOX = "-41.23,174.85,-41.10,174.98"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
QUERY = f"""
[out:json][timeout:60][bbox:{BBOX}];
way["waterway"="river"]["name"~"Hutt River|Te Awa Kairangi", i];
out geom;
"""

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = os.path.join(OUT_DIR, "hutt_river_osm.geojson")


def main():
    print("Querying Overpass API for the Hutt River / Te Awa Kairangi waterway...")
    req = urllib.request.Request(
        OVERPASS_URL,
        data=("data=" + QUERY).encode("utf-8"),
        headers={
            # Overpass API rejects requests with no/default User-Agent (406).
            "User-Agent": "HuttValleyFloodHazard-project/1.0 (personal portfolio project)",
            "Accept": "application/json",
        },
    )
    data = urllib.request.urlopen(req, timeout=90).read()
    result = json.loads(data)

    features = []
    for el in result.get("elements", []):
        if el.get("type") == "way" and "geometry" in el:
            coords = [[pt["lon"], pt["lat"]] for pt in el["geometry"]]
            features.append({
                "type": "Feature",
                "properties": {"id": el.get("id"), "tags": el.get("tags", {})},
                "geometry": {"type": "LineString", "coordinates": coords},
            })

    geojson = {"type": "FeatureCollection", "features": features}
    with open(OUT_PATH, "w") as f:
        json.dump(geojson, f)

    print(f"Found {len(features)} way segments.")
    print(f"Written to: {OUT_PATH}")
    if not features:
        print("WARNING: no segments found -- the name match or bbox may need adjusting.")


if __name__ == "__main__":
    main()
