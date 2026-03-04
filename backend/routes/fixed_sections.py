from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, SystemSetting
import json

fixed_sections_bp = Blueprint('fixed_sections', __name__)

DEFAULT_FIXED_SECTIONS = [
    {
        "name": "Condition Summary",
        "enabled": True,
        "items": []
    },
    {
        "name": "Cleaning Summary",
        "enabled": True,
        "items": []
    },
    {
        "name": "Smoke & Carbon Alarms",
        "enabled": True,
        "items": [
            {"name": "Smoke Alarm — Hallway",        "description": "", "requires_photo": True,  "requires_condition": True},
            {"name": "Smoke Alarm — Landing",        "description": "", "requires_photo": True,  "requires_condition": True},
            {"name": "Carbon Monoxide Detector",     "description": "", "requires_photo": True,  "requires_condition": True},
            {"name": "Heat Alarm — Kitchen",         "description": "", "requires_photo": True,  "requires_condition": True},
        ]
    },
    {
        "name": "Fire Door Safety",
        "enabled": True,
        "items": [
            {"name": "Front Door — Self Closing",    "description": "", "requires_photo": True,  "requires_condition": True},
            {"name": "Fire Door Signage",            "description": "", "requires_photo": True,  "requires_condition": False},
        ]
    },
    {
        "name": "Health & Safety",
        "enabled": True,
        "items": [
            {"name": "Electrical Consumer Unit",     "description": "", "requires_photo": True,  "requires_condition": True},
            {"name": "Water Stop Tap Location",      "description": "", "requires_photo": True,  "requires_condition": False},
        ]
    },
    {
        "name": "Keys",
        "enabled": True,
        "items": [
            {"name": "Full Sets",                    "description": "", "requires_photo": False, "requires_condition": False},
            {"name": "Access at Check Out",          "description": "", "requires_photo": True,  "requires_condition": False},
        ]
    },
    {
        "name": "Utility Meter Readings",
        "enabled": True,
        "items": [
            {"name": "Gas Meter",                    "description": "", "requires_photo": True,  "requires_condition": False},
            {"name": "Electric Meter",               "description": "", "requires_photo": True,  "requires_condition": False},
            {"name": "Water Meter",                  "description": "", "requires_photo": True,  "requires_condition": False},
        ]
    },
]


def _get_setting():
    s = SystemSetting.query.filter_by(key='fixed_sections').first()
    if not s or not s.value:
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

    cleaned = []
    for s in data:
        name = str(s.get('name', '')).strip()
        if not name:
            continue
        items = []
        for item in (s.get('items') or []):
            item_name = str(item.get('name', '')).strip()
            if not item_name:
                continue
            items.append({
                'name':               item_name,
                'description':        str(item.get('description', '')),
                'requires_photo':     bool(item.get('requires_photo', True)),
                'requires_condition': bool(item.get('requires_condition', True)),
            })
        cleaned.append({
            'name':    name,
            'enabled': bool(s.get('enabled', True)),
            'items':   items,
        })

    _save_setting(cleaned)
    return jsonify(cleaned)
