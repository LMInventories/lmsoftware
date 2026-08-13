"""
services/floorplan_geometry.py — first real geometry step for floor-plan scans:
turns each frame's forward-facing depth reading + camera pose into a single
estimated wall-hit point in world space, then reports the resulting room
footprint (bounding box on the horizontal plane).

This is deliberately NOT a wall-detection/line-fitting algorithm. It's the
minimal geometry needed to sanity-check two things against a real, known room
size before any such algorithm is built:
  1. the quaternion rotation math itself (verified with synthetic unit tests
     — pure math, independent of anything ARCore-specific, so this part is
     on solid ground)
  2. the ARCore Pose/camera-space convention this relies on: translation is
     the camera's position in world space, and the camera looks down its
     local -Z axis with +Y up (right-handed, OpenGL-style) — this part is
     per ARCore's documented Pose convention only, NOT independently verified
     against real data beyond aggregate plausibility (does the resulting
     footprint roughly match a room the user told us the real size of).

If the resulting footprint estimate is wildly wrong, the most likely
suspects, in order, are: (a) the forward-axis convention, (b) whether pose
represents camera-to-world or needs inverting, (c) intrinsics/depth image
alignment — not the quaternion math itself.
"""

import io
import math
import random
import statistics
import zipfile
from dataclasses import dataclass, field
from typing import Optional

from services.floorplan_processing import ParsedScan, iter_depth_pixels


def quaternion_rotate_vector(qx: float, qy: float, qz: float, qw: float,
                              vx: float, vy: float, vz: float) -> tuple:
    """
    Rotate vector (vx,vy,vz) by unit quaternion (qx,qy,qz,qw) using the
    standard closed-form formula v' = v + 2*w*(q_xyz x v) + 2*(q_xyz x (q_xyz x v)).
    Pure math — verified independently with known test rotations (identity,
    90-degree axis rotations) in the accompanying test script.
    """
    # t = 2 * cross(q_xyz, v)
    tx = 2 * (qy * vz - qz * vy)
    ty = 2 * (qz * vx - qx * vz)
    tz = 2 * (qx * vy - qy * vx)

    # v' = v + w*t + cross(q_xyz, t)
    rx = vx + qw * tx + (qy * tz - qz * ty)
    ry = vy + qw * ty + (qz * tx - qx * tz)
    rz = vz + qw * tz + (qx * ty - qy * tx)

    return (rx, ry, rz)


def forward_vector_world(pose: dict) -> Optional[tuple]:
    """
    World-space forward direction the camera was pointing in for this frame,
    per ARCore's documented convention: camera looks down its local -Z axis.
    Returns None if the pose is missing rotation fields.
    """
    qx, qy, qz, qw = pose.get('qx'), pose.get('qy'), pose.get('qz'), pose.get('qw')
    if None in (qx, qy, qz, qw):
        return None
    return quaternion_rotate_vector(qx, qy, qz, qw, 0.0, 0.0, -1.0)


def scaled_depth_intrinsics(intrinsics: dict, depth_width: int, depth_height: int) -> Optional[dict]:
    """
    Scale captured intrinsics (for the GPU texture image — see
    FloorPlanScanRecorder.kt's recordIntrinsicsAsync, which captures
    frame.camera.textureIntrinsics, NOT imageIntrinsics) to the depth
    image's own resolution.

    Formula confirmed against Google's own official ARCore raw-depth sample
    (PointCloudHelper.convertRawDepthImagesTo3dPointBuffer, arcore-android-sdk
    repo) rather than guessed: each axis is scaled independently by that
    axis's own resolution ratio (fx * depthWidth/textureWidth, etc.) — this
    is correct even when the depth image's aspect ratio differs from the
    texture image's (confirmed true on the real device this was captured on:
    depth 160x90 vs a differently-shaped texture image), because it's an
    anisotropic per-axis scale, not an assumption that the two share a
    field of view.

    Returns None if the captured intrinsics are missing required fields —
    scans captured before this fix used imageIntrinsics instead of
    textureIntrinsics, which is the wrong source; per-pixel backprojection
    should not be trusted against those even if this doesn't error.
    """
    try:
        fx = intrinsics['focalLengthX']
        fy = intrinsics['focalLengthY']
        cx = intrinsics['principalPointX']
        cy = intrinsics['principalPointY']
        src_w = intrinsics['imageWidth']
        src_h = intrinsics['imageHeight']
    except (KeyError, TypeError):
        return None
    if not src_w or not src_h:
        return None

    return {
        'fx': fx * depth_width / src_w,
        'fy': fy * depth_height / src_h,
        'cx': cx * depth_width / src_w,
        'cy': cy * depth_height / src_h,
    }


