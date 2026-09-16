"""
Validate the DEM-derived stream network (from step2_hydrology.py) against
the real Hutt River centerline (OpenStreetMap, data/hutt_river_osm.geojson).

Method: reproject the OSM river line into the DEM's CRS (NZTM2000), sample
points along it at a fixed interval, and for each sampled point measure the
distance to the nearest derived-stream cell. Report the distribution of
those distances -- this tells us directly whether the flow-accumulation
threshold chosen in step 2 (1 km^2 contributing area) actually recovers the
real river's location, rather than assuming it does.
"""

import json
import os

import numpy as np
import rasterio
from pyproj import Transformer
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, "data")
OUT_DIR = os.path.join(APP_DIR, "outputs")

RIVER_GEOJSON = os.path.join(DATA_DIR, "hutt_river_osm.geojson")
STREAM_5M = os.path.join(OUT_DIR, "stream_mask_5m.tif")
FACC_5M = os.path.join(OUT_DIR, "flow_accum_5m.tif")


def load_river_points_nztm():
    with open(RIVER_GEOJSON) as f:
        gj = json.load(f)

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2193", always_xy=True)

    # IMPORTANT: densify WITHIN each LineString feature separately. An
    # earlier version of this script flattened all features into one point
    # list before interpolating between consecutive points -- which drew a
    # fake straight-line "bridge" between the last point of one feature and
    # the first point of the next, even though those two features are two
    # separate OSM ways whose endpoints aren't necessarily adjacent along
    # the same line. That fabricated a long bogus chord across the valley
    # and badly inflated the distance stats. Caught by cross-checking
    # against an independent nearest-neighbour computation -- fixed here by
    # never interpolating across a feature boundary.
    densified = []
    for feat in gj["features"]:
        coords = feat["geometry"]["coordinates"]  # [lon, lat]
        pts = [transformer.transform(lon, lat) for lon, lat in coords]
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            seg_len = np.hypot(x1 - x0, y1 - y0)
            n_steps = max(1, int(seg_len // 25))
            for t in np.linspace(0, 1, n_steps, endpoint=False):
                densified.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
        densified.append(pts[-1])
    return np.array(densified)


def main():
    print("--- Loading real Hutt River centerline (OSM), reprojecting to NZTM2000 ---")
    river_pts = load_river_points_nztm()
    print(f"River sample points (after densifying to ~25m spacing): {len(river_pts)}")
    print(f"River extent (NZTM2000): x [{river_pts[:,0].min():.0f}, {river_pts[:,0].max():.0f}], "
          f"y [{river_pts[:,1].min():.0f}, {river_pts[:,1].max():.0f}]")

    with rasterio.open(STREAM_5M) as src:
        stream = src.read(1).astype(bool)
        transform = src.transform
        raster_bounds = src.bounds
        res = src.res[0]
    print(f"\nDerived stream raster: {stream.sum():,} stream cells at {res}m resolution")
    print(f"Raster bounds (NZTM2000): {raster_bounds}")

    # Distance (in cells) from every cell to the nearest stream cell, via
    # Euclidean distance transform on the inverse of the stream mask.
    dist_cells = distance_transform_edt(~stream)
    dist_m = dist_cells * res

    # Convert river points (map coords) to raster row/col
    inv_transform = ~transform
    rows, cols = [], []
    in_bounds_pts = []
    for x, y in river_pts:
        if not (raster_bounds.left <= x <= raster_bounds.right and
                raster_bounds.bottom <= y <= raster_bounds.top):
            continue
        col, row = inv_transform * (x, y)
        row, col = int(row), int(col)
        if 0 <= row < stream.shape[0] and 0 <= col < stream.shape[1]:
            rows.append(row)
            cols.append(col)
            in_bounds_pts.append((x, y))

    print(f"\nRiver points falling within this DEM tile-set's coverage: {len(rows)} of {len(river_pts)}")
    if len(rows) == 0:
        print("No overlap between the OSM river line and this DEM's extent -- cannot validate here.")
        return

    rows = np.array(rows)
    cols = np.array(cols)
    point_distances = dist_m[rows, cols]

    print(f"\n--- Distance from real river to nearest DEM-derived stream cell ---")
    print(f"Mean: {point_distances.mean():.1f} m")
    print(f"Median: {np.median(point_distances):.1f} m")
    print(f"90th percentile: {np.percentile(point_distances, 90):.1f} m")
    print(f"Max: {point_distances.max():.1f} m")
    for thresh in [10, 25, 50, 100, 200]:
        pct = 100 * (point_distances <= thresh).mean()
        print(f"  Within {thresh}m: {pct:.1f}% of sampled river points")

    # Also report: of the points that are NOT near a derived stream cell,
    # are they systematically at one end (e.g. headwaters where the real
    # river is too small to be captured at this resolution/threshold)?
    far = point_distances > 100
    if far.sum() > 0:
        far_pts = np.array(in_bounds_pts)[far]
        print(f"\n{far.sum()} points >100m from nearest derived stream cell.")
        print(f"  Their y-range (NZTM northing): {far_pts[:,1].min():.0f} to {far_pts[:,1].max():.0f}")
        print(f"  (compare to full river y-range above to see if these cluster at one end)")

    # --- Threshold sensitivity: was 1.0 km^2 (the choice made in step 2)
    # actually a reasonable pick, or would a different contributing-area
    # threshold have matched the real river better? Checked directly
    # rather than assumed.
    print(f"\n--- Threshold sensitivity (contributing area -> match quality) ---")
    xy = np.array(in_bounds_pts)
    with rasterio.open(FACC_5M) as src:
        acc = src.read(1)
    for thresh_km2 in [0.1, 0.25, 0.5, 1.0, 2.0, 4.0]:
        thresh_cells = thresh_km2 * 1e6 / (res ** 2)
        mask = acc > thresh_cells
        sr, sc = np.where(mask)
        if len(sr) == 0:
            print(f"  {thresh_km2} km^2: no cells above threshold")
            continue
        sx = transform.c + (sc + 0.5) * transform.a
        sy = transform.f + (sr + 0.5) * transform.e
        tree = cKDTree(np.column_stack([sx, sy]))
        d, _ = tree.query(xy)
        print(f"  {thresh_km2:>5} km^2 ({int(thresh_cells):>6} cells): "
              f"n_stream_cells={mask.sum():>7,}  median_dist={np.median(d):>5.1f}m  "
              f"within_50m={100*(d<=50).mean():>5.1f}%  within_100m={100*(d<=100).mean():>5.1f}%")


if __name__ == "__main__":
    main()
