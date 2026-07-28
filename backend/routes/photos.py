"""
routes/photos.py — Pre-signed URL endpoint for direct mobile → S3 photo upload.

Flow:
  1. Mobile calls POST /api/photos/presign  { "count": N, "prefix": "inspections/123/photos" }
  2. Server returns N pre-signed PUT URLs + final public URLs
  3. Mobile uploads each compressed JPEG directly to S3 (no data through Flask)
  4. Mobile embeds the final public URLs in report_data and syncs normally

This means the sync payload goes from ~18 MB (base64 photos) to ~50 KB (text only).
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from utils.s3 import is_configured, new_key, presign_put, public_url
from permissions import require_admin_or_manager

photos_bp = Blueprint('photos', __name__)

_MAX_BATCH = 500   # hard cap — prevents abuse


@photos_bp.route('/presign', methods=['POST'])
@jwt_required()
def get_presigned_urls():
    """
    Generate pre-signed S3 PUT URLs for direct mobile photo upload.

    Request body (JSON):
        {
          "count":  <int>,          // number of photos to upload
          "prefix": <str>           // e.g. "inspections/42/photos"
        }

    OR supply explicit keys:
        {
          "keys": ["inspections/42/photos/abc.jpg", ...]
        }

    Response:
        {
          "uploads": [
            { "key": "inspections/42/photos/abc.jpg",
              "upload_url": "https://s3.aws.com/...",   // PUT here
              "final_url":  "https://bucket.s3.../..." }, // embed this
            ...
          ]
        }
    """
    if not is_configured():
        return jsonify({'error': 'Photo storage is not configured on this server'}), 503

    data = request.json or {}

    if 'keys' in data:
        keys = list(data['keys'])[:_MAX_BATCH]
    elif 'count' in data and 'prefix' in data:
        count  = min(int(data['count']), _MAX_BATCH)
        prefix = str(data['prefix']).strip('/')
        keys   = [new_key(prefix) for _ in range(count)]
    else:
        return jsonify({'error': 'Provide either "keys" or "count" + "prefix"'}), 400

    uploads = []
    for key in keys:
        uploads.append({
            'key':        key,
            'upload_url': presign_put(key, expires=900),   # 15-minute window
            'final_url':  public_url(key),
        })

    return jsonify({'uploads': uploads})


@photos_bp.route('/delete', methods=['POST'])
@jwt_required()
def delete_photo():
    """
    Delete a photo from S3 by key.
    Used for cleanup when a photo is removed from a report.

    Request: { "key": "inspections/42/photos/abc.jpg" }
    """
    if not is_configured():
        return jsonify({'ok': True})   # no-op if S3 not set up

    data = request.json or {}
    key  = data.get('key', '').strip()
    if not key:
        return jsonify({'error': 'key is required'}), 400

    from utils.s3 import delete_object
    delete_object(key)
    return jsonify({'ok': True})


@photos_bp.route('/orphaned/<int:inspection_id>', methods=['GET'])
@jwt_required()
@require_admin_or_manager
def list_orphaned_photos(inspection_id):
    """
    Admin/manager only — recovery tool.

    Lists S3 objects under inspections/<id>/photos/ that are NOT referenced
    anywhere in the inspection's CURRENT report_data. This surfaces photos
    that genuinely uploaded successfully at some point but whose pointer was
    later lost — e.g. a stale local copy on the clerk's device overwrote
    report_data on a later, unrelated edit-and-resync (see syncService.ts),
    reverting an already-resolved photo URL back to a local file:// path.
    Nothing deletes S3 objects except an explicit "remove photo" action, so
    if a photo was ever successfully uploaded, it should still be here.

    Match orphaned entries to the missing photo by size/upload time, then
    call POST /api/photos/orphaned/<id>/reassign to attach it directly to
    the correct room/item — no download/re-upload round-trip needed since
    the file is already hosted and valid.
    """
    if not is_configured():
        return jsonify({'error': 'Photo storage is not configured on this server'}), 503

    import json
    from models import db, Inspection
    from utils.s3 import list_objects

    insp = db.session.get(Inspection, inspection_id)
    if not insp:
        return jsonify({'error': 'Inspection not found'}), 404

    rd = {}
    if insp.report_data:
        try:
            rd = json.loads(insp.report_data) if isinstance(insp.report_data, str) else insp.report_data
        except Exception:
            rd = {}

    # Collect every photo URL/URI referenced anywhere in report_data, however
    # deeply nested (room items, _extra rows, _overview, fixed sections, subs).
    referenced = set()

    def walk(node):
        if isinstance(node, dict):
            photos = node.get('_photos')
            if isinstance(photos, list):
                for p in photos:
                    if isinstance(p, str):
                        referenced.add(p)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(rd)

    objects  = list_objects(f'inspections/{inspection_id}/photos')
    orphaned = [o for o in objects if o['public_url'] not in referenced]

    # Oldest → newest (upload time, the closest server-side proxy for capture
    # time) so orphaned photos line up roughly in the order the report was
    # walked through, making them easier to place back in the right room/item.
    orphaned.sort(key=lambda o: o['last_modified'])

    return jsonify({
        'inspection_id':    inspection_id,
        'total_in_s3':       len(objects),
        'still_referenced':  len(objects) - len(orphaned),
        'orphaned':          orphaned,
    })


@photos_bp.route('/orphaned/<int:inspection_id>/reassign', methods=['POST'])
@jwt_required()
@require_admin_or_manager
def reassign_orphaned_photos(inspection_id):
    """
    Admin/manager only — attach one or more orphaned S3 photos (found via
    GET /api/photos/orphaned/<id>) directly onto a room item's _photos array.

    No download/re-upload round-trip is needed: the photo is already hosted
    and valid, so this just writes its existing public URL into report_data —
    the same place a normal photo capture would have put it.

    Body: { "keys": ["inspections/165/photos/<uuid>.jpg", ...],
            "section_key": "37", "item_id": "490" }
    Supports a whole batch (e.g. every photo from one room) in a single call.
    """
    data        = request.json or {}
    keys        = data.get('keys') or ([data['key']] if data.get('key') else [])
    section_key = str(data.get('section_key', '')).strip()
    item_id     = str(data.get('item_id', '')).strip()

    if not keys or not section_key or not item_id:
        return jsonify({'error': '"keys" (or "key"), "section_key", and "item_id" are required'}), 400

    # Safety: only allow keys that actually live under THIS inspection's own
    # S3 prefix — prevents attaching another inspection's (or a guessed)
    # object onto this report.
    prefix = f'inspections/{inspection_id}/photos/'
    bad_keys = [k for k in keys if not str(k).startswith(prefix)]
    if bad_keys:
        return jsonify({'error': f'Key(s) do not belong to this inspection: {bad_keys}'}), 400

    import json
    from models import db, Inspection

    insp = db.session.get(Inspection, inspection_id)
    if not insp:
        return jsonify({'error': 'Inspection not found'}), 404

    rd = {}
    if insp.report_data:
        try:
            rd = json.loads(insp.report_data) if isinstance(insp.report_data, str) else insp.report_data
        except Exception:
            rd = {}

    rd.setdefault(section_key, {})
    rd[section_key].setdefault(item_id, {})
    photos = rd[section_key][item_id].get('_photos')
    if not isinstance(photos, list):
        photos = []

    added = []
    for key in keys:
        url = public_url(key)
        if url not in photos:
            photos.append(url)
            added.append(url)
    rd[section_key][item_id]['_photos'] = photos

    insp.report_data = json.dumps(rd)
    db.session.commit()

    return jsonify({'ok': True, 'added': len(added), 'photos': photos})
