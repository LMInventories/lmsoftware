from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from models import db, User
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    
    print(f"Login attempt for: {data.get('email')}")
    
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Email and password required'}), 400
    
    user = User.query.filter_by(email=data['email']).first()
    
    if not user or not check_password_hash(user.password_hash, data['password']):
        print("Invalid credentials")
        return jsonify({'error': 'Invalid credentials'}), 401
    
    # Create access token
    access_token = create_access_token(identity=str(user.id))
    
    print(f"Login successful! User ID: {user.id}, Token created")
    
    return jsonify({
        'token': access_token,
        'user': {
            'id':          user.id,
            'name':        user.name,
            'email':       user.email,
            'role':        user.role,
            'color':       user.color,
            'is_ai':       user.is_ai,
            'typist_mode':   user.typist_mode,   # 'ai_instant' | 'ai_room' | 'human' | null
            'camera_option': user.camera_option,
            'client_id':     user.client_id,
        }
    })

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user_id = get_jwt_identity()
    print(f"Getting current user: {user_id}")
    user = db.session.get(User, int(user_id))

    if not user:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({
        'id':          user.id,
        'name':        user.name,
        'email':       user.email,
        'role':        user.role,
        'color':       user.color,
        'is_ai':       user.is_ai,
        'typist_mode':   user.typist_mode,
        'camera_option': user.camera_option,
        'client_id':     user.client_id,
    })


@auth_bp.route('/me', methods=['PATCH'])
@jwt_required()
def update_my_defaults():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))
    if not user:
        return jsonify({'error': 'User not found'}), 404
    data = request.get_json() or {}
    if 'typist_mode' in data:
        user.typist_mode = data['typist_mode'] or None
    if 'camera_option' in data:
        user.camera_option = data['camera_option'] or None
    db.session.commit()
    return jsonify({
        'id':            user.id,
        'name':          user.name,
        'email':         user.email,
        'role':          user.role,
        'color':         user.color,
        'is_ai':         user.is_ai,
        'typist_mode':   user.typist_mode,
        'camera_option': user.camera_option,
        'client_id':     user.client_id,
    })


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required()
def refresh_token():
    """Issue a fresh token for a still-valid token.

    Called automatically by the frontend when a 401 is received so users are
    never kicked out due to a transient network blip or an imminent expiry.
    """
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))

    if not user:
        return jsonify({'error': 'User not found'}), 404

    new_token = create_access_token(identity=str(user.id))
    return jsonify({'token': new_token})
