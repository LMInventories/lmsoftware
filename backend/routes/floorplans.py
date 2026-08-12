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

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, Inspection, FloorPlanScan
from utils.s3 import is_configured, new_key, presign_put

floorplans_bp = Blueprint('floorplans', __name__)


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
