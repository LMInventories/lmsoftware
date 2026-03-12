import secrets
import string
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, Client, User

clients_bp = Blueprint('clients', __name__)

def _generate_password(length=12):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    return ''.join(secrets.choice(alphabet) for _ in range(length))

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
    )

    db.session.add(client)
    db.session.commit()

    # Always create a linked User account so the client can log in immediately
    plain_password = _generate_password()
    existing_user = User.query.filter_by(email=client.email).first() if client.email else None
    if client.email and not existing_user:
        portal_user = User(
            name=client.name,
            email=client.email,
            phone=client.phone or '',
            role='client',
            client_id=client.id,
            color='#6366f1',
        )
        portal_user.set_password(plain_password)
        db.session.add(portal_user)
        db.session.commit()

        # Send welcome email with credentials
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

    db.session.commit()
    return jsonify(client.to_dict())

@clients_bp.route('/<int:client_id>', methods=['DELETE'])
@jwt_required()
def delete_client(client_id):
    client = Client.query.get_or_404(client_id)
    db.session.delete(client)
    db.session.commit()
    return '', 204
