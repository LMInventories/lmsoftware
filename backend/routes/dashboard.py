from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Inspection, Client, Property, User
from datetime import datetime, date

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    user_id = get_jwt_identity()
    current_user = User.query.get(int(user_id))

    # Status counts (role-filtered)
    def count_status(status):
        q = Inspection.query.filter_by(status=status)
        if current_user and current_user.role in ('clerk', 'typist'):
            q = q.filter(
                (Inspection.inspector_id == current_user.id) |
                (Inspection.typist_id == current_user.id)
            )
        return q.count()

    # Totals
    total_clients     = Client.query.count()
    total_properties  = Property.query.count()
    total_users       = User.query.count()
    total_inspections = Inspection.query.count()

    # ── Activity: last 20 inspections ordered by updated_at/created_at ──
    activity_q = Inspection.query.order_by(
        Inspection.updated_at.desc() if hasattr(Inspection, 'updated_at') else Inspection.created_at.desc()
    ).limit(20).all()

    activity_list = []
    for i in activity_q:
        activity_list.append({
            'id': i.id,
            'label': i.property.address if i.property else 'Unknown',
            'sub': (i.property.client.name if i.property and i.property.client else None),
            'status': i.status,
            'time': (
                i.updated_at.isoformat() if hasattr(i, 'updated_at') and i.updated_at
                else (i.created_at.isoformat() if i.created_at else None)
            ),
            'inspection_type': i.inspection_type,
        })

    # ── Upcoming: inspections with conduct_date >= today, ordered by date ──
    today = datetime.combine(date.today(), datetime.min.time())
    upcoming_q = (
        Inspection.query
        .filter(Inspection.conduct_date >= today)
        .filter(Inspection.status.notin_(['complete']))
        .order_by(Inspection.conduct_date.asc())
        .limit(30)
        .all()
    )

    # Also include active/assigned inspections without a date (show them in activity, not upcoming)
    upcoming_list = []
    for i in upcoming_q:
        upcoming_list.append({
            'id': i.id,
            'property_address': i.property.address if i.property else 'Unknown',
            'client_name': (i.property.client.name if i.property and i.property.client else None),
            'client_id': (i.property.client_id if i.property else None),
            'inspection_type': i.inspection_type,
            'status': i.status,
            'conduct_date': i.conduct_date.isoformat() if i.conduct_date else None,
            'conduct_time_preference': i.conduct_time_preference,
            'inspector_name': i.inspector.name if i.inspector else None,
            'typist_name': i.typist.name if i.typist else None,
            'created_at': i.created_at.isoformat() if i.created_at else None,
        })

    # ── recent_inspections kept for backwards compat (last 10 by created) ──
    recent_q = Inspection.query.order_by(Inspection.created_at.desc()).limit(10).all()
    recent_list = []
    for i in recent_q:
        recent_list.append({
            'id': i.id,
            'property_address': i.property.address if i.property else 'Unknown',
            'client_name': (i.property.client.name if i.property and i.property.client else None),
            'client_id': (i.property.client_id if i.property else None),
            'inspection_type': i.inspection_type,
            'status': i.status,
            'conduct_date': i.conduct_date.isoformat() if i.conduct_date else None,
            'updated_at': (
                i.updated_at.isoformat() if hasattr(i, 'updated_at') and i.updated_at
                else (i.created_at.isoformat() if i.created_at else None)
            ),
            'created_at': i.created_at.isoformat() if i.created_at else None,
            'inspector_name': i.inspector.name if i.inspector else None,
            'typist_name': i.typist.name if i.typist else None,
        })

    return jsonify({
        'status_counts': {
            'created':    count_status('created'),
            'assigned':   count_status('assigned'),
            'active':     count_status('active'),
            'processing': count_status('processing'),
            'review':     count_status('review'),
            'complete':   count_status('complete'),
        },
        'totals': {
            'clients':     total_clients,
            'properties':  total_properties,
            'users':       total_users,
            'inspections': total_inspections,
        },
        'activity':             activity_list,
        'upcoming':             upcoming_list,
        'recent_inspections':   recent_list,   # kept for compat
    })
