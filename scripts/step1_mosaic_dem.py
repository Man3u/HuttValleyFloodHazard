"""
Mosaic the 12 Hutt City 2021 1m LiDAR DEM tiles into a single raster, and
run basic QA checks before any hydrology processing.

Deliberately keeps every tile's real data -- no cropping to a "nicer"
extent that would throw away genuine coverage -- and reports data-quality
issues (voids, extreme outlier cells) explicitly rather than silently
patching over them.
"""

import glob
import os

import numpy as np
import rasterio
from rasterio.merge import merge

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(APP_DIR, "data", "dem_1m_raw")
OUT_DIR = os.path.join(APP_DIR, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

MOSAIC_PATH = os.path.join(OUT_DIR, "hutt_dem_1m_mosaic.tif")


def main():
    tile_paths = sorted(glob.glob(os.path.join(RAW_DIR, "*.tiff")))
    print(f"Found {len(tile_paths)} DEM tiles:")
    for p in tile_paths:
        print(f"  {os.path.basename(p)}")
    assert len(tile_paths) == 12, f"Expected 12 tiles, found {len(tile_paths)}"

    srcs = [rasterio.open(p) for p in tile_paths]
    crs_set = {s.crs.to_epsg() for s in srcs}
    print(f"\nCRS across tiles: {crs_set}")
    assert len(crs_set) == 1, "Tiles are in inconsistent CRSs -- would silently misalign if merged as-is"

    mosaic, out_transform = merge(srcs, nodata=srcs[0].nodata)
    print(f"\nMosaic shape: {mosaic.shape}  (bands, rows, cols)")
    print(f"Pixel size: {out_transform.a} x {abs(out_transform.e)} (map units, should be ~1m)")

    band = mosaic[0]
    nodata_val = srcs[0].nodata
    print(f"\nNodata value: {nodata_val}")

    valid = band != nodata_val
    if nodata_val is not None and not np.isnan(nodata_val):
        valid &= ~np.isnan(band)
    else:
        valid &= ~np.isnan(band)

    n_total = band.size
    n_valid = int(valid.sum())
    n_void = n_total - n_valid
    print(f"\n--- QA: void / coverage check ---")
    print(f"Total cells: {n_total:,}")
    print(f"Valid (data) cells: {n_valid:,} ({100 * n_valid / n_total:.2f}%)")
    print(f"Void/nodata cells: {n_void:,} ({100 * n_void / n_total:.2f}%)")
    print("(Void cells are expected here: the mosaic's bounding rectangle covers a wider")
    print(" area than the union of the 12 irregular tile footprints, plus each tile itself")
    print(" is a non-rectangular LiDAR capture polygon. These are boundary/no-capture areas,")
    print(" not sensor error -- they are preserved as nodata, not filled with a fabricated value.)")

    valid_vals = band[valid]
    print(f"\n--- QA: elevation range check ---")
    print(f"Min elevation: {valid_vals.min():.2f} m")
    print(f"Max elevation: {valid_vals.max():.2f} m")
    print(f"Mean elevation: {valid_vals.mean():.2f} m")
    print(f"1st / 99th percentile: {np.percentile(valid_vals, 1):.2f} / {np.percentile(valid_vals, 99):.2f} m")

    # Lower Hutt sits on a coastal floodplain rising to surrounding hill country;
    # sanity-check the range is physically plausible for this area (sea level to
    # a few hundred metres in the surrounding hills captured at tile edges).
    implausible = (valid_vals < -10) | (valid_vals > 800)
    n_implausible = int(implausible.sum())
    print(f"\nCells outside plausible range (-10m to 800m) for this area: {n_implausible:,}"
          f" ({100 * n_implausible / n_valid:.4f}% of valid cells)")
    if n_implausible > 0:
        print("  -> Flagged, not silently dropped. See flagged value range below.")
        print(f"     Flagged min/max: {valid_vals[implausible].min():.2f} / {valid_vals[implausible].max():.2f}")

    profile = srcs[0].profile.copy()
    profile.update({
        "height": mosaic.shape[1],
        "width": mosaic.shape[2],
        "transform": out_transform,
        "compress": "lzw",
    })
    with rasterio.open(MOSAIC_PATH, "w", **profile) as dst:
        dst.write(mosaic)

    for s in srcs:
        s.close()

    print(f"\nMosaic written to: {MOSAIC_PATH}")
    print(f"File size: {os.path.getsize(MOSAIC_PATH) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
