from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Inspection, Property, User, Template
from datetime import datetime

inspections_bp = Blueprint('inspections', __name__)

@inspections_bp.route('', methods=['GET'])
@jwt_required()
def get_inspections():
    inspections = Inspection.query.all()
    return jsonify([{
        'id': i.id,
        'property_id': i.property_id,
        'property_address': i.property.address if i.property else None,
        'client_id': i.property.client_id if i.property else None,
        'client_name': i.property.client.name if i.property and i.property.client else None,
        'inspector_id': i.inspector_id,
        'inspector_name': i.inspector.name if i.inspector else None,
        'typist_id': i.typist_id,
        'typist_name': i.typist.name if i.typist else None,
        'inspection_type': i.inspection_type,
        'status': i.status,
        'conduct_date': i.conduct_date.isoformat() if i.conduct_date else None,
        'conduct_time_preference': i.conduct_time_preference,
        'scheduled_date': i.scheduled_date.isoformat() if i.scheduled_date else None,
        'created_at': i.created_at.isoformat() if i.created_at else None
    } for i in inspections])

@inspections_bp.route('/<int:inspection_id>', methods=['GET'])
@jwt_required()
def get_inspection(inspection_id):
    inspection = Inspection.query.get_or_404(inspection_id)
    
    result = {
        'id': inspection.id,
        'property_id': inspection.property_id,
        'inspector_id': inspection.inspector_id,
        'typist_id': inspection.typist_id,
        'template_id': inspection.template_id,
        'inspection_type': inspection.inspection_type,
        'status': inspection.status,
        'conduct_date': inspection.conduct_date.isoformat() if inspection.conduct_date else None,
        'conduct_time_preference': inspection.conduct_time_preference,
        'scheduled_date': inspection.scheduled_date.isoformat() if inspection.scheduled_date else None,
        'key_location': inspection.key_location,
        'key_return': inspection.key_return,
        'internal_notes': inspection.internal_notes,
        'tenant_email': inspection.tenant_email,
        'client_email_override': inspection.client_email_override,
        'created_at': inspection.created_at.isoformat() if inspection.created_at else None,
        'property': None,
        'client': None,
        'inspector': None,
        'typist': None,
        'template_name': None
    }
    
    # Safely add property details
    if inspection.property:
        result['property'] = {
            'id': inspection.property.id,
            'address': inspection.property.address,
            'property_type': inspection.property.property_type,
            'bedrooms': inspection.property.bedrooms,
            'bathrooms': inspection.property.bathrooms,
            'furnished': inspection.property.furnished,
            'parking': inspection.property.parking,
            'garden': inspection.property.garden,
            'client_id': inspection.property.client_id,
        }
        
        # Safely add client details
        if inspection.property.client:
            result['client'] = {
                'id': inspection.property.client.id,
                'name': inspection.property.client.name,
                'email': inspection.property.client.email,
                'phone': inspection.property.client.phone,
                'company': inspection.property.client.company,
            }
    
    # Safely add inspector details
    if inspection.inspector:
        result['inspector'] = {
            'id': inspection.inspector.id,
            'name': inspection.inspector.name,
            'email': inspection.inspector.email,
            'phone': inspection.inspector.phone,
        }
    
    # Safely add typist details
    if inspection.typist:
        result['typist'] = {
            'id': inspection.typist.id,
            'name': inspection.typist.name,
            'email': inspection.typist.email,
            'phone': inspection.typist.phone,
        }
    
    # Safely add template name
    if inspection.template:
        result['template_name'] = inspection.template.name
    
    return jsonify(result)

@inspections_bp.route('', methods=['POST'])
@jwt_required()
def create_inspection():
    data = request.json
    
    # Use explicitly selected template, or fall back to default for the type
    template_id = data.get('template_id')
    if not template_id:
        default_template = Template.query.filter_by(
            inspection_type=data.get('inspection_type', 'check_in'),
            is_default=True
        ).first()
        template_id = default_template.id if default_template else None

    # Parse conduct_date if provided
    conduct_date = None
    if data.get('conduct_date'):
        try:
            conduct_date = datetime.fromisoformat(data['conduct_date'])
        except (ValueError, TypeError):
            pass

    inspection = Inspection(
        property_id=data.get('property_id'),
        inspector_id=data.get('inspector_id'),
        typist_id=data.get('typist_id'),
        template_id=template_id,
        inspection_type=data.get('inspection_type', 'check_in'),
        status='assigned' if data.get('inspector_id') else 'created',
        tenant_email=data.get('tenant_email'),
        client_email_override=data.get('client_email_override'),
        conduct_date=conduct_date,
        conduct_time_preference=data.get('conduct_time_preference')
    )
    
    db.session.add(inspection)
    db.session.commit()
    
    return jsonify({
        'id': inspection.id,
        'property_id': inspection.property_id,
        'inspector_id': inspection.inspector_id,
        'typist_id': inspection.typist_id,
        'template_id': inspection.template_id,
        'inspection_type': inspection.inspection_type,
        'status': inspection.status,
        'tenant_email': inspection.tenant_email,
        'client_email_override': inspection.client_email_override,
        'conduct_date': inspection.conduct_date.isoformat() if inspection.conduct_date else None,
        'conduct_time_preference': inspection.conduct_time_preference
    }), 201

@inspections_bp.route('/<int:inspection_id>', methods=['PUT'])
@jwt_required()
def update_inspection(inspection_id):
    inspection = Inspection.query.get_or_404(inspection_id)
    data = request.json
    
    if 'status' in data:
        inspection.status = data['status']
    
    # Auto-update status based on clerk assignment
    if 'inspector_id' in data:
        if data['inspector_id'] is None:
            # No clerk assigned - revert to created
            inspection.status = 'created'
            inspection.inspector_id = None
        else:
            # Clerk assigned - move to assigned (if currently created)
            inspection.inspector_id = data['inspector_id']
            if inspection.status == 'created':
                inspection.status = 'assigned'
    
    if 'typist_id' in data:
        inspection.typist_id = data['typist_id']
    if 'template_id' in data:
        inspection.template_id = data['template_id']
    if 'conduct_date' in data:
        try:
            inspection.conduct_date = datetime.fromisoformat(data['conduct_date']) if data['conduct_date'] else None
        except (ValueError, TypeError):
            inspection.conduct_date = None
    if 'conduct_time_preference' in data:
        inspection.conduct_time_preference = data['conduct_time_preference']
    if 'scheduled_date' in data:
        try:
            inspection.scheduled_date = datetime.fromisoformat(data['scheduled_date']) if data['scheduled_date'] else None
        except (ValueError, TypeError):
            inspection.scheduled_date = None
    if 'key_location' in data:
        inspection.key_location = data['key_location']
    if 'key_return' in data:
        inspection.key_return = data['key_return']
    if 'internal_notes' in data:
        inspection.internal_notes = data['internal_notes']
    if 'tenant_email' in data:
        inspection.tenant_email = data['tenant_email']
    if 'client_email_override' in data:
        inspection.client_email_override = data['client_email_override']
    if 'report_data' in data:
        inspection.report_data = data['report_data']
    
    db.session.commit()
    return jsonify({'message': 'Inspection updated'})

@inspections_bp.route('/<int:inspection_id>', methods=['DELETE'])
@jwt_required()
def delete_inspection(inspection_id):
    inspection = Inspection.query.get_or_404(inspection_id)
    db.session.delete(inspection)
    db.session.commit()
    return '', 204
