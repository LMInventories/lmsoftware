"""
services/floorplan_render.py — deterministic SVG rendering of floor-plan
geometry (walls, corners, optionally the raw point cloud) for a scan.

This is a diagnostic/preview renderer, not the final polished floor-plan
image the original feature request describes ("the final 2D floorplan
image" in the PDF/webapp). It exists to make the geometry pipeline's output
actually visible for the first time — every previous increment produced
numbers in JSON, verified via scripts and print statements, never an image
a person could look at. Confident walls, uncertain (drift-flagged) walls,
and corners are rendered with different, honest visual treatment rather
than presenting a single clean-looking room outline that overstates what
was actually found.
"""

import math
from typing import Optional


def render_floorplan_svg(walls: list, corners: list, points: Optional[list] = None,
                          uncertain_threshold_m: float = 0.4,
                          padding_m: float = 0.5, scale_px_per_m: float = 60.0,
                          point_subsample: int = 8) -> str:
    """
    Render wall segments (WallLineSegment), corners (Corner), and optionally
    a raw point cloud (WorldPoint, with .x/.z) into a self-contained SVG
    string. World (x, z) maps directly to SVG (x, y) — top-down view, no
    compass alignment.

    Confident walls (nearby_conflict_m is None or >= uncertain_threshold_m)
    render as solid black lines. Walls flagged as position-uncertain
    (likely ARCore pose drift or a bad-surface artifact — see
    merge_collinear_walls' docstring) render as dashed orange lines, so
    the image itself communicates which parts of the plan are trustworthy.
    Corners render as filled red circles. The point cloud, if given,
    renders as small light-gray dots for context (subsampled — real scans
    have thousands of points, no need to render all of them).

    Returns '' for a completely empty scan (no walls, no points) rather
    than a blank-but-technically-valid SVG, so callers can distinguish
    "nothing to show" from "here's an empty room."
    """
    if not walls and not points:
        return ''

    xs, zs = [], []
    for w in walls:
        xs += [w.x1, w.x2]
        zs += [w.z1, w.z2]
    for c in corners:
        xs.append(c.x)
        zs.append(c.z)
    if points:
        for p in points:
            xs.append(p.x)
            zs.append(p.z)

    min_x, max_x = min(xs) - padding_m, max(xs) + padding_m
    min_z, max_z = min(zs) - padding_m, max(zs) + padding_m
    width_m = max(max_x - min_x, 0.1)
    height_m = max(max_z - min_z, 0.1)
    svg_w = width_m * scale_px_per_m
    svg_h = height_m * scale_px_per_m

    def to_svg(x, z):
        return ((x - min_x) * scale_px_per_m, (z - min_z) * scale_px_per_m)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w:.0f}" height="{svg_h:.0f}" '
        f'viewBox="0 0 {svg_w:.0f} {svg_h:.0f}" style="background:#fff">'
    ]

    if points:
        for i, p in enumerate(points):
            if i % point_subsample != 0:
                continue
            px, pz = to_svg(p.x, p.z)
            parts.append(f'<circle cx="{px:.1f}" cy="{pz:.1f}" r="1" fill="#ccc" />')

    for w in walls:
        x1, z1 = to_svg(w.x1, w.z1)
        x2, z2 = to_svg(w.x2, w.z2)
        uncertain = w.nearby_conflict_m is not None and w.nearby_conflict_m < uncertain_threshold_m
        stroke = '#e67e22' if uncertain else '#111'
        dash = ' stroke-dasharray="8,5"' if uncertain else ''
        parts.append(
            f'<line x1="{x1:.1f}" y1="{z1:.1f}" x2="{x2:.1f}" y2="{z2:.1f}" '
            f'stroke="{stroke}" stroke-width="4"{dash} stroke-linecap="round" />'
        )

    for c in corners:
        cx, cz = to_svg(c.x, c.z)
        parts.append(f'<circle cx="{cx:.1f}" cy="{cz:.1f}" r="6" fill="#c0392b" />')

    # 1-meter scale bar, bottom-left
    bar_x0, bar_y = 10, svg_h - 15
    parts.append(
        f'<line x1="{bar_x0}" y1="{bar_y}" x2="{bar_x0 + scale_px_per_m:.0f}" y2="{bar_y}" '
        f'stroke="#111" stroke-width="2" />'
    )
    parts.append(
        f'<text x="{bar_x0}" y="{bar_y - 5}" font-size="12" fill="#111">1m</text>'
    )

    parts.append('</svg>')
    return ''.join(parts)
