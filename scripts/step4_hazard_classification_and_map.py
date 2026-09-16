"""
Classify HAND into flood hazard zones and produce a cartographic map of
Lower Hutt / the Hutt Valley.

Hazard bands (HAND-based, a standard, cheap-to-compute relative hazard
proxy -- explicitly NOT a substitute for a calibrated hydraulic model /
official regulatory flood extent, and the map says so):
  Very High : HAND <= 2m
  High      : 2m  < HAND <= 5m
  Moderate  : 5m  < HAND <= 10m
  Low       : HAND > 10m

Cartography built with Python (rasterio + matplotlib), not a QGIS GUI --
this sandbox has no QGIS installed, so the map is produced programmatically
rather than claimed to be a QGIS export.
"""

import json
import os

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Rectangle
from matplotlib_scalebar.scalebar import ScaleBar
from pyproj import Transformer
from rasterio.transform import xy as transform_xy

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(APP_DIR, "outputs")
DATA_DIR = os.path.join(APP_DIR, "data")
MAPS_DIR = os.path.join(APP_DIR, "maps")
os.makedirs(MAPS_DIR, exist_ok=True)

DEM_5M = os.path.join(OUT_DIR, "hutt_dem_5m.tif")
HAND_5M = os.path.join(OUT_DIR, "hand_5m.tif")
RIVER_GEOJSON = os.path.join(DATA_DIR, "hutt_river_osm.geojson")
HAZARD_TIF = os.path.join(OUT_DIR, "flood_hazard_zones_5m.tif")
MAP_PNG = os.path.join(MAPS_DIR, "hutt_valley_flood_hazard_map.png")

HAZARD_BANDS = [
    (0, 2, "Very High", "#a50026"),
    (2, 5, "High", "#f46d43"),
    (5, 10, "Moderate", "#fee08b"),
    (10, np.inf, "Low", "#a6d96a"),
]


def hillshade(dem, cellsize, azimuth=315, altitude=45):
    az = np.radians(360.0 - azimuth + 90)
    alt = np.radians(altitude)
    dy, dx = np.gradient(dem, cellsize)
    slope = np.pi / 2.0 - np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    shaded = (np.sin(alt) * np.sin(slope) +
              np.cos(alt) * np.cos(slope) * np.cos(az - aspect))
    return np.clip(shaded, -1, 1)


def classify_hazard(hand_arr, valid_mask):
    hazard = np.full(hand_arr.shape, 255, dtype="uint8")  # 255 = nodata/unresolved
    for i, (lo, hi, name, color) in enumerate(HAZARD_BANDS):
        band_mask = valid_mask & (hand_arr > lo if lo > 0 else hand_arr >= lo) & (hand_arr <= hi)
        hazard[band_mask] = i
    return hazard