def backproject_pixel(u: int, v: int, depth_mm: float, scaled_intrinsics: dict) -> tuple:
    """
    Convert a depth-image pixel + depth reading into a camera-local 3D point
    (meters), per the exact formula in Google's official raw-depth sample:
    x = depth*(u-cx)/fx, y = depth*(cy-v)/fy [note the flip: image v
    increases downward, camera Y increases upward], z = -depth [camera
    looks down its local -Z axis]. At u=cx, v=cy this reduces exactly to
    (0, 0, -depth), consistent with forward_vector_world's center-ray case.
    """
    depth_m = depth_mm / 1000.0
    x = depth_m * (u - scaled_intrinsics['cx']) / scaled_intrinsics['fx']
    y = depth_m * (scaled_intrinsics['cy'] - v) / scaled_intrinsics['fy']
    z = -depth_m
    return (x, y, z)


@dataclass
class WorldPoint:
    frame_index: int
    x: float
    y: float
    z: float


def build_point_cloud(zip_bytes: bytes, parsed: ParsedScan, subsample_step: int = 4) -> list:
    """
    Full per-pixel point cloud (not just one ray per frame): for each frame
    with valid pose + depth + intrinsics, backprojects a subsampled grid of
    valid depth pixels into world space.

    Needs zip_bytes again (not just the already-parsed ParsedScan) because
    per-frame depth grids aren't retained after parse_scan_package computes
    their aggregate stats — re-reads each depth file from the zip.

    subsample_step=4 keeps this fast and the output size reasonable (a
    160x90 frame has 14400 pixels; step=4 keeps ~900 candidates per frame
    before sentinel-filtering) — same idea as Google's sample's own
    uniform-subsampling approach, just a fixed step here rather than
    computed from a target point budget.
    """
    if not parsed.intrinsics:
        return []

    points = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        for f in parsed.frames:
            if f.depth is None:
                continue
            pose = f.pose or {}
            tx, ty, tz = pose.get('tx'), pose.get('ty'), pose.get('tz')
            if tx is None:
                continue
            fwd_rot_args = (pose.get('qx'), pose.get('qy'), pose.get('qz'), pose.get('qw'))
            if None in fwd_rot_args:
                continue

            depth_width, depth_height = f.depth.width, f.depth.height
            scaled = scaled_depth_intrinsics(parsed.intrinsics, depth_width, depth_height)
            if scaled is None:
                continue

            # depthFile name follows the manifest's own convention
            # (depth/{index}.raw) — re-derive it the same way the manifest did.
            depth_file = f"depth/{f.index}.raw"
            if depth_file not in names:
                continue
            raw = zf.read(depth_file)

            for x, y, depth_mm, _raw_value in iter_depth_pixels(raw, depth_width, depth_height, f.depth.row_stride):
                if depth_mm == 0:
                    continue
                if x % subsample_step != 0 or y % subsample_step != 0:
                    continue

                cx_cam, cy_cam, cz_cam = backproject_pixel(x, y, depth_mm, scaled)
                wx, wy, wz = quaternion_rotate_vector(*fwd_rot_args, cx_cam, cy_cam, cz_cam)
                points.append(WorldPoint(
                    frame_index=f.index, x=tx + wx, y=ty + wy, z=tz + wz,
                ))

    return points


@dataclass
class WallHitPoint:
    frame_index: int
    x: float
    y: float
    z: float
    center_depth_m: float


