"""
routes/floorplans.py — Floor-plan scan upload endpoints (Milestone 1 / Phase 5).

Flow (mobile side — inspectpro-mobile, not yet wired as of this commit):
  1. Mobile finishes a scan (FloorPlanScannerModule.stopScan()), zips the
     local package (manifest.json + depth/*.raw — compression not yet built
     either, see the module's own docs), and calls
     POST /api/floorplans/<inspection_id>/scans to get an upload URL.
  2. Mobile PUTs the zip directly to S3 using that URL (same direct-upload
     pattern as routes/photos.py).
  3. Mobile calls PATCH /api/floorplans/scans/<id> to mark it UPLOADED.

Privacy note: unlike photos.py's public presign_put usage, scan packages are
raw sensor data, not something to expose via a guessable public URL. This
file never calls utils.s3.public_url() for scan objects and never returns
s3_key in a response — the only way to read a scan back out is a future,
explicitly-authorized endpoint that calls presign_get() on demand. Whether
the bucket itself also blocks unauthenticated GETs depends on its own
policy, which this code doesn't control — worth confirming directly with
whoever manages the bucket before treating this as a real privacy guarantee.

There is no backend processing pipeline yet — status only ever moves
UPLOADING → UPLOADED (or → FAILED). The full plan's QUEUED →
RECONSTRUCTING → ... → READY_FOR_REVIEW pipeline is unbuilt (Milestone 2+).
"""

from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required
from models import db, Inspection, FloorPlanScan
from permissions import require_admin_or_manager
from utils.s3 import is_configured, new_key, presign_put, download_bytes
from services.floorplan_processing import parse_scan_package, summarize
from services.floorplan_geometry import (
    estimate_room_footprint, summarize_footprint, build_point_cloud, fit_wall_lines,
    merge_collinear_walls, find_corners,
)
from services.floorplan_render import render_floorplan_svg

floorplans_bp = Blueprint('floorplans', __name__)


def _download_and_parse(scan):
    """Shared by inspect_scan/render_scan: download + parse a scan's zip.
    Returns (zip_bytes, parsed, None) on success, or (None, None, error_response)."""
    if scan.status != 'UPLOADED' or not scan.s3_key:
        return None, None, (jsonify({'error': 'Scan has not been successfully uploaded yet'}), 409)

    try:
        zip_bytes = download_bytes(scan.s3_key)
    except Exception as e:
        return None, None, (jsonify({'error': f'Failed to download scan package: {e}'}), 502)

    try:
        parsed = parse_scan_package(zip_bytes)
    except ValueError as e:
        return None, None, (jsonify({'error': f'Failed to parse scan package: {e}'}), 422)

    return zip_bytes, parsed, None


