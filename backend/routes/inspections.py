from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Inspection, Property, User, Template, Section, Item
from permissions import get_current_user, require_admin_or_manager, filter_inspections_for_user, is_admin_or_manager
from sqlalchemy.orm import joinedload, selectinload
from datetime import datetime
import json
import re
import time
import random
import string

# Bust dashboard cache after any write so counts/activity stay accurate
def _bust_dashboard():
    try:
        from routes.dashboard import invalidate_dashboard_cache
        invalidate_dashboard_cache()
    except Exception:
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
    # Eager-load all relationships accessed in the list serialiser in a single
    # query (4 JOINs) instead of issuing 4 lazy-load queries per inspection.
    # Without this, 50 inspections → 200+ round trips → intermittent timeouts.
    eager = Inspection.query.options(
        joinedload(Inspection.property).joinedload(Property.client),
        joinedload(Inspection.inspector),
        joinedload(Inspection.typist),
    )
    query = filter_inspections_for_user(eager, user)
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
    inspection_type = data.get('inspection_type', 'check_in')

    # Standalone types (midterm, damage_report) are not part of the
    # check_in → check_out lifecycle and must never inherit a source
    # inspection's template — that would silently assign the wrong template type.
    STANDALONE_TYPES = {'midterm', 'damage_report'}
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

    # Standalone inspections have no source lifecycle link
    source_id = None if is_standalone else data.get('source_inspection_id')
    include_photos = bool(data.get('include_photos', False))
    seeded_report_data = None

    # ── Seed from source inspection (lifecycle types only) ───────────────
    # Only attempt transform when the source has actual report_data saved.
    if source_id:
        source = Inspection.query.get(source_id)
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
        client_email_override=data.get('client_email_override'),
        conduct_date=conduct_date,
        conduct_time_preference=data.get('conduct_time_preference'),
        report_data=seeded_report_data,
    )

    db.session.add(inspection)
    db.session.commit()
    _bust_dashboard()
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

    # ── Commit all field changes first ───────────────────────────────────────
    # Status is saved before PDF generation so a slow/failing PDF never blocks
    # or rolls back the status update.
    db.session.commit()
    _bust_dashboard()

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
                    from models import Inspection as _Inspection
                    insp   = _Inspection.query.get(_insp_id)
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
                                        _key = f"reports/inspection-{_insp_id}-{_dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
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
    if not emails:
        return jsonify({'error': 'No email addresses provided'}), 400
    if not inspection.report_data:
        return jsonify({'error': 'No report data — inspection has not been filled in yet'}), 400

    try:
        pdf_bytes = generate_inspection_pdf(inspection_id)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': f'PDF generation failed: {e}'}), 500

    # Run the SMTP send in a background thread so the HTTP response returns
    # immediately and Gunicorn's request timeout can't kill the worker.
    from flask import current_app
    _app        = current_app._get_current_object()
    _insp_id    = inspection_id
    _emails     = list(emails)
    _pdf_bytes  = pdf_bytes

    def _send_shared():
        with _app.app_context():
            try:
                from models import Inspection as _Insp
                from routes.email_service import send_report_complete
                insp   = _Insp.query.get(_insp_id)
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

                # ── Large-PDF handling (same threshold as auto-send) ──────
                _PDF_ATTACH_LIMIT = 25 * 1024 * 1024  # 25 MB
                _pdf_dl_url = None
                if len(_pdf_bytes) > _PDF_ATTACH_LIMIT:
                    print(f'[share-pdf] PDF is {len(_pdf_bytes)//1024//1024} MB — uploading to S3')
                    try:
                        from utils.s3 import is_configured as s3_ok, upload_bytes, presign_get
                        if s3_ok():
                            import datetime as _dt
                            _key = f"reports/inspection-{_insp_id}-{_dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
                            upload_bytes(_pdf_bytes, _key, content_type='application/pdf')
                            _pdf_dl_url = presign_get(_key, expires=604800)  # 7 days (AWS S3 maximum)
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

    # Return immediately — the send happens in the background
    return jsonify({'message': f'Report queued for delivery to {", ".join(emails)}'})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers for apply_pdf_import
# ─────────────────────────────────────────────────────────────────────────────

def _pdf_norm(s):
    """Normalise a string for fuzzy section/item name matching."""
    return re.sub(r'[\s/,&\-()\[\]]', '', (s or '').lower())

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
    {'name': 'Keys',                   'enabled': True, 'columns': ['name', 'description'],                     'items': []},
    {'name': 'Utility Meter Readings', 'enabled': True, 'columns': ['name', 'location_serial', 'reading'],      'items': []},
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