def convex_hull(points: list) -> list:
    """
    Andrew's monotone chain convex hull over a list of (x, z) tuples.
    Returns hull vertices in counter-clockwise order, duplicate-free.
    """
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def min_area_rect(points: list) -> Optional[dict]:
    """
    Minimum-area bounding rectangle of a set of (x, z) points, via rotating
    calipers over the convex hull — one edge of the optimal rectangle is
    always collinear with a hull edge, so trying each hull edge's angle and
    taking the axis-aligned (in that rotated frame) bbox is exhaustive.

    Unlike a plain axis-aligned bounding box, this isn't thrown off by the
    room not being aligned with ARCore's arbitrary world X/Z axes (which are
    set by wherever the phone was facing when the AR session started, not by
    the room's own walls) — it finds the room's own orientation instead of
    assuming one.

    Returns None if fewer than 3 distinct points (can't form a hull).
    """
    hull = convex_hull(points)
    if len(hull) < 3:
        return None

    best = None
    n = len(hull)
    for i in range(n):
        x1, z1 = hull[i]
        x2, z2 = hull[(i + 1) % n]
        edge_angle = math.atan2(z2 - z1, x2 - x1)
        cos_a, sin_a = math.cos(-edge_angle), math.sin(-edge_angle)

        # rotate every hull point into this edge's frame
        rxs, rzs = [], []
        for (px, pz) in hull:
            rxs.append(px * cos_a - pz * sin_a)
            rzs.append(px * sin_a + pz * cos_a)

        w = max(rxs) - min(rxs)
        h = max(rzs) - min(rzs)
        area = w * h
        if best is None or area < best['area']:
            best = {'area': area, 'w': w, 'h': h, 'angle_deg': math.degrees(edge_angle)}

    return {
        'sideAM': best['w'],
        'sideBM': best['h'],
        'angleDeg': best['angle_deg'],
        'areaSqM': best['area'],
    }


def reject_ray_outliers(points: list, k: float = 3.5) -> tuple:
    """
    Split points into (kept, excluded) using a median + k*MAD threshold on
    ray length (center_depth_m) — a standard robust outlier test, not tuned
    against any expected room size.

    Real captured scans showed individual frames whose forward ray passed
    through an open doorway and measured whatever was beyond it (a hallway,
    another room) rather than this room's own wall — those rays are real,
    correct depth readings, just not readings of this room's boundary. A
    single-ray-per-frame method has no way to distinguish "wall" from "saw
    through a gap in the wall" other than by how much of an outlier the
    resulting distance is relative to the rest of the scan.

    MAD (median absolute deviation) is used instead of mean/stddev because
    it isn't itself dragged around by the outliers it's trying to detect.
    Returns (points, []) unchanged if fewer than 4 points (not enough to
    make outlier rejection meaningful) or if MAD is 0 (no spread to measure).
    """
    if len(points) < 4:
        return points, []

    depths = [p.center_depth_m for p in points]
    med = statistics.median(depths)
    mad = statistics.median([abs(d - med) for d in depths])
    if mad == 0:
        return points, []

    # 1.4826 scales MAD to be comparable to a standard deviation under a
    # normal distribution — the conventional constant for this test.
    threshold = med + k * mad * 1.4826

    kept = [p for p in points if p.center_depth_m <= threshold]
    excluded = [p for p in points if p.center_depth_m > threshold]
    return kept, excluded


@dataclass
class WallLineSegment:
    x1: float
    z1: float
    x2: float
    z2: float
    inlier_count: int


def fit_wall_lines(points: list, distance_threshold: float = 0.15,
                    min_inliers: int = 4, max_walls: int = 8,
                    iterations: int = 300, seed: int = 42) -> list:
    """
    Sequential RANSAC line-fitting over (x, z) points: repeatedly finds the
    line with the most points within distance_threshold (meters), removes
    those inlier points, and repeats — the standard approach for extracting
    multiple line segments (walls) from a noisy 2D point set.

    Deliberately built on top of the SAME points already used/validated for
    the footprint estimate (one forward-ray hit per frame) rather than a
    denser per-pixel point cloud: per-pixel backprojection would need camera
    intrinsics matched to the depth image's own resolution, and ARCore's
    public API has no such accessor — Camera.getImageIntrinsics() is
    documented for the CPU/color image only, and the depth image's own
    size/aspect ratio is described by Google's docs as tied to the device's
    *display* aspect ratio, not the color camera's. Guessing a scale factor
    between the two would repeat exactly the kind of unverified-assumption
    mistake this whole feature has been built around avoiding. So this
    works with the sparser but trusted point set instead.

    seed is fixed by default for reproducible results — this is a real
    algorithm choice affecting output, not a test-only concern, and repeated
    runs on the same scan should give the same walls.

    Returns a list of WallLineSegment, most-supported line first. With only
    ~30-56 points per real scan so far, this is a genuine experiment, not a
    guaranteed-good result — expect it to work better on scans with more
    frames actually facing a real wall (as opposed to furniture, the floor,
    or an open doorway).
    """
    rng = random.Random(seed)
    remaining = list(points)
    walls = []

    while len(remaining) >= min_inliers and len(walls) < max_walls:
        best_inliers = []
        best_dir = None
        best_origin = None

        for _ in range(iterations):
            if len(remaining) < 2:
                break
            p1, p2 = rng.sample(remaining, 2)
            dx, dz = p2[0] - p1[0], p2[1] - p1[1]
            length = math.hypot(dx, dz)
            if length < 1e-9:
                continue
            ux, uz = dx / length, dz / length
            nx, nz = -uz, ux  # unit normal to the candidate line

            inliers = [p for p in remaining
                       if abs((p[0] - p1[0]) * nx + (p[1] - p1[1]) * nz) <= distance_threshold]

            if len(inliers) > len(best_inliers):
                best_inliers = inliers
                best_dir = (ux, uz)
                best_origin = p1

        if best_dir is None or len(best_inliers) < min_inliers:
            break

        ux, uz = best_dir
        ox, oz = best_origin
        projections = sorted((p[0] - ox) * ux + (p[1] - oz) * uz for p in best_inliers)
        t_min, t_max = projections[0], projections[-1]

        walls.append(WallLineSegment(
            x1=ox + t_min * ux, z1=oz + t_min * uz,
            x2=ox + t_max * ux, z2=oz + t_max * uz,
            inlier_count=len(best_inliers),
        ))

        inlier_set = set(best_inliers)
        remaining = [p for p in remaining if p not in inlier_set]

    return walls


