from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db
from permissions import get_current_user, is_admin_or_manager
import json

actions_bp = Blueprint('actions', __name__)

# ─────────────────────────────────────────────────────────────────────────────
# Storage: actions are stored as a JSON config in a single settings row.
# We use a simple ActionConfig model (or fallback to a flat file approach via
# a SystemSetting model if one exists). If neither exists, we use a module-level
# in-memory store that persists for the process lifetime — add a DB model for
# production persistence.
#
# Expected schema in DB: SystemSetting(key='actions_config', value=JSON string)
# If your app has a different settings model, swap the load/save helpers below.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_ACTIONS = [
    {"id": "act_1", "name": "Review",               "color": "#3b82f6"},
    {"id": "act_2", "name": "Maintenance Required",  "color": "#f59e0b"},
    {"id": "act_3", "name": "Cleaning Required",     "color": "#8b5cf6"},
    {"id": "act_4", "name": "Missing Item",          "color": "#ef4444"},
    {"id": "act_5", "name": "Fair Wear & Tear",      "color": "#10b981"},
]

DEFAULT_RESPONSIBILITIES = ["Tenant", "Landlord/Agent", "Investigate", "Shared"]


def _load_config():
    """Load actions config from DB (SystemSetting) or return defaults."""
    try:
        from models import SystemSetting
        row = SystemSetting.query.filter_by(key='actions_config').first()
        if row and row.value:
            return json.loads(row.value)
    except Exception:
        pass
    return {
        "actions": DEFAULT_ACTIONS,
        "responsibilities": DEFAULT_RESPONSIBILITIES,
    }


def _save_config(config):
    """Persist actions config to DB."""
    try:
        from models import SystemSetting
        row = SystemSetting.query.filter_by(key='actions_config').first()
        if row:
            row.value = json.dumps(config)
        else:
            row = SystemSetting(key='actions_config', value=json.dumps(config))
            db.session.add(row)
        db.session.commit()
        return True
    except Exception:
        return False


# ─── GET /api/actions ────────────────────────────────────────────────────────
@actions_bp.route('', methods=['GET'])
@jwt_required()
def get_actions():
    return jsonify(_load_config())


# ─── PUT /api/actions ─────────────────────────────────────────────────────────
# Full replace — frontend sends the complete config object.
@actions_bp.route('', methods=['PUT'])
@jwt_required()
def save_actions():
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.json
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid payload'}), 400

    config = {
        "actions": data.get("actions", []),
        "responsibilities": data.get("responsibilities", []),
    }

    # Validate action shape
    for act in config["actions"]:
        if not isinstance(act, dict) or not act.get("id") or not act.get("name"):
            return jsonify({'error': 'Each action needs id and name'}), 400

    _save_config(config)
    return jsonify(config)
