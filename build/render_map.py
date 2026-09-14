#!/usr/bin/env python
"""
Draw a static picture of the moratoria layer for the README.

    python build/render_map.py

Reads   data/nc_datacenter_moratoria.geojson   (written by build_layer.py)
        data/summary.json
Writes  data/map.png

GitHub's built-in GeoJSON preview draws every shape in one default color and
opens no popups, so the README shows this picture instead. Colors and outlines
come from the same style() function that styles the layer, so the picture
cannot disagree with it.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgba
from matplotlib.patches import Patch

import build_layer as layer

ROOT = Path(__file__).resolve().parent.parent
GEOJSON = ROOT / "data" / "nc_datacenter_moratoria.geojson"
SUMMARY = ROOT / "data" / "summary.json"
PNG = ROOT / "data" / "map.png"

DPI = 150
PX = 72 / DPI   # style widths are screen pixels; matplotlib wants points
INK, MUTED = "#1F2328", "#57606A"


def patch_style(s: dict) -> dict:
    return {"facecolor": to_rgba(s["fill"], s["fill-opacity"]),
            "edgecolor": to_rgba(s["stroke"], s["stroke-opacity"]),
            "linewidth": s["stroke-width"] * PX}


def main() -> None:
    features = gpd.read_file(GEOJSON).to_crs("EPSG:32119")
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    as_of = date.fromisoformat(summary["status_as_of"])

    fig = plt.figure(figsize=(12, 6.28), dpi=DPI, facecolor="white")
    ax = fig.add_axes((0.015, 0.075, 0.97, 0.745))
    ax.set_axis_off()
    ax.set_aspect("equal")

    # The layer is already in draw order: counties, then municipalities, then
    # the tribal nation, with records needing confirmation last in each.
    keys = ("fill", "fill-opacity", "stroke", "stroke-width", "stroke-opacity")
    for _, f in features.iterrows():
        gpd.GeoSeries([f.geometry]).plot(ax=ax, **patch_style({k: f[k] for k in keys}))
    counties = features[features["level"] == "County"]
    gpd.GeoSeries([counties.union_all().boundary]).plot(ax=ax, color="#8C959F", linewidth=0.7)

    categories = [
        Patch(label=cat, **patch_style(layer.style("county", cat, False)))
        for cat in (layer.IN_EFFECT, layer.CONSIDERING, layer.ENDED_CAT, layer.NO_ACTION)
    ]
    shapes = [
        Patch(label="County action: filled",
              **patch_style(layer.style("county", layer.IN_EFFECT, False))),
        Patch(label="City, town, or tribal action: outlined",
              **patch_style(layer.style("municipal", layer.IN_EFFECT, False))),
        Patch(label="Record still needs confirmation", facecolor="none",
              edgecolor="#111111", linewidth=layer.style("county", layer.IN_EFFECT, True)["stroke-width"] * PX),
    ]
    common = {"frameon": False, "fontsize": 10, "handlelength": 1.6, "handleheight": 1.1,
              "labelcolor": INK, "borderaxespad": 0.2}
    first = ax.legend(handles=categories, loc="lower left", bbox_to_anchor=(0.0, 0.0), **common)
    ax.add_artist(first)
    ax.legend(handles=shapes, loc="lower left", bbox_to_anchor=(0.27, 0.0), **common)

    in_effect = summary["by_category"][layer.IN_EFFECT]
    pending = summary["in_effect_needing_confirmation"]
    fig.text(0.02, 0.925, "North Carolina data center moratoria", fontsize=21,
             fontweight="bold", color=INK, va="center")
    fig.text(0.02, 0.862,
             f"Local government actions as of {as_of:%B} {as_of.day}, {as_of.year}  ·  "
             f"{in_effect} moratoria or bans in effect, {pending} of them still needing confirmation",
             fontsize=12, color=MUTED, va="center")
    fig.text(0.02, 0.05,
             "Informative overlay: records what local governments have done, not whether any site "
             "is suitable.",
             fontsize=8.5, color=MUTED, va="center")
    fig.text(0.02, 0.022,
             "Data: Josh Childers, CC BY 4.0  ·  Boundaries: U.S. Census Bureau  ·  "
             "github.com/joshchilders11-rgb/nc-data-center-moratoria",
             fontsize=8.5, color=MUTED, va="center")

    # No software version in the file, so an unchanged map is byte-identical
    # and the workflow does not commit it again.
    fig.savefig(PNG, dpi=DPI, facecolor="white", metadata={"Software": None})
    print(f"Wrote {PNG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