def main():
    with rasterio.open(DEM_5M) as src:
        dem = src.read(1)
        dem_nodata = src.nodata
        transform = src.transform
        crs = src.crs
        res = src.res[0]
        bounds = src.bounds

    with rasterio.open(HAND_5M) as src:
        hand = src.read(1)
        hand_nodata = src.nodata

    valid_mask = (hand != hand_nodata) & np.isfinite(hand)
    print(f"Classifying {int(valid_mask.sum()):,} resolved HAND cells into hazard zones...")

    hazard = classify_hazard(hand, valid_mask)

    counts = {}
    for i, (lo, hi, name, color) in enumerate(HAZARD_BANDS):
        n = int((hazard == i).sum())
        counts[name] = n
        area_km2 = n * (res ** 2) / 1e6
        print(f"  {name:12s} (HAND {lo}-{hi if hi != np.inf else '>10'}m): "
              f"{n:>9,} cells = {area_km2:.2f} km^2")

    profile = {
        "driver": "GTiff", "dtype": "uint8", "nodata": 255,
        "width": hazard.shape[1], "height": hazard.shape[0],
        "count": 1, "crs": crs, "transform": transform, "compress": "lzw",
    }
    with rasterio.open(HAZARD_TIF, "w", **profile) as dst:
        dst.write(hazard[np.newaxis, :, :])
    print(f"\nHazard raster written to: {HAZARD_TIF}")

    # --- Cartography ---
    print("\nBuilding cartographic map...")
    dem_valid = (dem != dem_nodata) & np.isfinite(dem)
    dem_for_shade = np.where(dem_valid, dem, np.nan)
    hs = hillshade(np.nan_to_num(dem_for_shade, nan=0.0), res)

    cmap = ListedColormap([c for _, _, _, c in HAZARD_BANDS])
    bounds_cls = list(range(len(HAZARD_BANDS) + 1))
    norm = BoundaryNorm(bounds_cls, cmap.N)

    hazard_plot = np.ma.masked_where(hazard == 255, hazard)

    with open(RIVER_GEOJSON) as f:
        river_gj = json.load(f)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2193", always_xy=True)

    fig, ax = plt.subplots(figsize=(12, 14), dpi=200)

    extent = (bounds.left, bounds.right, bounds.bottom, bounds.top)
    ax.imshow(hs, cmap="gray", extent=extent, origin="upper", alpha=1.0)
    ax.imshow(hazard_plot, cmap=cmap, norm=norm, extent=extent, origin="upper", alpha=0.65)

    for feat in river_gj["features"]:
        coords = feat["geometry"]["coordinates"]
        xy = [transformer.transform(lon, lat) for lon, lat in coords]
        xs, ys = zip(*xy)
        ax.plot(xs, ys, color="#08306b", linewidth=1.8, solid_capstyle="round",
                label="Te Awa Kairangi / Hutt River (OSM reference)")

    # Zoom to the union of the valid DEM extent (drop the wide nodata margins)
    rows, cols = np.where(dem_valid)
    if len(rows):
        r0, r1 = rows.min(), rows.max()
        c0, c1 = cols.min(), cols.max()
        x0, y0 = transform_xy(transform, r1, c0)
        x1, y1 = transform_xy(transform, r0, c1)
        pad = 500
        ax.set_xlim(x0 - pad, x1 + pad)
        ax.set_ylim(y0 - pad, y1 + pad)

    ax.set_title("Hutt Valley (Lower Hutt, New Zealand) -- Flood Hazard Zones",
                  fontsize=16, fontweight="bold", pad=14)
    ax.set_xlabel("NZTM2000 Easting (m)", fontsize=9)
    ax.set_ylabel("NZTM2000 Northing (m)", fontsize=9)
    ax.tick_params(labelsize=8)

    handles = [Rectangle((0, 0), 1, 1, facecolor=c, alpha=0.75, edgecolor="none")
               for _, _, _, c in HAZARD_BANDS]
    labels = [f"{name} (HAND {lo}-{hi if hi != np.inf else '>10'}m)"
              for lo, hi, name, _ in HAZARD_BANDS]
    river_line = ax.get_legend_handles_labels()
    handles += river_line[0][:1]
    labels += river_line[1][:1]
    legend = ax.legend(handles, labels, loc="lower left", fontsize=8.5,
                        title="Flood hazard (HAND proxy)", title_fontsize=9,
                        framealpha=0.92)

    scalebar = ScaleBar(1, units="m", location="lower right", box_alpha=0.85, font_properties={"size": 8})
    ax.add_artist(scalebar)

    ax.annotate("N", xy=(0.965, 0.16), xytext=(0.965, 0.09),
                xycoords="axes fraction",
                arrowprops=dict(facecolor="black", width=4, headwidth=12, headlength=12),
                ha="center", fontsize=13, fontweight="bold")

    caption = (
        "Source: LINZ open LiDAR (Hutt City 2021, 1m), resampled to 5m for hydrology processing.\n"
        "Method: D8 flow accumulation -> stream network (1 km2 contributing-area threshold) -> "
        "HAND (Height Above Nearest Drainage).\n"
        "Validated against OpenStreetMap's Hutt River centerline: median offset 21.2m, "
        "80.8% of the real river within 100m of the derived network.\n"
        "This is a relative hazard PROXY from terrain shape alone, not a calibrated hydraulic model "
        "or an official regulatory flood extent -- it has no rainfall/discharge input and does not "
        "account for stopbanks' actual protection level."
    )
    fig.text(0.5, 0.015, caption, ha="center", fontsize=7.3, wrap=True, color="#333333")

    plt.tight_layout(rect=[0, 0.05, 1, 1])
    plt.savefig(MAP_PNG, dpi=200, bbox_inches="tight")
    print(f"\nMap written to: {MAP_PNG}")


if __name__ == "__main__":
    main()
