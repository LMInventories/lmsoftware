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


def _lerp(p1, p2, t):
    return (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)


def _dist(p1, p2):
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def _inward_normal(p1, p2, centroid):
    """Unit vector perpendicular to wall (p1,p2), pointing toward centroid
    (i.e. into the room) rather than away from it — tried both perpendicular
    candidates and picked whichever one centroid actually lies on."""
    dx, dz = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dz) or 1.0
    nx, nz = -dz / length, dx / length
    mid = _lerp(p1, p2, 0.5)
    # Does centroid lie on the (nx,nz) side or the opposite side of the wall?
    to_centroid = (centroid[0] - mid[0], centroid[1] - mid[1])
    if nx * to_centroid[0] + nz * to_centroid[1] < 0:
        nx, nz = -nx, -nz
    return (nx, nz)


def _arc_sweep_flag(a, b, c):
    """
    SVG sweep-flag (0 or 1) for an arc centered at `a` from point `b` to
    point `c`, both equidistant from `a`. Derived from the sign of the
    cross product of (b-a) and (c-a) in (x, z) — NOT visually verified
    (no renderer available in this environment), but the sign convention
    itself is: SVG's y-axis increases downward, and this module's to_svg()
    maps world z directly onto SVG y without flipping it, so a
    counterclockwise turn in world (x,z) math-space appears clockwise on
    screen — SVG's sweep-flag=1 means "positive-angle" (clockwise in a
    y-down system), so a positive cross product maps to sweep-flag=1.
    """
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return 1 if cross > 0 else 0


