from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Inspection, Property, User, Template
from datetime import datetime
import json

inspections_bp = Blueprint('inspections', __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build the full detail dict for a single inspection
# ─────────────────────────────────────────────────────────────────────────────
def inspection_detail(inspection):
    result = {
        'id': inspection.id,
        'property_id': inspection.property_id,
        'inspector_id': inspection.inspector_id,
        'typist_id': inspection.typist_id,
        'template_id': inspection.template_id,
        'inspection_type': inspection.inspection_type,
        'status': inspection.status,
        'source_inspection_id': inspection.source_inspection_id,
        'report_data': inspection.report_data,
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
        'template_name': None,
    }

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
            'overview_photo': inspection.property.overview_photo,
        }
        if inspection.property.client:
            result['client'] = {
                'id': inspection.property.client.id,
                'name': inspection.property.client.name,
                'email': inspection.property.client.email,
                'phone': inspection.property.client.phone,
                'company': inspection.property.client.company,
                'logo': inspection.property.client.logo,
                'primary_color': inspection.property.client.primary_color,
                'report_disclaimer': inspection.property.client.report_disclaimer,
            }

    if inspection.inspector:
        result['inspector'] = {
            'id': inspection.inspector.id,
            'name': inspection.inspector.name,
            'email': inspection.inspector.email,
            'phone': inspection.inspector.phone,
        }

    if inspection.typist:
        result['typist'] = {
            'id': inspection.typist.id,
            'name': inspection.typist.name,
            'email': inspection.typist.email,
            'phone': inspection.typist.phone,
        }

    if inspection.template:
        result['template_name'] = inspection.template.name

    return result


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inspections  — list all
# ─────────────────────────────────────────────────────────────────────────────
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
        'source_inspection_id': i.source_inspection_id,
        'conduct_date': i.conduct_date.isoformat() if i.conduct_date else None,
        'conduct_time_preference': i.conduct_time_preference,
        'scheduled_date': i.scheduled_date.isoformat() if i.scheduled_date else None,
        'created_at': i.created_at.isoformat() if i.created_at else None,
    } for i in inspections])


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inspections/<id>  — single inspection detail
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>', methods=['GET'])
@jwt_required()
def get_inspection(inspection_id):
    inspection = Inspection.query.get_or_404(inspection_id)
    return jsonify(inspection_detail(inspection))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inspections/property/<property_id>/history
# Returns all inspections for a property, newest first, with summary data
# Used by the "work from previous report" feature
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/property/<int:property_id>/history', methods=['GET'])
@jwt_required()
def get_property_history(property_id):
    inspections = (
        Inspection.query
        .filter_by(property_id=property_id)
        .order_by(Inspection.created_at.desc())
        .all()
    )
    return jsonify([{
        'id': i.id,
        'inspection_type': i.inspection_type,
        'status': i.status,
        'source_inspection_id': i.source_inspection_id,
        'conduct_date': i.conduct_date.isoformat() if i.conduct_date else None,
        'created_at': i.created_at.isoformat() if i.created_at else None,
        'has_report_data': bool(i.report_data),
        'template_id': i.template_id,
        'template_name': i.template.name if i.template else None,
    } for i in inspections])


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/inspections  — create inspection
# Accepts optional source_inspection_id; if provided, seeds report_data
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('', methods=['POST'])
@jwt_required()
def create_inspection():
    data = request.json

    # Use explicitly selected template, or fall back to default for the type
    template_id = data.get('template_id')
    if not template_id:
        inspection_type = data.get('inspection_type', 'check_in')
        default_template = Template.query.filter_by(
            inspection_type=inspection_type,
            is_default=True
        ).first()
        template_id = default_template.id if default_template else None

        # If still no template found, inherit from source inspection's template
        # (e.g. check_out inherits the check_in template — same structure, checkout columns added by frontend)
        if not template_id and data.get('source_inspection_id'):
            source_insp = Inspection.query.get(data['source_inspection_id'])
            if source_insp and source_insp.template_id:
                template_id = source_insp.template_id

    # Parse conduct_date if provided
    conduct_date = None
    if data.get('conduct_date'):
        try:
            conduct_date = datetime.fromisoformat(data['conduct_date'])
        except (ValueError, TypeError):
            pass

    source_id = data.get('source_inspection_id')
    include_photos = bool(data.get('include_photos', False))
    seeded_report_data = None

    # If seeding from a previous inspection, transform that report_data
    if source_id:
        source = Inspection.query.get(source_id)
        if source and source.report_data:
            new_type = data.get('inspection_type', 'check_in')
            transformed = _transform_report_data(
                source_type=source.inspection_type,
                target_type=new_type,
                raw=source.report_data,
                include_photos=include_photos,
            )
            seeded_report_data = json.dumps(transformed) if transformed else None

    inspection = Inspection(
        property_id=data.get('property_id'),
        inspector_id=data.get('inspector_id'),
        typist_id=data.get('typist_id'),
        template_id=template_id,
        inspection_type=data.get('inspection_type', 'check_in'),
        status='assigned' if data.get('inspector_id') else 'created',
        source_inspection_id=source_id,
        tenant_email=data.get('tenant_email'),
        client_email_override=data.get('client_email_override'),
        conduct_date=conduct_date,
        conduct_time_preference=data.get('conduct_time_preference'),
        report_data=seeded_report_data,
    )

    db.session.add(inspection)
    db.session.commit()

    return jsonify(inspection_detail(inspection)), 201


