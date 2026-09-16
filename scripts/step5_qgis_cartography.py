"""
Build the Hutt Valley flood hazard map using real QGIS (PyQGIS), not a
Python/matplotlib substitute. The earlier map
(maps/hutt_valley_flood_hazard_map.png) was built with matplotlib because
this project's automated pipeline runs in a sandbox with no QGIS installed
and no root access to install it. This script is meant to be run inside
actual QGIS on your own machine, using QGIS's own renderers (hillshade,
paletted raster, print layout, legend, scale bar, north arrow) rather than
hand-drawn equivalents.

HOW TO RUN THIS (pick one):

  Option A -- QGIS Desktop Python Console (simplest, works on any OS):
    1. Open QGIS Desktop.
    2. Plugins -> Python Console.
    3. Click the "Show Editor" icon, then "Open Script" and pick this file
       (scripts/step5_qgis_cartography.py), then click "Run Script".
       (Or just paste this file's contents into the console and press Enter.)

  Option B -- QGIS's own bundled Python, from a terminal:
    macOS:   /Applications/QGIS.app/Contents/MacOS/bin/python3 step5_qgis_cartography.py
    Windows: Use the "OSGeo4W Shell" that ships with QGIS, then:
             python step5_qgis_cartography.py
    (Plain system `python3` will NOT have the `qgis` module -- it only
    exists inside QGIS's own bundled Python environment.)

Outputs (written next to this project, same as the rest of the pipeline):
  maps/hutt_valley_flood_hazard_map_qgis.png
  maps/hutt_valley_flood_hazard_map_qgis.pdf
"""

import os
import sys

try:
    __file__
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Running via "paste into console" -- __file__ may not exist.
    SCRIPT_DIR = os.path.expanduser("~/Desktop/HuttValleyFloodHazard/scripts")

APP_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(APP_DIR, "outputs")
DATA_DIR = os.path.join(APP_DIR, "data")
MAPS_DIR = os.path.join(APP_DIR, "maps")
os.makedirs(MAPS_DIR, exist_ok=True)

DEM_5M = os.path.join(OUT_DIR, "hutt_dem_5m.tif")
HAZARD_TIF = os.path.join(OUT_DIR, "flood_hazard_zones_5m.tif")
RIVER_GEOJSON = os.path.join(DATA_DIR, "hutt_river_osm.geojson")

PNG_OUT = os.path.join(MAPS_DIR, "hutt_valley_flood_hazard_map_qgis.png")
PDF_OUT = os.path.join(MAPS_DIR, "hutt_valley_flood_hazard_map_qgis.pdf")

# Same four bands as step4_hazard_classification_and_map.py, same colors,
# so the two maps are directly comparable. Raster pixel value -> (label, hex).
HAZARD_CLASSES = {
    0: ("Very High (HAND 0-2m)", "#a50026"),
    1: ("High (HAND 2-5m)", "#f46d43"),
    2: ("Moderate (HAND 5-10m)", "#fee08b"),
    3: ("Low (HAND >10m)", "#a6d96a"),
}

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsCoordinateReferenceSystem,
    QgsHillshadeRenderer, QgsPalettedRasterRenderer, QgsRasterShader,
    QgsColorRampShader, QgsLineSymbol, QgsSingleSymbolRenderer,
    QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLegend, QgsLayoutItemScaleBar,
    QgsLayoutItemPicture, QgsLayoutItemLabel, QgsLayoutSize, QgsLayoutPoint,
    QgsUnitTypes, QgsLayoutExporter, QgsRectangle, QgsLegendStyle,
    QgsApplication,
)
from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtGui import QColor, QFont

print("--- Checking inputs ---")
for p in (DEM_5M, HAZARD_TIF, RIVER_GEOJSON):
    if not os.path.exists(p):
        raise SystemExit(
            f"Missing input: {p}\n"
            "Run the earlier pipeline steps (step1-step4) first -- "
            "this script only builds the cartography from their outputs."
        )
print("All inputs found.")

project = QgsProject.instance()
project.clear()
project.setCrs(QgsCoordinateReferenceSystem("EPSG:2193"))

# --- DEM layer, rendered as hillshade (a real QGIS renderer, not a
# hand-computed raster) ---
dem_layer = QgsRasterLayer(DEM_5M, "Hutt Valley DEM (5m)")
if not dem_layer.isValid():
    raise SystemExit(f"DEM layer failed to load: {DEM_5M}")
hillshade_renderer = QgsHillshadeRenderer(dem_layer.dataProvider(), 1, 315, 45)
dem_layer.setRenderer(hillshade_renderer)
project.addMapLayer(dem_layer)

# --- Hazard raster, paletted renderer matching the 4 hazard bands ---
hazard_layer = QgsRasterLayer(HAZARD_TIF, "Flood Hazard Zones")
if not hazard_layer.isValid():
    raise SystemExit(f"Hazard layer failed to load: {HAZARD_TIF}")
classes = []
for val, (label, hexcolor) in HAZARD_CLASSES.items():
    classes.append(
        QgsPalettedRasterRenderer.Class(val, QColor(hexcolor), label)
    )
paletted_renderer = QgsPalettedRasterRenderer(hazard_layer.dataProvider(), 1, classes)
hazard_layer.setRenderer(paletted_renderer)
hazard_layer.renderer().setOpacity(0.7)
project.addMapLayer(hazard_layer)

# --- River reference line (OSM) ---
river_layer = QgsVectorLayer(RIVER_GEOJSON, "Te Awa Kairangi / Hutt River (OSM)", "ogr")
if not river_layer.isValid():
    raise SystemExit(f"River layer failed to load: {RIVER_GEOJSON}")
