"""
routes/floorplan_manual.py — manual floor-plan measurement tool.

The inspector walks each room's perimeter, measures each wall (laser
measure or tape) and optionally a diagonal for non-square corners (see the
mobile app's angleFromDiagonal — law of cosines, replaces guessing degrees
with a second real measurement), and the app computes a closed 2D polygon
per room client-side. A property can have several floors (Levels), each
containing several rooms; rooms are independently-drawn polygons the
inspector arranges by dragging into place — there's no automatic wall-
sharing between adjacent rooms.

This endpoint just stores that structure and renders it on demand — no
geometry inference happens here, unlike routes/floorplans.py's ARCore scan
pipeline (point cloud -> RANSAC -> drift-aware merging -> statistical
corner-finding). That pipeline is left in place and still works, but real
device testing showed ARCore's own pose-tracking drift means it can find
individual walls but not reliably close a room polygon. A physical
measurement has no drift, which is the entire reason this simpler path
exists.

Registered at /api/floorplan-manual — a distinct prefix from the ARCore
blueprint's /api/floorplans, so there's no path collision.
"""

import json

from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required
from models import db, Inspection, FloorPlanLevel, FloorPlanRoom
from permissions import get_current_user, is_admin_or_manager
from services.floorplan_render import render_level_svg

floorplan_manual_bp = Blueprint('floorplan_manual', __name__)


def _can_edit_floorplan(user, inspection) -> bool:
    """
    Same ownership rule as routes/floorplans.py's _can_view_scan_render:
    admin/manager always allowed, or the clerk (this codebase's field-
    inspector role) assigned to the inspection.
    """
    if is_admin_or_manager(user):
        return True
    return bool(user) and user.role == 'clerk' and inspection.inspector_id == user.id


def _authorize_inspection(inspection):
    """Returns an error (response, status) tuple, or None if authorized."""
    user = get_current_user()
    if not _can_edit_floorplan(user, inspection):
        return jsonify({'error': 'Forbidden'}), 403
    return None


@floorplan_manual_bp.route('/<int:inspection_id>/levels', methods=['GET'])
@jwt_required()
def list_levels(inspection_id):
    """All levels (floors) with their nested rooms — the main load call;
    the mobile app fetches this once on screen open. Empty list (not 404)
    when no levels exist yet, since 'no floor plan' is a valid, common
    state, not an error."""
    inspection = Inspection.query.get_or_404(inspection_id)
    error = _authorize_inspection(inspection)
    if error:
        return error

    levels = (
        FloorPlanLevel.query
        .filter_by(inspection_id=inspection_id)
        .order_by(FloorPlanLevel.order_index)
        .all()
    )
    return jsonify([lvl.to_dict() for lvl in levels])


@floorplan_manual_bp.route('/<int:inspection_id>/levels', methods=['POST'])
@jwt_required()
def create_level(inspection_id):
    """
    Body: { "name": "1st Floor", "copyFromLevelId": <int, optional> }
    If copyFromLevelId is given, deep-copies that level's rooms (new row
    IDs, same corners/symbols data) as a starting point — mirrors
    RoomSketcher's "copy an existing level" for floors with a similar
    footprint.
    """
    inspection = Inspection.query.get_or_404(inspection_id)
    error = _authorize_inspection(inspection)
    if error:
        return error

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400

    max_order = db.session.query(db.func.max(FloorPlanLevel.order_index)) \
        .filter_by(inspection_id=inspection_id).scalar()
    level = FloorPlanLevel(
        inspection_id=inspection_id, name=name,
        order_index=(max_order + 1) if max_order is not None else 0,
    )
    db.session.add(level)
    db.session.flush()  # assigns level.id before we reference it below

    copy_from_id = data.get('copyFromLevelId')
    if copy_from_id:
        source_level = FloorPlanLevel.query.get(copy_from_id)
        if source_level and source_level.inspection_id == inspection_id:
            for room in sorted(source_level.rooms, key=lambda r: r.order_index):
                db.session.add(FloorPlanRoom(
                    level_id=level.id, name=room.name, data=room.data,
                    order_index=room.order_index,
                ))

    db.session.commit()
    return jsonify(level.to_dict())


