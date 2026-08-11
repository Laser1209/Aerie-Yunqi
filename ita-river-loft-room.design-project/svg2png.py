#!/usr/bin/env python3
"""Convert SVG floor plans to PNG using svglib + reportlab."""
import os
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

assets_dir = r"e:\Agent_reply\ita-river-loft-room.design-project\assets"

for level in [1, 2]:
    svg_path = os.path.join(assets_dir, f"floor_plan_level{level}.svg")
    png_path = os.path.join(assets_dir, f"floor_plan_level{level}.png")
    print(f"Converting {svg_path} -> {png_path}")
    drawing = svg2rlg(svg_path)
    if drawing is None:
        print(f"ERROR: could not load {svg_path}")
        continue
    # Render at 2x for crispness
    renderPM.drawToFile(drawing, png_path, fmt="PNG", dpi=144)
    print(f"  Done: {png_path}")

print("All conversions complete.")
