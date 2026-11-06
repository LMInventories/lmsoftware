from datetime import date
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, UserUnavailability
from services.availability import unavailable_user_ids

availability_bp = Blueprint('availability', __name__)

KINDS = ('repeating', 'holiday')


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


@availability_bp.route('/me', methods=['GET'])
@jwt_required()
def list_mine():
    uid = int(get_jwt_identity())
    rows = UserUnavailability.query.filter_by(user_id=uid).order_by(UserUnavailability.id).all()
    return jsonify([r.to_dict() for r in rows])


@availability_bp.route('/me', methods=['POST'])
@jwt_required()
def create_block():
    data = request.json or {}
    kind = data.get('kind')
    if kind not in KINDS:
        return jsonify({'error': "kind must be 'repeating' or 'holiday'"}), 400
    block = UserUnavailability(user_id=int(get_jwt_identity()), kind=kind)
    err = _apply(block, data)
    if err:
        return jsonify({'error': err}), 400
    db.session.add(block)
    db.session.commit()
    return jsonify(block.to_dict()), 201


@availability_bp.route('/me/<int:block_id>', methods=['PUT'])
@jwt_required()
def update_block(block_id):
    block = UserUnavailability.query.filter_by(id=block_id, user_id=int(get_jwt_identity())).first_or_404()
    err = _apply(block, request.json or {})
    if err:
        db.session.rollback()
        return jsonify({'error': err}), 400
    db.session.commit()
    return jsonify(block.to_dict())


@availability_bp.route('/me/<int:block_id>', methods=['DELETE'])
@jwt_required()
def delete_block(block_id):
    block = UserUnavailability.query.filter_by(id=block_id, user_id=int(get_jwt_identity())).first_or_404()
    db.session.delete(block)
    db.session.commit()
    return '', 204


@availability_bp.route('/me', methods=['DELETE'])
@jwt_required()
def clear_blocks():
    """Remove all unavailability of one kind (?kind=repeating|holiday)."""
    kind = request.args.get('kind')
    if kind not in KINDS:
        return jsonify({'error': "kind must be 'repeating' or 'holiday'"}), 400
    UserUnavailability.query.filter_by(user_id=int(get_jwt_identity()), kind=kind).delete()
    db.session.commit()
    return '', 204


@availability_bp.route('/unavailable', methods=['GET'])
@jwt_required()
def unavailable():
    """User IDs unavailable for ?date=YYYY-MM-DD&time=am|pm|anytime|specific:HH_MM."""
    d = _parse_date((request.args.get('date') or '')[:10])
    if not d:
        return jsonify({'user_ids': []})
    return jsonify({'user_ids': sorted(unavailable_user_ids(d, request.args.get('time')))})