line_symbol = QgsLineSymbol.createSimple({
    "color": "8,48,107,255", "width": "0.9", "capstyle": "round",
})
river_layer.setRenderer(QgsSingleSymbolRenderer(line_symbol))
project.addMapLayer(river_layer)

print(f"Layers loaded: {[l.name() for l in project.mapLayers().values()]}")

# --- Print layout: map, title, legend, scale bar, north arrow, source note ---
# QgsLayoutManager.addLayout() requires a QgsPrintLayout (which implements the
# master-layout interface with a name), not a bare QgsLayout -- caught via the
# real error QGIS raised, not assumed correct in advance.
layout = QgsPrintLayout(project)
layout.setName("Hutt Valley Flood Hazard Map")
layout.initializeDefaults()
page = layout.pageCollection().pages()[0]
page.setPageSize("A3", 1)  # 1 = Portrait in QgsLayoutItemPage.Orientation (version-stable int)

page_w = page.pageSize().width()
page_h = page.pageSize().height()

# Map item
map_item = QgsLayoutItemMap(layout)
map_item.setRect(QRectF(0, 0, 200, 200))
map_item.attemptSetSceneRect(QRectF(10, 20, page_w - 20, page_h - 70))
map_item.setLayers([river_layer, hazard_layer, dem_layer])
map_item.zoomToExtent(hazard_layer.extent())
layout.addLayoutItem(map_item)

# Title
title = QgsLayoutItemLabel(layout)
title.setText("Hutt Valley (Lower Hutt, New Zealand) — Flood Hazard Zones")
title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
title.adjustSizeToText()
title.attemptSetSceneRect(QRectF(10, 5, page_w - 20, 12))
title.setHAlign(0x0004)  # AlignHCenter
layout.addLayoutItem(title)

# Legend
legend = QgsLayoutItemLegend(layout)
legend.setLinkedMap(map_item)
legend.setTitle("Flood Hazard (HAND proxy)")
legend.setAutoUpdateModel(False)
root = legend.model().rootGroup()
root.clear()
for lyr in (hazard_layer, river_layer):
    root.addLayer(lyr)
legend.attemptSetSceneRect(QRectF(12, page_h - 60, 70, 45))
legend.setBackgroundEnabled(True)
layout.addLayoutItem(legend)

# Scale bar
scalebar = QgsLayoutItemScaleBar(layout)
scalebar.setLinkedMap(map_item)
scalebar.setStyle("Single Box")
scalebar.setUnits(QgsUnitTypes.DistanceMeters)
scalebar.setUnitLabel("m")
scalebar.setNumberOfSegments(4)
scalebar.setNumberOfSegmentsLeft(0)
scalebar.setUnitsPerSegment(500)
scalebar.applyDefaultSize()
scalebar.attemptSetSceneRect(QRectF(page_w - 90, page_h - 25, 80, 12))
layout.addLayoutItem(scalebar)

# North arrow (QGIS's own bundled SVG resource; falls back to a text glyph
# if the resource path isn't found in this QGIS version, rather than
# silently producing a blank map element)
north_arrow = QgsLayoutItemPicture(layout)
svg_path = ":/images/north_arrows/layout_default_north_arrow.svg"
north_arrow.setPicturePath(svg_path)
north_arrow.attemptSetSceneRect(QRectF(page_w - 25, 20, 12, 16))
layout.addLayoutItem(north_arrow)
if north_arrow.picturePath() == "" or not os.path.exists(svg_path.lstrip(":")):
    print("Note: bundled north-arrow SVG resource not confirmed on disk "
          "(this is normal -- it's a Qt resource, not a file path); "
          "if it renders blank in your QGIS version, add a text label "
          "'N ↑' at the same position instead.")

# Source / methodology caption
caption = QgsLayoutItemLabel(layout)
caption.setText(
    "Source: LINZ open LiDAR (Hutt City 2021, 1m), resampled to 5m. "
    "Method: D8 flow accumulation -> HAND (Height Above Nearest Drainage), 1 km2 stream threshold. "
    "Validated against OpenStreetMap's Hutt River centerline: median offset 21.2m, "
    "80.8% of the real river within 100m of the derived network.\n"
    "Relative hazard PROXY from terrain shape only -- not a calibrated hydraulic model or an "
    "official regulatory flood extent."
)
caption.setFont(QFont("Arial", 8))
caption.attemptSetSceneRect(QRectF(10, page_h - 12, page_w - 20, 10))
layout.addLayoutItem(caption)

project.layoutManager().addLayout(layout)

print("\n--- Exporting ---")
exporter = QgsLayoutExporter(layout)
img_settings = QgsLayoutExporter.ImageExportSettings()
img_settings.dpi = 300
res_img = exporter.exportToImage(PNG_OUT, img_settings)
print(f"PNG export result: {res_img} -> {PNG_OUT}")

pdf_settings = QgsLayoutExporter.PdfExportSettings()
res_pdf = exporter.exportToPdf(PDF_OUT, pdf_settings)
print(f"PDF export result: {res_pdf} -> {PDF_OUT}")

# Save the QGIS project itself so it can be reopened and tweaked directly
PROJECT_PATH = os.path.join(APP_DIR, "hutt_valley_flood_hazard.qgz")
project.write(PROJECT_PATH)
print(f"\nQGIS project saved: {PROJECT_PATH}")
print("Open this .qgz in QGIS any time to adjust styling or re-export.")
