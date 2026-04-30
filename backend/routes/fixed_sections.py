from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, SystemSetting
import json

fixed_sections_bp = Blueprint('fixed_sections', __name__)

VALID_COLUMNS = {
    'name', 'question', 'answer', 'cleanliness', 'description',
    'condition', 'additional_notes', 'location_serial', 'reading'
}

DEFAULT_FIXED_SECTIONS = [
    {
        "name": "Condition Summary",
        "enabled": True,
        "columns": ["name", "condition", "additional_notes"],
        "items": []
    },
    {
        "name": "Cleaning Summary",
        "enabled": True,
        "columns": ["name", "cleanliness", "additional_notes"],
        "items": []
    },
    {
        "name": "Smoke & Carbon Alarms",
        "enabled": True,
        "columns": ["name", "answer", "condition"],
        "items": [
            {"name": "Smoke Alarm — Hallway",    "answer": "Yes", "condition": ""},
            {"name": "Smoke Alarm — Landing",    "answer": "Yes", "condition": ""},
            {"name": "Carbon Monoxide Detector", "answer": "Yes", "condition": ""},
            {"name": "Heat Alarm — Kitchen",     "answer": "Yes", "condition": ""},
        ]
    },
    {
        "name": "Fire Door Safety",
        "enabled": True,
        "columns": ["name", "answer", "condition"],
        "items": [
            {"name": "Front Door — Self Closing", "answer": "Yes", "condition": ""},
            {"name": "Fire Door Signage",         "answer": "Yes", "condition": ""},
        ]
    },
    {
        "name": "Health & Safety",
        "enabled": True,
        "columns": ["name", "answer", "description"],
        "items": [
            {"name": "Electrical Consumer Unit",  "answer": "Yes", "description": ""},
            {"name": "Water Stop Tap Location",   "answer": "Yes", "description": ""},
        ]
    },
    {
        "name": "Keys",
        "enabled": True,
        "columns": ["name", "description"],
        "items": [
            {"name": "Full Sets",           "description": ""},
            {"name": "Access at Check Out", "description": ""},
        ]
    },
    {
        "name": "Utility Meter Readings",
        "enabled": True,
        "columns": ["name", "location_serial", "reading"],
        "items": [
            {"name": "Gas Meter",      "location_serial": "", "reading": ""},
            {"name": "Electric Meter", "location_serial": "", "reading": ""},
            {"name": "Water Meter",    "location_serial": "", "reading": ""},
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

        # Sanitise columns — keep only valid keys, at least one
        raw_cols = s.get('columns') or ['name']
        cols = [c for c in raw_cols if c in VALID_COLUMNS] or ['name']

        # Sanitise items — only keep keys that match the section's columns
        items = []
        for item in (s.get('items') or []):
            cleaned_item = {}
            for col in cols:
                cleaned_item[col] = str(item.get(col, ''))
            items.append(cleaned_item)

        cleaned.append({
            'name':    name,
            'enabled': bool(s.get('enabled', True)),
            'columns': cols,
            'items':   items,
        })

    _save_setting(cleaned)
    return jsonify(cleaned)


# ── Midterm Sections ─────────────────────────────────────────────────────────
# Parallel blueprint for midterm inspection fixed sections.
# Stored under SystemSetting key 'midterm_sections'.

midterm_sections_bp = Blueprint('midterm_sections', __name__)

DEFAULT_MIDTERM_SECTIONS = [
    {
        "name": "Property Condition Overview",
        "enabled": True,
        "columns": ["name", "condition", "additional_notes"],
        "items": []
    },
    {
        "name": "Safety & Alarms",
        "enabled": True,
        "columns": ["name", "answer", "condition"],
        "items": [
            {"name": "Smoke Alarm — Hallway",    "answer": "Yes", "condition": ""},
            {"name": "Carbon Monoxide Detector", "answer": "Yes", "condition": ""},
            {"name": "Heat Alarm — Kitchen",     "answer": "Yes", "condition": ""},
        ]
    },
    {
        "name": "Health & Safety",
        "enabled": True,
        "columns": ["name", "answer", "description"],
        "items": [
            {"name": "Electrical Consumer Unit", "answer": "Yes", "description": ""},
            {"name": "Water Stop Tap Location",  "answer": "Yes", "description": ""},
        ]
    },
    {
        "name": "Utility Meter Readings",
        "enabled": True,
        "columns": ["name", "location_serial", "reading"],
        "items": [
            {"name": "Gas Meter",      "location_serial": "", "reading": ""},
            {"name": "Electric Meter", "location_serial": "", "reading": ""},
            {"name": "Water Meter",    "location_serial": "", "reading": ""},
        ]
    },
    {
        "name": "Keys",
        "enabled": True,
        "columns": ["name", "description"],
        "items": [
            {"name": "Full Sets",    "description": ""},
            {"name": "Access Notes", "description": ""},
        ]
    },
]


def _get_midterm_setting():
    s = SystemSetting.query.filter_by(key='midterm_sections').first()
    if not s or not s.value:
        return DEFAULT_MIDTERM_SECTIONS
    try:
        return json.loads(s.value)
    except Exception:
        return DEFAULT_MIDTERM_SECTIONS


def _save_midterm_setting(sections):
    s = SystemSetting.query.filter_by(key='midterm_sections').first()
    if not s:
        s = SystemSetting(key='midterm_sections')
        db.session.add(s)
    s.value = json.dumps(sections)
    db.session.commit()


@midterm_sections_bp.route('', methods=['OPTIONS'])
def midterm_preflight():
    return '', 204


@midterm_sections_bp.route('', methods=['GET'])
@jwt_required()
def get_midterm_sections():
    return jsonify(_get_midterm_setting())


def _sanitise_sections(data):
    """Shared sanitiser for both fixed and midterm section lists."""
    if not isinstance(data, list):
        return None
    cleaned = []
    for s in data:
        name = str(s.get('name', '')).strip()
        if not name:
            continue
        raw_cols = s.get('columns') or ['name']
        cols = [c for c in raw_cols if c in VALID_COLUMNS] or ['name']
        items = []
        for item in (s.get('items') or []):
            cleaned_item = {col: str(item.get(col, '')) for col in cols}
            items.append(cleaned_item)
        cleaned.append({
            'name':    name,
            'enabled': bool(s.get('enabled', True)),
            'columns': cols,
            'items':   items,
        })
    return cleaned


@midterm_sections_bp.route('', methods=['PUT'])
@jwt_required()
def update_midterm_sections():
    data = request.get_json(force=True)
    cleaned = _sanitise_sections(data)
    if cleaned is None:
        return jsonify({'error': 'Expected a list'}), 400
    _save_midterm_setting(cleaned)
    return jsonify(cleaned)
