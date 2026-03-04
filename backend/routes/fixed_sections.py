from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, SystemSetting
import json

fixed_sections_bp = Blueprint('fixed_sections', __name__)

DEFAULT_FIXED_SECTIONS = [
    { "name": "Condition Summary",       "enabled": True },
    { "name": "Cleaning Summary",        "enabled": True },
    { "name": "Smoke & Carbon Alarms",   "enabled": True },
    { "name": "Fire Door Safety",        "enabled": True },
    { "name": "Health & Safety",         "enabled": True },
    { "name": "Keys",                    "enabled": True },
    { "name": "Utility Meter Readings",  "enabled": True },
]

def _get_setting():
    s = SystemSetting.query.filter_by(key='fixed_sections').first()
    if not s:
        return DEFAULT_FIXED_SECTIONS
    try:
        return json.loads(s.value)
    except Exception:
        return DEFAULT_FIXED_SECTIONS

def _save_setting(sections):
    s = SystemSetting.query.filter_by(key='fixed_sections').first()
    if not s:
        s = SystemSetting(key='fixed_sections')
        db.session.add(s)
    s.value = json.dumps(sections)
    db.session.commit()


@fixed_sections_bp.route('', methods=['OPTIONS'])
def preflight():
    return '', 204


@fixed_sections_bp.route('', methods=['GET'])
@jwt_required()
def get_fixed_sections():
    return jsonify(_get_setting())


@fixed_sections_bp.route('', methods=['PUT'])
@jwt_required()
def update_fixed_sections():
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return jsonify({'error': 'Expected a list'}), 400
    # Sanitise — only keep name + enabled
    cleaned = [
        {'name': str(s.get('name', '')).strip(), 'enabled': bool(s.get('enabled', True))}
        for s in data if str(s.get('name', '')).strip()
    ]
    _save_setting(cleaned)
    return jsonify(cleaned)
