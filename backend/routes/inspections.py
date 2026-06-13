from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Inspection, Property, Client, User, Template, Section, Item
from permissions import get_current_user, require_admin_or_manager, filter_inspections_for_user, is_admin_or_manager, is_client
from sqlalchemy.orm import joinedload, selectinload, defer
from datetime import datetime
import json
import os
import re
import time
import random
import string
import uuid as _uuid_mod

# ── Inspections list cache ────────────────────────────────────────────────────
# Keyed per user so role-based filtering is preserved.
# Busted on any inspection write.
_INSP_CACHE: dict = {}
_INSP_CACHE_TTL = 300  # 5 minutes


def _insp_cache_get(key: str):
    entry = _INSP_CACHE.get(key)
    if entry and time.monotonic() - entry['ts'] < _INSP_CACHE_TTL:
        return entry['data']
    return None


def _insp_cache_set(key: str, data):
    _INSP_CACHE[key] = {'data': data, 'ts': time.monotonic()}
    if len(_INSP_CACHE) > 500:
        oldest = sorted(_INSP_CACHE, key=lambda k: _INSP_CACHE[k]['ts'])
        for k in oldest[:100]:
            _INSP_CACHE.pop(k, None)


def invalidate_inspections_cache(user_id=None):
    if user_id is not None:
        _INSP_CACHE.pop(f'insp:{user_id}', None)
    else:
        _INSP_CACHE.clear()


# Bust dashboard + properties + inspections caches after any inspection write
def _bust_dashboard():
    try:
        from routes.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception:
        pass
    try:
        from routes.properties import invalidate_properties_cache
        invalidate_properties_cache()
    except Exception:
        pass
    invalidate_inspections_cache()


# ── Redistribution job store (file-based, same pattern as pdf_import.py) ─────
# Background AI-redistribution jobs are tracked via JSON files in /tmp so the
# status endpoint can check them without shared in-process state.
_REDISTRIB_JOBS_DIR = '/tmp/redistribution_jobs'
try:
    os.makedirs(_REDISTRIB_JOBS_DIR, exist_ok=True)
except Exception:
    pass


def _rj_path(job_id):
    return os.path.join(_REDISTRIB_JOBS_DIR, job_id + '.json')


def _rj_write(job_id, data):
    with open(_rj_path(job_id), 'w') as _f:
        json.dump(data, _f)


def _rj_read(job_id):
    try:
        with open(_rj_path(job_id)) as _f:
            return json.load(_f)
    except FileNotFoundError:
        return None


