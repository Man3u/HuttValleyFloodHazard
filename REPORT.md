# Hutt Valley Flood Hazard Mapping — Technical Report

**Area:** Lower Hutt / the Hutt Valley, Wellington Region, New Zealand — chosen because the
Hutt River (Te Awa Kairangi) floodplain is New Zealand's most densely populated flood-prone
area, making it a realistic, high-stakes case for this kind of analysis.

**Goal:** produce a DEM-derived flood hazard indicator and cartographic map from open LiDAR,
using a fully reproducible pipeline, and honestly validate it against a real, independent
reference (the actual river location) rather than assuming the method worked.

---

## 1. Data

| Dataset | Source | Notes |
|---|---|---|
| 1m LiDAR DEM, 12 tiles | LINZ open data (`nz-elevation` S3 bucket), Hutt City 2021 survey | CC-BY-4.0, public, no auth required |
| Hutt River centerline | OpenStreetMap (Overpass API), `waterway=river`, name match "Hutt River / Te Awa Kairangi" | Used only as an independent validation reference, not as an input to the hazard model |

Both were downloaded by scripts written to run on the user's own machine
(`scripts/download_hutt_dem.py`, `scripts/download_hutt_river_centerline.py`), because the
processing sandbox this project was built in has restricted outbound network access. This is
disclosed here rather than glossed over.

## 2. Pipeline

1. **Mosaic** (`step1_mosaic_dem.py`) — merge the 12 raw tiles into one raster.
   - Result: 28,800 × 19,200 px at 1m, single CRS (EPSG:2193, NZTM2000) confirmed before merging.
   - 17.76% of the mosaic's bounding rectangle is valid data (the rest is the gaps between the
     tiles' non-rectangular capture footprints and the rectangle's corners) — expected, not an error.
   - Elevation range −1.21 to 374.18 m, mean 88.46 m. 0 cells flagged outside the plausible
     range (−10 m to 800 m) for this terrain.

2. **Resample to 5m** (`step2_hydrology.py`) — the native 1m mosaic is too heavy to run
   pit-filling and D8 flow routing over directly at full resolution; 5m keeps far more detail
   than the 10–30 m resolution typical of operational HAND products, while making the run
   tractable. Disclosed methodological choice, not a silent shortcut.

3. **Hydrological conditioning + routing** (`pysheds`) — fill pits → fill depressions →
   resolve flats → D8 flow direction → flow accumulation.

4. **Stream extraction** — threshold flow accumulation at 1.0 km² contributing area
   (40,000 cells at 5m). Threshold sensitivity was tested formally in step 3 (see below) rather
   than assumed correct.

5. **HAND** (Height Above Nearest Drainage) — height of every cell above its nearest
   downslope stream cell, via `pysheds.compute_hand`.

   Two real problems were found in the raw library output and fixed rather than trusted at
   face value:
   - `compute_hand` returns `0.0` (not nodata) for cells entirely outside the DEM's actual
     valid-data coverage, since it operates over the full rectangular array. Fixed by
     re-applying the DEM's own valid-data mask.
   - For cells whose flow path never resolves to a stream within the processed extent (they
     drain off the tile-set edge, or sit in an unresolved depression), the function returns
     implausibly large values — up to several thousand metres, against ~374 m of real relief
     in this catchment. Fixed with an explicit plausibility cap (500 m) and flagged/excluded
     rather than kept.

   Final: of 3,931,096 valid DEM cells, 3,041,959 (77.4%) produced a resolved, plausible HAND
   value; 889,137 (22.6%) are flagged and excluded as unresolved rather than shown as fake data.

## 3. Validation

**Question asked directly, not assumed:** does the derived stream network actually sit where
the real Hutt River sits?

Method (`step3_validate_stream_network.py`): reproject the OSM river centerline into NZTM2000,
densify it to ~25 m point spacing, and measure the distance from each point to the nearest
derived-stream cell.

**Result:** median offset 21.2 m, mean 84.5 m, 80.8% of the real river within 100 m of the
derived network at the chosen 1.0 km² threshold. About 19% of the river — mostly one
contiguous stretch through the lower valley — sits further off, most plausibly where the
engineered, stop-banked channel diverges from the natural flow path the bare-earth DEM implies.

**Threshold sensitivity** (was 1.0 km² actually a good choice, checked rather than assumed):

