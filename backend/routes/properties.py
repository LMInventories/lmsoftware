from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, Property
from permissions import get_current_user, filter_properties_for_user, is_admin_or_manager, is_client

properties_bp = Blueprint('properties', __name__)

@properties_bp.route('', methods=['GET'])
@jwt_required()
def get_properties():
    user = get_current_user()
    query = filter_properties_for_user(Property.query, user)
    properties = query.all()
    return jsonify([p.to_dict() for p in properties])

@properties_bp.route('/<int:property_id>', methods=['GET'])
@jwt_required()
def get_property(property_id):
    user = get_current_user()
    prop = Property.query.get_or_404(property_id)
    # Clients can only view properties belonging to their client
    if user.role == 'client':
        if prop.client_id != user.client_id:
            return jsonify({'error': 'Forbidden'}), 403
        return jsonify(prop.to_dict())
    # Clerks can only view properties linked to their inspections
    if not is_admin_or_manager(user):
        from models import Inspection
        assigned = Inspection.query.filter_by(
            property_id=property_id,
            inspector_id=user.id
        ).first()
        if not assigned:
            return jsonify({'error': 'Forbidden'}), 403
    return jsonify(prop.to_dict())

@properties_bp.route('', methods=['POST'])
@jwt_required()
def create_property():
    user = get_current_user()
    if not is_admin_or_manager(user) and not is_client(user):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json

    # Clients can only create properties under their own client_id
    if is_client(user):
        data['client_id'] = user.client_id
    prop = Property(
        address=data.get('address'),
        property_type=data.get('property_type', 'residential'),
        bedrooms=data.get('bedrooms'),
        bathrooms=data.get('bathrooms'),
        furnished=data.get('furnished'),
        parking=bool(data.get('parking', False)),
        garden=bool(data.get('garden', False)),
        elevator=bool(data.get('elevator', False)),
        detachment_type=data.get('detachment_type'),
        elevation=data.get('elevation'),
        meter_electricity=data.get('meter_electricity'),
        meter_gas=data.get('meter_gas'),
        meter_heat=data.get('meter_heat'),
        meter_water=data.get('meter_water'),
        client_id=data.get('client_id'),
        overview_photo=data.get('overview_photo'),
    )
    db.session.add(prop)
    db.session.commit()
    return jsonify(prop.to_dict()), 201

@properties_bp.route('/<int:property_id>', methods=['PUT'])
@jwt_required()
def update_property(property_id):
    user = get_current_user()
    prop = Property.query.get_or_404(property_id)
    if is_client(user):
        if prop.client_id != user.client_id:
            return jsonify({'error': 'Forbidden'}), 403
    elif not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json
    if 'address'           in data: prop.address           = data['address']
    if 'property_type'     in data: prop.property_type     = data['property_type']
    if 'bedrooms'          in data: prop.bedrooms          = data['bedrooms']
    if 'bathrooms'         in data: prop.bathrooms         = data['bathrooms']
    if 'furnished'         in data: prop.furnished         = data['furnished']
    if 'parking'           in data: prop.parking           = bool(data['parking'])
    if 'garden'            in data: prop.garden            = bool(data['garden'])
    if 'elevator'          in data: prop.elevator          = bool(data['elevator'])
    if 'detachment_type'   in data: prop.detachment_type   = data['detachment_type']
    if 'elevation'         in data: prop.elevation         = data['elevation']
    if 'meter_electricity' in data: prop.meter_electricity = data['meter_electricity']
    if 'meter_gas'         in data: prop.meter_gas         = data['meter_gas']
    if 'meter_heat'        in data: prop.meter_heat        = data['meter_heat']
    if 'meter_water'       in data: prop.meter_water       = data['meter_water']
    if 'client_id'         in data: prop.client_id         = data['client_id']
    if 'overview_photo'    in data: prop.overview_photo    = data['overview_photo']
    if 'notes'             in data: prop.notes             = data['notes']
    db.session.commit()
    return jsonify(prop.to_dict())

@properties_bp.route('/<int:property_id>/photo', methods=['POST'])
@jwt_required()
def upload_property_photo(property_id):
    """Accept a base64-encoded photo string and store it on the property."""
    user = get_current_user()
    prop = Property.query.get_or_404(property_id)
    if is_client(user):
        if prop.client_id != user.client_id:
            return jsonify({'error': 'Forbidden'}), 403
    elif not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json
    if not data or 'photo' not in data:
        return jsonify({'error': 'No photo provided'}), 400
    prop.overview_photo = data['photo']
    db.session.commit()
    return jsonify({'overview_photo': prop.overview_photo})

@properties_bp.route('/<int:property_id>', methods=['DELETE'])
@jwt_required()
def delete_property(property_id):
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    prop = Property.query.get_or_404(property_id)
    db.session.delete(prop)
    db.session.commit()
    return '', 204
