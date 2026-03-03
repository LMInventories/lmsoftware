"""
backend/routes/section_presets.py

Section Library — lets users save a section (with all its items) as a reusable
preset, then instantly add it to any template.

Endpoints:
  GET    /api/section-presets               — list all presets
  POST   /api/section-presets               — create a new preset manually
  POST   /api/section-presets/from-section/<section_id>
                                            — save an existing section as a preset
  POST   /api/section-presets/<preset_id>/add-to-template/<template_id>
                                            — add a preset into a template as a new section
  PUT    /api/section-presets/<preset_id>   — rename / edit preset
  DELETE /api/section-presets/<preset_id>   — delete preset
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, SectionPreset, Section, Item
import json

section_presets_bp = Blueprint('section_presets', __name__)


def preset_to_dict(p):
    items = json.loads(p.items_json) if p.items_json else []
    return {
        'id':          p.id,
        'name':        p.name,
        'description': p.description,
        'category':    p.category,
        'items':       items,
        'item_count':  len(items),
        'created_at':  p.created_at.isoformat() if p.created_at else None,
    }


# ── List ──────────────────────────────────────────────────────────────────────
@section_presets_bp.route('', methods=['GET'])
@jwt_required()
def list_presets():
    presets = SectionPreset.query.order_by(SectionPreset.name).all()
    return jsonify([preset_to_dict(p) for p in presets])


# ── Create manually ───────────────────────────────────────────────────────────
@section_presets_bp.route('', methods=['POST'])
@jwt_required()
def create_preset():
    data = request.get_json(force=True)
    if not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    preset = SectionPreset(
        name=data['name'].strip(),
        description=data.get('description', ''),
        category=data.get('category', 'room'),
        items_json=json.dumps(data.get('items', [])),
    )
    db.session.add(preset)
    db.session.commit()
    return jsonify(preset_to_dict(preset)), 201


# ── Save from existing section ────────────────────────────────────────────────
@section_presets_bp.route('/from-section/<int:section_id>', methods=['POST'])
@jwt_required()
def save_section_as_preset(section_id):
    section = Section.query.get_or_404(section_id)
    data = request.get_json(force=True) or {}

    # Build items snapshot
    items_snapshot = []
    for item in sorted(section.items, key=lambda i: i.order_index):
        items_snapshot.append({
            'name':               item.name,
            'description':        item.description or '',
            'requires_photo':     item.requires_photo,
            'requires_condition': item.requires_condition,
            'order_index':        item.order_index,
        })

    preset_name = data.get('name') or section.name

    preset = SectionPreset(
        name=preset_name.strip(),
        description=data.get('description', ''),
        category=section.section_type or 'room',
        items_json=json.dumps(items_snapshot),
    )
    db.session.add(preset)
    db.session.commit()
    return jsonify(preset_to_dict(preset)), 201


# ── Add preset to a template ──────────────────────────────────────────────────
@section_presets_bp.route('/<int:preset_id>/add-to-template/<int:template_id>', methods=['POST'])
@jwt_required()
def add_preset_to_template(preset_id, template_id):
    preset = SectionPreset.query.get_or_404(preset_id)
    data = request.get_json(force=True) or {}

    # Work out the next order_index for this template
    existing = Section.query.filter_by(template_id=template_id).all()
    next_order = max((s.order_index for s in existing), default=-1) + 1

    # Allow the caller to override the section name
    section_name = data.get('name') or preset.name

    section = Section(
        template_id=template_id,
        name=section_name.strip(),
        section_type=preset.category or 'room',
        order_index=next_order,
        is_required=False,
    )
    db.session.add(section)
    db.session.flush()   # need section.id for items

    items_data = json.loads(preset.items_json) if preset.items_json else []
    for idx, item_data in enumerate(items_data):
        item = Item(
            section_id=section.id,
            name=item_data.get('name', ''),
            description=item_data.get('description', ''),
            requires_photo=item_data.get('requires_photo', True),
            requires_condition=item_data.get('requires_condition', True),
            order_index=idx,
        )
        db.session.add(item)

    db.session.commit()

    # Return the newly-created section with items so the frontend can push it locally
    return jsonify({
        'id':           section.id,
        'template_id':  section.template_id,
        'name':         section.name,
        'section_type': section.section_type,
        'order_index':  section.order_index,
        'is_required':  section.is_required,
        'items': [{
            'id':                 i.id,
            'name':               i.name,
            'description':        i.description,
            'requires_photo':     i.requires_photo,
            'requires_condition': i.requires_condition,
            'order_index':        i.order_index,
        } for i in sorted(section.items, key=lambda x: x.order_index)],
    }), 201


# ── Update ────────────────────────────────────────────────────────────────────
@section_presets_bp.route('/<int:preset_id>', methods=['PUT'])
@jwt_required()
def update_preset(preset_id):
    preset = SectionPreset.query.get_or_404(preset_id)
    data = request.get_json(force=True)

    if 'name' in data:
        preset.name = data['name'].strip()
    if 'description' in data:
        preset.description = data['description']
    if 'category' in data:
        preset.category = data['category']
    if 'items' in data:
        preset.items_json = json.dumps(data['items'])

    db.session.commit()
    return jsonify(preset_to_dict(preset))


# ── Delete ────────────────────────────────────────────────────────────────────
@section_presets_bp.route('/<int:preset_id>', methods=['DELETE'])
@jwt_required()
def delete_preset(preset_id):
    preset = SectionPreset.query.get_or_404(preset_id)
    db.session.delete(preset)
    db.session.commit()
    return '', 204
