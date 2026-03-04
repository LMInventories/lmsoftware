from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, Template, Section, Item
import copy

templates_bp = Blueprint('templates', __name__)


# ── CORS preflight ────────────────────────────────────────────────────────────
@templates_bp.route('', methods=['OPTIONS'])
@templates_bp.route('/<int:template_id>', methods=['OPTIONS'])
@templates_bp.route('/<int:template_id>/sections', methods=['OPTIONS'])
@templates_bp.route('/sections/<int:section_id>', methods=['OPTIONS'])
@templates_bp.route('/sections/<int:section_id>/items', methods=['OPTIONS'])
@templates_bp.route('/sections/<int:section_id>/reorder', methods=['OPTIONS'])
@templates_bp.route('/sections/<int:section_id>/duplicate', methods=['OPTIONS'])
@templates_bp.route('/items/<int:item_id>', methods=['OPTIONS'])
@templates_bp.route('/items/<int:item_id>/reorder', methods=['OPTIONS'])
@templates_bp.route('/items/<int:item_id>/duplicate', methods=['OPTIONS'])
def handle_options(**kwargs):
    return '', 204


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

@templates_bp.route('', methods=['GET'])
@jwt_required()
def get_templates():
    templates = Template.query.order_by(Template.name).all()
    return jsonify([t.to_dict() for t in templates])


@templates_bp.route('/<int:template_id>', methods=['GET'])
@jwt_required()
def get_template(template_id):
    template = Template.query.get_or_404(template_id)
    return jsonify(template.to_dict())


@templates_bp.route('', methods=['POST'])
@jwt_required()
def create_template():
    data = request.get_json(force=True)
    if not data.get('name') or not data.get('inspection_type'):
        return jsonify({'error': 'name and inspection_type are required'}), 400

    if data.get('is_default'):
        Template.query.filter_by(
            inspection_type=data['inspection_type'], is_default=True
        ).update({'is_default': False})

    template = Template(
        name=data['name'],
        inspection_type=data['inspection_type'],
        content=data.get('content', '{}'),
        is_default=data.get('is_default', False),
    )
    db.session.add(template)
    db.session.commit()
    return jsonify(template.to_dict()), 201


@templates_bp.route('/<int:template_id>', methods=['PUT'])
@jwt_required()
def update_template(template_id):
    template = Template.query.get_or_404(template_id)
    data = request.get_json(force=True)

    if 'name' in data:
        template.name = data['name']
    if 'inspection_type' in data:
        template.inspection_type = data['inspection_type']
    if 'content' in data:
        template.content = data['content']
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
    template = Template.query.get_or_404(template_id)
    db.session.delete(template)
    db.session.commit()
    return '', 204


# ══════════════════════════════════════════════════════════════════════════════
# SECTIONS  (room sections belonging to a template)
# ══════════════════════════════════════════════════════════════════════════════

@templates_bp.route('/<int:template_id>/sections', methods=['POST'])
@jwt_required()
def add_section(template_id):
    Template.query.get_or_404(template_id)  # 404 if template missing
    data = request.get_json(force=True)

    if not data.get('name', '').strip():
        return jsonify({'error': 'name is required'}), 400

    # Place at end
    max_order = db.session.query(
        db.func.max(Section.order_index)
    ).filter_by(template_id=template_id).scalar() or -1

    section = Section(
        template_id=template_id,
        name=data['name'].strip(),
        section_type=data.get('section_type', 'room'),
        order_index=max_order + 1,
        is_required=False,
    )
    db.session.add(section)
    db.session.commit()
    return jsonify(section.to_dict()), 201


@templates_bp.route('/sections/<int:section_id>', methods=['PUT'])
@jwt_required()
def update_section(section_id):
    section = Section.query.get_or_404(section_id)
    data = request.get_json(force=True)
    if 'name' in data:
        section.name = data['name'].strip()
    db.session.commit()
    return jsonify(section.to_dict())


@templates_bp.route('/sections/<int:section_id>', methods=['DELETE'])
@jwt_required()
def delete_section(section_id):
    section = Section.query.get_or_404(section_id)
    if section.is_required:
        return jsonify({'error': 'Cannot delete required sections'}), 400
    db.session.delete(section)
    db.session.commit()
    return '', 204