# POST /api/inspections/<id>/apply-pdf-import
#
# Stores Claude's parsed PDF data as the full report_data for the check-in.
# If no template is assigned, creates one from the PDF structure.
# Data is written to both the main report_data fields (so the check-in view
# renders it) and to _importedSource (so check-out comparison columns work).
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

    pdf_rooms = parsed.get('rooms') or []
    pdf_fixed = parsed.get('fixedSections') or {}

    # ── Resolve template (create from PDF if none assigned) ───────────────
    template = None
    if inspection.template_id:
        template = Template.query.get(inspection.template_id)

    if not template:
        template = _build_template_from_pdf(pdf_rooms, inspection)
        inspection.template_id = template.id

    # ── Build report_data keyed by real DB section/item IDs ───────────────
    report_data = {}

    db_room_sections = [s for s in template.sections if s.section_type == 'room']

    for pdf_room in pdf_rooms:
        matched_sec = _fuzzy_match_section(pdf_room['name'], db_room_sections)
        if not matched_sec:
            continue
        sec_key = str(matched_sec.id)
        report_data[sec_key] = {}
        for pdf_item in (pdf_room.get('items') or []):
            matched_item = _fuzzy_match_item(pdf_item.get('label', ''), matched_sec.items)
            if not matched_item:
                continue
            item_entry = {
                'description': pdf_item.get('description') or '',
                'condition':   pdf_item.get('condition')   or '',
            }
            # Carry across sub-items (e.g. Contents list)
            pdf_subs = pdf_item.get('_subs')
            if isinstance(pdf_subs, list) and pdf_subs:
                built_subs = []
                for sub in pdf_subs:
                    sid = 'sub_' + str(int(time.time() * 1000)) + '_' + ''.join(random.choices(string.ascii_lowercase, k=4))
                    built_subs.append({
                        '_sid':        sid,
                        'description': sub.get('description') or '',
                        'condition':   sub.get('condition')   or '',
                    })
                item_entry['_subs'] = built_subs
            report_data[sec_key][str(matched_item.id)] = item_entry

    # ── Fixed sections — keyed with the same IDs the frontend computes ────
    #
    # The frontend computes:
    #   section ID : f"fs_{secIdx}_{name_slug}"    (secIdx = index among enabled sections)
    #   row ID     : f"fs_{secIdx}_{rowIdx}"        (rowIdx = item's index within section)
    # where secIdx counts only enabled sections (enabled !== false).
    #
    # We replicate that here so the report view finds the data.
    global_fixed = _get_global_fixed_sections()
    enabled_fixed = [s for s in global_fixed if s.get('enabled', True) is not False]

    # Build lookup: pdf_type → (secIdx, global_section)
    type_to_global = {}
    for sec_idx, gsec in enumerate(enabled_fixed):
        typ = _infer_fs_type(gsec.get('columns') or [])
        if typ not in type_to_global:
            type_to_global[typ] = (sec_idx, gsec)

    for pdf_type, pdf_rows in pdf_fixed.items():
        if not isinstance(pdf_rows, list) or not pdf_rows:
            continue
        match = type_to_global.get(pdf_type)
        if not match:
            continue
        sec_idx, gsec = match
        sec_id = f'fs_{sec_idx}_{_fs_slug(gsec["name"])}'
        fields = _FS_FIELD_MAP.get(pdf_type, ['condition'])

        report_data[sec_id] = {}
        for i, pdf_row in enumerate(pdf_rows):
            # Guard: AI sometimes returns plain strings instead of dicts
            if not isinstance(pdf_row, dict):
                pdf_row = {fields[0]: str(pdf_row)} if fields else {}
            # Row ID mirrors the frontend: fs_{secIdx}_{rowIdx}
            row_id = f'fs_{sec_idx}_{i}'
            report_data[sec_id][row_id] = {f: pdf_row.get(f, '') for f in fields}
        print(f'[apply-pdf-import] fixed {pdf_type} → {sec_id}: {len(pdf_rows)} rows')

    # ── Also store as _importedSource (check-out comparison fallback) ─────
    report_data['_importedSource']   = {k: v for k, v in report_data.items() if not k.startswith('_')}
    report_data['_importedFileName'] = parsed.get('_fileName', '')

    inspection.report_data = json.dumps(report_data)
    db.session.commit()

    room_count = len(pdf_rooms)
    item_count = sum(len(r.get('items') or []) for r in pdf_rooms)
    print(f'[apply-pdf-import] inspection {inspection_id}: {room_count} rooms, {item_count} items, template {template.id}')

    return jsonify({
        'message': f'PDF imported: {room_count} rooms, {item_count} items',
        'room_count': room_count,
        'item_count': item_count,
        'template_id': template.id,
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
def _combine_conditions(inv_cond, co_cond, fallback=''):
    """
    Build a combined condition string for a new Check In seeded from a Check Out.
    Shows both the original Check In condition and the Check Out condition, labelled,
    so the new clerk can see the full history in one field.
    """
    inv = (inv_cond or '').strip()
    co  = (co_cond  or '').strip()
    parts = []
    if inv:
        parts.append(f'Check In: {inv}')
    if co:
        parts.append(f'Check Out: {co}')
    if not parts:
        fb = (fallback or '').strip()
        if fb:
            return fb
    return '\n'.join(parts)


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
