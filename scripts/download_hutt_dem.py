"""
Download the Hutt City (2021) 1m LiDAR DEM tiles from LINZ's public
'nz-elevation' AWS Open Data bucket.

No login, no API key, no AWS account needed -- the bucket is public and
the data is released under CC-BY-4.0 (must attribute Toitu Te Whenua LINZ).
Source: https://github.com/linz/elevation

Run this on your own machine (not in the sandbox -- it has no outbound
access to this bucket). From this project folder:

    python3 scripts/download_hutt_dem.py

Downloads ~156MB total (12 GeoTIFF tiles + metadata) into
data/dem_1m_raw/. Safe to re-run -- skips files already downloaded.
"""

import os
import urllib.request

BASE = "https://nz-elevation.s3-ap-southeast-2.amazonaws.com/wellington/hutt-city_2021/dem_1m/2193/"

TILES = [
    "BP32_10000_0502.tiff",
    "BP32_10000_0503.tiff",
    "BQ31_10000_0105.tiff",
    "BQ31_10000_0205.tiff",
    "BQ32_10000_0101.tiff",
    "BQ32_10000_0102.tiff",
    "BQ32_10000_0103.tiff",
    "BQ32_10000_0201.tiff",
    "BQ32_10000_0202.tiff",
    "BQ32_10000_0203.tiff",
    "BQ32_10000_0301.tiff",
    "BQ32_10000_0302.tiff",
]
EXTRAS = ["capture-area.geojson", "collection.json"]

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dem_1m_raw")
os.makedirs(OUT_DIR, exist_ok=True)


def fetch(name):
    dest = os.path.join(OUT_DIR, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"  already have {name}, skipping")
        return
    url = BASE + name
    print(f"  downloading {name} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"    -> {os.path.getsize(dest) / 1e6:.1f} MB")


if __name__ == "__main__":
    print(f"Downloading Hutt City 2021 1m LiDAR DEM into {OUT_DIR}")
    for f in TILES + EXTRAS:
        fetch(f)
    print("Done. 12 DEM tiles + capture-area.geojson + collection.json ready to mosaic.")