@templates_bp.route('/sections/<int:section_id>/reorder', methods=['POST'])
@jwt_required()
def reorder_section(section_id):
    section = Section.query.get_or_404(section_id)
    direction = request.get_json(force=True).get('direction')

    siblings = Section.query.filter_by(
        template_id=section.template_id
    ).order_by(Section.order_index).all()

    idx = next((i for i, s in enumerate(siblings) if s.id == section_id), None)
    if idx is None:
        return jsonify({'error': 'not found'}), 404

    if direction == 'up' and idx > 0:
        siblings[idx].order_index, siblings[idx - 1].order_index = (
            siblings[idx - 1].order_index, siblings[idx].order_index
        )
    elif direction == 'down' and idx < len(siblings) - 1:
        siblings[idx].order_index, siblings[idx + 1].order_index = (
            siblings[idx + 1].order_index, siblings[idx].order_index
        )

    db.session.commit()
    return jsonify({'ok': True})


@templates_bp.route('/sections/<int:section_id>/duplicate', methods=['POST'])
@jwt_required()
def duplicate_section(section_id):
    section = Section.query.get_or_404(section_id)

    max_order = db.session.query(
        db.func.max(Section.order_index)
    ).filter_by(template_id=section.template_id).scalar() or 0

    new_section = Section(
        template_id=section.template_id,
        name=f"{section.name} (copy)",
        section_type=section.section_type,
        order_index=max_order + 1,
        is_required=False,
    )
    db.session.add(new_section)
    db.session.flush()

    for item in section.items:
        new_item = Item(
            section_id=new_section.id,
            name=item.name,
            description=item.description,
            requires_photo=item.requires_photo,
            requires_condition=item.requires_condition,
            order_index=item.order_index,
        )
        db.session.add(new_item)

    db.session.commit()
    return jsonify(new_section.to_dict()), 201


# ══════════════════════════════════════════════════════════════════════════════
# ITEMS  (items belonging to a section)
# ══════════════════════════════════════════════════════════════════════════════

@templates_bp.route('/sections/<int:section_id>/items', methods=['POST'])
@jwt_required()
def add_item(section_id):
    Section.query.get_or_404(section_id)
    data = request.get_json(force=True)

    if not data.get('name', '').strip():
        return jsonify({'error': 'name is required'}), 400

    max_order = db.session.query(
        db.func.max(Item.order_index)
    ).filter_by(section_id=section_id).scalar() or -1

    item = Item(
        section_id=section_id,
        name=data['name'].strip(),
        description=data.get('description', ''),
        requires_photo=data.get('requires_photo', True),
        requires_condition=data.get('requires_condition', True),
        order_index=max_order + 1,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@templates_bp.route('/items/<int:item_id>', methods=['PUT'])
@jwt_required()
def update_item(item_id):
    item = Item.query.get_or_404(item_id)
    data = request.get_json(force=True)

    if 'name' in data:
        item.name = data['name'].strip()
    if 'description' in data:
        item.description = data['description']
    if 'requires_photo' in data:
        item.requires_photo = data['requires_photo']
    if 'requires_condition' in data:
        item.requires_condition = data['requires_condition']

    db.session.commit()
    return jsonify(item.to_dict())


@templates_bp.route('/items/<int:item_id>', methods=['DELETE'])
@jwt_required()
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return '', 204


@templates_bp.route('/items/<int:item_id>/reorder', methods=['POST'])
@jwt_required()
def reorder_item(item_id):
    item = Item.query.get_or_404(item_id)
    direction = request.get_json(force=True).get('direction')

    siblings = Item.query.filter_by(
        section_id=item.section_id
    ).order_by(Item.order_index).all()

    idx = next((i for i, it in enumerate(siblings) if it.id == item_id), None)
    if idx is None:
        return jsonify({'error': 'not found'}), 404

    if direction == 'up' and idx > 0:
        siblings[idx].order_index, siblings[idx - 1].order_index = (
            siblings[idx - 1].order_index, siblings[idx].order_index
        )
    elif direction == 'down' and idx < len(siblings) - 1:
        siblings[idx].order_index, siblings[idx + 1].order_index = (
            siblings[idx + 1].order_index, siblings[idx].order_index
        )

    db.session.commit()
    return jsonify({'ok': True})


@templates_bp.route('/items/<int:item_id>/duplicate', methods=['POST'])
@jwt_required()
def duplicate_item(item_id):
    item = Item.query.get_or_404(item_id)

    max_order = db.session.query(
        db.func.max(Item.order_index)
    ).filter_by(section_id=item.section_id).scalar() or 0

    new_item = Item(
        section_id=item.section_id,
        name=f"{item.name} (copy)",
        description=item.description,
        requires_photo=item.requires_photo,
        requires_condition=item.requires_condition,
        order_index=max_order + 1,
    )
    db.session.add(new_item)
    db.session.commit()
    return jsonify(new_item.to_dict()), 201