def merge_collinear_walls(walls: list, angle_threshold_deg: float = 15.0,
                           offset_threshold_m: float = 0.3) -> list:
    """
    Merge near-duplicate wall segments that sequential RANSAC found as
    separate detections of the SAME physical wall — a well-known RANSAC
    limitation: it removes only a found line's own inliers, so a
    well-populated wall with any noise/curvature can get "rediscovered" as
    2-3 slightly-offset segments instead of one. Confirmed happening on real
    data: 6 of 8 dense-cloud walls from one real scan shared near-identical
    orientation (10-22 degrees) at slightly different positions.

    Two walls are merged if their orientations differ by less than
    angle_threshold_deg (mod 180 — undirected line comparison) AND their
    perpendicular offset from a shared reference line differs by less than
    offset_threshold_m. Merged walls keep the higher-inlier-count wall's
    line direction, extend the endpoints to cover every merged segment's
    projected extent, and sum inlier counts.

    angle_threshold_deg=15 comfortably covers the ~12 degree spread seen
    within one real merged-wall group while staying well clear of a
    rectangular room's 90-degree wall separation. offset_threshold_m=0.3 is
    roughly 2x fit_wall_lines' own distance_threshold, since separate RANSAC
    passes over noisy data can land a bit further apart than a single pass's
    inlier band.
    """
    if not walls:
        return []

    def wall_angle(w):
        return math.atan2(w.z2 - w.z1, w.x2 - w.x1) % math.pi

    def wall_offset(w, angle):
        # perpendicular distance from origin to the infinite line through
        # (w.x1, w.z1) in direction `angle`, using a normal derived from
        # that SAME angle (not the compared wall's own angle) so two walls
        # being compared are measured against one consistent reference.
        nx, nz = -math.sin(angle), math.cos(angle)
        return w.x1 * nx + w.z1 * nz

    ordered = sorted(walls, key=lambda w: -w.inlier_count)
    used = [False] * len(ordered)
    merged = []

    for i, w in enumerate(ordered):
        if used[i]:
            continue
        angle_i = wall_angle(w)
        offset_i = wall_offset(w, angle_i)
        cluster = [w]
        used[i] = True

        for j in range(i + 1, len(ordered)):
            if used[j]:
                continue
            w2 = ordered[j]
            angle_diff = abs(math.degrees(angle_i - wall_angle(w2))) % 180
            angle_diff = min(angle_diff, 180 - angle_diff)
            if angle_diff > angle_threshold_deg:
                continue
            if abs(wall_offset(w2, angle_i) - offset_i) > offset_threshold_m:
                continue
            cluster.append(w2)
            used[j] = True

        ux, uz = math.cos(angle_i), math.sin(angle_i)
        ox, oz = w.x1, w.z1
        projections = []
        total_inliers = 0
        for cw in cluster:
            projections.append((cw.x1 - ox) * ux + (cw.z1 - oz) * uz)
            projections.append((cw.x2 - ox) * ux + (cw.z2 - oz) * uz)
            total_inliers += cw.inlier_count
        t_min, t_max = min(projections), max(projections)

        merged.append(WallLineSegment(
            x1=ox + t_min * ux, z1=oz + t_min * uz,
            x2=ox + t_max * ux, z2=oz + t_max * uz,
            inlier_count=total_inliers,
        ))

    return sorted(merged, key=lambda w: -w.inlier_count)


