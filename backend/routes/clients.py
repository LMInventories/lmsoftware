from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Client, User

clients_bp = Blueprint('clients', __name__)

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
    )

    db.session.add(client)
    db.session.commit()
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

    db.session.commit()
    return jsonify(client.to_dict())

@clients_bp.route('/<int:client_id>', methods=['DELETE'])
@jwt_required()
def delete_client(client_id):
    client = Client.query.get_or_404(client_id)
    db.session.delete(client)
    db.session.commit()
    return '', 204
