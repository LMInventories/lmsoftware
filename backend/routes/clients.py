import secrets
import string
import types
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, Client, User

clients_bp = Blueprint('clients', __name__)

def _generate_password(length=12):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def _parse_emails(email_str):
    """Return a list of lowercase stripped individual email addresses."""
    if not email_str:
        return []
    return [e.strip().lower() for e in str(email_str).split(',') if e.strip()]

def _sync_client_users(client, plain_password=None):
    """
    Ensure exactly one User row exists per email in client.email (comma-separated).
    Also fixes any legacy comma-string User.email records in-place (pre-migration
    records where the whole 'a@x.com, b@x.com' string was stored in User.email).

    plain_password: shared password for newly-created users; auto-generated if None.
    Returns list of (new_user, plain_password) for newly created users only.
    """
    target_email_set = set(_parse_emails(client.email))
    if not target_email_set:
        return []

    # Fix any legacy comma-string User.email records for this client in-place.
    legacy_users = User.query.filter(
        User.client_id == client.id,
        User.role == 'client',
        User.email.contains(',')
    ).all()
    for lu in legacy_users:
        parts = _parse_emails(lu.email)
        if not parts:
            continue
        lu.email = parts[0]
        for em in parts[1:]:
            conflict = User.query.filter(db.func.lower(User.email) == em).first()
            if not conflict:
                extra = User(
                    name=lu.name, email=em, phone=lu.phone or '',
                    role='client', client_id=lu.client_id,
                    color=lu.color or '#6366f1',
                    password_hash=lu.password_hash,
                )
                db.session.add(extra)
    db.session.flush()

    # Re-fetch after fixing legacy records
    existing_users = User.query.filter_by(client_id=client.id, role='client').all()
    existing_email_set = {u.email.lower() for u in existing_users}

    created = []
    pw = plain_password or _generate_password()

    for em in target_email_set:
        if em not in existing_email_set:
            conflict = User.query.filter(
                db.func.lower(User.email) == em,
                User.client_id != client.id
            ).first()
            if conflict:
                print(f'[clients] {em} already used by user {conflict.id} (client {conflict.client_id}), skipping')
                continue
            new_user = User(
                name=client.name, email=em, phone=client.phone or '',
                role='client', client_id=client.id, color='#6366f1',
            )
            new_user.set_password(pw)
            db.session.add(new_user)
            created.append((new_user, pw))

    # Remove users whose emails are no longer in the target list
    for u in existing_users:
        if u.email.lower() not in target_email_set:
            db.session.delete(u)

    return created


@clients_bp.route('', methods=['GET'])
@jwt_required()
def get_clients():
    clients = Client.query.all()
    return jsonify([c.to_dict() for c in clients])

@clients_bp.route('/<int:client_id>', methods=['GET'])
@jwt_required()
def get_client(client_id):
    client = Client.query.get_or_404(client_id)
    return jsonify(client.to_dict())

@clients_bp.route('', methods=['POST'])
@jwt_required()
def create_client():
    data = request.json

    client = Client(
        name=data.get('name'),
        email=data.get('email'),
        phone=data.get('phone'),
        company=data.get('company'),
        address=data.get('address'),
        logo=data.get('logo'),
        primary_color=data.get('primary_color', '#1E3A8A'),
        report_disclaimer=data.get('report_disclaimer'),
        report_color_override=data.get('report_color_override'),
        report_photo_settings=data.get('report_photo_settings'),
        report_header_text_color=data.get('report_header_text_color'),
        report_body_text_color=data.get('report_body_text_color'),
        report_orientation=data.get('report_orientation'),
        invert_logo=bool(data.get('invert_logo', False)),
        report_footer_text_color=data.get('report_footer_text_color'),
    )

    db.session.add(client)
    db.session.commit()

    # Create one User account per email address with a shared password
    plain_password = _generate_password()
    created_users = _sync_client_users(client, plain_password=plain_password)
    db.session.commit()

    if created_users:
        try:
            from routes.email_notifications import trigger_welcome_client
            trigger_welcome_client(client, plain_password)
        except Exception as email_err:
            print(f'[email] welcome client failed (non-fatal): {email_err}')

    return jsonify(client.to_dict()), 201

@clients_bp.route('/<int:client_id>', methods=['PUT'])
@jwt_required()
def update_client(client_id):
    client = Client.query.get_or_404(client_id)
    data = request.json

    if 'name' in data:
        client.name = data['name']
    if 'email' in data:
        client.email = data['email']
    if 'phone' in data:
        client.phone = data['phone']
    if 'company' in data:
        client.company = data['company']
    if 'address' in data:
        client.address = data['address']
    if 'logo' in data:
        client.logo = data['logo']
    if 'primary_color' in data:
        client.primary_color = data['primary_color']
    if 'report_disclaimer' in data:
        client.report_disclaimer = data['report_disclaimer']
    if 'report_color_override' in data:
        client.report_color_override = data['report_color_override']
    if 'report_photo_settings' in data:
        client.report_photo_settings = data['report_photo_settings']
    if 'report_header_text_color' in data:
        client.report_header_text_color = data['report_header_text_color']
    if 'report_body_text_color' in data:
        client.report_body_text_color = data['report_body_text_color']
    if 'report_orientation' in data:
        client.report_orientation = data['report_orientation']
    if 'invert_logo' in data:
        client.invert_logo = bool(data['invert_logo'])
    if 'report_footer_text_color' in data:
        client.report_footer_text_color = data['report_footer_text_color']

    db.session.commit()

    # Sync user accounts whenever email is present in the update payload
    if 'email' in data:
        new_users = _sync_client_users(client)
        db.session.commit()
        for new_user, pw in new_users:
            try:
                from routes.email_service import send_welcome_client
                # Send welcome to this specific new email only
                mock = types.SimpleNamespace(
                    name=client.name,
                    email=new_user.email,
                    company=client.company,
                )
                send_welcome_client(mock, pw)
            except Exception as email_err:
                print(f'[email] welcome for {new_user.email} failed (non-fatal): {email_err}')

    return jsonify(client.to_dict())

@clients_bp.route('/<int:client_id>/push-credentials', methods=['POST'])
@jwt_required()
def push_credentials(client_id):
    """
    Generate a new password for all User accounts linked to this client,
    then email the login details to every email address on the account.
    Admin-only action — the calling view enforces this on the frontend,
    but JWT presence is the hard gate.
    """
    client = Client.query.get_or_404(client_id)

    users = User.query.filter_by(client_id=client.id, role='client').all()
    if not users:
        return jsonify({'error': 'No portal accounts found for this client. Save the client to create one.'}), 404

    plain_password = _generate_password()
    for u in users:
        u.set_password(plain_password)
    db.session.commit()

    try:
        from routes.email_service import send_welcome_client
        send_welcome_client(client, plain_password)
    except Exception as e:
        print(f'[email] push_credentials email failed: {e}')
        return jsonify({'error': f'Password reset but email failed to send: {e}'}), 500

    return jsonify({'message': f'Credentials sent to {client.email}'}), 200


@clients_bp.route('/<int:client_id>', methods=['DELETE'])
@jwt_required()
def delete_client(client_id):
    client = Client.query.get_or_404(client_id)
    db.session.delete(client)
    db.session.commit()
    return '', 204
