"""
backend/routes/system_settings.py
----------------------------------
System-wide settings endpoint.
Register in app.py:
    from routes.system_settings import system_settings_bp
    app.register_blueprint(system_settings_bp, url_prefix='/api/system-settings')
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, SystemSetting

system_settings_bp = Blueprint('system_settings', __name__)

# Keys permitted to be read / written via this endpoint
ALLOWED_KEYS = {
    # Company info
    'company_name', 'address_line1', 'address_line2',
    'city', 'postcode', 'email', 'phone', 'website', 'logo',
    # AIIC membership branding
    'aiic_logo',
    # Report style (global)
    'report_header_text_color',
    'report_body_text_color',
    'report_orientation',
}


def _upsert(key: str, value: str):
    """Insert or update a single SystemSetting row."""
    row = SystemSetting.query.filter_by(key=key).first()
    if row is None:
        row = SystemSetting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value


@system_settings_bp.route('', methods=['OPTIONS'])
def handle_options():
    return '', 204


@system_settings_bp.route('', methods=['GET'])
@jwt_required()
def get_settings():
    """Return all system settings as a flat JSON object."""
    rows = SystemSetting.query.all()
    data = {r.key: r.value for r in rows}
    # Return every allowed key so the frontend always gets a consistent shape
    result = {k: data.get(k, '') for k in ALLOWED_KEYS}
    return jsonify(result)


@system_settings_bp.route('', methods=['PUT'])
@jwt_required()
def update_settings():
    """Bulk-update system settings. Silently ignores unknown keys."""
    payload = request.json or {}
    updated = []
    for key, value in payload.items():
        if key not in ALLOWED_KEYS:
            continue
        _upsert(key, value if value is not None else '')
        updated.append(key)
    db.session.commit()
    # Return the current full settings so the frontend can sync
    rows = SystemSetting.query.all()
    data = {r.key: r.value for r in rows}
    return jsonify({
        'updated': updated,
        'settings': {k: data.get(k, '') for k in ALLOWED_KEYS},
    })