@dataclass
class FootprintEstimate:
    points: list
    frames_used: int
    frames_skipped: int
    bounds_x: Optional[dict]
    bounds_z: Optional[dict]
    width_m: Optional[float]
    depth_m: Optional[float]
    oriented_rect: Optional[dict] = None
    outlier_frame_indices: list = field(default_factory=list)
    oriented_rect_trimmed: Optional[dict] = None
    wall_lines: list = field(default_factory=list)


def estimate_room_footprint(parsed: ParsedScan) -> FootprintEstimate:
    """
    For each frame with a usable center-depth reading and pose, cast a single
    ray from the camera position along its forward direction for
    center_depth_mm, producing one estimated wall-hit point per frame.
    Aggregates those into a horizontal (X/Z) bounding box as a rough
    room-footprint estimate.

    This assumes the room is convex-ish and the camera stayed roughly inside
    it (true for a rotate-in-place or walk-around capture) — the bounding box
    of "what's in front of me" points approximates the room's extent, though
    it is NOT true wall geometry (no line-fitting, no corner detection).
    """
    points = []
    skipped = 0

    for f in parsed.frames:
        pose = f.pose or {}
        tx, ty, tz = pose.get('tx'), pose.get('ty'), pose.get('tz')
        if tx is None or f.depth is None or f.depth.center_depth_mm is None:
            skipped += 1
            continue

        fwd = forward_vector_world(pose)
        if fwd is None:
            skipped += 1
            continue

        depth_m = f.depth.center_depth_mm / 1000.0
        wx = tx + fwd[0] * depth_m
        wy = ty + fwd[1] * depth_m
        wz = tz + fwd[2] * depth_m

        points.append(WallHitPoint(
            frame_index=f.index, x=wx, y=wy, z=wz, center_depth_m=depth_m
        ))

    if not points:
        return FootprintEstimate(
            points=[], frames_used=0, frames_skipped=skipped,
            bounds_x=None, bounds_z=None, width_m=None, depth_m=None,
        )

    xs = [p.x for p in points]
    zs = [p.z for p in points]
    bounds_x = {'min': min(xs), 'max': max(xs)}
    bounds_z = {'min': min(zs), 'max': max(zs)}

    kept, excluded = reject_ray_outliers(points)

    return FootprintEstimate(
        points=points,
        frames_used=len(points),
        frames_skipped=skipped,
        bounds_x=bounds_x,
        bounds_z=bounds_z,
        width_m=bounds_x['max'] - bounds_x['min'],
        depth_m=bounds_z['max'] - bounds_z['min'],
        oriented_rect=min_area_rect([(p.x, p.z) for p in points]),
        outlier_frame_indices=[p.frame_index for p in excluded],
        oriented_rect_trimmed=min_area_rect([(p.x, p.z) for p in kept]) if excluded else None,
        wall_lines=merge_collinear_walls(fit_wall_lines([(p.x, p.z) for p in kept])),
    )


def summarize_footprint(estimate: FootprintEstimate) -> dict:
    return {
        'framesUsed': estimate.frames_used,
        'framesSkipped': estimate.frames_skipped,
        'boundsX': estimate.bounds_x,
        'boundsZ': estimate.bounds_z,
        'estimatedWidthM': estimate.width_m,
        'estimatedDepthM': estimate.depth_m,
        'orientedRect': estimate.oriented_rect,
        'orientedRectTrimmed': estimate.oriented_rect_trimmed,
        'outlierFrameIndices': estimate.outlier_frame_indices,
        'wallLines': [
            {'x1': w.x1, 'z1': w.z1, 'x2': w.x2, 'z2': w.z2, 'inlierCount': w.inlier_count}
            for w in estimate.wall_lines
        ],
        'points': [
            {'frameIndex': p.frame_index, 'x': p.x, 'y': p.y, 'z': p.z, 'centerDepthM': p.center_depth_m}
            for p in estimate.points
        ],
    }
