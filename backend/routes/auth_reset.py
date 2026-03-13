"""
auth_reset.py — Password reset endpoints.

POST /api/auth/forgot-password   { email }           → always 200 (no enumeration)
POST /api/auth/reset-password    { token, password } → 200 or 400
"""
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from models import db, User
import os

auth_reset_bp = Blueprint('auth_reset', __name__)

APP_BASE_URL = os.environ.get('APP_BASE_URL', 'https://app.lminventories.co.uk')


@auth_reset_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    data  = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()

    # Always return 200 — never reveal whether the email exists
    if not email:
        return jsonify({'message': 'If that email exists, a reset link has been sent.'}), 200

    user = User.query.filter(
        db.func.lower(User.email) == email
    ).first()

    if user:
        token  = secrets.token_urlsafe(32)
        expiry = datetime.utcnow() + timedelta(hours=1)

        user.reset_token        = token
        user.reset_token_expiry = expiry
        db.session.commit()

        reset_url = f"{APP_BASE_URL}/reset-password?token={token}"
        try:
            from routes.email_service import send_password_reset
            send_password_reset(user, reset_url)
        except Exception as e:
            print(f'[email] password reset send failed: {e}')

    return jsonify({'message': 'If that email exists, a reset link has been sent.'}), 200


@auth_reset_bp.route('/reset-password', methods=['POST'])
def reset_password():
    data     = request.get_json() or {}
    token    = (data.get('token') or '').strip()
    password = data.get('password', '')

    if not token or not password:
        return jsonify({'error': 'Token and new password are required.'}), 400

    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters.'}), 400

    user = User.query.filter_by(reset_token=token).first()

    if not user:
        return jsonify({'error': 'This reset link is invalid or has already been used.'}), 400

    if user.reset_token_expiry < datetime.utcnow():
        return jsonify({'error': 'This reset link has expired. Please request a new one.'}), 400

    user.set_password(password)
    user.reset_token        = None
    user.reset_token_expiry = None
    db.session.commit()

    return jsonify({'message': 'Password updated successfully. You can now log in.'}), 200
