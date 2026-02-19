from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, Property

properties_bp = Blueprint('properties', __name__)

@properties_bp.route('', methods=['GET'])
@jwt_required()
def get_properties():
    properties = Property.query.all()
    return jsonify([p.to_dict() for p in properties])

@properties_bp.route('/<int:property_id>', methods=['GET'])
@jwt_required()
def get_property(property_id):
    prop = Property.query.get_or_404(property_id)
    return jsonify(prop.to_dict())

@properties_bp.route('', methods=['POST'])
@jwt_required()
def create_property():
    data = request.json
    prop = Property(
        address=data.get('address'),
        property_type=data.get('property_type', 'residential'),
        bedrooms=data.get('bedrooms'),
        bathrooms=data.get('bathrooms'),
        client_id=data.get('client_id'),
        overview_photo=data.get('overview_photo'),
    )
    db.session.add(prop)
    db.session.commit()
    return jsonify(prop.to_dict()), 201

@properties_bp.route('/<int:property_id>', methods=['PUT'])
@jwt_required()
def update_property(property_id):
    prop = Property.query.get_or_404(property_id)
    data = request.json
    if 'address' in data:
        prop.address = data['address']
    if 'property_type' in data:
        prop.property_type = data['property_type']
    if 'bedrooms' in data:
        prop.bedrooms = data['bedrooms']
    if 'bathrooms' in data:
        prop.bathrooms = data['bathrooms']
    if 'client_id' in data:
        prop.client_id = data['client_id']
    if 'overview_photo' in data:
        prop.overview_photo = data['overview_photo']
    db.session.commit()
    return jsonify(prop.to_dict())

@properties_bp.route('/<int:property_id>', methods=['DELETE'])
@jwt_required()
def delete_property(property_id):
    prop = Property.query.get_or_404(property_id)
    db.session.delete(prop)
    db.session.commit()
    return '', 204