@floorplan_manual_bp.route('/levels/<int:level_id>', methods=['PATCH'])
@jwt_required()
def rename_level(level_id):
    level = FloorPlanLevel.query.get_or_404(level_id)
    error = _authorize_inspection(level.inspection)
    if error:
        return error

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400

    level.name = name
    db.session.commit()
    return jsonify(level.to_dict())


@floorplan_manual_bp.route('/levels/<int:level_id>', methods=['DELETE'])
@jwt_required()
def delete_level(level_id):
    level = FloorPlanLevel.query.get_or_404(level_id)
    error = _authorize_inspection(level.inspection)
    if error:
        return error

    db.session.delete(level)
    db.session.commit()
    return jsonify({'deleted': True})


@floorplan_manual_bp.route('/levels/<int:level_id>/rooms', methods=['POST'])
@jwt_required()
def create_room(level_id):
    """Body: { "name": "Living Room", "corners": [[x,z],...], "symbols": [...] }"""
    level = FloorPlanLevel.query.get_or_404(level_id)
    error = _authorize_inspection(level.inspection)
    if error:
        return error

    data = request.get_json() or {}
    name = (data.get('name') or '').strip() or 'Room'
    corners = data.get('corners')
    if not isinstance(corners, list) or len(corners) < 3:
        return jsonify({'error': 'corners must be a list of at least 3 [x, z] pairs'}), 400
    symbols = data.get('symbols') or []

    max_order = db.session.query(db.func.max(FloorPlanRoom.order_index)) \
        .filter_by(level_id=level_id).scalar()
    room = FloorPlanRoom(
        level_id=level_id, name=name,
        data=json.dumps({'corners': corners, 'symbols': symbols}),
        order_index=(max_order + 1) if max_order is not None else 0,
    )
    db.session.add(room)
    db.session.commit()
    return jsonify(room.to_dict())


@floorplan_manual_bp.route('/rooms/<int:room_id>', methods=['PUT'])
@jwt_required()
def update_room(room_id):
    """
    Partial update: { "name"?: str, "corners"?: [[x,z],...], "symbols"?: [...] }
    Only fields present in the body are overwritten — used for both the
    drag-to-reposition save (corners only) and symbol add/edit (symbols
    only), so neither has to resend the other.
    """
    room = FloorPlanRoom.query.get_or_404(room_id)
    error = _authorize_inspection(room.level.inspection)
    if error:
        return error

    data = request.get_json() or {}
    current = json.loads(room.data)

    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'name cannot be empty'}), 400
        room.name = name

    if 'corners' in data:
        corners = data.get('corners')
        if not isinstance(corners, list) or len(corners) < 3:
            return jsonify({'error': 'corners must be a list of at least 3 [x, z] pairs'}), 400
        current['corners'] = corners

    if 'symbols' in data:
        symbols = data.get('symbols')
        if not isinstance(symbols, list):
            return jsonify({'error': 'symbols must be a list'}), 400
        current['symbols'] = symbols

    room.data = json.dumps(current)
    db.session.commit()
    return jsonify(room.to_dict())


@floorplan_manual_bp.route('/rooms/<int:room_id>', methods=['DELETE'])
@jwt_required()
def delete_room(room_id):
    room = FloorPlanRoom.query.get_or_404(room_id)
    error = _authorize_inspection(room.level.inspection)
    if error:
        return error

    db.session.delete(room)
    db.session.commit()
    return jsonify({'deleted': True})


@floorplan_manual_bp.route('/levels/<int:level_id>/render', methods=['GET'])
@jwt_required()
def render_level(level_id):
    """Returns image/svg+xml directly, for direct <img src> / SvgXml use."""
    level = FloorPlanLevel.query.get_or_404(level_id)
    error = _authorize_inspection(level.inspection)
    if error:
        return error

    rooms = [
        {'corners': [tuple(pt) for pt in r.to_dict()['corners']], 'symbols': r.to_dict()['symbols']}
        for r in level.rooms
    ]
    svg = render_level_svg(rooms)
    if not svg:
        return jsonify({'error': 'Not enough geometry to render'}), 422

    return Response(svg, mimetype='image/svg+xml')
