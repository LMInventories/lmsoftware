"""
routes/zapier.py
──────────────────
Groundwork for a future Zapier integration.

Unlike Google/Microsoft/Dropbox/Slack, Zapier doesn't have a "connect account"
consent screen for InspectPro to redirect to — a real Zapier integration means
InspectPro gets *listed on* Zapier's platform (built via Zapier's Developer/SDK
platform) and Zapier's own users connect *to* InspectPro using an API key, the
reverse direction. This module builds the InspectPro side of that: generating,
storing, and verifying an API key — without building/publishing the actual
Zapier app (that requires real trigger/action endpoints, tracked separately).

Endpoints:
  POST   /api/zapier/generate-key   → (admin/manager only) generate + store a new key,
                                       returned in plaintext ONCE
  GET    /api/zapier/status         → { configured, last4, generated_at }
  DELETE /api/zapier/revoke-key     → (admin/manager only) revoke the current key
  GET    /api/zapier/ping           → authenticated via `Authorization: Bearer <api key>`
                                       (not JWT) — proves the key works end-to-end;
                                       the same require_zapier_api_key decorator real
                                       future trigger/action endpoints would reuse

The key itself is never stored in plaintext — only its SHA-256 hash, plus the
last 4 characters for UI display (same "shown once" pattern as GitHub PATs).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, request, jsonify

zapier_bp = Blueprint('zapier', __name__)

_KEY_PREFIX = 'ipz_live_'
_SETTING_KEYS = ('zapier_api_key_hash', 'zapier_api_key_last4', 'zapier_api_key_generated_at')


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _load() -> dict:
    from models import SystemSetting
    rows = SystemSetting.query.filter(SystemSetting.key.in_(_SETTING_KEYS)).all()
    return {r.key: r.value for r in rows}


def require_zapier_api_key(fn):
    """Decorator for endpoints authenticated by the Zapier API key instead of a JWT."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing API key'}), 401

        provided = auth_header[len('Bearer '):].strip()
        stored = _load()
        stored_hash = stored.get('zapier_api_key_hash', '')
        if not stored_hash or not provided:
            return jsonify({'error': 'Invalid API key'}), 401
        if not secrets.compare_digest(_hash_key(provided), stored_hash):
            return jsonify({'error': 'Invalid API key'}), 401

        return fn(*args, **kwargs)
    return wrapper


@zapier_bp.route('', methods=['OPTIONS'])
@zapier_bp.route('/generate-key', methods=['OPTIONS'])
@zapier_bp.route('/status', methods=['OPTIONS'])
@zapier_bp.route('/revoke-key', methods=['OPTIONS'])
@zapier_bp.route('/ping', methods=['OPTIONS'])
def handle_options():
    return '', 204


@zapier_bp.route('/generate-key', methods=['POST'])
def generate_key():
    from flask_jwt_extended import verify_jwt_in_request
    from permissions import get_current_user, is_admin_or_manager
    from models import db, SystemSetting

    verify_jwt_in_request()
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403

    key = _KEY_PREFIX + secrets.token_urlsafe(32)
    data = {
        'zapier_api_key_hash':         _hash_key(key),
        'zapier_api_key_last4':        key[-4:],
        'zapier_api_key_generated_at': datetime.now(timezone.utc).isoformat(),
    }
    for k, v in data.items():
        row = SystemSetting.query.filter_by(key=k).first()
        if row is None:
            db.session.add(SystemSetting(key=k, value=v))
        else:
            row.value = v
    db.session.commit()

    return jsonify({'api_key': key, 'last4': key[-4:]})


@zapier_bp.route('/status', methods=['GET'])
def status():
    from flask_jwt_extended import verify_jwt_in_request
    verify_jwt_in_request()

    stored = _load()
    return jsonify({
        'configured':   bool(stored.get('zapier_api_key_hash')),
        'last4':        stored.get('zapier_api_key_last4', ''),
        'generated_at': stored.get('zapier_api_key_generated_at', ''),
    })


@zapier_bp.route('/revoke-key', methods=['DELETE'])
def revoke_key():
    from flask_jwt_extended import verify_jwt_in_request
    from permissions import get_current_user, is_admin_or_manager
    from models import db, SystemSetting

    verify_jwt_in_request()
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403

    SystemSetting.query.filter(SystemSetting.key.in_(_SETTING_KEYS)).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'revoked': True})


@zapier_bp.route('/ping', methods=['GET'])
@require_zapier_api_key
def ping():
    from models import SystemSetting
    company_row = SystemSetting.query.filter_by(key='company_name').first()
    return jsonify({'ok': True, 'company': (company_row.value if company_row else '') or ''})
