from datetime import date
from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required
from models import db, User, UserUnavailability
from permissions import require_role, get_current_user, is_admin_or_manager
from services.availability import unavailable_user_ids

availability_bp = Blueprint('availability', __name__)

KINDS = ('repeating', 'holiday')
# Only people who can be booked onto jobs (or schedule them) manage availability.
AVAILABILITY_ROLES = ('clerk', 'manager', 'admin')


def _parse_date(v):
    try:
        return date.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def _apply(block, data):
    """Validate + copy payload onto a block. Returns an error string or None."""
    if block.kind == 'repeating':
        wd = data.get('weekday')
        if not isinstance(wd, int) or not 0 <= wd <= 6:
            return 'weekday must be 0-6'
        block.weekday = wd
        block.start_date = block.end_date = None
    else:
        sd = _parse_date(data.get('start_date'))
        ed = _parse_date(data.get('end_date')) or sd
        if not sd or ed < sd:
            return 'valid start_date/end_date required'
        block.start_date, block.end_date, block.weekday = sd, ed, None
    sm, em = data.get('start_min'), data.get('end_min')
    if sm is None and em is None:
        block.start_min = block.end_min = None
    else:
        if not (isinstance(sm, int) and isinstance(em, int) and 0 <= sm < em <= 1440):
            return 'start_min/end_min must be minutes with start < end'
        if block.kind == 'holiday' and block.end_date != block.start_date:
            return 'multi-day ranges must be all day'
        block.start_min, block.end_min = sm, em
    return None


def _target_user_id():
    """Whose availability this request acts on.

    Everyone acts on themselves. Admins and managers may pass ?user_id=<id> to act on
    any other admin/manager/clerk. Returns (user_id, error_response_or_None).
    """
    me = get_current_user()
    raw = request.args.get('user_id')
    if raw in (None, '', str(me.id)):
        return me.id, None
    if not is_admin_or_manager(me):
        return None, (jsonify({'error': 'Forbidden'}), 403)
    try:
        uid = int(raw)
    except ValueError:
        return None, (jsonify({'error': 'invalid user_id'}), 400)
    target = db.session.get(User, uid)
    if not target or target.role not in AVAILABILITY_ROLES:
        return None, (jsonify({'error': 'User not found'}), 404)
    return uid, None


def _own_block_or_404(block_id):
    """Fetch a block the requester may change: their own, or anyone's for admin/manager."""
    me = get_current_user()
    block = UserUnavailability.query.get_or_404(block_id)
    if block.user_id != me.id and not is_admin_or_manager(me):
        abort(404)
    return block


@availability_bp.route('/me', methods=['GET'])
@jwt_required()
@require_role(*AVAILABILITY_ROLES)
def list_mine():
    uid, err = _target_user_id()
    if err:
        return err
    rows = UserUnavailability.query.filter_by(user_id=uid).order_by(UserUnavailability.id).all()
    return jsonify([r.to_dict() for r in rows])


@availability_bp.route('/team', methods=['GET'])
@jwt_required()
@require_role('admin', 'manager')
def team():
    """Every admin/manager/clerk with their colour and unavailability blocks."""
    users = (User.query.filter(User.role.in_(AVAILABILITY_ROLES), User.is_ai.is_(False))
             .order_by(User.name).all())
    blocks = {}
    for r in UserUnavailability.query.order_by(UserUnavailability.id).all():
        blocks.setdefault(r.user_id, []).append(r.to_dict())
    return jsonify([
        {'id': u.id, 'name': u.name, 'role': u.role, 'color': u.color or '#6366f1',
         'blocks': blocks.get(u.id, [])}
        for u in users
    ])


@availability_bp.route('/me', methods=['POST'])
@jwt_required()
@require_role(*AVAILABILITY_ROLES)
def create_block():
    uid, err = _target_user_id()
    if err:
        return err
    data = request.json or {}
    kind = data.get('kind')
    if kind not in KINDS:
        return jsonify({'error': "kind must be 'repeating' or 'holiday'"}), 400
    block = UserUnavailability(user_id=uid, kind=kind)
    err = _apply(block, data)
    if err:
        return jsonify({'error': err}), 400
    db.session.add(block)
    db.session.commit()
    return jsonify(block.to_dict()), 201


@availability_bp.route('/me/<int:block_id>', methods=['PUT'])
@jwt_required()
@require_role(*AVAILABILITY_ROLES)
def update_block(block_id):
    block = _own_block_or_404(block_id)
    err = _apply(block, request.json or {})
    if err:
        db.session.rollback()
        return jsonify({'error': err}), 400
    db.session.commit()
    return jsonify(block.to_dict())


@availability_bp.route('/me/<int:block_id>', methods=['DELETE'])
@jwt_required()
@require_role(*AVAILABILITY_ROLES)
def delete_block(block_id):
    block = _own_block_or_404(block_id)
    db.session.delete(block)
    db.session.commit()
    return '', 204


@availability_bp.route('/me', methods=['DELETE'])
@jwt_required()
@require_role(*AVAILABILITY_ROLES)
def clear_blocks():
    """Remove all unavailability of one kind (?kind=repeating|holiday)."""
    uid, err = _target_user_id()
    if err:
        return err
    kind = request.args.get('kind')
    if kind not in KINDS:
        return jsonify({'error': "kind must be 'repeating' or 'holiday'"}), 400
    UserUnavailability.query.filter_by(user_id=uid, kind=kind).delete()
    db.session.commit()
    return '', 204


@availability_bp.route('/unavailable', methods=['GET'])
@jwt_required()
@require_role('admin', 'manager', 'clerk', 'typist')
def unavailable():
    """User IDs unavailable for ?date=YYYY-MM-DD&time=am|pm|anytime|specific:HH_MM."""
    d = _parse_date((request.args.get('date') or '')[:10])
    if not d:
        return jsonify({'user_ids': []})
    return jsonify({'user_ids': sorted(unavailable_user_ids(d, request.args.get('time')))})
