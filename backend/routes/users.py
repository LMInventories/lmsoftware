from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User
from permissions import get_current_user, is_admin_or_manager
import traceback

users_bp = Blueprint('users', __name__)

@users_bp.route('', methods=['GET'])
@jwt_required()
def get_users():
    user = get_current_user()
    # Clerks and typists can read the users list (needed for inspector/typist dropdowns)
    # but cannot create, update or delete
    users = User.query.all()
    return jsonify([u.to_dict() for u in users])

@users_bp.route('/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())

@users_bp.route('', methods=['POST'])
@jwt_required()
def create_user():
    current = get_current_user()
    if not is_admin_or_manager(current):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        data = request.json
        print(f"CREATE USER payload keys: {list(data.keys())}")
        if not data.get('email'):
            return jsonify({'error': 'Email is required'}), 400
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        if not data.get('password'):
            return jsonify({'error': 'Password is required'}), 400
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already exists'}), 400
        user = User(
            email=data['email'],
            name=data['name'],
            phone=data.get('phone') or None,
            role=data.get('role', 'clerk'),
            color=data.get('color', '#6366f1')
        )
        user.set_password(data['password'])
        db.session.add(user)
        db.session.commit()
        print(f"User created: id={user.id}")
        return jsonify(user.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        print(f"CREATE USER ERROR: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@users_bp.route('/<int:user_id>', methods=['PUT'])
@jwt_required()
def update_user(user_id):
    current = get_current_user()
    if not is_admin_or_manager(current):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        user = User.query.get_or_404(user_id)
        data = request.json
        print(f"UPDATE USER {user_id} payload keys: {list(data.keys())}")
        if 'email' in data and data['email']:
            existing = User.query.filter_by(email=data['email']).first()
            if existing and existing.id != user_id:
                return jsonify({'error': 'Email already exists'}), 400
            user.email = data['email']
        if 'name'     in data and data['name']:     user.name  = data['name']
        if 'phone'    in data:                       user.phone = data['phone'] or None
        if 'role'     in data and data['role']:      user.role  = data['role']
        if 'color'    in data and data['color']:     user.color = data['color']
        if 'password' in data and data['password']:  user.set_password(data['password'])
        db.session.commit()
        print(f"User updated: id={user.id}")
        return jsonify(user.to_dict())
    except Exception as e:
        db.session.rollback()
        print(f"UPDATE USER ERROR: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@users_bp.route('/me/change-password', methods=['POST'])
@jwt_required()
def change_password():
    import re
    current = get_current_user()
    data = request.json or {}

    current_password = data.get('current_password', '')
    new_password     = data.get('new_password', '')

    if not current.check_password(current_password):
        return jsonify({'error': 'Current password is incorrect'}), 400

    if len(new_password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    if not re.search(r'[A-Z]', new_password):
        return jsonify({'error': 'Password must contain at least one uppercase letter'}), 400
    if not re.search(r'[a-z]', new_password):
        return jsonify({'error': 'Password must contain at least one lowercase letter'}), 400
    if not re.search(r'[0-9]', new_password):
        return jsonify({'error': 'Password must contain at least one number'}), 400

    current.set_password(new_password)
    db.session.commit()
    return jsonify({'message': 'Password changed successfully'})


@users_bp.route('/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    current = get_current_user()
    if not is_admin_or_manager(current):
        return jsonify({'error': 'Forbidden'}), 403
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return '', 204
