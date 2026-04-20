from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Inspection, Client, Property, User
from datetime import datetime, date
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload, selectinload

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    user_id = get_jwt_identity()
    current_user = User.query.get(int(user_id))
    role = current_user.role if current_user else None

    def _base_inspection_query():
        """Return an Inspection query pre-filtered for the current user's role."""
        q = Inspection.query
        if role == 'clerk':
            q = q.filter(Inspection.inspector_id == current_user.id)
        elif role == 'typist':
            q = q.filter(Inspection.typist_id == current_user.id)
        elif role == 'client':
            # Join through Property to filter by client_id
            q = (q.join(Property, Inspection.property_id == Property.id)
                  .filter(Property.client_id == current_user.client_id))
        return q

    # ── Status counts — one aggregation query instead of 6 separate COUNTs ──
    # with_entities() replaces the SELECT * with SELECT status, COUNT(id)
    # while keeping all the same WHERE / JOIN filters from _base_inspection_query().
    status_rows = (
        _base_inspection_query()
        .with_entities(Inspection.status, func.count(Inspection.id))
        .group_by(Inspection.status)
        .all()
    )
    sc = {s: c for s, c in status_rows}  # e.g. {'created': 3, 'active': 12, ...}

    # ── Totals — scoped to role ──────────────────────────────────────────────
    if role in ('admin', 'manager'):
        total_clients     = Client.query.count()
        total_properties  = Property.query.count()
        total_users       = User.query.count()
        total_inspections = Inspection.query.count()
    elif role == 'client':
        total_clients     = 1
        total_properties  = Property.query.filter_by(client_id=current_user.client_id).count()
        total_users       = None
        total_inspections = _base_inspection_query().count()
    else:
        # clerk / typist — show their own inspection count only
        total_clients     = None
        total_properties  = None
        total_users       = None
        total_inspections = _base_inspection_query().count()

    # Shared eager-load options for the 3 list queries below.
    # Without this, accessing i.property / i.property.client / i.inspector / i.typist
    # triggers a lazy-load query per inspection — 4 × N extra round trips.
    # selectinload (SELECT…IN) is used instead of joinedload to avoid a conflict
    # with the explicit Property JOIN that the 'client' role filter already adds.
    _eager = [
        selectinload(Inspection.property).selectinload(Property.client),
        selectinload(Inspection.inspector),
        selectinload(Inspection.typist),
    ]

    # ── Activity: last 20 inspections, role-filtered ─────────────────────────
    activity_q = (
        _base_inspection_query()
        .options(*_eager)
        .order_by(
            Inspection.updated_at.desc() if hasattr(Inspection, 'updated_at')
            else Inspection.created_at.desc()
        )
        .limit(20)
        .all()
    )

    activity_list = []
    for i in activity_q:
        activity_list.append({
            'id':             i.id,
            'label':          i.property.address if i.property else 'Unknown',
            'sub':            (i.property.client.name if i.property and i.property.client else None),
            'status':         i.status,
            'time': (
                i.updated_at.isoformat() if hasattr(i, 'updated_at') and i.updated_at
                else (i.created_at.isoformat() if i.created_at else None)
            ),
            'inspection_type': i.inspection_type,
        })

    # ── Upcoming: role-filtered, conduct_date >= today ───────────────────────
    today = datetime.combine(date.today(), datetime.min.time())
    upcoming_q = (
        _base_inspection_query()
        .options(*_eager)
        .filter(Inspection.conduct_date >= today)
        .filter(Inspection.status.notin_(['complete']))
        .order_by(Inspection.conduct_date.asc())
        .limit(30)
        .all()
    )

    upcoming_list = []
    for i in upcoming_q:
        upcoming_list.append({
            'id':                      i.id,
            'property_address':        i.property.address if i.property else 'Unknown',
            'client_name':             (i.property.client.name if i.property and i.property.client else None),
            'client_id':               (i.property.client_id if i.property else None),
            'inspection_type':         i.inspection_type,
            'status':                  i.status,
            'conduct_date':            i.conduct_date.isoformat() if i.conduct_date else None,
            'conduct_time_preference': i.conduct_time_preference,
            'inspector_name':          i.inspector.name if i.inspector else None,
            'typist_name':             i.typist.name if i.typist else None,
            'created_at':              i.created_at.isoformat() if i.created_at else None,
        })

    # ── Recent inspections (backwards compat) — role-filtered ────────────────
    recent_q = (
        _base_inspection_query()
        .options(*_eager)
        .order_by(Inspection.created_at.desc())
        .limit(10)
        .all()
    )
    recent_list = []
    for i in recent_q:
        recent_list.append({
            'id':               i.id,
            'property_address': i.property.address if i.property else 'Unknown',
            'client_name':      (i.property.client.name if i.property and i.property.client else None),
            'client_id':        (i.property.client_id if i.property else None),
            'inspection_type':  i.inspection_type,
            'status':           i.status,
            'conduct_date':     i.conduct_date.isoformat() if i.conduct_date else None,
            'updated_at': (
                i.updated_at.isoformat() if hasattr(i, 'updated_at') and i.updated_at
                else (i.created_at.isoformat() if i.created_at else None)
            ),
            'created_at':       i.created_at.isoformat() if i.created_at else None,
            'inspector_name':   i.inspector.name if i.inspector else None,
            'typist_name':      i.typist.name if i.typist else None,
        })

    return jsonify({
        'status_counts': {
            'created':    sc.get('created',    0),
            'assigned':   sc.get('assigned',   0),
            'active':     sc.get('active',     0),
            'processing': sc.get('processing', 0),
            'review':     sc.get('review',     0),
            'complete':   sc.get('complete',   0),
        },
        'totals': {
            'clients':     total_clients,
            'properties':  total_properties,
            'users':       total_users,
            'inspections': total_inspections,
        },
        'activity':           activity_list,
        'upcoming':           upcoming_list,
        'recent_inspections': recent_list,
    })
