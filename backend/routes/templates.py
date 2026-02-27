from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, Template
from permissions import get_current_user, is_admin_or_manager

templates_bp = Blueprint('templates', __name__)

@templates_bp.route('', methods=['OPTIONS'])
def handle_options():
    return '', 204

@templates_bp.route('/<int:template_id>', methods=['OPTIONS'])
def handle_options_with_id(template_id):
    return '', 204

@templates_bp.route('', methods=['GET'])
@jwt_required()
def get_templates():
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    templates = Template.query.all()
    return jsonify([t.to_dict() for t in templates])

@templates_bp.route('/<int:template_id>', methods=['GET'])
@jwt_required()
def get_template(template_id):
    # All authenticated users can fetch a single template (needed by inspectors)
    template = Template.query.get_or_404(template_id)
    return jsonify(template.to_dict())

@templates_bp.route('', methods=['POST'])
@jwt_required()
def create_template():
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json
    template = Template(
        name=data['name'],
        inspection_type=data['inspection_type'],
        content=data['content'],
        is_default=data.get('is_default', False)
    )
    if template.is_default:
        Template.query.filter_by(
            inspection_type=template.inspection_type,
            is_default=True
        ).update({'is_default': False})
    db.session.add(template)
    db.session.commit()
    return jsonify(template.to_dict()), 201

@templates_bp.route('/<int:template_id>', methods=['PUT'])
@jwt_required()
def update_template(template_id):
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    template = Template.query.get_or_404(template_id)
    data = request.json
    if 'name'             in data: template.name             = data['name']
    if 'inspection_type'  in data: template.inspection_type  = data['inspection_type']
    if 'content'          in data: template.content          = data['content']
    if 'is_default' in data:
        if data['is_default']:
            Template.query.filter(
                Template.inspection_type == template.inspection_type,
                Template.id != template_id,
                Template.is_default == True
            ).update({'is_default': False})
        template.is_default = data['is_default']
    db.session.commit()
    return jsonify(template.to_dict())

@templates_bp.route('/<int:template_id>', methods=['DELETE'])
@jwt_required()
def delete_template(template_id):
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    template = Template.query.get_or_404(template_id)
    db.session.delete(template)
    db.session.commit()
    return '', 204