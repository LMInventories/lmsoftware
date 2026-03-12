"""
Route permission helpers for InspectPro.

Role hierarchy:
  admin   → everything
  manager → everything
  clerk   → own assigned inspections + properties only, read-only reports
  typist  → own assigned inspections in Processing stage only, full report edit
  client  → inspections and properties belonging to their linked client_id, read-only
"""

from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity
from models import User


def get_current_user():
    """Return the User object for the current JWT identity."""
    return User.query.get(int(get_jwt_identity()))


def require_role(*roles):
    """
    Decorator: only allow users whose role is in `roles`.
    Usage:
        @require_role('admin', 'manager')
        def my_route(): ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user or user.role not in roles:
                return jsonify({'error': 'Forbidden'}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_admin_or_manager(fn):
    """Shortcut: admin or manager only."""
    return require_role('admin', 'manager')(fn)


def is_admin_or_manager(user):
    return user and user.role in ('admin', 'manager')


def is_clerk(user):
    return user and user.role == 'clerk'


def is_typist(user):
    return user and user.role == 'typist' and not user.is_ai


def is_client(user):
    return user and user.role == 'client'


def filter_inspections_for_user(query, user):
    """
    Apply role-based filtering to an Inspection query.

    - admin/manager: see everything
    - clerk: only inspections where inspector_id == user.id
    - typist: only inspections where typist_id == user.id AND status == 'processing'
    """
    from models import Inspection
    if user.role in ('admin', 'manager'):
        return query
    elif user.role == 'clerk':
        return query.filter(Inspection.inspector_id == user.id)
    elif user.role == 'typist':
        return query.filter(
            Inspection.typist_id == user.id,
            Inspection.status == 'processing'
        )
    elif user.role == 'client':
        from models import Property
        return query.join(Property, Inspection.property_id == Property.id).filter(
            Property.client_id == user.client_id
        )
    # Unknown role — return nothing
    return query.filter(False)


def filter_properties_for_user(query, user):
    """
    Apply role-based filtering to a Property query.

    - admin/manager: see everything
    - clerk: only properties that have at least one inspection assigned to them
    - typist: no direct property access needed
    """
    from models import Property, Inspection
    if user.role in ('admin', 'manager'):
        return query
    elif user.role == 'clerk':
        assigned_property_ids = (
            Inspection.query
            .filter(Inspection.inspector_id == user.id)
            .with_entities(Inspection.property_id)
            .distinct()
        )
        return query.filter(Property.id.in_(assigned_property_ids))
    elif user.role == 'typist':
        # Typists don't need property lists — return empty
        return query.filter(False)
    elif user.role == 'client':
        return query.filter(Property.client_id == user.client_id)
    return query.filter(False)