def _rj_delete(job_id):
    try:
        os.remove(_rj_path(job_id))
    except FileNotFoundError:
        pass


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
        'reference_number': inspection.reference_number,
        'tenant_name': inspection.tenant_name,
        'tenant_email': inspection.tenant_email,
        'landlord_email': inspection.landlord_email,
        'client_email_override': inspection.client_email_override,
        'deposit_amount': float(inspection.deposit_amount) if inspection.deposit_amount is not None else None,
        'deposit_scheme': inspection.deposit_scheme,
        'deposit_ref': inspection.deposit_ref,
        'depositary_tenancy_id': inspection.depositary_tenancy_id,
        'depositary_pushed_at': inspection.depositary_pushed_at.isoformat() if inspection.depositary_pushed_at else None,
        'confirmed': inspection.confirmed,
        'confirmed_at': inspection.confirmed_at.isoformat() if inspection.confirmed_at else None,
        'client_booked': inspection.client_booked,
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
                'report_color_override':    inspection.property.client.report_color_override,
                'report_header_text_color': inspection.property.client.report_header_text_color,
                'report_body_text_color':   inspection.property.client.report_body_text_color,
                'report_orientation':       inspection.property.client.report_orientation,
                'report_photo_settings':    inspection.property.client.report_photo_settings,
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
            'id':          inspection.typist.id,
            'name':        inspection.typist.name,
            'email':       inspection.typist.email,
            'phone':       inspection.typist.phone,
            'is_ai':       inspection.typist.is_ai,
            'typist_mode': inspection.typist.typist_mode,  # clerk-level default
        }
    result['typist_is_ai'] = inspection.typist.is_ai if inspection.typist else False
    # Per-inspection typist_mode takes precedence; falls back to clerk-level profile value.
    result['typist_mode'] = (
        inspection.typist_mode
        or (inspection.typist.typist_mode if inspection.typist else None)
    )

    if inspection.template:
        result['template_name'] = inspection.template.name
        # Embed full template so mobile app can work offline after download.
        # The app caches this inside the inspection's `data` blob in SQLite —
        # no extra network call is needed when the clerk opens a room section.
        result['template'] = inspection.template.to_dict()

    return result


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inspections  — list all
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('', methods=['GET'])
@jwt_required()
def get_inspections():
    user = get_current_user()
    cache_key = f'insp:{user.id}'
    cached = _insp_cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)
    # Eager-load all relationships accessed in the list serialiser in a single
    # query (4 JOINs) instead of issuing 4 lazy-load queries per inspection.
    # Without this, 50 inspections → 200+ round trips → intermittent timeouts.
    #
    # defer() prevents SQLAlchemy from including large TEXT columns in the
    # SELECT. report_data alone can be several MB per row — loading it for
    # every inspection in the list would transfer GBs from the DB for no
    # reason. Client.logo / logo_inverted are base64 blobs that appear in
    # every JOIN row and are similarly never needed by the list serialiser.
    eager = Inspection.query.options(
        defer(Inspection.report_data),
        joinedload(Inspection.property).options(
            defer(Property.overview_photo),
            joinedload(Property.client).options(
                defer(Client.logo),
                defer(Client.logo_inverted),
                defer(Client.report_disclaimer),
                defer(Client.email_notifications),
            ),
        ),
        joinedload(Inspection.inspector),
        joinedload(Inspection.typist),
    )
    query = filter_inspections_for_user(eager, user)
    inspections = query.all()
    data = [{
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
        'reference_number': i.reference_number,
        'source_inspection_id': i.source_inspection_id,
        'conduct_date': i.conduct_date.isoformat() if i.conduct_date else None,
        'conduct_time_preference': i.conduct_time_preference,
        'scheduled_date': i.scheduled_date.isoformat() if i.scheduled_date else None,
        'created_at': i.created_at.isoformat() if i.created_at else None,
    } for i in inspections]
    _insp_cache_set(cache_key, data)
    return jsonify(data)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inspections/<id>  — single inspection detail
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>', methods=['GET'])
@jwt_required()
def get_inspection(inspection_id):
    user = get_current_user()
    # Eager-load every relationship accessed by inspection_detail() in a single
    # query (6 JOINs) to avoid the N+1 cascade through template.sections.items.
    inspection = (
        Inspection.query
        .options(
            joinedload(Inspection.property).joinedload(Property.client),
            joinedload(Inspection.inspector),
            joinedload(Inspection.typist),
            # selectinload for template chain: joinedload would multiply report_data
            # (a large column) by the number of template items in the JOIN result,
            # potentially sending gigabytes to SQLAlchemy for a full inspection.
            # selectinload fires 3 small follow-up queries instead.
            selectinload(Inspection.template)
                .selectinload(Template.sections)
                .selectinload(Section.items),
        )
        .filter_by(id=inspection_id)
        .first_or_404()
    )
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
        .options(joinedload(Inspection.template))
        .filter_by(property_id=property_id)
        .order_by(Inspection.created_at.desc())
        .all()
    )
    return jsonify([{
        'id': i.id,
        'inspection_type': i.inspection_type,
        'status': i.status,
        'reference_number': i.reference_number,
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
    if not is_admin_or_manager(user) and not is_client(user):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json

    # Clients can only create inspections for their own portfolio and cannot
    # set clerk, typist, or template — those are admin-only assignments.
    if is_client(user):
        prop = db.session.get(Property, data.get('property_id'))
        if not prop or prop.client_id != user.client_id:
            return jsonify({'error': 'Forbidden'}), 403
        data = {k: v for k, v in data.items()
                if k not in ('inspector_id', 'typist_id', 'template_id', 'typist_mode', 'status')}

    # ── Template resolution ──────────────────────────────────────────────
    inspection_type = data.get('inspection_type', 'check_in')

    # Standalone types (midterm, damage_report) are not part of the
    # check_in → check_out lifecycle and must never inherit a source
    # inspection's template — that would silently assign the wrong template type.
    STANDALONE_TYPES = {'midterm', 'damage_report', 'heads_up'}
    is_standalone = inspection_type in STANDALONE_TYPES

    template_id = data.get('template_id')
    if not template_id:
        default_template = Template.query.filter_by(
            inspection_type=inspection_type,
            is_default=True
        ).first()
        template_id = default_template.id if default_template else None

        # Inherit from source inspection's template ONLY for lifecycle types
        if not template_id and not is_standalone and data.get('source_inspection_id'):
            source_insp = db.session.get(Inspection, data['source_inspection_id'])
            if source_insp and source_insp.template_id:
                template_id = source_insp.template_id

    # ── Parse conduct_date ───────────────────────────────────────────────
    conduct_date = None
    if data.get('conduct_date'):
        try:
            conduct_date = datetime.fromisoformat(data['conduct_date'])
        except (ValueError, TypeError):
            pass

    # Standalone inspections have no source lifecycle link
    source_id = None if is_standalone else data.get('source_inspection_id')
    include_photos = bool(data.get('include_photos', False))
    seeded_report_data = None

    # ── Seed from source inspection (lifecycle types only) ───────────────
    # Only attempt transform when the source has actual report_data saved.
    if source_id:
        source = db.session.get(Inspection, source_id)
        if source and source.report_data:
            transformed = _transform_report_data(
                source_type=source.inspection_type,
                target_type=inspection_type,
                raw=source.report_data,
                include_photos=include_photos,
            )
            seeded_report_data = json.dumps(transformed) if transformed else None

    # Allow admin/manager to set status directly (e.g. backdated PDF imports)
    _allowed_statuses = {'created', 'assigned', 'active', 'processing', 'review', 'complete'}
    _req_status = data.get('status')
    if _req_status in _allowed_statuses:
        initial_status = _req_status
    else:
        initial_status = 'assigned' if data.get('inspector_id') else 'created'

    inspection = Inspection(
        property_id=data.get('property_id'),
        inspector_id=data.get('inspector_id'),
        typist_id=data.get('typist_id'),
        typist_mode=data.get('typist_mode'),  # per-inspection mode; None → falls back to clerk default
        template_id=template_id,
        inspection_type=inspection_type,
        status=initial_status,
        source_inspection_id=source_id,
        tenant_email=data.get('tenant_email'),
        reference_number=data.get('reference_number') or None,
        client_email_override=data.get('client_email_override'),
        conduct_date=conduct_date,
        conduct_time_preference=data.get('conduct_time_preference'),
        report_data=seeded_report_data,
        client_booked=is_client(user),
    )

    db.session.add(inspection)
    db.session.commit()
    _bust_dashboard()

    # ── Auto-assign reference number if none was provided ─────────────────
    # The ID is only known after the first commit, so we persist it now so
    # it appears in the Inspection Detail view (and everywhere else).
    if not inspection.reference_number:
        inspection.reference_number = f'INS-{inspection.id}'
        db.session.commit()

    # ── Master sheet append (fire-and-forget) ────────────────────────────
    # Skip for PDF imports: they are backdated reference inspections, not
    # billable jobs completed by the company, so they must not appear in the
    # scheduling/invoicing spreadsheet.
    if data.get('pdf_import'):
        print(f'[sheets] skipped — pdf_import flag set on inspection {inspection.id}')
    else:
        try:
            from services.google_sheets import append_inspection_row
            ok, err = append_inspection_row(inspection)
            if not ok:
                print(f'[sheets] non-fatal: {err}')
        except Exception as _sheet_exc:
            print(f'[sheets] non-fatal exception: {_sheet_exc}')

    # ── Google Calendar event (fire-and-forget) ──────────────────────────
    # Also skip for PDF imports — there is no scheduled visit to record.
    if not data.get('pdf_import'):
        try:
            from services.google_calendar import push_calendar_event, is_calendar_connected
            if is_calendar_connected() and inspection.conduct_date:
                ok, result = push_calendar_event(inspection)
                if not ok:
                    print(f'[calendar] non-fatal: {result}')
        except Exception as _cal_exc:
            print(f'[calendar] non-fatal exception: {_cal_exc}')

    # ── Notify admin when a client submits a booking ────────────────────
    if is_client(user) and not data.get('pdf_import'):
        try:
            from routes.email_service import send_client_booking_to_admin
            prop = inspection.property
            client_obj = prop.client if prop else None
            if client_obj:
                ok, err = send_client_booking_to_admin(inspection, client_obj, prop)
                if not ok:
                    print(f'[email] client booking admin notify failed (non-fatal): {err}')
        except Exception as _email_exc:
            print(f'[email] client booking admin notify exception (non-fatal): {_email_exc}')

    # ── Auto-create linked Heads-Up Report ───────────────────────────────
    if data.get('create_heads_up') and inspection_type != 'heads_up':
        try:
            hu_status = 'assigned' if data.get('inspector_id') else 'created'
            hu = Inspection(
                property_id    = inspection.property_id,
                inspector_id   = inspection.inspector_id,
                inspection_type = 'heads_up',
                status         = hu_status,
                conduct_date   = inspection.conduct_date,
                conduct_time_preference = inspection.conduct_time_preference,
                reference_number = inspection.reference_number,
            )
            db.session.add(hu)
            db.session.commit()
            _bust_dashboard()
        except Exception as _hu_exc:
            print(f'[heads_up] auto-create failed (non-fatal): {_hu_exc}')

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
    # Clients cannot modify inspections via the API
    if user.role == 'client':
        return jsonify({'error': 'Forbidden'}), 403

    # Clerks can update their own inspections when assigned, active, or in review.
    # 'assigned' must be included so the mobile app can activate the inspection
    # (Assigned → Active) and so offline-started inspections can sync directly
    # to the finalised state (Assigned → Review / Processing) in one call.
    if user.role == 'clerk':
        if inspection.inspector_id != user.id:
            return jsonify({'error': 'Forbidden'}), 403
        if inspection.status not in ('assigned', 'active', 'review'):
            return jsonify({'error': 'Clerks can only edit reports in assigned, active or review stage'}), 403
    # Typists can only update report_data and move to review on their own processing inspections
    if user.role == 'typist':
        if inspection.typist_id != user.id or inspection.status != 'processing':
            return jsonify({'error': 'Forbidden'}), 403
        allowed_keys = {'report_data', 'status'}
        if not set(data.keys()).issubset(allowed_keys):
            return jsonify({'error': 'Typists can only update report data and status'}), 403
        if 'status' in data and data['status'] not in ('processing', 'review'):
            return jsonify({'error': 'Typists can only move inspection to review'}), 403

    # ── Conflict detection ────────────────────────────────────────────────────
    # The mobile app sends `client_updated_at` = the server's updated_at timestamp
    # from when it last downloaded or successfully synced this inspection.
    # If the DB has a newer updated_at, another device has pushed changes since
    # then — reject with 409 so the client can re-download before overwriting.
    client_updated_at_str = data.get('client_updated_at')
    if client_updated_at_str and inspection.updated_at:
        try:
            client_updated_at = datetime.fromisoformat(client_updated_at_str.replace('Z', '+00:00'))
            # Normalise both sides to naive UTC for comparison (DB stores naive UTC)
            server_updated_at = inspection.updated_at
            if server_updated_at.tzinfo is None:
                # Legacy naive datetime — treat as UTC
                from datetime import timezone as _tz
                server_updated_at = server_updated_at.replace(tzinfo=_tz.utc)
            if client_updated_at.tzinfo is None:
                from datetime import timezone as _tz
                client_updated_at = client_updated_at.replace(tzinfo=_tz.utc)
            if server_updated_at > client_updated_at:
                return jsonify({
                    'error': (
                        'This inspection was updated on another device or the web '
                        'since you last synced it. Please re-download it to get the '
                        'latest version before syncing your changes.'
                    )
                }), 409
        except (ValueError, TypeError) as _cua_err:
            # Malformed timestamp — skip conflict check rather than blocking sync
            print(f'[conflict] could not parse client_updated_at: {_cua_err}')

    going_complete = (
        'status' in data and
        data['status'] == 'complete' and
        inspection.status != 'complete'
    )

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
    if 'reference_number' in data:
        inspection.reference_number = data['reference_number'] or None
    if 'key_location' in data:
        inspection.key_location = data['key_location']
    if 'key_return' in data:
        inspection.key_return = data['key_return']
    if 'internal_notes' in data:
        inspection.internal_notes = data['internal_notes']
    if 'tenant_name' in data:
        inspection.tenant_name = data['tenant_name']
    if 'tenant_email' in data:
        inspection.tenant_email = data['tenant_email']
    if 'landlord_email' in data:
        inspection.landlord_email = data['landlord_email'] or None
    if 'deposit_amount' in data:
        inspection.deposit_amount = data['deposit_amount'] or None
    if 'deposit_scheme' in data:
        inspection.deposit_scheme = data['deposit_scheme'] or None
    if 'deposit_ref' in data:
        inspection.deposit_ref = data['deposit_ref'] or None
    if 'client_email_override' in data:
        inspection.client_email_override = data['client_email_override']
    if 'typist_mode' in data:
        inspection.typist_mode = data['typist_mode'] or None  # empty string → null
    if 'confirmed' in data:
        newly_confirmed = bool(data['confirmed']) and not inspection.confirmed
        inspection.confirmed = bool(data['confirmed'])
        if inspection.confirmed:
            from datetime import timezone as _tz
            inspection.confirmed_at = datetime.now(_tz.utc)
        else:
            inspection.confirmed_at = None
        if newly_confirmed and inspection.client_booked:
            try:
                from routes.email_service import send_booking_confirmation_to_client
                prop = inspection.property
                client_obj = prop.client if prop else None
                if client_obj:
                    ok, err = send_booking_confirmation_to_client(inspection, client_obj, prop)
                    if not ok:
                        print(f'[email] booking confirmation failed (non-fatal): {err}')
            except Exception as _conf_exc:
                print(f'[email] booking confirmation exception (non-fatal): {_conf_exc}')
    if 'report_data' in data:
        inspection.report_data = data['report_data']
        # ── Extract overview photo from report_data and save to property ──────
        # The mobile app stores the property overview photo inside report_data
        # at _overview.items.photo.uri — either a base64 data URI (legacy) or
        # an S3 HTTPS URL (new flow).  Lift it out and persist on the Property
        # so the web app can display it regardless of which format was used.
        try:
            rd = json.loads(data['report_data']) if isinstance(data['report_data'], str) else data['report_data']
            overview_uri = (rd.get('_overview') or {}).get('items', {}).get('photo', {}).get('uri', '')
            if overview_uri and (overview_uri.startswith('data:') or overview_uri.startswith('https://')) and inspection.property:
                inspection.property.overview_photo = overview_uri
        except Exception as _ov_err:
            print(f'[sync] overview photo extraction failed (non-fatal): {_ov_err}')

        # ── Lift in-person signatures out of report_data and persist to DB ──────
        # The mobile app stores captured signatures at report_data._signatures as:
        # { clerk: { signer_name, signature_data, signed_at },
        #   tenant: { ... }, landlord_agent: { ... } }
        try:
            from models import InspectionSignature
            from datetime import datetime as _dt
            rd_sigs = json.loads(data['report_data']) if isinstance(data['report_data'], str) else data['report_data']
            _sigs_blob = rd_sigs.get('_signatures') or {}
            # Use a savepoint so a failure here only rolls back the signature
            # writes — it must NOT roll back the status change or other field
            # updates already pending in the session.
            with db.session.begin_nested():
                for _role, _sd in _sigs_blob.items():
                    if _role not in ('clerk', 'tenant', 'landlord_agent'):
                        continue
                    if not (_sd or {}).get('signature_data'):
                        continue
                    # Replace any existing in-person record for this role
                    existing_sig = InspectionSignature.query.filter_by(
                        inspection_id=inspection_id, role=_role, method='in_person'
                    ).first()
                    if existing_sig:
                        db.session.delete(existing_sig)
                    _signed_at = None
                    try:
                        _signed_at = _dt.fromisoformat(_sd['signed_at'])
                    except Exception:
                        _signed_at = _dt.utcnow()
                    db.session.add(InspectionSignature(
                        inspection_id  = inspection_id,
                        role           = _role,
                        signer_name    = _sd.get('signer_name', ''),
                        signature_data = _sd['signature_data'],
                        signed_at      = _signed_at,
                        method         = 'in_person',
                    ))
        except Exception as _sig_err:
            print(f'[sync] signature extraction failed (non-fatal): {_sig_err}')

    # ── Commit all field changes first ───────────────────────────────────────
    # Status is saved before PDF generation so a slow/failing PDF never blocks
    # or rolls back the status update.
    db.session.commit()
    _bust_dashboard()

    # ── Sync Google Sheets + Calendar when scheduling fields change ─────────
    _SYNC_FIELDS = {'conduct_date', 'inspector_id', 'inspection_type',
                    'tenant_name', 'conduct_time_preference', 'reference_number'}
    if any(k in data for k in _SYNC_FIELDS):
        try:
            from services.google_sheets import sync_inspection_row
            ok, err = sync_inspection_row(inspection)
            if not ok:
                print(f'[sheets] non-fatal: {err}')
        except Exception as _sheet_exc:
            print(f'[sheets] non-fatal exception: {_sheet_exc}')

        try:
            from services.google_calendar import push_calendar_event, is_calendar_connected
            if is_calendar_connected() and inspection.conduct_date:
                ok, result = push_calendar_event(inspection)
                if not ok:
                    print(f'[calendar] non-fatal: {result}')
        except Exception as _cal_exc:
            print(f'[calendar] non-fatal exception: {_cal_exc}')

    # ── Generate PDF and email in a background thread ────────────────────────
    # Runs after commit and completely outside the HTTP request so the client
    # gets an immediate 200 and the worker is never killed by a slow PDF build.
    if going_complete:
        from flask import current_app
        import threading

        # Snapshot values needed in the thread before the request context closes
        _app        = current_app._get_current_object()
        _insp_id    = inspection_id
        _prop_addr  = inspection.property.address if inspection.property else 'unknown'
        _cli_email  = inspection.client_email_override
        _ten_email  = inspection.tenant_email

        def _generate_and_send():
            with _app.app_context():
                try:
                    from models import db as _db, Inspection as _Inspection
                    insp   = _db.session.get(_Inspection, _insp_id)
                    if not insp:
                        print(f'[pdf] inspection {_insp_id} not found in background thread')
                        return

                    prop   = insp.property
                    client = prop.client if prop else None

                    print(f'[pdf] ── background thread: inspection {_insp_id} ──')
                    print(f'[pdf]   address        : {_prop_addr}')
                    print(f'[pdf]   client         : {client.name if client else "NONE"}')
                    print(f'[pdf]   client email   : {client.email if client else "NONE"}')
                    print(f'[pdf]   email override : {insp.client_email_override!r}')
                    print(f'[pdf]   tenant email   : {insp.tenant_email!r}')

                    from routes.pdf_generator import generate_inspection_pdf, _get_report_recipients
                    recipients = _get_report_recipients(insp)
                    print(f'[pdf]   recipients     : {recipients}')

                    # Generate PDF (always — Drive upload + Depositary also need it)
                    pdf_bytes = generate_inspection_pdf(_insp_id)
                    print(f'[pdf] PDF generated OK — {len(pdf_bytes)} bytes')

                    # ── Auto email — only on first completion ─────────
                    # If completion_email_sent is already True the inspection was
                    # previously completed, emailed, then re-opened for edits.
                    # Skip the auto send so the client only ever receives one
                    # automatic email; any subsequent sends are via Share PDF.
                    if insp.completion_email_sent:
                        print(f'[pdf] auto email suppressed — already sent for inspection {_insp_id}')
                    else:
                        if not recipients:
                            print(f'[pdf] WARNING: no recipients resolved — set client email, email override, or tenant email on the inspection.')
                        else:
                            # Send — use client object if available; fall back to a stub so the
                            # email body still renders when client relationship can't be loaded.
                            from routes.email_service import send_report_complete
                            effective_client = client
                            if not effective_client:
                                class _StubClient:
                                    name    = 'Client'
                                    email   = ''
                                    company = ''
                                    logo    = None
                                    primary_color            = '#1E3A8A'
                                    report_color_override    = None
                                    report_header_text_color = '#FFFFFF'
                                    report_body_text_color   = '#1e293b'
                                    report_orientation       = 'portrait'
                                    report_disclaimer        = ''
                                effective_client = _StubClient()
                                print(f'[pdf] WARNING: no client object — using stub for email body')

                            # ── Large-PDF handling ──────────────────────────
                            # Resend's limit is 40 MB total (content + attachments).
                            # A 30 MB PDF encodes to ~40 MB in base64, so we upload
                            # anything over 25 MB to S3 and send a download link.
                            _PDF_ATTACH_LIMIT = 25 * 1024 * 1024  # 25 MB
                            _pdf_dl_url = None
                            if len(pdf_bytes) > _PDF_ATTACH_LIMIT:
                                print(f'[pdf] PDF is {len(pdf_bytes)//1024//1024} MB — uploading to S3 for download link')
                                try:
                                    from utils.s3 import is_configured as s3_ok, upload_bytes, presign_get, new_key
                                    if s3_ok():
                                        import datetime as _dt
                                        _key = f"reports/inspection-{_insp_id}-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d%H%M%S')}.pdf"
                                        upload_bytes(pdf_bytes, _key, content_type='application/pdf')
                                        _pdf_dl_url = presign_get(_key, expires=604800)  # 7 days (AWS S3 maximum)
                                        print(f'[pdf] S3 upload OK — presigned URL generated (7-day expiry)')
                                    else:
                                        print(f'[pdf] WARNING: PDF too large for email and S3 is not configured — will attempt attachment anyway')
                                except Exception as _s3_err:
                                    print(f'[pdf] S3 upload failed (non-fatal): {_s3_err} — will attempt attachment anyway')

                            ok, err = send_report_complete(
                                insp, effective_client, prop,
                                pdf_bytes  = None if _pdf_dl_url else pdf_bytes,
                                recipients = recipients,
                                pdf_download_url = _pdf_dl_url,
                            )
                            if ok:
                                print(f'[pdf] email sent OK → {recipients}')
                                # Mark so re-completions don't trigger another auto email
                                insp.completion_email_sent = True
                                db.session.commit()
                            else:
                                print(f'[pdf] email FAILED: {err}')
                                if 'credentials not configured' in str(err):
                                    print(f'[pdf] ACTION REQUIRED: set SMTP_USER and SMTP_PASSWORD in Railway environment variables')

                    # ── Push to The Depositary (check_out inspections only) ────
                    if insp.inspection_type == 'check_out':
                        try:
                            from services.depositary import push_checkout, is_configured
                            if is_configured():
                                print(f'[depositary] pushing checkout for inspection {_insp_id}...')
                                dep_ok, dep_result = push_checkout(insp, pdf_bytes)
                                if dep_ok:
                                    print(f'[depositary] push OK — tenancy_id={dep_result}')
                                else:
                                    print(f'[depositary] push FAILED: {dep_result}')
                            else:
                                print(f'[depositary] not configured — skipping push (set depositary_api_url + depositary_api_key in Settings → Integrations to enable)')
                        except Exception as dep_err:
                            print(f'[depositary] push error (non-fatal): {dep_err}')

                    # ── Upload PDF to Google Drive (all inspection types) ─────
                    try:
                        from services.google_drive import upload_report, is_drive_connected
                        if is_drive_connected():
                            print(f'[google_drive] uploading PDF for inspection {_insp_id}...')
                            drive_ok, drive_result = upload_report(insp, pdf_bytes)
                            if drive_ok:
                                print(f'[google_drive] upload OK — {drive_result}')
                            else:
                                print(f'[google_drive] upload FAILED: {drive_result}')
                        else:
                            print(f'[google_drive] not connected — skipping upload')
                    except Exception as drive_err:
                        print(f'[google_drive] upload error (non-fatal): {drive_err}')

                except Exception:
                    import traceback
                    print(f'[pdf] EXCEPTION in background PDF thread:')
                    print(traceback.format_exc())

        # daemon=False — thread must finish before worker exits, so the SMTP send completes.
        # The 30-second timeout in _send() prevents it from hanging forever.
        threading.Thread(target=_generate_and_send, daemon=False).start()

    return jsonify({
        'message':    'Inspection updated',
        'updated_at': inspection.updated_at.isoformat() if inspection.updated_at else None,
    })


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

    # ── Delete Google Calendar event if one was created ──────────────────────
    if inspection.calendar_event_id:
        try:
            from services.google_calendar import delete_calendar_event
            delete_calendar_event(inspection.calendar_event_id)
        except Exception as _cal_exc:
            print(f'[calendar] delete error (non-fatal): {_cal_exc}')

    db.session.delete(inspection)
    db.session.commit()
    _bust_dashboard()
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
# GET /api/inspections/<id>/preview-pdf
#
# Generates the server-side PDF (same as the auto-send on Complete) and returns
# it as an inline attachment for admin/manager review — without marking the
# inspection complete or sending any email.  Useful for QA before release.
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>/preview-pdf', methods=['GET'])
@jwt_required()
def preview_pdf(inspection_id):
    from flask import make_response
    from routes.pdf_generator import generate_inspection_pdf

    user       = get_current_user()
    inspection = Inspection.query.get_or_404(inspection_id)

    # Apply the same access rules as the GET single-inspection endpoint.
    # Clerks may only export their own inspections.
    # Typists may only export inspections assigned to them.
    # Clients may only export complete inspections linked to their client account.
    if user.role == 'clerk' and inspection.inspector_id != user.id:
        return jsonify({'error': 'Forbidden'}), 403
    if user.role == 'typist' and inspection.typist_id != user.id:
        return jsonify({'error': 'Forbidden'}), 403
    if user.role == 'client':
        if inspection.status != 'complete':
            return jsonify({'error': 'The PDF is only available once the inspection is complete'}), 403
        client_id = getattr(user, 'client_id', None)
        prop_client_id = inspection.property.client_id if inspection.property else None
        if not client_id or prop_client_id != client_id:
            return jsonify({'error': 'Forbidden'}), 403

    if not inspection.report_data:
        return jsonify({'error': 'No report data — inspection has not been filled in yet'}), 400

    try:
        pdf_bytes = generate_inspection_pdf(inspection_id)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': f'PDF generation failed: {e}'}), 500

    # Build a descriptive filename
    addr  = (inspection.property.address if inspection.property else 'inspection').replace(',', '').replace(' ', '_')[:40]
    itype = inspection.inspection_type or 'report'
    fname = f'{itype}_{addr}_{inspection_id}.pdf'

    resp = make_response(pdf_bytes)
    resp.headers['Content-Type']        = 'application/pdf'
    resp.headers['Content-Disposition'] = f'inline; filename="{fname}"'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/inspections/<id>/share-pdf
#
# Generates the inspection PDF and emails it to one or more addresses provided
# by the user.  Uses the same send_report_complete template as the auto-send.
#
# Request body:
#   { "emails": ["alice@example.com", "bob@example.com"] }
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>/share-pdf', methods=['POST'])
@jwt_required()
def share_pdf(inspection_id):
    from routes.pdf_generator import generate_inspection_pdf
    from permissions import is_admin_or_manager
    import threading

    user = get_current_user()
    inspection = Inspection.query.get_or_404(inspection_id)

    # Admins and managers can share any inspection's PDF.
    # Clients can share PDFs for complete inspections linked to their own client account.
    if user.role == 'client':
        if inspection.status != 'complete':
            return jsonify({'error': 'The PDF is only available once the inspection is complete'}), 403
        client_id = getattr(user, 'client_id', None)
        prop_client_id = inspection.property.client_id if inspection.property else None
        if not client_id or prop_client_id != client_id:
            return jsonify({'error': 'Forbidden'}), 403
    elif not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403

    data   = request.get_json(force=True) or {}
    emails = data.get('emails', [])
    if isinstance(emails, str):
        emails = [e.strip() for e in emails.split(',') if e.strip()]
    emails = [e.strip() for e in emails if e.strip()]
    notes  = (data.get('notes') or '').strip()
    if not emails:
        return jsonify({'error': 'No email addresses provided'}), 400
    if not inspection.report_data:
        return jsonify({'error': 'No report data — inspection has not been filled in yet'}), 400

    # PDF generation + send both happen in a background thread so the HTTP
    # response returns instantly. Previously, generating the PDF synchronously
    # could exceed the frontend's 30 s axios timeout, producing a "Failed"
    # toast even though the email subsequently sent correctly.
    from flask import current_app
    _app     = current_app._get_current_object()
    _insp_id = inspection_id
    _emails  = list(emails)
    _notes   = notes

    def _send_shared():
        with _app.app_context():
            try:
                from routes.pdf_generator import generate_inspection_pdf as _gen_pdf
                from models import db as _db2, Inspection as _Insp
                from routes.email_service import send_report_complete
                insp   = _db2.session.get(_Insp, _insp_id)
                client = insp.property.client if insp.property else None
                prop   = insp.property

                class _StubClient:
                    name                     = 'Client'
                    email                    = ''
                    company                  = ''
                    logo                     = None
                    primary_color            = '#1E3A8A'
                    report_color_override    = None
                    report_header_text_color = '#FFFFFF'
                    report_body_text_color   = '#1e293b'
                    report_orientation       = 'portrait'
                    report_disclaimer        = ''

                effective_client = client or _StubClient()

                print(f'[share-pdf] generating PDF for inspection {_insp_id}')
                _pdf_bytes = _gen_pdf(_insp_id)
                print(f'[share-pdf] PDF generated ({len(_pdf_bytes)//1024} KB) — sending to {_emails}')

                # ── Large-PDF handling (same threshold as auto-send) ──────
                _PDF_ATTACH_LIMIT = 25 * 1024 * 1024  # 25 MB
                _pdf_dl_url = None
                if len(_pdf_bytes) > _PDF_ATTACH_LIMIT:
                    print(f'[share-pdf] PDF is {len(_pdf_bytes)//1024//1024} MB — uploading to S3')
                    try:
                        from utils.s3 import is_configured as s3_ok, upload_bytes, presign_get
                        if s3_ok():
                            import datetime as _dt
                            _key = f"reports/inspection-{_insp_id}-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d%H%M%S')}.pdf"
                            upload_bytes(_pdf_bytes, _key, content_type='application/pdf')
                            _pdf_dl_url = presign_get(_key, expires=604800)  # 7 days
                            print(f'[share-pdf] S3 upload OK — presigned URL generated')
                        else:
                            print(f'[share-pdf] WARNING: PDF too large and S3 not configured — attempting attachment anyway')
                    except Exception as _s3_err:
                        print(f'[share-pdf] S3 upload failed (non-fatal): {_s3_err} — attempting attachment anyway')

                ok, err = send_report_complete(
                    insp, effective_client, prop,
                    pdf_bytes        = None if _pdf_dl_url else _pdf_bytes,
                    recipients       = _emails,
                    pdf_download_url = _pdf_dl_url,
                    notes            = _notes,
                )
                if ok:
                    print(f'[share-pdf] sent OK → {_emails}')
                else:
                    print(f'[share-pdf] FAILED: {err}')
            except Exception:
                import traceback
                print('[share-pdf] EXCEPTION:')
                print(traceback.format_exc())

    threading.Thread(target=_send_shared, daemon=False).start()

    # Return immediately — PDF generation + send happen in the background.
    return jsonify({'queued': True, 'message': f'Report being sent to {", ".join(_emails)}'})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers for apply_pdf_import
# ─────────────────────────────────────────────────────────────────────────────

def _attach_room_photos_to_report_data(report_data, room_photo_map, room_to_sec_id,
                                        room_photo_refs=None):
    """
    For each room that had photos extracted during PDF import, attach those
    photo URLs to the appropriate item row in the corresponding report_data section.

    If a photo has a reference number (from its PDF caption) and an item's
    description/condition contains that reference, the photo goes to that item.
    Otherwise it falls back to the first item in the section.

    room_photo_map  : {room_name: [url, ...]}
    room_to_sec_id  : {room_name: section_id (int or str)}
    room_photo_refs : {room_name: [ref_str|None, ...]}  — parallel to room_photo_map
    """
    if room_photo_refs is None:
        room_photo_refs = {}

    for room_name, sec_id in room_to_sec_id.items():
        photos = room_photo_map.get(room_name)
        if not photos:
            continue
        refs     = room_photo_refs.get(room_name) or [None] * len(photos)
        sec_key  = str(sec_id)
        sec_data = report_data.get(sec_key)
        if not sec_data or not isinstance(sec_data, dict):
            continue

        item_keys = [k for k in sec_data if not k.startswith('_')
                     and isinstance(sec_data.get(k), dict)]
        first_key = item_keys[0] if item_keys else None

        # Build ref → item_key mapping.
        # For "X.Y" refs (L&M PDFs): Y is the 1-based item index — look up directly.
        # For plain number refs: scan item text for a matching reference.
        ref_to_key: dict = {}
        for ref in refs:
            if not ref or ref in ref_to_key:
                continue
            if '.' in str(ref):
                # "X.Y" format — Y is 1-based item position in this section
                try:
                    item_idx = int(str(ref).split('.')[1]) - 1  # 0-based
                    if 0 <= item_idx < len(item_keys):
                        ref_to_key[ref] = item_keys[item_idx]
                except (ValueError, IndexError):
                    pass
            else:
                # Plain number ref — scan item descriptions/conditions
                for ik in item_keys:
                    item_data = sec_data[ik]
                    combined = (
                        (item_data.get('description') or '') + ' ' +
                        (item_data.get('condition')   or '')
                    ).lower()
                    if _ref_in_text(ref, combined):
                        ref_to_key[ref] = ik
                        break

        for url, ref in zip(photos, refs):
            target = ref_to_key.get(ref) if ref else None
            if target and isinstance(sec_data.get(target), dict):
                sec_data[target].setdefault('_photos', []).append(url)
            else:
                # No match → Room Overview Photos (_overview strip)
                if not isinstance(sec_data.get('_overview'), dict):
                    sec_data['_overview'] = {}
                sec_data['_overview'].setdefault('_photos', []).append(url)


def _pdf_norm(s):
    """Normalise a string for fuzzy section/item name matching."""
    return re.sub(r'[\s/,&\-()\[\]]', '', (s or '').lower())


_ITEM_REF_CACHE: dict = {}

def _ref_in_text(ref_num, text):
    """
    Return True if text contains a photo reference matching ref_num.
    Matches patterns like: 'Photo 1', 'Ref 1', 'Fig 1', '(1)', '[1]',
    'see 1', 'photo no. 1', 'P1', etc.
    """
    n = str(ref_num)
    if n not in _ITEM_REF_CACHE:
        _ITEM_REF_CACHE[n] = re.compile(
            rf'(?i)\bphoto[\s._#:\-]*{re.escape(n)}\b'
            rf'|\bphot[\s._#:\-]*{re.escape(n)}\b'
            rf'|\bref(?:erence)?[\s._#:\-]*{re.escape(n)}\b'
            rf'|\bfig(?:ure)?[\s._#:\-]*{re.escape(n)}\b'
            rf'|\bpic(?:ture)?[\s._#:\-]*{re.escape(n)}\b'
            rf'|\bimg[\s._#:\-]*{re.escape(n)}\b'
            rf'|\bsee\s+{re.escape(n)}\b'
            rf'|\({re.escape(n)}\)'
            rf'|\[{re.escape(n)}\]'
        )
    return bool(_ITEM_REF_CACHE[n].search(text))

def _fuzzy_match_section(name, sections):
    n = _pdf_norm(name)
    for sec in sections:
        if _pdf_norm(sec.name) == n:
            return sec
    for sec in sections:
        sn = _pdf_norm(sec.name)
        if sn and (sn in n or n in sn):
            return sec
    return None

def _fuzzy_match_item(label, items):
    n = _pdf_norm(label)
    for item in items:
        if _pdf_norm(item.name) == n:
            return item
    for item in items:
        ln = _pdf_norm(item.name)
        if ln and (ln in n or n in ln):
            return item
    return None


# ── Global fixed-section helpers (mirrors frontend logic exactly) ─────────────

def _fs_slug(name):
    """Mirror of frontend: name.toLowerCase().replace(/[^a-z0-9]/g, '_')"""
    return re.sub(r'[^a-z0-9]', '_', (name or '').lower())

def _infer_fs_type(cols):
    """Mirror of frontend _inferType — maps a section's columns list to its type string."""
    c = cols or []
    if 'reading'                                            in c: return 'meter_readings'
    if 'cleanliness'                                        in c: return 'cleaning_summary'
    if 'name' in c and 'answer' in c and 'question' in c       : return 'fire_door_safety'
    if 'answer' in c and 'question' in c                        : return 'smoke_alarms'
    if 'answer' in c and 'description' in c                     : return 'health_safety'
    if 'answer' in c and 'name' in c                            : return 'smoke_alarms'
    if 'condition'                                          in c: return 'condition_summary'
    if 'description'                                        in c: return 'keys'
    return 'condition_summary'

# Same defaults as fixed_sections.py DEFAULT_FIXED_SECTIONS
_DEFAULT_GLOBAL_FIXED = [
    {'name': 'Condition Summary',      'enabled': True, 'columns': ['name', 'condition', 'additional_notes'],  'items': []},
    {'name': 'Cleaning Summary',       'enabled': True, 'columns': ['name', 'cleanliness', 'additional_notes'], 'items': []},
    {'name': 'Smoke & Carbon Alarms',  'enabled': True, 'columns': ['name', 'answer', 'condition'],             'items': []},
    {'name': 'Fire Door Safety',       'enabled': True, 'columns': ['name', 'answer', 'condition'],             'items': []},
    {'name': 'Health & Safety',        'enabled': True, 'columns': ['name', 'answer', 'description'],           'items': []},
    {'name': 'Keys',                   'enabled': True, 'columns': ['name', 'description'],                     'items': [
        {'name': 'Full Sets',           'description': ''},
        {'name': 'Access at Check In',  'description': ''},
        {'name': 'Access at Check Out', 'description': ''},
    ]},
    {'name': 'Utility Meter Readings', 'enabled': True, 'columns': ['name', 'location_serial', 'reading'],      'items': [
        {'name': 'Gas Meter',      'location_serial': '', 'reading': ''},
        {'name': 'Electric Meter', 'location_serial': '', 'reading': ''},
        {'name': 'Water Meter',    'location_serial': '', 'reading': ''},
        {'name': 'Heat Meter',     'location_serial': '', 'reading': ''},
    ]},
]

def _get_global_fixed_sections():
    """Load the system-wide fixed sections config (mirrors GET /api/fixed-sections)."""
    from models import SystemSetting
    s = SystemSetting.query.filter_by(key='fixed_sections').first()
    if s and s.value:
        try:
            return json.loads(s.value)
        except Exception:
            pass
    return _DEFAULT_GLOBAL_FIXED


_DEFAULT_MIDTERM_FIXED = [
    {'name': 'Overview',                                    'enabled': True, 'columns': ['name', 'answer', 'additional_notes'], 'items': []},
    {'name': 'Keys',                                        'enabled': True, 'columns': ['name', 'description'],                'items': []},
    {'name': 'Smoke & Carbon Monoxide Detector Summary',    'enabled': True, 'columns': ['name', 'answer', 'additional_notes'], 'items': []},
    {'name': 'Utility Meter Readings',                      'enabled': True, 'columns': ['name', 'location_serial', 'reading'], 'items': []},
]


def _get_midterm_fixed_sections():
    """Load the midterm-specific fixed sections config (mirrors GET /api/midterm-sections)."""
    from models import SystemSetting
    s = SystemSetting.query.filter_by(key='midterm_sections').first()
    if s and s.value:
        try:
            return json.loads(s.value)
        except Exception:
            pass
    return _DEFAULT_MIDTERM_FIXED

# Which fields to write into report_data for each fixed section type
# (mirrors the field names used by the frontend's get/set helpers)
_FS_FIELD_MAP = {
    'meter_readings':    ['reading', 'locationSerial'],
    'cleaning_summary':  ['cleanliness', 'cleanlinessNotes'],
    'condition_summary': ['condition'],
    'keys':              ['description'],
    'smoke_alarms':      ['answer', 'notes'],
    'health_safety':     ['answer', 'notes'],
    'fire_door_safety':  ['answer', 'notes'],
}


def _meter_classifier(name):
    """Normalize a meter name to a canonical utility type for fuzzy matching.
    Handles variations like 'Electricity Meter' → same bucket as 'Electric Meter'."""
    n = (name or '').lower()
    if 'electric' in n or 'electricity' in n:
        return 'electric'
    if 'gas' in n:
        return 'gas'
    if 'water' in n:
        return 'water'
    if 'heat' in n:
        return 'heat'
    return n.strip()


def _key_classifier(name):
    """Normalize a key/access row name to a canonical type for fuzzy matching."""
    n = re.sub(r'[\s\-]', '', (name or '').lower())
    if 'checkin' in n:
        return 'checkin'
    if 'checkout' in n:
        return 'checkout'
    if 'fullset' in n:
        return 'fullsets'
    return n.strip()


def _build_template_from_pdf(pdf_rooms, inspection):
    """
    Create a new Template with relational Section+Item records for each room.
    Fixed sections are global (not per-template) so we don't need to store
    them in template.content.
    """
    prop = getattr(inspection, 'property', None)
    tpl_name = 'PDF Import'
    if prop and getattr(prop, 'address', None):
        tpl_name = 'PDF Import \u2013 ' + prop.address

    template = Template(
        name=tpl_name,
        inspection_type='check_in',
        content='{}',
        is_default=False,
        is_transient=True,   # hidden from Templates UI; functional for this inspection only
    )
    db.session.add(template)
    db.session.flush()  # get template.id

    for i, room in enumerate(pdf_rooms or []):
        section = Section(
            template_id=template.id,
            name=room['name'],
            section_type='room',
            order_index=i,
        )
        db.session.add(section)
        db.session.flush()  # get section.id
        for j, item in enumerate(room.get('items') or []):
            db.session.add(Item(
                section_id=section.id,
                name=item.get('label', 'Item'),
                description='',
                requires_photo=False,
                requires_condition=True,
                order_index=j,
            ))

    db.session.flush()
    # Expire the sections relationship so it's re-fetched from DB on next access.
    # SQLAlchemy won't auto-populate the collection when sections are added via
    # db.session.add rather than template.sections.append().
    db.session.expire(template, ['sections'])
    return template


# ── AI redistribution ────────────────────────────────────────────────────────
#
# Second AI pass: takes the composite template structure and all extracted PDF
# content, then redistributes every piece of information to the correct
# template section/item — including splitting compound PDF items (e.g.
# "Walls" description that mentions skirting → Walls + Woodwork items).
#
# Returns a report_data dict keyed by composite section/item IDs.
# ─────────────────────────────────────────────────────────────────────────────

_REDISTRIBUTION_PROMPT = """You are a UK property inventory expert. Your task is to redistribute extracted PDF content into a specific template for a Check In report.

COMPOSITE TEMPLATE STRUCTURE (your target — use these exact IDs):
__TEMPLATE_JSON__

EXTRACTED PDF CONTENT (raw, as the AI read the PDF):
__PDF_CONTENT_JSON__

═══════════════════════════════════════
YOUR TASK
═══════════════════════════════════════
Read ALL extracted PDF content and assign every piece of information to the most appropriate template section and item. A single PDF entry may need to be SPLIT across multiple template items. Never leave content unassigned if a suitable template item exists.

═══════════════════════════════════════
STEP 1 — MANDATORY KEYWORD SCAN (DO THIS FIRST, BEFORE ANY OTHER PROCESSING)
═══════════════════════════════════════
Before you do ANYTHING else, scan every word of every PDF item's description and condition text for these trigger keywords. When a trigger keyword appears — even embedded inside a longer sentence, even if the PDF heading says something different — you MUST extract that text into the target template item. This overrides the PDF heading label.

Trigger keyword(s)                                     → MUST go to template item
──────────────────────────────────────────────────────────────────────────────────
"skirting", "skirting board", "skirting boards"       → Woodwork
"architrave", "architraves"                            → Woodwork
"picture rail", "dado rail", "coving"                 → Woodwork
"door stop beading", "beading", "exposed timber"      → Woodwork
"banister", "handrail"                                → Woodwork
"curtain", "curtain pole", "curtain track"            → Curtains & Blinds
"blind", "blinds", "roller blind", "venetian"         → Curtains & Blinds
"radiator", "rad ", "TRV", "thermostatic valve"       → Heating
"smoke alarm", "heat alarm", "carbon monoxide",
  "CO alarm", "CO detector"                           → Smoke/Carbon Alarms
"socket", "sockets", "switch", "switches"             → Switches / Sockets
"extractor fan", "extractor"                          → Extractor (if item exists)
"intercom", "door entry"                              → Intercom (if item exists)

HOW TO APPLY: Read the description sentence-by-sentence. If a sentence contains a trigger keyword, move ONLY that sentence (or the relevant clause) to the target item — do NOT move the entire description.

Example:
  PDF "Walls" description: "White painted walls to all elevations. White painted skirting boards and architraves."
  → Walls item: description = "White painted walls to all elevations"
  → Woodwork item: description = "White painted skirting boards and architraves"

═══════════════════════════════════════
STEP 2 — LABEL NORMALISATION
═══════════════════════════════════════
PDF labels vary; map them to these exact template item names:

PDF label variants                                  → Template item name
──────────────────────────────────────────────────────────────────────────
"Door & Frame", "Door/Frame", "Door/Frame/Threshold" → "Door and Frame"
"Door Fittings", "Door/Fittings"                    → "Door Fittings"
"Windows & Frames", "Windows/Frames", "Window(s)/Sill",
  "Window & Sill", "Windows/Sill"                   → "Windows & Frames"
"Curtains & Blinds", "Curtains/Blinds"              → "Curtains & Blinds"
"Switches & Sockets", "Switches/Sockets"            → "Switches / Sockets"
"Smoke/Carbon Alarms", "Smoke & Carbon Alarms",
  "Smoke Alarms"                                    → "Smoke/Carbon Alarms"
"Built-in Storage", "Built In Storage"              → "Built-In Storage"
"Shower & Screens", "Shower & Screen",
  "Shower/Screen"                                   → "Shower & Screen"
"Bath & Taps", "Bath/Taps"                         → "Bath & Taps"
"Sink & Taps", "Sink/Taps"                         → "Sink & Taps"
"Wash Basin", "Basin"                              → "Wash Basin"
"Wall Units", "Wall Mounted Units"                 → "Wall Units"
"Base Units", "Base Mounted Units"                 → "Base Units"
"Worktop", "Work Surface"                          → "Worktop"
"Boundaries", "Garden Boundaries"                  → "Boundaries"
"Contents", "Furnishings", "Furniture",
  "Fixtures and Fittings", "F&F"                   → "Contents"

If the PDF label does not appear above, use semantic similarity to the nearest template item name.

═══════════════════════════════════════
STEP 3 — COMPOUND HEADING SPLITTING
═══════════════════════════════════════
These PDF heading patterns MUST be split across separate template items:

A) "Door/Frame/Threshold", "Door, Frame & Fittings", "Door/Frame/Fittings":
   • Door panel + frame material/description → "Door and Frame"
   • Handles, locks, hinges, letterbox, knocker, spy hole, latch, bolt → "Door Fittings"

B) "Walls" / "Walls/Skirting" / "Wall Surfaces" — ALWAYS check for skirting content:
   • Painted/plastered wall surface text → "Walls"
   • Any skirting board, architrave, picture rail, dado rail, coving or exposed timber → "Woodwork"
   RULE: Even if the PDF label is just "Walls", you MUST scan the description for skirting
   keywords (Step 1 above) and split the content. This is the most common missed split.

C) "Window(s)/Sill", "Windows & Sill", "Windows/Frame/Fittings":
   • Glazing, frames, sills, window material → "Windows & Frames"
   • Window handles, stays, restrictors, locks → Window Fittings (if item exists)

D) "Walls/Ceiling" or "Walls & Ceiling":
   • Wall surface → "Walls"
   • Ceiling surface → "Ceiling"

E) "Floor/Skirting", "Floor & Skirting":
   • Floor covering → "Flooring"
   • Skirting/architrave → "Woodwork"

═══════════════════════════════════════
STEP 4 — SEMANTIC ITEM RULES
═══════════════════════════════════════

CONTENTS items (template "Contents"):
  ✓ Furniture: sofas, chairs, tables, beds, wardrobes, chests of drawers, bookshelves
  ✓ Soft furnishings: rugs, throws, cushions, lamp shades, picture frames
  ✓ Mirrors, artwork, decorative items if not fixed to the wall
  ✓ Any items listed under a "Contents" or "Furnishings" heading in the PDF
  ✓ In garden rooms: bins, garden furniture, plant pots, BBQ
  Note: if a PDF room has a "Contents" item, it MUST be mapped to the template "Contents" item

WALLS items (template "Walls"):
  ✓ Painted/plastered wall surfaces, wallpaper, wall tiles (non-splashback)
  ✗ NOT skirting boards, architraves, picture rails → those go to Woodwork
  ✗ NOT ceiling → goes to Ceiling

WOODWORK items (template "Woodwork"):
  ✓ Skirting boards, architraves, picture rails, dado rails, door stop beading
  ✓ Exposed painted timber that is not a door/frame/floor
  ✓ Coving if described as part of the woodwork finish
  ✓ Banisters/handrails on stairs (if no separate item exists)

DOOR AND FRAME items (template "Door and Frame"):
  ✓ Door panel (material, colour, paint finish, glass inserts)
  ✓ Door frame / surround / architrave attached to the door
  ✗ NOT handles, locks, hinges, letter box, knocker, spy hole → Door Fittings

DOOR FITTINGS items (template "Door Fittings"):
  ✓ Handles (lever/knob), hinges, latch, mortice lock, Yale lock, bolt lock
  ✓ Letterbox, door knocker, door number, spy hole
  ✓ Door chain, door stop

WINDOWS & FRAMES items (template "Windows & Frames"):
  ✓ Window frame material and colour (uPVC, timber, aluminium)
  ✓ Window panes/glazing, sills (internal and external), trickle vents
  ✓ Window handles, integrated locks, restrictors
  ✓ Any item labelled "Window(s)/Sill" in the PDF in its entirety

CURTAINS & BLINDS items (template "Curtains & Blinds"):
  ✓ Curtains, curtain poles/tracks/rings
  ✓ Roller blinds, Venetian blinds, Roman blinds, wand, pull cord, acorns

HEATING items (template "Heating"):
  ✓ Radiators, electric panel heaters, underfloor heating manifold
  ✓ Thermostatic radiator valves (TRVs) if described with the radiator

BUILT-IN STORAGE items (template "Built-In Storage"):
  ✓ Built-in wardrobes, airing cupboards, understairs cupboards
  ✓ Fitted shelving units, meter cupboards integrated into the room

SMOKE/CARBON ALARMS items (template "Smoke/Carbon Alarms"):
  ✓ Smoke alarms, heat alarms, carbon monoxide alarms
  ✓ Combined CO/smoke detectors

APPLIANCE ITEMS (Extractor, Hob, Oven, Boiler, Washing Machine, Dishwasher, Fridge-Freezer):
  ✓ Match each appliance to its named template item exactly
  ✓ Include make, model, serial number in description; condition issues in condition

═══════════════════════════════════════
FORMATTING RULES
═══════════════════════════════════════

• Sentence case throughout: "WHITE PAINTED WALLS" → "White painted walls"
• Preserve brand-specific capitalisation: uPVC, UPVC, GCH, Ideal, Hotpoint, Beko
• Multi-element description: join with newline character (\\n)
  e.g. "White painted door\\nWhite painted frame\\n2 x glass inserts"
• Condition field: the assessment, defects, or "In good order" / "Good clean condition"
  e.g. "Light scratches consistent with use", "Tested for power", "Appears complete"
• If the PDF does not separate description from condition, split at the first condition
  signal word/phrase: Good / Fair / Poor / As new / Scratch / Mark / Chip / Crack /
  Worn / Loose / Missing / Damaged / Slight / Minor / Heavy / In good order /
  Tested for power / Appears complete
• If no defects are noted and condition is implied good, set condition to "In good order"

═══════════════════════════════════════
ROOM ASSIGNMENT
═══════════════════════════════════════

• Assign each PDF room's content to the matching template section (they are pre-matched — the sectionId in the template corresponds to the PDF room).
• If the same template section appears multiple times in the template JSON (merged rooms), combine content from all matching PDF rooms into that one section, deduplicating where possible.

═══════════════════════════════════════
OUTPUT
═══════════════════════════════════════
Return ONLY valid JSON — no markdown fences, no explanation, no trailing text:
{
  "SECTION_ID": {
    "ITEM_ID": {
      "description": "...",
      "condition": "..."
    }
  }
}

Rules:
• Use the exact numeric string IDs from the template above
• Only include sections and items that have actual content to fill
• Every item must have both "description" and "condition" keys (use empty string "" if genuinely absent)
• Do not invent content — only use what is in the extracted PDF"""


def _ai_redistribute_items(composite_template, pdf_rooms):
    """
    Call Claude to redistribute all extracted PDF content into the composite
    template's section/item structure. Returns a report_data dict ready to save,
    or None on failure (caller should fall back to fuzzy matching).
    """
    import os
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None

    # Build a clean template representation for the AI
    template_json = []
    for sec in (composite_template.sections or []):
        if sec.section_type != 'room':
            continue
        sec_entry = {'sectionId': str(sec.id), 'name': sec.name, 'items': []}
        for item in (sec.items or []):
            sec_entry['items'].append({'itemId': str(item.id), 'name': item.name})
        template_json.append(sec_entry)

    # Build a clean PDF content representation for the AI
    pdf_content = []
    for room in pdf_rooms:
        room_entry = {'room': room.get('name', ''), 'items': []}
        for item in (room.get('items') or []):
            room_entry['items'].append({
                'label':       item.get('label', ''),
                'description': item.get('description', ''),
                'condition':   item.get('condition', ''),
            })
        pdf_content.append(room_entry)

    prompt = _REDISTRIBUTION_PROMPT \
        .replace('__TEMPLATE_JSON__', json.dumps(template_json, indent=2)) \
        .replace('__PDF_CONTENT_JSON__', json.dumps(pdf_content, indent=2))

    try:
        from anthropic import Anthropic
        client  = Anthropic(api_key=api_key)
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=8192,
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = response.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        redistributed = json.loads(raw)
        print(f'[apply-pdf-import] AI redistribution returned {len(redistributed)} sections')
        return redistributed
    except Exception as e:
        print(f'[apply-pdf-import] AI redistribution failed: {e}')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers used by apply_pdf_import (both sync and async paths)
# ─────────────────────────────────────────────────────────────────────────────

def _build_report_data_fuzzy(
    pdf_rooms,
    pdf_room_to_src_sec_id,    # {room_name → src_sec_id | None}
    src_id_to_new_sec_id,      # {src_sec_id → new_sec_id}
    new_room_name_to_sec_id,   # {room_name → new_sec_id}
):
    """
    Fuzzy-match extracted PDF rooms into composite template sections without AI.
    Returns a partial report_data dict (no fixed sections or metadata yet).
    Safe to call from both the request context and a background thread.
    """
    report_data = {}
    for pdf_room in pdf_rooms:
        room_name  = pdf_room.get('name', '')
        src_sec_id = pdf_room_to_src_sec_id.get(room_name)   # int | None

        if src_sec_id is None:
            # "New room" — write items into the composite new-room section
            new_sec_id = new_room_name_to_sec_id.get(room_name)
            if not new_sec_id:
                continue
            sec_key = str(new_sec_id)
            if sec_key not in report_data:
                report_data[sec_key] = {}
            for pdf_item in (pdf_room.get('items') or []):
                item_key = ('item_' + str(int(time.time() * 1000)) + '_'
                            + ''.join(random.choices(string.ascii_lowercase, k=4)))
                report_data[sec_key][item_key] = {
                    '_label':      pdf_item.get('label', ''),
                    'description': pdf_item.get('description') or '',
                    'condition':   pdf_item.get('condition')   or '',
                }
            print(f'[apply-pdf-import] room "{room_name}" → new composite section {new_sec_id}')
            continue

        new_sec_id = src_id_to_new_sec_id.get(src_sec_id)
        if not new_sec_id:
            continue
        sec_key = str(new_sec_id)
        if sec_key not in report_data:
            report_data[sec_key] = {}

        new_items = Item.query.filter_by(section_id=new_sec_id).all()

        for pdf_item in (pdf_room.get('items') or []):
            matched_item = _fuzzy_match_item(pdf_item.get('label', ''), new_items)
            if not matched_item:
                extra_key = '_extra_' + ''.join(random.choices(string.ascii_lowercase, k=6))
                report_data[sec_key][extra_key] = {
                    '_label':      pdf_item.get('label', ''),
                    'description': pdf_item.get('description') or '',
                    'condition':   pdf_item.get('condition')   or '',
                }
                continue

            new_desc = (pdf_item.get('description') or '').strip()
            new_cond = (pdf_item.get('condition')   or '').strip()
            item_key = str(matched_item.id)

            if item_key in report_data[sec_key]:
                existing = report_data[sec_key][item_key]
                old_desc = (existing.get('description') or '').strip()
                old_cond = (existing.get('condition')   or '').strip()
                if new_desc and new_desc not in old_desc:
                    existing['description'] = (old_desc + '\n' + new_desc).strip() if old_desc else new_desc
                if new_cond and new_cond not in old_cond:
                    existing['condition'] = (old_cond + '\n' + new_cond).strip() if old_cond else new_cond
                pdf_subs = pdf_item.get('_subs')
                if isinstance(pdf_subs, list) and pdf_subs:
                    existing_subs  = existing.get('_subs') or []
                    existing_descs = {s.get('description', '') for s in existing_subs}
                    for sub in pdf_subs:
                        sub_desc = sub.get('description', '')
                        if sub_desc not in existing_descs:
                            existing_subs.append({
                                '_sid':        ('sub_' + str(int(time.time() * 1000)) + '_'
                                                + ''.join(random.choices(string.ascii_lowercase, k=4))),
                                'description': sub_desc,
                                'condition':   sub.get('condition') or '',
                            })
                            existing_descs.add(sub_desc)
                    if existing_subs:
                        existing['_subs'] = existing_subs
            else:
                item_entry = {'description': new_desc, 'condition': new_cond}
                pdf_subs = pdf_item.get('_subs')
                if isinstance(pdf_subs, list) and pdf_subs:
                    item_entry['_subs'] = [{
                        '_sid':        ('sub_' + str(int(time.time() * 1000)) + '_'
                                        + ''.join(random.choices(string.ascii_lowercase, k=4))),
                        'description': sub.get('description') or '',
                        'condition':   sub.get('condition')   or '',
                    } for sub in pdf_subs]
                report_data[sec_key][item_key] = item_entry

        print(f'[apply-pdf-import] room "{room_name}" → composite sec {new_sec_id} (fuzzy)')

    return report_data


def _apply_pdf_fixed_sections(report_data, pdf_fixed, pdf_file_name,
                               keys_photos=None, meter_photos=None):
    """
    Apply fixed sections (meter readings, keys, etc.) and import metadata to
    report_data in-place.  Also stamps _importedSource and _importedFileName.

    keys_photos   : [url, ...]  — photos extracted from the Keys page(s) of the PDF
    meter_photos  : [url, ...]  — photos extracted from the Meter Readings page(s)
    """
    global_fixed  = _get_global_fixed_sections()
    enabled_fixed = [s for s in global_fixed if s.get('enabled', True) is not False]

    type_to_global = {}
    for sec_idx, gsec in enumerate(enabled_fixed):
        typ = _infer_fs_type(gsec.get('columns') or [])
        if typ not in type_to_global:
            type_to_global[typ] = (sec_idx, gsec)

    for pdf_type, pdf_rows in pdf_fixed.items():
        if not isinstance(pdf_rows, list) or not pdf_rows:
            continue
        # Never overwrite Condition Summary or Cleaning Summary from PDF —
        # these are filled in by the clerk during the inspection itself.
        if pdf_type in ('condition_summary', 'cleaning_summary'):
            continue
        match = type_to_global.get(pdf_type)
        if not match:
            continue
        sec_idx, gsec = match
        sec_id = f'fs_{sec_idx}_{_fs_slug(gsec["name"])}'

        if pdf_type == 'meter_readings':
            # Match each PDF meter row to the closest predefined template item by
            # utility type (handles "Electricity Meter" → "Electric Meter" etc.).
            # Matched rows fill the predefined slot; unmatched overflow to _extra.
            template_items = gsec.get('items') or []
            report_data[sec_id] = {}
            used_item_indices = set()
            extra = []
            meter_row_refs = []  # ordered refs for photo attachment

            for pdf_row in pdf_rows:
                if not isinstance(pdf_row, dict):
                    pdf_row = {}
                pdf_key = _meter_classifier(pdf_row.get('name', ''))
                matched_idx = next(
                    (i for i, item in enumerate(template_items)
                     if i not in used_item_indices
                     and _meter_classifier(item.get('name', '')) == pdf_key),
                    None
                )
                if matched_idx is not None:
                    used_item_indices.add(matched_idx)
                    row_id = f'fs_{sec_idx}_{matched_idx}'
                    row_data = {
                        'reading':        pdf_row.get('reading', ''),
                        'locationSerial': pdf_row.get('locationSerial', ''),
                    }
                    report_data[sec_id][row_id] = row_data
                    meter_row_refs.append(row_data)
                else:
                    entry = {
                        '_eid':           f'pdf_fs_{sec_idx}_{len(extra)}',
                        'name':           pdf_row.get('name', ''),
                        'locationSerial': pdf_row.get('locationSerial', ''),
                        'reading':        pdf_row.get('reading', ''),
                    }
                    extra.append(entry)
                    meter_row_refs.append(entry)

            if extra:
                report_data[sec_id]['_extra'] = extra

        elif pdf_type == 'keys':
            # Match each PDF key row to the closest predefined template item by
            # key type (handles "Keys at Check In" → "Access at Check In" etc.).
            # Matched rows fill the predefined slot; unmatched overflow to _extra.
            template_items = gsec.get('items') or []
            report_data[sec_id] = {}
            used_item_indices = set()
            extra = []

            for pdf_row in pdf_rows:
                if not isinstance(pdf_row, dict):
                    pdf_row = {}
                pdf_key = _key_classifier(pdf_row.get('name', ''))
                matched_idx = next(
                    (i for i, item in enumerate(template_items)
                     if i not in used_item_indices
                     and _key_classifier(item.get('name', '')) == pdf_key),
                    None
                )
                if matched_idx is not None:
                    used_item_indices.add(matched_idx)
                    row_id = f'fs_{sec_idx}_{matched_idx}'
                    report_data[sec_id][row_id] = {
                        'description': pdf_row.get('description', ''),
                    }
                else:
                    extra.append({
                        '_eid':        f'pdf_fs_{sec_idx}_{len(extra)}',
                        'name':        pdf_row.get('name', ''),
                        'description': pdf_row.get('description', ''),
                    })

            if extra:
                report_data[sec_id]['_extra'] = extra

        else:
            # smoke_alarms, fire_door_safety, health_safety — write to predefined row slots
            fields = _FS_FIELD_MAP.get(pdf_type, ['condition'])
            report_data[sec_id] = {}
            for i, pdf_row in enumerate(pdf_rows):
                if not isinstance(pdf_row, dict):
                    pdf_row = {fields[0]: str(pdf_row)} if fields else {}
                row_id = f'fs_{sec_idx}_{i}'
                report_data[sec_id][row_id] = {f: pdf_row.get(f, '') for f in fields}

        print(f'[apply-pdf-import] fixed {pdf_type} → {sec_id}: {len(pdf_rows)} rows')

        # Attach photos extracted from the relevant PDF page to this section.
        # Keys photos all go to the section's _overview strip.
        # Meter photos are matched by order to each meter row (predefined or extra),
        # then any remainder goes to _overview.
        if pdf_type == 'keys' and keys_photos:
            if not isinstance(report_data[sec_id].get('_overview'), dict):
                report_data[sec_id]['_overview'] = {}
            report_data[sec_id]['_overview'].setdefault('_photos', []).extend(keys_photos)
            print(f'[apply-pdf-import] attached {len(keys_photos)} keys photo(s) → {sec_id}')

        elif pdf_type == 'meter_readings' and meter_photos:
            for i, url in enumerate(meter_photos):
                if i < len(meter_row_refs):
                    meter_row_refs[i].setdefault('_photos', []).append(url)
                else:
                    if not isinstance(report_data[sec_id].get('_overview'), dict):
                        report_data[sec_id]['_overview'] = {}
                    report_data[sec_id]['_overview'].setdefault('_photos', []).append(url)
            print(f'[apply-pdf-import] attached {len(meter_photos)} meter photo(s) → {sec_id}')

    report_data['_importedSource']   = {k: v for k, v in report_data.items() if not k.startswith('_')}
    report_data['_importedFileName'] = pdf_file_name


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/inspections/<id>/apply-pdf-import
#
# Phase 1 (synchronous, fast): build composite template + copy sections/items,
#   commit, then either:
#   • keep-layout mode  → fuzzy-match + save report_data → 200 OK
#   • smart mode        → start background thread for AI call → 202 Accepted + {job_id}
#
# GET /api/inspections/<id>/apply-pdf-import-status/<job_id>
#   Poll the background job.  Returns {status: processing|done|error, ...}.
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>/apply-pdf-import', methods=['POST'])
@jwt_required()
def apply_pdf_import(inspection_id):
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403

    inspection = Inspection.query.get_or_404(inspection_id)
    parsed = request.json
    if not parsed:
        return jsonify({'error': 'No parsed data provided'}), 400

    pdf_rooms          = parsed.get('rooms') or []
    pdf_fixed          = parsed.get('fixedSections') or {}
    room_mappings      = parsed.get('roomMappings') or []
    redistribute_items = bool(parsed.get('redistributeItems', False))
    pdf_file_name      = parsed.get('_fileName', '')
    pdf_cover_photo    = parsed.get('_coverPhoto') or None
    pdf_keys_photos    = parsed.get('_keysPhotos') or []
    pdf_meter_photos   = parsed.get('_meterPhotos') or []

    # ── Keep-layout path: preserve exact PDF structure, ignore template mapping
    if not redistribute_items:
        prop     = inspection.property
        tpl_name = 'PDF Import'
        if prop and getattr(prop, 'address', None):
            tpl_name = f'PDF Import – {prop.address}'

        composite = Template(
            name=tpl_name,
            inspection_type='check_in',
            content='{}',
            is_default=False,
            is_transient=True,
        )
        db.session.add(composite)
        db.session.flush()

        report_data = {}
        for order_idx, pdf_room in enumerate(pdf_rooms):
            room_name = pdf_room.get('name', '')
            new_sec = Section(
                template_id  = composite.id,
                name         = room_name,
                section_type = 'room',
                order_index  = order_idx,
            )
            db.session.add(new_sec)
            db.session.flush()

            sec_key = str(new_sec.id)
            report_data[sec_key] = {}

            first_item_id = None
            for item_idx, pdf_item in enumerate(pdf_room.get('items') or []):
                item_label = pdf_item.get('label', '')
                new_item = Item(
                    section_id         = new_sec.id,
                    name               = item_label,
                    description        = '',
                    requires_photo     = False,
                    requires_condition = True,
                    order_index        = item_idx,
                )
                db.session.add(new_item)
                db.session.flush()
                if item_idx == 0:
                    first_item_id = new_item.id

                item_entry = {
                    'description': pdf_item.get('description') or '',
                    'condition':   pdf_item.get('condition')   or '',
                }
                pdf_subs = pdf_item.get('_subs')
                if isinstance(pdf_subs, list) and pdf_subs:
                    item_entry['_subs'] = [{
                        '_sid':        ('sub_' + str(int(time.time() * 1000)) + '_'
                                        + ''.join(random.choices(string.ascii_lowercase, k=4))),
                        'description': sub.get('description') or '',
                        'condition':   sub.get('condition')   or '',
                    } for sub in pdf_subs]
                report_data[sec_key][str(new_item.id)] = item_entry

            # Attach photos to items.
            # For "X.Y" refs (L&M PDFs): Y is the 1-based item index — direct lookup.
            # For plain-number refs: scan item text for a matching reference.
            # No match → Room Overview Photos strip.
            room_photo_urls = pdf_room.get('_photos') or []
            room_photo_refs = pdf_room.get('_photoRefs') or [None] * len(room_photo_urls)
            if room_photo_urls:
                item_keys = [k for k in report_data.get(sec_key, {})
                             if not k.startswith('_')
                             and isinstance(report_data[sec_key].get(k), dict)]
                ref_to_key: dict = {}
                for ref in set(r for r in room_photo_refs if r):
                    if '.' in str(ref):
                        try:
                            item_idx = int(str(ref).split('.')[1]) - 1  # 0-based
                            if 0 <= item_idx < len(item_keys):
                                ref_to_key[ref] = item_keys[item_idx]
                        except (ValueError, IndexError):
                            pass
                    else:
                        for ik in item_keys:
                            ie = report_data[sec_key][ik]
                            combined = (
                                (ie.get('description') or '') + ' ' +
                                (ie.get('condition')   or '')
                            ).lower()
                            if _ref_in_text(ref, combined):
                                ref_to_key[ref] = ik
                                break

                for url, ref in zip(room_photo_urls, room_photo_refs):
                    target = ref_to_key.get(ref) if ref else None
                    if (target and sec_key in report_data
                            and isinstance(report_data[sec_key].get(target), dict)):
                        report_data[sec_key][target].setdefault('_photos', []).append(url)
                    else:
                        if sec_key in report_data:
                            if not isinstance(report_data[sec_key].get('_overview'), dict):
                                report_data[sec_key]['_overview'] = {}
                            report_data[sec_key]['_overview'].setdefault('_photos', []).append(url)

        inspection.template_id = composite.id

        # Overview photos → first room's _overview strip
        overview_photos = parsed.get('_overviewPhotos') or []
        if overview_photos:
            first_sec = next((k for k in report_data if not k.startswith('_')), None)
            if first_sec:
                if not isinstance(report_data[first_sec].get('_overview'), dict):
                    report_data[first_sec]['_overview'] = {}
                report_data[first_sec]['_overview'].setdefault('_photos', []).extend(overview_photos)

        _apply_pdf_fixed_sections(report_data, pdf_fixed, pdf_file_name,
                                   keys_photos=pdf_keys_photos,
                                   meter_photos=pdf_meter_photos)
        inspection.report_data = json.dumps(report_data)
        if pdf_cover_photo and inspection.property:
            inspection.property.overview_photo = pdf_cover_photo
        db.session.commit()

        room_count = len(pdf_rooms)
        item_count = sum(len(r.get('items') or []) for r in pdf_rooms)
        print(f'[apply-pdf-import] inspection {inspection_id}: {room_count} rooms, '
              f'{item_count} items (keep-layout), template {composite.id}')
        return jsonify({
            'message':     f'PDF imported: {room_count} rooms, {item_count} items',
            'room_count':  room_count,
            'item_count':  item_count,
            'template_id': composite.id,
        }), 200

    # ── Resolve each PDF room to a source Section (from any check-in template)
    source_section_map = {}   # pdf_room_name → Section | None
    for m in room_mappings:
        rname = m.get('pdfRoomName', '')
        sid   = m.get('templateSectionId')
        if not rname:
            continue
        if sid:
            sec = Section.query.options(selectinload(Section.items)).filter_by(id=int(sid)).first()
            source_section_map[rname] = sec
        else:
            source_section_map[rname] = None   # explicit "new room"

    # ── Build a composite template from the selected sections ─────────────
    seen_src_ids = set()
    ordered_src_sections = []
    new_room_names = []
    for pdf_room in pdf_rooms:
        rname = pdf_room.get('name', '')
        src   = source_section_map.get(rname, None)
        if src is None:
            new_room_names.append(rname)
        elif src.id not in seen_src_ids:
            seen_src_ids.add(src.id)
            ordered_src_sections.append(src)

    prop     = inspection.property
    tpl_name = 'PDF Import'
    if prop and getattr(prop, 'address', None):
        tpl_name = f'PDF Import – {prop.address}'

    composite = Template(
        name=tpl_name,
        inspection_type='check_in',
        content='{}',
        is_default=False,
        is_transient=True,
    )
    db.session.add(composite)
    db.session.flush()

    src_to_new_sec = {}
    order = 0
    for src_sec in ordered_src_sections:
        new_sec = Section(
            template_id  = composite.id,
            name         = src_sec.name,
            section_type = 'room',
            order_index  = order,
        )
        db.session.add(new_sec)
        db.session.flush()
        for jdx, src_item in enumerate(src_sec.items or []):
            db.session.add(Item(
                section_id         = new_sec.id,
                name               = src_item.name,
                description        = src_item.description or '',
                requires_photo     = src_item.requires_photo,
                requires_condition = src_item.requires_condition,
                order_index        = jdx,
            ))
        src_to_new_sec[src_sec.id] = new_sec
        order += 1

    new_room_sec_map = {}
    for rname in new_room_names:
        new_sec = Section(
            template_id  = composite.id,
            name         = rname,
            section_type = 'room',
            order_index  = order,
        )
        db.session.add(new_sec)
        db.session.flush()
        new_room_sec_map[rname] = new_sec
        order += 1

    db.session.flush()
    db.session.expire(composite, ['sections'])

    inspection.template_id = composite.id

    for src_id, new_sec in src_to_new_sec.items():
        db.session.refresh(new_sec)
    for new_sec in new_room_sec_map.values():
        db.session.refresh(new_sec)
    db.session.refresh(composite)

    # ── Serialise structure as IDs (safe for cross-thread use) ────────────
    composite_id            = composite.id
    src_id_to_new_sec_id    = {sid: sec.id for sid, sec in src_to_new_sec.items()}
    new_room_name_to_sec_id = {rn: sec.id  for rn, sec in new_room_sec_map.items()}
    pdf_room_to_src_sec_id  = {
        rn: (sec.id if sec else None)
        for rn, sec in source_section_map.items()
    }

    # ── Phase 1 commit ────────────────────────────────────────────────────
    # Commit the composite template + inspection link BEFORE starting any
    # background thread so the thread sees committed data in a fresh session.
    db.session.commit()

    room_count = len(pdf_rooms)
    item_count = sum(len(r.get('items') or []) for r in pdf_rooms)

    # ── Keep-layout path (synchronous, no AI) ────────────────────────────
    if not redistribute_items:
        report_data = _build_report_data_fuzzy(
            pdf_rooms,
            pdf_room_to_src_sec_id,
            src_id_to_new_sec_id,
            new_room_name_to_sec_id,
        )
        _room_photo_map  = {r.get('name', ''): r['_photos']              for r in pdf_rooms if r.get('_photos')}
        _room_photo_refs = {r.get('name', ''): r.get('_photoRefs', [])   for r in pdf_rooms if r.get('_photos')}
        _room_to_sec_id  = {
            r.get('name', ''): (
                src_id_to_new_sec_id.get(pdf_room_to_src_sec_id.get(r.get('name', '')))
                or new_room_name_to_sec_id.get(r.get('name', ''))
            )
            for r in pdf_rooms
        }
        _attach_room_photos_to_report_data(report_data, _room_photo_map, _room_to_sec_id, _room_photo_refs)
        _overview_photos = parsed.get('_overviewPhotos') or []
        if _overview_photos:
            _first_sec = next((k for k in report_data if not k.startswith('_')), None)
            if _first_sec:
                if not isinstance(report_data[_first_sec].get('_overview'), dict):
                    report_data[_first_sec]['_overview'] = {}
                report_data[_first_sec]['_overview'].setdefault('_photos', []).extend(_overview_photos)
        _apply_pdf_fixed_sections(report_data, pdf_fixed, pdf_file_name,
                                   keys_photos=pdf_keys_photos,
                                   meter_photos=pdf_meter_photos)
        inspection.report_data = json.dumps(report_data)
        if pdf_cover_photo and inspection.property:
            inspection.property.overview_photo = pdf_cover_photo
        db.session.commit()
        print(f'[apply-pdf-import] inspection {inspection_id}: {room_count} rooms, '
              f'{item_count} items (keep-layout), template {composite_id}')
        return jsonify({
            'message':     f'PDF imported: {room_count} rooms, {item_count} items',
            'room_count':  room_count,
            'item_count':  item_count,
            'template_id': composite_id,
        }), 200

    # ── Smart-redistribution path — background thread → 202 ──────────────
    # We return immediately with a job_id; the frontend polls the status
    # endpoint until done/error.  This avoids Gunicorn worker timeouts on
    # large or complex PDFs where the Claude call can exceed 60 seconds.
    job_id              = str(_uuid_mod.uuid4())
    pdf_overview_photos = parsed.get('_overviewPhotos') or []   # capture before thread starts
    _rj_write(job_id, {'status': 'processing'})

    from flask import current_app
    _app           = current_app._get_current_object()
    _inspection_id = inspection_id   # close over int, not the ORM object

    def _redistrib_thread():
        with _app.app_context():
            try:
                from models import db as _db, Inspection as _Insp, Template as _Tpl

                _composite = _db.session.get(_Tpl, composite_id)
                _insp      = _db.session.get(_Insp, _inspection_id)
                if not _composite or not _insp:
                    _rj_write(job_id, {'status': 'error',
                                       'error': 'Inspection or template not found in background thread'})
                    return

                ai_result = _ai_redistribute_items(_composite, pdf_rooms)

                if ai_result:
                    valid_sec_ids  = {str(s.id) for s in (_composite.sections or [])}
                    valid_item_ids = {str(i.id) for s in (_composite.sections or [])
                                      for i in (s.items or [])}
                    report_data = {}
                    for sec_id, items in ai_result.items():
                        if sec_id not in valid_sec_ids:
                            continue
                        report_data[sec_id] = {}
                        for item_id, entry in items.items():
                            if item_id not in valid_item_ids:
                                continue
                            if isinstance(entry, dict):
                                report_data[sec_id][item_id] = {
                                    'description': (entry.get('description') or '').strip(),
                                    'condition':   (entry.get('condition')   or '').strip(),
                                }
                    total_items = sum(
                        len([v for v in sec.values() if isinstance(v, dict)])
                        for sec in report_data.values()
                        if isinstance(sec, dict)
                    )
                    if total_items == 0:
                        # AI returned something but validation stripped all items
                        # (e.g. composite template sections had no DB items because
                        # all rooms were mapped to "new"). Fall back to fuzzy match
                        # so PDF content isn't silently lost.
                        print(f'[apply-pdf-import] job {job_id}: AI result had no valid items — falling back to fuzzy match')
                        report_data = _build_report_data_fuzzy(
                            pdf_rooms,
                            pdf_room_to_src_sec_id,
                            src_id_to_new_sec_id,
                            new_room_name_to_sec_id,
                        )
                    else:
                        print(f'[apply-pdf-import] job {job_id}: AI redistribution — '
                              f'{len(report_data)} sections, {total_items} items populated')
                else:
                    print(f'[apply-pdf-import] job {job_id}: AI failed — falling back to fuzzy match')
                    report_data = _build_report_data_fuzzy(
                        pdf_rooms,
                        pdf_room_to_src_sec_id,
                        src_id_to_new_sec_id,
                        new_room_name_to_sec_id,
                    )

                # Attach photos to items using reference-number matching
                _room_photo_map  = {r.get('name', ''): r['_photos']            for r in pdf_rooms if r.get('_photos')}
                _room_photo_refs = {r.get('name', ''): r.get('_photoRefs', []) for r in pdf_rooms if r.get('_photos')}
                _room_to_sec_id  = {
                    r.get('name', ''): (
                        src_id_to_new_sec_id.get(pdf_room_to_src_sec_id.get(r.get('name', '')))
                        or new_room_name_to_sec_id.get(r.get('name', ''))
                    )
                    for r in pdf_rooms
                }
                _attach_room_photos_to_report_data(
                    report_data, _room_photo_map, _room_to_sec_id, _room_photo_refs,
                )

                # Overview photos — images that appeared before any room heading in the PDF
                if pdf_overview_photos:
                    _first_sec = next((k for k in report_data if not k.startswith('_')), None)
                    if _first_sec:
                        if not isinstance(report_data[_first_sec].get('_overview'), dict):
                            report_data[_first_sec]['_overview'] = {}
                        report_data[_first_sec]['_overview'].setdefault('_photos', []).extend(
                            pdf_overview_photos,
                        )

                _apply_pdf_fixed_sections(report_data, pdf_fixed, pdf_file_name,
                                           keys_photos=pdf_keys_photos,
                                           meter_photos=pdf_meter_photos)
                _insp.report_data = json.dumps(report_data)
                if pdf_cover_photo and _insp.property:
                    _insp.property.overview_photo = pdf_cover_photo
                _db.session.commit()

                print(f'[apply-pdf-import] job {job_id} done: '
                      f'{room_count} rooms, {item_count} items, template {composite_id}')
                _rj_write(job_id, {
                    'status':      'done',
                    'room_count':  room_count,
                    'item_count':  item_count,
                    'template_id': composite_id,
                })
            except Exception as _e:
                import traceback
                print(f'[apply-pdf-import] job {job_id} error: {_e}')
                traceback.print_exc()
                _rj_write(job_id, {'status': 'error', 'error': str(_e)})

    import threading
    threading.Thread(target=_redistrib_thread, daemon=True).start()
    print(f'[apply-pdf-import] inspection {inspection_id}: background job {job_id} started')
    return jsonify({'job_id': job_id}), 202


@inspections_bp.route('/<int:inspection_id>/apply-source/<int:source_id>', methods=['POST'])
@jwt_required()
def apply_source_inspection(inspection_id, source_id):
    """Copy template and report_data from a completed check-in into this inspection."""
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403

    inspection = Inspection.query.get_or_404(inspection_id)
    source     = Inspection.query.get_or_404(source_id)

    if source.property_id != inspection.property_id:
        return jsonify({'error': 'Source inspection belongs to a different property'}), 400
    if not source.template_id:
        return jsonify({'error': 'Source inspection has no template'}), 400
    if not source.report_data:
        return jsonify({'error': 'Source inspection has no report data'}), 400

    inspection.template_id         = source.template_id
    inspection.source_inspection_id = source_id

    # When the source is a check-in/inventory and the target is a damage report,
    # upgrade the target to a proper check-out rather than leaving it as a damage report.
    if (inspection.inspection_type == 'damage_report'
            and source.inspection_type in ('check_in', 'inventory')):
        inspection.inspection_type = 'check_out'

    # Transform report_data when going check-in/inventory → check-out so that
    # condition fields are split into inventoryCondition / checkOutCondition (blank),
    # exactly as if the check-out had been created the normal way.
    if (source.inspection_type in ('check_in', 'inventory')
            and inspection.inspection_type == 'check_out'):
        transformed = _transform_report_data(
            source.inspection_type, 'check_out', source.report_data
        )
        inspection.report_data = json.dumps(transformed) if transformed else source.report_data
    else:
        inspection.report_data = source.report_data

    db.session.commit()
    _bust_dashboard()

    print(f'[apply-source] inspection {inspection_id} ← source {source_id} '
          f'(template {source.template_id}, type now {inspection.inspection_type})')
    return jsonify(inspection_detail(inspection)), 200


@inspections_bp.route('/<int:inspection_id>/apply-pdf-import-status/<job_id>', methods=['GET'])
@jwt_required()
def apply_pdf_import_status(inspection_id, job_id):
    """Poll status of a background AI-redistribution job."""
    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403
    if not job_id or len(job_id) > 40:
        return jsonify({'error': 'Invalid job_id'}), 400
    job = _rj_read(job_id)
    if not job:
        return jsonify({'error': 'Job not found — it may have expired or never existed'}), 404
    if job.get('status') in ('done', 'error'):
        _rj_delete(job_id)   # clean up once the client has seen the result
    return jsonify(job)


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
_AS_INVENTORY_RE = re.compile(r'^as\s+inventory\+?[,\s]*', re.IGNORECASE)
_TRIVIAL_CI_RE   = re.compile(r'^(?:in\s+)?good\s+order[.,!\s]*$', re.IGNORECASE)


def _combine_conditions(inv_cond, co_cond, fallback=''):
    """
    Merge CI and CO conditions into a single condition string for a new Check In.

    - Strips the CO-specific "As Inventory+" prefix (meaning "same as original, plus...").
    - Drops trivial CI defaults ("In good order", "Good order") when CO has real content.
    - Combines CI + CO extras when CI has meaningful content and CO adds to it.
    - Preserves CI as-is when CO recorded no change (empty or just "As Inventory+").
    - Falls back to `fallback` only when both CI and CO are empty.
    """
    inv = (inv_cond or '').strip()
    co  = (co_cond  or '').strip()

    # Strip "As Inventory+" (and "As Inventory,") prefix — CO-specific shorthand
    co_clean = _AS_INVENTORY_RE.sub('', co).strip().strip(',').strip()

    inv_trivial = bool(_TRIVIAL_CI_RE.match(inv)) if inv else False
    include_inv = bool(inv) and not (inv_trivial and co_clean)
    include_co  = bool(co_clean)

    if include_inv and include_co:
        # Append CO extras after CI; lowercase the CO continuation
        co_part = co_clean[0].lower() + co_clean[1:] if co_clean[0].isupper() else co_clean
        result  = f'{inv}, {co_part}'
    elif include_inv:
        result = inv
    elif include_co:
        result = co_clean
    else:
        # Nothing meaningful from either — keep CI as-is (e.g. "In good order" when
        # CO recorded no change), or use the raw fallback.
        if inv:
            return inv
        return (fallback or '').strip()

    return result[0].upper() + result[1:] if result else result


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
                # Strip action fields from extras
                new_ex = {k: v for k, v in new_ex.items() if not k.startswith('_actions_')}
                if source_type in ('check_in', 'inventory') and target_type == 'check_out':
                    new_ex['inventoryCondition'] = ex.get('condition', '')
                    new_ex['checkOutCondition'] = ''
                    new_ex.pop('condition', None)
                    if not include_photos:
                        new_ex.pop('_photos', None)
                        new_ex.pop('_photoTs', None)
                elif source_type == 'check_out' and target_type in ('check_in', 'inventory'):
                    new_ex['description'] = ex.get('description', '')
                    new_ex['condition'] = _combine_conditions(
                        ex.get('inventoryCondition'), ex.get('checkOutCondition'),
                        fallback=ex.get('condition', '')
                    )
                    new_ex.pop('checkOutCondition', None)
                    new_ex.pop('inventoryCondition', None)
                    if not include_photos:
                        new_ex.pop('_photos', None)
                        new_ex.pop('_photoTs', None)
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
                # Photos — stored as _photos (underscore prefix) in modern sync
                if include_photos:
                    for photo_field in ('_photos', '_photoTs'):
                        if photo_field in row_data:
                            new_row[photo_field] = row_data[photo_field]
                # Carry sub-items — promote condition → inventoryCondition
                if '_subs' in row_data and isinstance(row_data['_subs'], list):
                    new_row['_subs'] = [
                        {
                            '_sid':               sub.get('_sid', ''),
                            'description':        sub.get('description', ''),
                            'inventoryCondition': sub.get('condition', ''),
                            'checkOutCondition':  '',
                        }
                        for sub in row_data['_subs']
                    ]

            elif source_type == 'check_out' and target_type in ('check_in', 'inventory'):
                new_row['description'] = row_data.get('description', '')
                new_row['condition'] = _combine_conditions(
                    row_data.get('inventoryCondition'), row_data.get('checkOutCondition'),
                    fallback=row_data.get('condition', '')
                )
                for field in ('cleanliness', 'cleanlinessNotes', 'locationSerial',
                              'reading', 'answer', 'notes', 'name'):
                    if field in row_data:
                        new_row[field] = row_data[field]
                # Photos
                if include_photos:
                    for photo_field in ('_photos', '_photoTs'):
                        if photo_field in row_data:
                            new_row[photo_field] = row_data[photo_field]
                # Carry sub-items — combine conditions
                if '_subs' in row_data and isinstance(row_data['_subs'], list):
                    new_row['_subs'] = [
                        {
                            '_sid':        sub.get('_sid', ''),
                            'description': sub.get('description', ''),
                            'condition':   _combine_conditions(
                                sub.get('inventoryCondition'), sub.get('checkOutCondition'),
                                fallback=sub.get('condition', '')
                            ),
                        }
                        for sub in row_data['_subs']
                    ]

            new_section[row_id] = new_row

        dst[section_id] = new_section

    return dst


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/inspections/<id>/save_as_template
# Admin/manager only. Inspection must be complete.
# Extracts all room items (condition text stored as item descriptions) so the
# same building can be re-inspected quickly with just updated photos.
# ─────────────────────────────────────────────────────────────────────────────
@inspections_bp.route('/<int:inspection_id>/save_as_template', methods=['POST', 'OPTIONS'])
@jwt_required()
def save_as_template(inspection_id):
    if request.method == 'OPTIONS':
        return '', 204

    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'error': 'Forbidden'}), 403

    inspection = Inspection.query.options(
        selectinload(Inspection.template).selectinload(Template.sections).selectinload(Section.items),
        joinedload(Inspection.property),
    ).get_or_404(inspection_id)

    if inspection.status != 'complete':
        return jsonify({'error': 'Only completed inspections can be saved as a template'}), 400

    body = request.get_json(force=True) or {}
    address = (inspection.property.address if inspection.property else '') or ''
    template_name = (body.get('name') or address or f'Inspection {inspection_id}').strip()
    inspection_type = body.get('inspection_type') or inspection.inspection_type or 'check_in'

    rd = {}
    if inspection.report_data:
        try:
            rd = json.loads(inspection.report_data) if isinstance(inspection.report_data, str) else inspection.report_data
        except Exception:
            pass

    room_names_override = rd.get('_roomNames', {})
    hidden_rooms = set(str(x) for x in (rd.get('_hiddenRooms') or []))
    rooms_to_extract = []

    # 1. Template-based rooms
    tmpl = inspection.template
    if tmpl:
        for s in sorted(tmpl.sections or [], key=lambda x: x.order_index):
            if s.section_type != 'room' or str(s.id) in hidden_rooms:
                continue
            room_name = room_names_override.get(str(s.id), s.name)
            section_rd = rd.get(str(s.id), {})
            deleted_items = set(str(d) for d in (section_rd.get('_deleted', []) or []))
            items_out = []
            for item in sorted(s.items or [], key=lambda i: i.order_index):
                if str(item.id) in deleted_items:
                    continue
                item_rd = section_rd.get(str(item.id), {})
                condition = (
                    item_rd.get('condition') or item_rd.get('inventoryCondition')
                    or item_rd.get('checkOutCondition') or ''
                ).strip()
                subs_out = []
                for sub in (item_rd.get('_subs') or []):
                    sub_cond = (
                        sub.get('condition') or sub.get('inventoryCondition')
                        or sub.get('checkOutCondition') or ''
                    ).strip()
                    subs_out.append({'name': sub.get('description') or '', 'description': sub_cond})
                items_out.append({
                    'name': item.name,
                    'description': condition,
                    'requires_photo': bool(item.requires_photo),
                    'requires_condition': bool(item.requires_condition),
                    'answer_options': item.answer_options or '',
                    'subs': subs_out,
                })
            # Extra items added by clerk in the field
            for ex in (section_rd.get('_extra') or []):
                eid = str(ex.get('_eid', ''))
                ex_data = section_rd.get(eid, {}) if eid else {}
                merged = {**ex_data, **ex}
                ex_cond = (
                    merged.get('condition') or merged.get('inventoryCondition')
                    or merged.get('checkOutCondition') or ''
                ).strip()
                items_out.append({
                    'name': merged.get('name') or merged.get('description') or 'Item',
                    'description': ex_cond,
                    'requires_photo': True,
                    'requires_condition': True,
                    'answer_options': '',
                    'subs': [],
                })
            rooms_to_extract.append({'name': room_name, 'items': items_out})

    # 2. Custom rooms added by clerk (not in template)
    for cr in (rd.get('_customRooms') or []):
        key = str(cr.get('key') or '')
        if not key or key in hidden_rooms:
            continue
        room_name = room_names_override.get(key, cr.get('name') or 'Room')
        cr_rd = rd.get(key, {})
        items_out = []
        for ex in (cr_rd.get('_extra') or []):
            eid = str(ex.get('_eid', ''))
            ex_data = cr_rd.get(eid, {}) if eid else {}
            merged = {**ex_data, **ex}
            ex_cond = (
                merged.get('condition') or merged.get('inventoryCondition')
                or merged.get('checkOutCondition') or ''
            ).strip()
            items_out.append({
                'name': merged.get('name') or merged.get('description') or 'Item',
                'description': ex_cond,
                'requires_photo': True,
                'requires_condition': True,
                'answer_options': '',
                'subs': [],
            })
        rooms_to_extract.append({'name': room_name, 'items': items_out})

    # Create the template
    new_template = Template(
        name=template_name,
        inspection_type=inspection_type,
        content='{}',
        is_default=False,
        is_transient=False,
    )
    db.session.add(new_template)
    db.session.flush()

    for room_idx, room in enumerate(rooms_to_extract):
        section = Section(
            template_id=new_template.id,
            name=room['name'],
            section_type='room',
            order_index=room_idx,
            is_required=False,
        )
        db.session.add(section)
        db.session.flush()
        for item_idx, it in enumerate(room['items']):
            db.session.add(Item(
                section_id=section.id,
                name=it['name'],
                description=it['description'],
                requires_photo=it['requires_photo'],
                requires_condition=it['requires_condition'],
                answer_options=it['answer_options'],
                order_index=item_idx,
            ))

    db.session.commit()
    room_count = len(rooms_to_extract)
    item_count = sum(len(r['items']) for r in rooms_to_extract)
    print(f'[save_as_template] created template "{template_name}" (id={new_template.id}) '
          f'from inspection {inspection_id}: {room_count} rooms, {item_count} items')
    return jsonify({
        'template_id': new_template.id,
        'name': new_template.name,
        'inspection_type': new_template.inspection_type,
        'room_count': room_count,
        'item_count': item_count,
    }), 201