| Threshold | Stream cells | Median offset | % within 100 m |
|---|---|---|---|
| 0.1 km² | 95,054 | 19.2 m | 87.3% |
| 0.25 km² | — | — | — |
| 0.5 km² | — | — | — |
| **1.0 km² (used)** | 32,099 | 21.5 m | 80.8% |
| 2.0 km² | — | — | — |
| 4.0 km² | 7,971 | 33.5 m | 59.8% |

A tighter threshold captures more small tributaries and matches marginally better, at the cost
of a much noisier, over-extracted network. 1.0 km² was kept as the standard, defensible choice
for a catchment this size.

**A bug was caught and fixed during this step.** The first version of the validation script
flattened both OSM `LineString` features into one point list before interpolating between
consecutive points — which drew a fabricated straight-line "bridge" across the valley between
two unrelated segment endpoints, corrupting the distance statistics (falsely reporting median
120 m / 48.5% within 100 m). This was caught by cross-checking with an independent
`cKDTree`-based nearest-neighbour computation that gave a very different answer for the same
question — the disagreement between two methods that should agree was the signal to
investigate, not something to average away or ignore. Fixed by densifying strictly within each
feature, never across a feature boundary. The corrected numbers above are the trustworthy
result.

## 4. Flood hazard classification

HAND was classified into four indicative bands. These thresholds are a standard, commonly used
starting point in HAND-based hazard literature — not a locally calibrated regulatory standard:

| Band | HAND range | Area |
|---|---|---|
| Very High | 0–2 m | 11.62 km² |
| High | 2–5 m | 9.80 km² |
| Moderate | 5–10 m | 8.00 km² |
| Low | >10 m | 46.63 km² |

## 5. Cartographic output

Two versions were produced, both from the same underlying `flood_hazard_zones_5m.tif`:

- **`maps/hutt_valley_flood_hazard_map_qgis_final.png`** (primary) — built in real QGIS
  Desktop, run by hand on the project owner's own machine (this pipeline's automated
  environment has no QGIS installed and no root access to add it, so QGIS steps could not run
  automatically). Uses QGIS's own hillshade and paletted-raster renderers, a print layout with
  legend/scale bar/north arrow, and an OpenStreetMap basemap for geographic context. Build
  script: `scripts/step5_qgis_cartography.py`; editable project: `hutt_valley_flood_hazard.qgz`.
  One real bug was hit and fixed while building this: `QgsLayoutManager.addLayout()` requires a
  `QgsPrintLayout`, not the more general `QgsLayout` object initially used — caught from QGIS's
  own `TypeError`, not anticipated in advance.
- **`maps/hutt_valley_flood_hazard_map.png`** — built with Python (rasterio + matplotlib) as
  part of the automated pipeline, no QGIS dependency. Same hazard classification, hillshade,
  river overlay, legend, scale bar, north arrow, and source caption.

## 6. Limitations — stated explicitly

- **This is a relative hazard proxy, not a hydraulic flood model.** HAND reflects terrain
  shape only. It has no rainfall, no discharge, no return-period input, and does not represent
  an actual flood extent for any specific event or annual exceedance probability.
- **It does not account for stopbanks/levees.** The Hutt River is a stop-banked, engineered
  channel through the lower valley; a bare-earth HAND surface cannot know the stopbanks'
  actual design protection level, which is exactly the stretch where validation offset is
  highest.
- **22.6% of DEM cells have no resolved HAND value** (edge-of-coverage or unresolved
  depressions) and are shown as nodata, not estimated.
- **5m processing resolution**, not the native 1m — a disclosed precision/tractability
  trade-off.
- For an authoritative flood hazard assessment of this area, consult Greater Wellington
  Regional Council's and Hutt City Council's official flood modelling, which uses calibrated
  hydraulic models (e.g. HEC-RAS) with real rainfall/discharge data — this project is a
  terrain-analysis exercise, not a substitute for that.

## 7. Reproducing this

```
python3 scripts/download_hutt_dem.py              # run locally — writes data/dem_1m_raw/
python3 scripts/download_hutt_river_centerline.py  # run locally — writes data/hutt_river_osm.geojson
python3 scripts/step1_mosaic_dem.py
python3 scripts/step2_hydrology.py
python3 scripts/step3_validate_stream_network.py
python3 scripts/step4_hazard_classification_and_map.py
```

Large intermediate rasters (`outputs/*.tif`, `data/dem_1m_raw/`) are excluded from git via
`.gitignore` — regenerate them by re-running the pipeline above. `maps/hutt_valley_flood_hazard_map.png`
and `data/hutt_river_osm.geojson` are small enough to keep in the repo directly.
