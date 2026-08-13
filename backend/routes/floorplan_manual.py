"""
routes/floorplan_manual.py — manual floor-plan measurement tool.

The inspector walks the property's perimeter, measures each wall (laser
measure or tape), and the mobile app computes a closed 2D polygon
client-side (turtle graphics: wall length + turn angle, defaulting to 90
degrees per corner). This endpoint just stores that polygon and renders it
on demand — no geometry inference happens here, unlike routes/floorplans.py's
ARCore scan pipeline (point cloud -> RANSAC -> drift-aware merging ->
statistical corner-finding). That pipeline is left in place and still works,
but real device testing showed ARCore's own pose-tracking drift means it can
find individual walls but not reliably close a room polygon. A physical
measurement has no drift, which is the entire reason this simpler path
exists — it isn't a smaller version of the same idea, it sidesteps the
problem that limited the ARCore approach.

Registered at /api/floorplan-manual — a distinct prefix from the ARCore
blueprint's /api/floorplans, so there's no path collision and no risk of
one feature's routes being mistaken for the other's.
"""

import json

from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required
from models import db, Inspection, FloorPlan
from permissions import get_current_user, is_admin_or_manager
from services.floorplan_geometry import polygon_to_walls
from services.floorplan_render import render_floorplan_svg

floorplan_manual_bp = Blueprint('floorplan_manual', __name__)


def _can_edit_floorplan(user, inspection) -> bool:
    """
    Same ownership rule as routes/floorplans.py's _can_view_scan_render:
    admin/manager always allowed, or the clerk (this codebase's field-
    inspector role) assigned to the inspection. The inspector who measured
    a room needs to save/view/edit their own floor plan, not just admins.
    """
    if is_admin_or_manager(user):
        return True
    return bool(user) and user.role == 'clerk' and inspection.inspector_id == user.id


@floorplan_manual_bp.route('/<int:inspection_id>', methods=['PUT'])
@jwt_required()
def save_floorplan(inspection_id):
    """
    Create or replace the floor plan for an inspection (upsert — one
    floor plan per inspection, matching the mobile app's Create/View
    Floorplan button's binary state).

    Request body: { "corners": [[x, z], [x, z], ...] } — a closed polygon
    in meters, NOT repeating the first point at the end.
    """
    inspection = Inspection.query.get_or_404(inspection_id)

    user = get_current_user()
    if not _can_edit_floorplan(user, inspection):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json() or {}
    corners = data.get('corners')
    if not isinstance(corners, list) or len(corners) < 3:
        return jsonify({'error': 'corners must be a list of at least 3 [x, z] pairs'}), 400
    for pt in corners:
        if not (isinstance(pt, list) and len(pt) == 2):
            return jsonify({'error': 'each corner must be a [x, z] pair'}), 400

    plan = FloorPlan.query.filter_by(inspection_id=inspection_id).first()
    if plan is None:
        plan = FloorPlan(inspection_id=inspection_id, corners=json.dumps(corners))
        db.session.add(plan)
    else:
        plan.corners = json.dumps(corners)

    db.session.commit()
    return jsonify(plan.to_dict())


@floorplan_manual_bp.route('/<int:inspection_id>', methods=['GET'])
@jwt_required()
def get_floorplan(inspection_id):
    """404 if no floor plan has been saved yet — the mobile app uses this
    to decide whether to show 'Create Floorplan' or 'View Floorplan'."""
    inspection = Inspection.query.get_or_404(inspection_id)

    user = get_current_user()
    if not _can_edit_floorplan(user, inspection):
        return jsonify({'error': 'Forbidden'}), 403

    plan = FloorPlan.query.filter_by(inspection_id=inspection_id).first()
    if plan is None:
        return jsonify({'error': 'No floor plan saved for this inspection yet'}), 404

    return jsonify(plan.to_dict())


@floorplan_manual_bp.route('/<int:inspection_id>/render', methods=['GET'])
@jwt_required()
def render_floorplan(inspection_id):
    """Returns image/svg+xml directly, for direct <img src> / SvgXml use."""
    inspection = Inspection.query.get_or_404(inspection_id)

    user = get_current_user()
    if not _can_edit_floorplan(user, inspection):
        return jsonify({'error': 'Forbidden'}), 403

    plan = FloorPlan.query.filter_by(inspection_id=inspection_id).first()
    if plan is None:
        return jsonify({'error': 'No floor plan saved for this inspection yet'}), 404

    corners = [tuple(pt) for pt in plan.to_dict()['corners']]
    walls, corner_objs = polygon_to_walls(corners)
    svg = render_floorplan_svg(walls, corner_objs)
    if not svg:
        return jsonify({'error': 'Not enough geometry to render'}), 422

    return Response(svg, mimetype='image/svg+xml')
