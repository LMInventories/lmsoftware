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
