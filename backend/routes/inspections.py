from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Inspection, Property, User, Template
from permissions import get_current_user, require_admin_or_manager, filter_inspections_for_user, is_admin_or_manager
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
    user = get_current_user()
    query = filter_inspections_for_user(Inspection.query, user)
    inspections = query.all()
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
    user = get_current_user()
    inspection = Inspection.query.get_or_404(inspection_id)
    # Clerks can only view their own inspections
    if user.role == 'clerk' and inspection.inspector_id != user.id:
        return jsonify({'error': 'Forbidden'}), 403
    # Typists can only view their own inspections in processing
    if user.role == 'typist' and (inspection.typist_id != user.id or inspection.status != 'processing'):
        return jsonify({'error': 'Forbidden'}), 403
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
# Accepts optional source_inspection_id; if provided, seeds report_data.
# Works even when the source has no report_data yet — in that case the
# source_inspection_id is stored so the report screen can load it live, and
# report_data is left null (the frontend fetches sourceReportData on demand).
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('', methods=['POST'])
@jwt_required()
def create_inspection():
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json

    # ── Template resolution ──────────────────────────────────────────────
    template_id = data.get('template_id')
    if not template_id:
        inspection_type = data.get('inspection_type', 'check_in')
        default_template = Template.query.filter_by(
            inspection_type=inspection_type,
            is_default=True
        ).first()
        template_id = default_template.id if default_template else None

        # If still no template, inherit from source inspection's template
        if not template_id and data.get('source_inspection_id'):
            source_insp = Inspection.query.get(data['source_inspection_id'])
            if source_insp and source_insp.template_id:
                template_id = source_insp.template_id

    # ── Parse conduct_date ───────────────────────────────────────────────
    conduct_date = None
    if data.get('conduct_date'):
        try:
            conduct_date = datetime.fromisoformat(data['conduct_date'])
        except (ValueError, TypeError):
            pass

    source_id = data.get('source_inspection_id')
    include_photos = bool(data.get('include_photos', False))
    seeded_report_data = None

    # ── Seed from source inspection ──────────────────────────────────────
    # Only attempt transform when the source has actual report_data saved.
    # If source exists but has no data yet, we store source_inspection_id
    # and leave report_data null — the report screen fetches the source
    # inspection live and displays it as read-only reference (sourceReportData).
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
    user = get_current_user()
    inspection = Inspection.query.get_or_404(inspection_id)
    data = request.json
    # Clerks can only update their own inspections in active or review stage
    if user.role == 'clerk':
        if inspection.inspector_id != user.id:
            return jsonify({'error': 'Forbidden'}), 403
        if inspection.status not in ('active', 'review'):
            return jsonify({'error': 'Clerks can only edit reports in active or review stage'}), 403
    # Typists can only update report_data and move to review on their own processing inspections
    if user.role == 'typist':
        if inspection.typist_id != user.id or inspection.status != 'processing':
            return jsonify({'error': 'Forbidden'}), 403
        allowed_keys = {'report_data', 'status'}
        if not set(data.keys()).issubset(allowed_keys):
            return jsonify({'error': 'Typists can only update report data and status'}), 403
        if 'status' in data and data['status'] not in ('processing', 'review'):
            return jsonify({'error': 'Typists can only move inspection to review'}), 403

    if 'status' in data:
        old_status = inspection.status
        inspection.status = data['status']
        # ── Notify typist when inspection enters Processing stage ──────────
        if data['status'] == 'processing' and old_status != 'processing':
            try:
                from routes.email_notifications import trigger_typist_assignment
                trigger_typist_assignment(inspection)
            except Exception as email_err:
                print(f'[email] typist assignment failed (non-fatal): {email_err}')

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
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    inspection = Inspection.query.get_or_404(inspection_id)
    db.session.delete(inspection)
    db.session.commit()
    return '', 204


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inspections/<id>/seed-preview
# Returns the transformed report_data that would be applied if this inspection
# were used as the source for a new Check Out or Check In.
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
# POST /api/inspections/<id>/apply-pdf-import
#
# Called by the frontend after Claude has parsed a Check In PDF.
# Receives the raw parsed JSON from Claude, maps it to the inspection's
# template structure, and stores the result as _importedSource in report_data.
#
# This is the server-side equivalent of applyPdfImport() in InspectionReportView —
# used when the PDF is uploaded at inspection creation time (before the user
# has ever opened the report screen).
#
# Request body:
#   {
#     "rooms": [ { "name": "Lounge", "items": [ { "label": "...", "description": "...", "condition": "..." } ] } ],
#     "fixedSections": { "keys": [...], "meter_readings": [...], ... }
#   }
#
# The template is fetched from the inspection's assigned template_id.
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>/apply-pdf-import', methods=['POST'])
@jwt_required()
def apply_pdf_import(inspection_id):
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403

    inspection = Inspection.query.get_or_404(inspection_id)
    parsed = request.json  # { rooms: [...], fixedSections: {...} }

    if not parsed:
        return jsonify({'error': 'No parsed data provided'}), 400

    # Load the template to map room/item names to real IDs
    template = None
    if inspection.template_id:
        template = Template.query.get(inspection.template_id)
    if not template:
        # Fall back to default template for check_out (or any type)
        template = Template.query.filter_by(is_default=True).first()
        if not template:
            template = Template.query.first()

    built = {}

    if template and template.content:
        try:
            tpl_content = json.loads(template.content)
        except Exception:
            tpl_content = {}
    else:
        tpl_content = {}

    template_rooms  = [s for s in tpl_content.get('rooms', []) if s.get('enabled', True)]
    template_fixed  = [s for s in tpl_content.get('fixedSections', []) if s.get('enabled', True)]

    # ── Map imported rooms → template room IDs (fuzzy name match) ────────
    for imported_room in (parsed.get('rooms') or []):
        imp_name_norm = imported_room['name'].lower().replace(' ', '').replace('/', '')

        match = None
        for r in template_rooms:
            r_name_norm = r['name'].lower().replace(' ', '').replace('/', '')
            if r_name_norm in imp_name_norm or imp_name_norm in r_name_norm:
                match = r
                break

        room_id = str(match['id']) if match else ('imp_rm_' + imported_room['name'].replace(' ', '_').lower())
        built[room_id] = {}

        t_items = (match.get('sections') or match.get('items') or []) if match else []

        for imp_item in (imported_room.get('items') or []):
            imp_label_norm = imp_item['label'].lower().replace(' ', '').replace(',', '').replace('&', '')

            matched_item = None
            for ti in t_items:
                ti_label_norm = (ti.get('label') or '').lower().replace(' ', '').replace(',', '').replace('&', '')
                if ti_label_norm and (ti_label_norm in imp_label_norm or imp_label_norm in ti_label_norm):
                    matched_item = ti
                    break

            item_id = str(matched_item['id']) if matched_item else (
                'imp_it_' + imp_item['label'].replace(' ', '_').lower()
            )

            # Store as Check In source data — description + condition
            # The report screen reads this via getCI(sectionId, rowId, field)
            built[room_id][item_id] = {
                'description': imp_item.get('description') or '',
                'condition':   imp_item.get('condition')   or '',
            }

    # ── Map fixed sections by type ────────────────────────────────────────
    for sec_type, rows in (parsed.get('fixedSections') or {}).items():
        if not isinstance(rows, list):
            continue
        sec = next((s for s in template_fixed if s.get('type') == sec_type), None)
        if not sec:
            continue
        built[str(sec['id'])] = {}
        t_rows = sec.get('rows') or []
        for i, row in enumerate(rows):
            t_row = t_rows[i] if i < len(t_rows) else None
            row_id = str(t_row['id']) if t_row else ('imp_fx_' + str(i))
            built[str(sec['id'])][row_id] = {k: v for k, v in row.items() if k != 'name'}

    # ── Merge into inspection's report_data ───────────────────────────────
    existing = {}
    if inspection.report_data:
        try:
            existing = json.loads(inspection.report_data)
        except Exception:
            existing = {}

    existing['_importedSource']   = built
    existing['_importedFileName'] = parsed.get('_fileName', '')
    inspection.report_data = json.dumps(existing)
    db.session.commit()

    room_count = len(parsed.get('rooms') or [])
    item_count = sum(len(r.get('items') or []) for r in (parsed.get('rooms') or []))

    return jsonify({
        'message': f'PDF imported: {room_count} rooms, {item_count} items',
        'room_count': room_count,
        'item_count': item_count,
        'importedSource': built,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# _transform_report_data
# Core logic for seeding one inspection's data into the next.
#
# check_in / inventory → check_out:
#   Copy description → description, condition → inventoryCondition.
#   Leave checkOutCondition blank (defaults to "As Inventory & Check In" in UI).
#   Clear actions.
#
# check_out → check_in:
#   Copy checkOutCondition (or inventoryCondition) → condition for the new CI.
#   Fixed sections are passed through as-is.
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

        # Skip internal-only keys that should never be seeded forward
        if section_id.startswith('_'):
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
            extras = []
            for ex in section_data['_extra']:
                new_ex = dict(ex)
                if source_type in ('check_in', 'inventory') and target_type == 'check_out':
                    new_ex['inventoryCondition'] = ex.get('condition', '')
                    new_ex['checkOutCondition'] = ''
                elif source_type == 'check_out' and target_type in ('check_in', 'inventory'):
                    new_ex['condition'] = ex.get('checkOutCondition') or ex.get('inventoryCondition') or ex.get('condition', '')
                    new_ex.pop('checkOutCondition', None)
                    new_ex.pop('inventoryCondition', None)
                # Strip actions
                new_ex = {k: v for k, v in new_ex.items() if not k.startswith('_actions_')}
                extras.append(new_ex)
            new_section['_extra'] = extras

        # Row-level data
        for row_id, row_data in section_data.items():
            if row_id.startswith('_'):
                continue
            if not isinstance(row_data, dict):
                continue

            new_row = {}

            if source_type in ('check_in', 'inventory') and target_type == 'check_out':
                new_row['description'] = row_data.get('description', '')
                new_row['inventoryCondition'] = row_data.get('condition', '')
                new_row['checkOutCondition'] = ''
                for field in ('cleanliness', 'cleanlinessNotes', 'locationSerial',
                              'reading', 'answer', 'notes', 'name'):
                    if field in row_data:
                        new_row[field] = row_data[field]
                if include_photos and 'photos' in row_data:
                    new_row['photos'] = row_data['photos']

            elif source_type == 'check_out' and target_type in ('check_in', 'inventory'):
                checkout_cond = (row_data.get('checkOutCondition')
                                 or row_data.get('inventoryCondition')
                                 or row_data.get('condition', ''))
                new_row['condition'] = checkout_cond
                new_row['description'] = row_data.get('description', '')
                for field in ('cleanliness', 'cleanlinessNotes', 'locationSerial',
                              'reading', 'answer', 'notes', 'name'):
                    if field in row_data:
                        new_row[field] = row_data[field]
                if include_photos and 'photos' in row_data:
                    new_row['photos'] = row_data['photos']

            else:
                # Same-type seeding — copy as-is, strip subs and actions
                new_row = {k: v for k, v in row_data.items()
                           if k != '_subs' and not k.startswith('_actions_')}

            new_section[row_id] = new_row

        dst[section_id] = new_section

    return dst