def _compute_dense_geometry(zip_bytes, parsed):
    """Shared by inspect_scan/render_scan: point cloud -> walls -> corners."""
    dense_cloud = build_point_cloud(zip_bytes, parsed, subsample_step=6)
    dense_raw_walls = fit_wall_lines(
        [(p.x, p.z) for p in dense_cloud],
        min_inliers=max(15, len(dense_cloud) // 200),
    ) if dense_cloud else []
    dense_walls = merge_collinear_walls(dense_raw_walls)
    corners = find_corners(dense_walls)
    return dense_cloud, dense_walls, corners


@floorplans_bp.route('/<int:inspection_id>/scans', methods=['POST'])
@jwt_required()
def create_scan(inspection_id):
    """
    Create a FloorPlanScan record and return a pre-signed upload URL for the
    zipped local scan package.

    Request body (JSON):
        { "scanUuid": "<uuid from FloorPlanScanRecorder.kt>", "frameCount": <int> }

    Response:
        { "id": <int>, "uploadUrl": "https://...", "expiresIn": 900 }
    """
    if not is_configured():
        return jsonify({'error': 'Object storage is not configured on this server'}), 503

    inspection = Inspection.query.get_or_404(inspection_id)

    data = request.get_json() or {}
    scan_uuid = (data.get('scanUuid') or '').strip()
    if not scan_uuid:
        return jsonify({'error': 'scanUuid is required'}), 400

    scan = FloorPlanScan(
        inspection_id = inspection.id,
        scan_uuid     = scan_uuid,
        status        = 'UPLOADING',
        frame_count   = data.get('frameCount'),
    )
    db.session.add(scan)
    db.session.commit()

    key = new_key(f'floorplan-scans/{inspection.id}', ext='zip')
    upload_url = presign_put(key, content_type='application/zip', expires=900)

    # Stored now so PATCH (step 3) doesn't need the caller to resend it —
    # s3_key only means "this is where the upload was directed", not "this
    # necessarily succeeded" until status flips to UPLOADED.
    scan.s3_key = key
    db.session.commit()

    return jsonify({
        'id':        scan.id,
        'uploadUrl': upload_url,
        'expiresIn': 900,
    })


@floorplans_bp.route('/scans/<int:scan_id>', methods=['PATCH'])
@jwt_required()
def update_scan(scan_id):
    """
    Mark a scan as uploaded (or failed) after the mobile app's direct S3 PUT
    completes (or fails).

    Request body (JSON):
        { "status": "UPLOADED" }                          — success
        { "status": "FAILED", "errorMessage": "..." }      — failure
        Optionally include "frameCount" to correct/confirm the value sent at
        creation time (the mobile app may not know the final count until the
        local zip is actually written).
    """
    scan = FloorPlanScan.query.get_or_404(scan_id)

    data = request.get_json() or {}
    status = data.get('status')
    if status not in ('UPLOADED', 'FAILED'):
        return jsonify({'error': 'status must be "UPLOADED" or "FAILED"'}), 400

    scan.status = status
    if status == 'FAILED':
        scan.error_message = data.get('errorMessage')
    if 'frameCount' in data:
        scan.frame_count = data.get('frameCount')

    db.session.commit()
    return jsonify(scan.to_dict())


@floorplans_bp.route('/<int:inspection_id>/scans', methods=['GET'])
@jwt_required()
def list_scans(inspection_id):
    """List scans for an inspection, newest first. No s3_key in the response — see module docstring."""
    Inspection.query.get_or_404(inspection_id)
    scans = (
        FloorPlanScan.query
        .filter_by(inspection_id=inspection_id)
        .order_by(FloorPlanScan.created_at.desc())
        .all()
    )
    return jsonify([s.to_dict() for s in scans])


@floorplans_bp.route('/scans/<int:scan_id>/inspect', methods=['GET'])
@jwt_required()
@require_admin_or_manager
def inspect_scan(scan_id):
    """
    Diagnostic endpoint (Milestone 2 groundwork): downloads an UPLOADED scan's
    zip package server-side, parses it, and returns aggregate stats (frame
    count, pose bounding box, depth-value ranges, warnings), a rough
    room-footprint estimate (single forward ray per frame, projected into an
    oriented minimum-area rectangle), and — if the scan's intrinsics look
    usable — a denser per-pixel point cloud fed through the same RANSAC wall
    fitter (see services/floorplan_geometry.py for the full reasoning on
    both).

    denseWallLines needs intrinsics captured via camera.textureIntrinsics
    (fixed in FloorPlanScanRecorder.kt); scans captured before that fix used
    imageIntrinsics, which is the wrong source for this — confirmed against
    real data to produce nonsense (5-14m "walls" in a ~6x4m room) once
    per-pixel density amplifies the error. Still computed for older scans
    (not blocked), but don't trust denseWallLines results predating that fix.

    Never returns s3_key — see module docstring's privacy note.
    """
    scan = FloorPlanScan.query.get_or_404(scan_id)

    zip_bytes, parsed, error = _download_and_parse(scan)
    if error:
        return error

    result = summarize(parsed)
    result['footprint'] = summarize_footprint(estimate_room_footprint(parsed))

    dense_cloud, dense_walls, dense_corners = _compute_dense_geometry(zip_bytes, parsed)

    result['densePointCount'] = len(dense_cloud)
    # nearbyConflictM: distance to the closest other wall detection at a
    # similar orientation that did NOT merge into this one because its
    # position disagreed too much — a real signal of ARCore pose drift
    # (a fixed wall seen at different positions across a scan's duration),
    # not a bug. A wall with a small/absent conflict is confidently placed;
    # one with a conflict under ~1m should not be trusted as precise until
    # this pipeline gets drift correction (see merge_collinear_walls docstring).
    result['denseWallLines'] = [
        {
            'x1': w.x1, 'z1': w.z1, 'x2': w.x2, 'z2': w.z2,
            'inlierCount': w.inlier_count, 'nearbyConflictM': w.nearby_conflict_m,
        }
        for w in dense_walls
    ]

    # Only confidently-placed walls (nearby_conflict_m None or large) are
    # used — a corner built from a drift-uncertain wall would fabricate
    # false precision. On a scan with too few confident, perpendicular
    # walls, this is honestly empty rather than a forced guess.
    result['denseCorners'] = [
        {'x': c.x, 'z': c.z, 'wallA': c.wall_a, 'wallB': c.wall_b, 'angleDeg': c.angle_deg}
        for c in dense_corners
    ]

    return jsonify(result)


@floorplans_bp.route('/scans/<int:scan_id>/render', methods=['GET'])
@jwt_required()
@require_admin_or_manager
def render_scan(scan_id):
    """
    Diagnostic SVG render of a scan's detected geometry (solid walls =
    confident, dashed orange = position-uncertain, red dots = corners) —
    see services/floorplan_render.py. This is NOT the polished "final 2D
    floorplan image" the original feature request describes; it's the
    pipeline's raw output made visible, useful for reviewing a scan before
    any such polished renderer exists.

    Returns image/svg+xml directly (not wrapped in JSON) so it can be used
    directly as an <img src> or opened in a browser.
    """
    scan = FloorPlanScan.query.get_or_404(scan_id)

    zip_bytes, parsed, error = _download_and_parse(scan)
    if error:
        return error

    dense_cloud, dense_walls, corners = _compute_dense_geometry(zip_bytes, parsed)

    svg = render_floorplan_svg(dense_walls, corners, points=dense_cloud)
    if not svg:
        return jsonify({'error': 'Not enough geometry to render'}), 422

    return Response(svg, mimetype='image/svg+xml')
