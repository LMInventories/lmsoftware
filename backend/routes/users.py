from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User
import traceback

users_bp = Blueprint('users', __name__)

@users_bp.route('', methods=['GET'])
@jwt_required()
def get_users():
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
    try:
        user = User.query.get_or_404(user_id)
        data = request.json
        print(f"UPDATE USER {user_id} payload keys: {list(data.keys())}")

        if 'email' in data and data['email']:
            existing = User.query.filter_by(email=data['email']).first()
            if existing and existing.id != user_id:
                return jsonify({'error': 'Email already exists'}), 400
            user.email = data['email']

        if 'name' in data and data['name']:
            user.name = data['name']
        if 'phone' in data:
            user.phone = data['phone'] or None
        if 'role' in data and data['role']:
            user.role = data['role']
        if 'color' in data and data['color']:
            user.color = data['color']
        if 'password' in data and data['password']:
            user.set_password(data['password'])

        db.session.commit()
        print(f"User updated: id={user.id}")
        return jsonify(user.to_dict())

    except Exception as e:
        db.session.rollback()
        print(f"UPDATE USER ERROR: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@users_bp.route('/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return '', 204