def render_level_svg(rooms: list, padding_m: float = 0.5, scale_px_per_m: float = 60.0) -> str:
    """
    Render every room of a floor-plan level, composited into one SVG, with
    door/window/stairs symbols drawn per standard architectural convention.
    Unlike render_floorplan_svg (ARCore-derived walls, with a confident vs.
    uncertain visual distinction), every wall here is solid black — manual
    measurements are always trusted, matching floorplan_geometry.
    polygon_to_walls' nearby_conflict_m=None convention.

    rooms: [{"corners": [(x,z), ...], "symbols": [...]}, ...] — corners is
    a closed polygon (NOT repeating the first point), symbols follow the
    shapes documented on models.FloorPlanRoom.

    Door/window symbols are wall-attached (an opening broken into a
    specific wall edge, identified by wallIndex + positionFraction of that
    edge's length, with widthM the opening's width); stairs are a free
    floor feature positioned by (x, z) with rotation, not tied to a wall.

    Returns '' if there are no rooms with at least 3 corners.
    """
    usable_rooms = [r for r in rooms if len(r.get('corners', [])) >= 3]
    if not usable_rooms:
        return ''

    xs, zs = [], []
    for room in usable_rooms:
        for (x, z) in room['corners']:
            xs.append(x)
            zs.append(z)
        for sym in room.get('symbols', []):
            if sym.get('type') == 'stairs':
                xs.append(sym.get('x', 0))
                zs.append(sym.get('z', 0))

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

    for room in usable_rooms:
        corners = room['corners']
        n = len(corners)
        centroid = (sum(c[0] for c in corners) / n, sum(c[1] for c in corners) / n)
        symbols = room.get('symbols', [])

        for i in range(n):
            p1, p2 = corners[i], corners[(i + 1) % n]
            wall_len = _dist(p1, p2) or 1e-9

            # gather door/window gaps on this wall, as (frac_start, frac_end) pairs
            gaps = []
            for sym in symbols:
                if sym.get('type') not in ('door', 'window'):
                    continue
                if sym.get('wallIndex') != i:
                    continue
                pos = max(0.0, min(1.0, sym.get('positionFraction', 0.5)))
                half = (sym.get('widthM', 0.9) / 2.0) / wall_len
                gaps.append((max(0.0, pos - half), min(1.0, pos + half), sym))
            gaps.sort(key=lambda g: g[0])

            # draw solid wall segments between gaps
            cursor = 0.0
            for gs, ge, _sym in gaps:
                if gs > cursor:
                    a, b = to_svg(*_lerp(p1, p2, cursor)), to_svg(*_lerp(p1, p2, gs))
                    parts.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                                 f'stroke="#111" stroke-width="4" stroke-linecap="round" />')
                cursor = max(cursor, ge)
            if cursor < 1.0:
                a, b = to_svg(*_lerp(p1, p2, cursor)), to_svg(*_lerp(p1, p2, 1.0))
                parts.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                             f'stroke="#111" stroke-width="4" stroke-linecap="round" />')

            # draw the gap symbols themselves
            for gs, ge, sym in gaps:
                world_a = _lerp(p1, p2, gs)  # hinge / near edge, in world meters
                world_b = _lerp(p1, p2, ge)  # far edge, in world meters
                svg_a, svg_b = to_svg(*world_a), to_svg(*world_b)

                if sym['type'] == 'window':
                    nx, nz = _inward_normal(p1, p2, centroid)
                    tick_m = 0.12
                    for edge_world in (world_a, world_b):
                        e = to_svg(*edge_world)
                        t1 = to_svg(edge_world[0] - nx * tick_m, edge_world[1] - nz * tick_m)
                        t2 = to_svg(edge_world[0] + nx * tick_m, edge_world[1] + nz * tick_m)
                        parts.append(f'<line x1="{t1[0]:.1f}" y1="{t1[1]:.1f}" x2="{t2[0]:.1f}" y2="{t2[1]:.1f}" '
                                     f'stroke="#111" stroke-width="3" />')
                elif sym['type'] == 'door':
                    nx, nz = _inward_normal(p1, p2, centroid)
                    radius_m = _dist(world_a, world_b)
                    open_world = (world_a[0] + nx * radius_m, world_a[1] + nz * radius_m)
                    svg_open = to_svg(*open_world)
                    radius_px = radius_m * scale_px_per_m
                    sweep = _arc_sweep_flag(world_a, world_b, open_world)
                    # leaf (hinge -> fully open) as a straight line, plus the swing arc
                    parts.append(f'<line x1="{svg_a[0]:.1f}" y1="{svg_a[1]:.1f}" '
                                 f'x2="{svg_open[0]:.1f}" y2="{svg_open[1]:.1f}" '
                                 f'stroke="#1f5f8b" stroke-width="2" />')
                    parts.append(
                        f'<path d="M{svg_open[0]:.1f},{svg_open[1]:.1f} '
                        f'A{radius_px:.1f},{radius_px:.1f} 0 0,{sweep} {svg_b[0]:.1f},{svg_b[1]:.1f}" '
                        f'stroke="#1f5f8b" stroke-width="1.5" fill="none" />'
                    )

        for sym in symbols:
            if sym.get('type') != 'stairs':
                continue
            cx, cz = to_svg(sym.get('x', 0), sym.get('z', 0))
            length_px = sym.get('lengthM', 3.0) * scale_px_per_m
            width_px = sym.get('widthM', 1.0) * scale_px_per_m
            rotation = sym.get('rotationDeg', 0)
            group = [f'<g transform="translate({cx:.1f},{cz:.1f}) rotate({rotation:.1f})">']
            group.append(
                f'<rect x="{-length_px/2:.1f}" y="{-width_px/2:.1f}" '
                f'width="{length_px:.1f}" height="{width_px:.1f}" '
                f'fill="none" stroke="#111" stroke-width="2" />'
            )
            tread_gap_px = min(25.0, length_px / 4) or 25.0
            n_treads = max(1, int(length_px // tread_gap_px))
            for t in range(1, n_treads):
                tx = -length_px / 2 + t * tread_gap_px
                group.append(
                    f'<line x1="{tx:.1f}" y1="{-width_px/2:.1f}" x2="{tx:.1f}" y2="{width_px/2:.1f}" '
                    f'stroke="#111" stroke-width="1" />'
                )
            label = 'UP' if sym.get('direction') == 'up' else 'DN'
            group.append(
                f'<text x="0" y="4" font-size="11" fill="#111" text-anchor="middle">{label}</text>'
            )
            group.append('</g>')
            parts.append(''.join(group))

    # 1-meter scale bar, bottom-left
    bar_x0, bar_y = 10, svg_h - 15
    parts.append(
        f'<line x1="{bar_x0}" y1="{bar_y}" x2="{bar_x0 + scale_px_per_m:.0f}" y2="{bar_y}" '
        f'stroke="#111" stroke-width="2" />'
    )
    parts.append(f'<text x="{bar_x0}" y="{bar_y - 5}" font-size="12" fill="#111">1m</text>')

    parts.append('</svg>')
    return ''.join(parts)
