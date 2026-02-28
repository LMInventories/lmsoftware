from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from models import db, Inspection, Client, Property, User
from permissions import get_current_user

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    user = get_current_user()

    # ── Base inspection query filtered by role ────────────────────────────
    from permissions import filter_inspections_for_user
    insp_query = filter_inspections_for_user(Inspection.query, user)
    inspections = insp_query.all()

    # Status counts (only over inspections this user can see)
    status_counts = {
        'created':    0,
        'assigned':   0,
        'active':     0,
        'processing': 0,
        'review':     0,
        'complete':   0,
    }
    for i in inspections:
        s = (i.status or '').lower()
        if s in status_counts:
            status_counts[s] += 1

    # ── Totals — admin/manager see global counts, others see own ─────────
    if user.role in ('admin', 'manager'):
        totals = {
            'clients':     Client.query.count(),
            'properties':  Property.query.count(),
            'users':       User.query.count(),
            'inspections': Inspection.query.count(),
        }
    else:
        # Clerk/typist — show only their own counts, hide portfolio/users
        totals = {
            'clients':     None,
            'properties':  len(set(i.property_id for i in inspections)),
            'users':       None,
            'inspections': len(inspections),
        }

    # ── Recent inspections (most recent 10 the user can see) ─────────────
    recent = (
        insp_query
        .order_by(Inspection.created_at.desc())
        .limit(10)
        .all()
    )

    recent_list = []
    for i in recent:
        recent_list.append({
            'id':               i.id,
            'property_address': i.property.address if i.property else '',
            'inspection_type':  i.inspection_type,
            'status':           i.status,
            'created_at':       i.created_at.isoformat() if i.created_at else None,
            'inspector_name':   i.inspector.name if i.inspector else None,
            'typist_name':      i.typist.name if i.typist else None,
        })

    return jsonify({
        'status_counts':      status_counts,
        'totals':             totals,
        'recent_inspections': recent_list,
    })