# ─────────────────────────────────────────────────────────────────────────────
# PUT /api/inspections/<id>  — update inspection
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>', methods=['PUT'])
@jwt_required()
def update_inspection(inspection_id):
    inspection = Inspection.query.get_or_404(inspection_id)
    data = request.json

    if 'status' in data:
        inspection.status = data['status']

    if 'inspector_id' in data:
        if data['inspector_id'] is None:
            inspection.status = 'created'
            inspection.inspector_id = None
        else:
            inspection.inspector_id = data['inspector_id']
            if inspection.status == 'created':
                inspection.status = 'assigned'

    if 'typist_id' in data:
        inspection.typist_id = data['typist_id']
    if 'template_id' in data:
        inspection.template_id = data['template_id']
    if 'source_inspection_id' in data:
        inspection.source_inspection_id = data['source_inspection_id']
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


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/inspections/<id>
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>', methods=['DELETE'])
@jwt_required()
def delete_inspection(inspection_id):
    inspection = Inspection.query.get_or_404(inspection_id)
    db.session.delete(inspection)
    db.session.commit()
    return '', 204


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inspections/<id>/seed-preview
# Returns the transformed report_data that would be applied if this inspection
# were used as the source for a new Check Out or Check In.
# The frontend calls this to let the user preview before confirming.
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>/seed-preview', methods=['GET'])
@jwt_required()
def seed_preview(inspection_id):
    source = Inspection.query.get_or_404(inspection_id)
    target_type = request.args.get('target_type', 'check_out')
    if not source.report_data:
        return jsonify({'seeded': {}, 'source_type': source.inspection_type})
    seeded = _transform_report_data(source.inspection_type, target_type, source.report_data)
    return jsonify({'seeded': seeded, 'source_type': source.inspection_type, 'source_template_id': source.template_id})


# ─────────────────────────────────────────────────────────────────────────────
# _transform_report_data
# Core logic for seeding one inspection's data into the next.
#
# check_in  → check_out:
#   For every room item, copy description into description,
#   copy condition into inventoryCondition.
#   Leave checkOutCondition blank (defaults to "As Inventory & Check In" in UI).
#   Clear actions.
#
# check_out → check_in:
#   For every room item, copy checkOutCondition (or inventoryCondition) into condition.
#   Copy description. This makes the new Check In start from the state the property
#   was left in at Check Out.
#   Fixed sections (meters, keys) are copied through as-is.
# ─────────────────────────────────────────────────────────────────────────────
def _transform_report_data(source_type, target_type, raw, include_photos=False):
    try:
        src = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}

    dst = {}

    for section_id, section_data in src.items():
        if not isinstance(section_data, dict):
            continue

        new_section = {}

        # Carry through meta-keys unchanged
        if '_hidden' in section_data:
            new_section['_hidden'] = section_data['_hidden']
        if '_hiddenItems' in section_data:
            new_section['_hiddenItems'] = section_data['_hiddenItems']
        if '_itemOrder' in section_data:
            new_section['_itemOrder'] = section_data['_itemOrder']
        if '_extra' in section_data:
            # Transform extra room items too
            extras = []
            for ex in section_data['_extra']:
                new_ex = dict(ex)
                if source_type in ('check_in', 'inventory') and target_type == 'check_out':
                    # Promote condition → inventoryCondition
                    new_ex['inventoryCondition'] = ex.get('condition', '')
                    new_ex['checkOutCondition'] = ''
                elif source_type == 'check_out' and target_type in ('check_in', 'inventory'):
                    # Promote checkOutCondition → condition for new CI
                    new_ex['condition'] = ex.get('checkOutCondition') or ex.get('inventoryCondition') or ex.get('condition', '')
                    new_ex.pop('checkOutCondition', None)
                    new_ex.pop('inventoryCondition', None)
                # Strip actions from extras in all transitions
                new_ex = {k: v for k, v in new_ex.items() if not k.startswith('_actions_')}
                extras.append(new_ex)
            new_section['_extra'] = extras

        # Row-level data (keyed by string row ID)
        for row_id, row_data in section_data.items():
            if row_id.startswith('_'):
                continue  # already handled above
            if not isinstance(row_data, dict):
                continue

            new_row = {}

            if source_type in ('check_in', 'inventory') and target_type == 'check_out':
                # Seed a Check Out from a Check In / Inventory
                new_row['description'] = row_data.get('description', '')
                new_row['inventoryCondition'] = row_data.get('condition', '')
                new_row['checkOutCondition'] = ''
                # Carry fixed-section fields straight through
                for field in ('cleanliness', 'cleanlinessNotes', 'locationSerial', 'reading',
                              'answer', 'notes', 'name'):
                    if field in row_data:
                        new_row[field] = row_data[field]
                # Carry photos if requested
                if include_photos and 'photos' in row_data:
                    new_row['photos'] = row_data['photos']
                # Do NOT carry _subs or actions

            elif source_type == 'check_out' and target_type in ('check_in', 'inventory'):
                # Seed a Check In from a Check Out — start from the state left at departure
                checkout_cond = row_data.get('checkOutCondition') or row_data.get('inventoryCondition') or row_data.get('condition', '')
                new_row['condition'] = checkout_cond
                new_row['description'] = row_data.get('description', '')
                # Carry fixed-section fields straight through
                for field in ('cleanliness', 'cleanlinessNotes', 'locationSerial', 'reading',
                              'answer', 'notes', 'name'):
                    if field in row_data:
                        new_row[field] = row_data[field]
                # Carry photos if requested
                if include_photos and 'photos' in row_data:
                    new_row['photos'] = row_data['photos']
                # Do NOT carry _subs or actions

            else:
                # Same type → same type (inventory → inventory etc.) — copy as-is
                new_row = {k: v for k, v in row_data.items()
                           if k != '_subs' and not k.startswith('_actions_')}

            new_section[row_id] = new_row

        dst[section_id] = new_section

    return dst
