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

    # 1. Primary lookup: exact match on User.email
    user = User.query.filter(
        db.func.lower(User.email) == email
    ).first()

    # 2. Fallback: legacy comma-string User.email (e.g. 'a@x.com, b@x.com')
    if not user:
        candidates = User.query.filter(
            User.role == 'client',
            User.email.contains(',')
        ).all()
        for candidate in candidates:
            if email in [e.strip().lower() for e in candidate.email.split(',')]:
                user = candidate
                break

    # 3. Fallback: email is in Client.email list but no User row exists yet
    if not user:
        from models import Client
        for c in Client.query.filter(Client.email.contains(email)).all():
            if email in [e.strip().lower() for e in (c.email or '').split(',')]:
                user = User.query.filter_by(client_id=c.id, role='client').first()
                if user:
                    break

    if user:
        token  = secrets.token_urlsafe(32)
        expiry = datetime.utcnow() + timedelta(hours=1)

        user.reset_token        = token
        user.reset_token_expiry = expiry
        db.session.commit()

        reset_url = f"{APP_BASE_URL}/reset-password?token={token}"
        try:
            from routes.email_service import send_password_reset
            # Send to the exact address the user typed (handles legacy comma-string users)
            send_password_reset(user, reset_url, to_email=email)
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

    # Propagate the new password to all other User rows for the same client account
    # so every email address for this client shares the same password.
    if user.client_id and user.role == 'client':
        siblings = User.query.filter(
            User.client_id == user.client_id,
            User.role == 'client',
            User.id != user.id
        ).all()
        for sibling in siblings:
            sibling.password_hash      = user.password_hash
            sibling.reset_token        = None
            sibling.reset_token_expiry = None

    db.session.commit()

    return jsonify({'message': 'Password updated successfully. You can now log in.'}), 200
