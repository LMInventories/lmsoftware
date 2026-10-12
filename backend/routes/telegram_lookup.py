"""
routes/telegram_lookup.py
───────────────────────────
The conversational, read-only /lookup for the Telegram bot — "who's the landlord
at 12 Smith St?", "what's on tomorrow?", "what hasn't Acme paid yet?", "show the
activity log for INS-150".

A small tool-use loop lets Claude search and fetch Properties, Clients and
Inspections (plus activity logs, the schedule, clerk availability, unpaid
invoices and a free-text search across notes/emails) and then write the reply
itself. telegram_integration.py replays the earlier turns of the conversation on
every message, so follow-ups like "and the tenant's email?" work.

Every tool is read-only and permission-scoped with the same helpers the webapp
uses (permissions.filter_*_for_user), so a clerk or client user can never see
more through the bot than in the app. An id outside the caller's scope is
reported as "not found", never "forbidden", so the bot doesn't confirm it
exists. Large blobs (report_data, logos, overview photos, signature images)
are never loaded or returned.

Unlike the write flows, the model does see database ids here — they only ever
flow between these read-only tools and are never used to change anything.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import anthropic

_MODEL = 'claude-sonnet-5'  # multi-step lookups; better at chaining searches and admitting "not found"
_MAX_ROUNDS = 6
_MAX_REPLY_CHARS = 4000  # Telegram's hard limit is 4096

_NOT_PINNED_DOWN = "I couldn't pin that down — try narrowing it with an address, a reference or a client name."

INSPECTION_STATUSES = ['created', 'assigned', 'active', 'processing', 'review', 'complete']


# ── Formatting helpers ──────────────────────────────────────────────────────

def _local_date(dt):
    """conduct_date/scheduled_date are naive local wall-clock values — see
    telegram_intent._today_london — so they're formatted as-is, never shifted."""
    return dt.strftime('%a %d %b %Y') if dt else None


def _utc_to_london(dt):
    """For genuinely-UTC columns (created_at, InspectionActivity.created_at, signed_at)."""
    from routes.telegram_intent import _LONDON
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_LONDON).strftime('%a %d %b %Y %H:%M')


def _label(value):
    return (value or '').replace('_', ' ').title() or None


def _clean(d: dict) -> dict:
    """Drop empty values so tool results stay compact."""
    return {k: v for k, v in d.items() if v not in (None, '', [], {})}


def _snippet(text: str, needle: str, width: int = 60) -> str:
    text = ' '.join(str(text).split())
    i = text.lower().find(needle.lower())
    if i < 0 or len(text) <= width * 2:
        return text[:width * 2]
    start = max(0, i - width)
    return ('…' if start else '') + text[start:i + len(needle) + width] + ('…' if i + len(needle) + width < len(text) else '')


# ── Scoped, blob-free base queries ──────────────────────────────────────────

def _client_light():
    from models import Client
    from sqlalchemy.orm import load_only
    return load_only(Client.id, Client.name, Client.company, Client.email, Client.phone)


def _properties(user):
    from models import Property
    from permissions import filter_properties_for_user
    from sqlalchemy.orm import defer, selectinload
    return filter_properties_for_user(Property.query, user).options(
        defer(Property.overview_photo),
        selectinload(Property.client).options(_client_light()),
    )


def _inspections(user):
    from models import Inspection, Property
    from permissions import filter_inspections_for_user
    from sqlalchemy.orm import defer, selectinload
    return filter_inspections_for_user(Inspection.query, user).options(
        defer(Inspection.report_data),
        selectinload(Inspection.property).options(
            defer(Property.overview_photo),
            selectinload(Property.client).options(_client_light()),
        ),
        selectinload(Inspection.inspector),
        selectinload(Inspection.typist),
    )


def _clients(user):
    from models import Client
    from permissions import filter_clients_for_user
    from sqlalchemy.orm import defer
    return filter_clients_for_user(Client.query, user).options(
        defer(Client.logo), defer(Client.logo_inverted), defer(Client.report_disclaimer),
        defer(Client.report_photo_settings),
    )


def _inspection_summary(insp) -> dict:
    prop = insp.property
    from routes.telegram_intent import format_time_preference
    return _clean({
        'inspection_id': insp.id,
        'reference': insp.reference_number,
        'type': _label(insp.inspection_type),
        'date': _local_date(insp.conduct_date),
        'time': format_time_preference(insp.conduct_time_preference) if insp.conduct_date else None,
        'status': _label(insp.status),
        'inspector': insp.inspector.name if insp.inspector else 'Unassigned',
        'address': prop.address if prop else None,
        'client': prop.client.name if prop and prop.client else None,
        'invoice_paid': insp.invoice_paid,
        'paper_import': insp.pdf_import or None,
    })


# ── Tools ───────────────────────────────────────────────────────────────────

def search_properties(user, query: str, client_name: str = ''):
    from models import Client, Inspection, Property
    from permissions import filter_inspections_for_user
    from sqlalchemy import func
    from routes.telegram_intent import _find_property_matches
    base = _properties(user)
    if client_name:
        base = base.join(Client, Client.id == Property.client_id).filter(
            (Client.name.ilike(f'%{client_name}%')) | (Client.company.ilike(f'%{client_name}%'))
        )
    if query:
        rows, fuzzy = _find_property_matches(query, base_query=base, limit=16)
    else:
        rows, fuzzy = base.order_by(Property.address.asc()).limit(16).all(), False
    rows = rows[:16]
    counts = dict(
        filter_inspections_for_user(Inspection.query, user)
        .filter(Inspection.property_id.in_([p.id for p in rows]))
        .with_entities(Inspection.property_id, func.count(Inspection.id))
        .group_by(Inspection.property_id).all()
    ) if rows else {}
    return {
        'fuzzy_match': fuzzy or None,
        'truncated': len(rows) > 15 or None,
        'properties': [_clean({
            'property_id': p.id,
            'address': p.address,
            'client': p.client.name if p.client else None,
            'inspection_count': counts.get(p.id, 0),
        }) for p in rows[:15]],
    }


def get_property(user, property_id: int):
    from models import Inspection
    p = _properties(user).filter_by(id=property_id).first()
    if p is None:
        return {'error': 'Property not found.'}
    inspections = (
        _inspections(user).filter(Inspection.property_id == p.id)
        .order_by(Inspection.conduct_date.desc().nullslast()).limit(21).all()
    )
    return _clean({
        'property_id': p.id,
        'address': p.address,
        'client': p.client.name if p.client else None,
        'client_id': p.client_id,
        'client_company': p.client.company if p.client else None,
        'property_type': p.property_type,
        'bedrooms': p.bedrooms,
        'bathrooms': p.bathrooms,
        'furnished': p.furnished,
        'detachment_type': p.detachment_type,
        'elevation': p.elevation,
        'parking': p.parking,
        'garden': p.garden,
        'lift': p.elevator,
        'meter_electricity': p.meter_electricity,
        'meter_gas': p.meter_gas,
        'meter_heat': p.meter_heat,
        'meter_water': p.meter_water,
        'notes': p.notes,
        'created': _utc_to_london(p.created_at),
        'inspections_newest_first': [_inspection_summary(i) for i in inspections[:20]],
        'more_inspections': len(inspections) > 20 or None,
    })


def search_clients(user, query: str):
    from models import Client
    q = f'%{query}%'
    rows = _clients(user).filter(
        Client.name.ilike(q) | Client.company.ilike(q) | Client.email.ilike(q) | Client.phone.ilike(q)
    ).order_by(Client.name.asc()).limit(16).all()
    return {
        'truncated': len(rows) > 15 or None,
        'clients': [_clean({
            'client_id': c.id, 'name': c.name, 'company': c.company, 'email': c.email, 'phone': c.phone,
        }) for c in rows[:15]],
    }


def get_client(user, client_id: int):
    from models import Inspection, Property, User
    from permissions import is_admin_or_manager
    from routes.email_notifications import DEFAULT_CLIENT_PREFS

    c = _clients(user).filter_by(id=client_id).first()
    if c is None:
        return {'error': 'Client not found.'}

    prefs = DEFAULT_CLIENT_PREFS.copy()
    if c.email_notifications:
        try:
            prefs.update(json.loads(c.email_notifications))
        except (ValueError, TypeError):
            pass

    props = _properties(user).filter(Property.client_id == c.id).order_by(Property.address.asc()).limit(31).all()
    recent = (
        _inspections(user)
        .filter(Inspection.property_id.in_(Property.query.filter(Property.client_id == c.id).with_entities(Property.id)))
        .order_by(Inspection.conduct_date.desc().nullslast()).limit(10).all()
    )
    result = {
        'client_id': c.id,
        'name': c.name,
        'company': c.company,
        'email': c.email,
        'phone': c.phone,
        'address': c.address,
        'created': _utc_to_london(c.created_at),
        'email_notifications': prefs,
        'properties': [{'property_id': p.id, 'address': p.address} for p in props[:30]],
        'more_properties': len(props) > 30 or None,
        'recent_inspections': [_inspection_summary(i) for i in recent],
    }
    if is_admin_or_manager(user):
        portal = User.query.filter_by(client_id=c.id, role='client').order_by(User.email.asc()).all()
        result['portal_logins'] = [_clean({'name': u.name, 'email': u.email}) for u in portal]
    return _clean(result)


def search_inspections(user, reference_number: str = '', property_id: int | None = None,
                       client_id: int | None = None, inspection_type: str = '', status: str = '',
                       date_from: str = '', date_to: str = '', inspector_name: str = '',
                       tenant: str = '', invoice_paid: bool | None = None, confirmed: bool | None = None,
                       unassigned_only: bool = False, include_paper_imports: bool = False,
                       newest_first: bool = True):
    from models import Inspection, Property, User
    from routes.telegram_intent import _day_bounds, normalize_inspection_type

    q = _inspections(user)
    if reference_number:
        q = q.filter(Inspection.reference_number.ilike(f'%{reference_number}%'))
    if property_id:
        q = q.filter(Inspection.property_id == property_id)
    if client_id:
        q = q.filter(Inspection.property_id.in_(
            Property.query.filter(Property.client_id == client_id).with_entities(Property.id)
        ))
    if inspection_type:
        t = normalize_inspection_type(inspection_type)
        if not t:
            return {'error': f'Unknown inspection type "{inspection_type}".'}
        q = q.filter(Inspection.inspection_type == t)
    if status:
        q = q.filter(Inspection.status == status)
    try:
        if date_from:
            q = q.filter(Inspection.conduct_date >= _day_bounds(datetime.fromisoformat(date_from).date())[0])
        if date_to:
            q = q.filter(Inspection.conduct_date < _day_bounds(datetime.fromisoformat(date_to).date())[1])
    except ValueError:
        return {'error': 'Dates must be ISO YYYY-MM-DD.'}
    if inspector_name:
        q = q.filter(Inspection.inspector_id.in_(
            User.query.filter(User.name.ilike(f'%{inspector_name}%')).with_entities(User.id)
        ))
    if unassigned_only:
        q = q.filter(Inspection.inspector_id.is_(None))
    if tenant:
        q = q.filter(Inspection.tenant_name.ilike(f'%{tenant}%') | Inspection.tenant_email.ilike(f'%{tenant}%'))
    if invoice_paid is not None:
        q = q.filter(Inspection.invoice_paid.is_(bool(invoice_paid)))
    if confirmed is not None:
        q = q.filter(Inspection.confirmed.is_(bool(confirmed)))
    if not include_paper_imports and not reference_number and not property_id:
        q = q.filter(Inspection.pdf_import.is_(False))

    order = Inspection.conduct_date.desc().nullslast() if newest_first else Inspection.conduct_date.asc().nullslast()
    rows = q.order_by(order).limit(26).all()
    return {
        'truncated': len(rows) > 25 or None,
        'inspections': [_inspection_summary(i) for i in rows[:25]],
    }


def get_inspection(user, inspection_id: int):
    from models import Inspection, InspectionSignature
    from permissions import is_admin_or_manager
    from routes.telegram_intent import format_time_preference
    from sqlalchemy.orm import defer, load_only

    insp = _inspections(user).filter(Inspection.id == inspection_id).first()
    if insp is None:
        return {'error': 'Inspection not found.'}
    prop = insp.property
    source = Inspection.query.options(
        load_only(Inspection.reference_number, Inspection.inspection_type, Inspection.conduct_date)
    ).filter_by(id=insp.source_inspection_id).first() if insp.source_inspection_id else None
    signatures = (
        InspectionSignature.query.filter_by(inspection_id=insp.id)
        .options(defer(InspectionSignature.signature_data)).all()
    )

    result = {
        'inspection_id': insp.id,
        'reference': insp.reference_number,
        'type': _label(insp.inspection_type),
        'status': _label(insp.status),
        'property_id': insp.property_id,
        'address': prop.address if prop else None,
        'client': prop.client.name if prop and prop.client else None,
        'client_id': prop.client_id if prop else None,
        'client_email': prop.client.email if prop and prop.client else None,
        'client_email_override': insp.client_email_override,
        'date': _local_date(insp.conduct_date),
        'time': format_time_preference(insp.conduct_time_preference),
        'inspector': insp.inspector.name if insp.inspector else 'Unassigned',
        'typist': insp.typist.name if insp.typist else None,
        'typist_mode': insp.typist_mode,
        'template': insp.template.name if insp.template else None,
        'continued_from': (source.reference_number or f'{_label(source.inspection_type)} {_local_date(source.conduct_date)}') if source else None,
        'tenant_name': insp.tenant_name,
        'tenant_email': insp.tenant_email,
        'landlord_email': insp.landlord_email,
        'key_location': insp.key_location,
        'key_return': insp.key_return,
        'deposit_amount': f'£{insp.deposit_amount}' if insp.deposit_amount is not None else None,
        'deposit_scheme': insp.deposit_scheme,
        'deposit_ref': insp.deposit_ref,
        'confirmed': insp.confirmed,
        'confirmed_at': _utc_to_london(insp.confirmed_at),
        'client_booked': insp.client_booked,
        'invoice_paid': insp.invoice_paid,
        'completion_email_sent': insp.completion_email_sent,
        'report_uploaded_to_drive': bool(insp.drive_file_id),
        'on_calendar': bool(insp.calendar_event_id),
        'paper_import': insp.pdf_import,
        'notes': insp.notes,
        'created': _utc_to_london(insp.created_at),
        'last_updated': _utc_to_london(insp.updated_at),
        'signatures': [_clean({
            'role': _label(s.role),
            'signer_name': s.signer_name,
            'signed': _utc_to_london(s.signed_at) if s.signed_at else 'not signed yet',
            'method': _label(s.method),
        }) for s in signatures],
    }
    if is_admin_or_manager(user):
        result['internal_notes'] = insp.internal_notes
    return _clean(result)


def get_activity_log(user, inspection_id: int):
    from models import Inspection, InspectionActivity
    from sqlalchemy.orm import selectinload

    insp = _inspections(user).filter(Inspection.id == inspection_id).first()
    if insp is None:
        return {'error': 'Inspection not found.'}
    rows = (
        InspectionActivity.query.filter_by(inspection_id=insp.id)
        .options(selectinload(InspectionActivity.user))
        .order_by(InspectionActivity.created_at.asc()).limit(101).all()
    )
    return {
        'reference': insp.reference_number,
        'address': insp.property.address if insp.property else None,
        'truncated': len(rows) > 100 or None,
        'events_oldest_first': [_clean({
            'when': _utc_to_london(a.created_at),
            'event': _label(a.event_type),
            'by': a.user.name if a.user else None,
            'detail': a.detail,
        }) for a in rows[:100]],
    }


def search_text(user, query: str):
    from models import Client, Inspection, Property
    from permissions import is_admin_or_manager
    from sqlalchemy import or_

    query = (query or '').strip()
    if len(query) < 2:
        return {'error': 'Search text must be at least 2 characters.'}
    like = f'%{query}%'
    needle = query.lower()
    hits = []

    def collect(rows, fields, describe):
        for row in rows:
            for field in fields:
                value = getattr(row, field)
                if value and needle in str(value).lower():
                    hits.append({**describe(row), 'field': field, 'text': _snippet(value, query)})

    prop_fields = ['address', 'notes', 'meter_electricity', 'meter_gas', 'meter_heat', 'meter_water']
    rows = _properties(user).filter(or_(*[getattr(Property, f).ilike(like) for f in prop_fields])).limit(20).all()
    collect(rows, prop_fields, lambda p: {'property_id': p.id, 'address': p.address})

    insp_fields = ['notes', 'tenant_name', 'tenant_email', 'landlord_email', 'client_email_override',
                   'key_location', 'key_return', 'deposit_ref', 'reference_number']
    if is_admin_or_manager(user):
        insp_fields.append('internal_notes')
    rows = _inspections(user).filter(or_(*[getattr(Inspection, f).ilike(like) for f in insp_fields])) \
        .order_by(Inspection.conduct_date.desc().nullslast()).limit(20).all()
    collect(rows, insp_fields, lambda i: _clean({
        'inspection_id': i.id, 'reference': i.reference_number, 'type': _label(i.inspection_type),
        'date': _local_date(i.conduct_date), 'address': i.property.address if i.property else None,
    }))

    client_fields = ['name', 'company', 'email', 'phone', 'address']
    rows = _clients(user).filter(or_(*[getattr(Client, f).ilike(like) for f in client_fields])).limit(20).all()
    collect(rows, client_fields, lambda c: {'client_id': c.id, 'client': c.name})

    return {'truncated': len(hits) > 20 or None, 'matches': hits[:20]}


def get_schedule(user, date_from: str = '', date_to: str = '', inspector_name: str = '',
                 unassigned_only: bool = False):
    """The agenda for a day or range (default: today), soonest first."""
    from routes.telegram_intent import _today_london
    today = _today_london().isoformat()
    return search_inspections(
        user, date_from=date_from or today, date_to=date_to or date_from or today,
        inspector_name=inspector_name, unassigned_only=unassigned_only, newest_first=False,
    )


def get_availability(user, date: str = ''):
    """Which clerks have nothing booked on a day, and what the busy ones are doing."""
    from models import Inspection, User
    from permissions import is_admin_or_manager
    from routes.telegram_intent import _day_bounds, _today_london, format_time_preference
    from sqlalchemy.orm import selectinload

    if not is_admin_or_manager(user):
        return {'error': 'Availability is visible to managers only.'}
    try:
        d = datetime.fromisoformat(date).date() if date else _today_london()
    except ValueError:
        return {'error': 'Date must be ISO YYYY-MM-DD.'}
    start, end = _day_bounds(d)
    roster = User.query.filter(User.role == 'clerk').order_by(User.name.asc()).all()
    if not roster:
        return {'error': 'No clerks are set up.'}
    busy = {}
    rows = (Inspection.query
            .filter(Inspection.conduct_date >= start, Inspection.conduct_date < end,
                    Inspection.inspector_id.isnot(None), Inspection.pdf_import.is_(False))
            .options(selectinload(Inspection.property)).order_by(Inspection.conduct_date.asc()).all())
    for insp in rows:
        busy.setdefault(insp.inspector_id, []).append(_clean({
            'address': insp.property.address if insp.property else None,
            'type': _label(insp.inspection_type),
            'time': format_time_preference(insp.conduct_time_preference),
        }))
    return {
        'date': _local_date(datetime.combine(d, datetime.min.time())),
        'free_clerks': [u.name for u in roster if u.id not in busy],
        'busy_clerks': [{'name': u.name, 'jobs': busy[u.id]} for u in roster if u.id in busy],
    }


def list_unpaid_invoices(user, client_name: str = '', client_id: int | None = None):
    """Completed inspections whose invoice hasn't been marked paid, optionally for one client."""
    from models import Client
    if client_name and not client_id:
        matches = _clients(user).filter(
            Client.name.ilike(f'%{client_name}%') | Client.company.ilike(f'%{client_name}%')).limit(6).all()
        if not matches:
            return {'error': f'No client matching "{client_name}".'}
        if len(matches) > 1:
            return {'error': 'More than one client matches — ask which.',
                    'clients': [{'client_id': c.id, 'name': c.name, 'company': c.company} for c in matches]}
        client_id = matches[0].id
    result = search_inspections(user, client_id=client_id, status='complete', invoice_paid=False,
                                newest_first=False)
    result['note'] = 'Completed inspections not yet marked invoice-paid, oldest first.'
    return result


_IMPLS = {
    'search_properties': search_properties,
    'get_property': get_property,
    'search_clients': search_clients,
    'get_client': get_client,
    'search_inspections': search_inspections,
    'get_inspection': get_inspection,
    'get_activity_log': get_activity_log,
    'search_text': search_text,
    'get_schedule': get_schedule,
    'get_availability': get_availability,
    'list_unpaid_invoices': list_unpaid_invoices,
}

_ID = {'type': 'integer'}

LOOKUP_TOOLS = [
    {
        'name': 'search_properties',
        'description': 'Find properties by any part of the address, optionally only those of a named client. Returns property_ids for get_property.',
        'input_schema': {'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': 'Any part of the address; may be empty when client_name is given'},
            'client_name': {'type': 'string', 'description': 'Client name or company, to list/narrow to their properties'},
        }, 'required': ['query']},
    },
    {
        'name': 'get_property',
        'description': 'Everything stored about one property — details, meters, notes, client — plus its inspections, newest first.',
        'input_schema': {'type': 'object', 'properties': {'property_id': _ID}, 'required': ['property_id']},
    },
    {
        'name': 'search_clients',
        'description': 'Find clients (letting agents / landlords) by name, company, email or phone. Returns client_ids for get_client.',
        'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
    },
    {
        'name': 'get_client',
        'description': "Everything about one client — contact details, email notification settings, portal logins, their properties and recent inspections.",
        'input_schema': {'type': 'object', 'properties': {'client_id': _ID}, 'required': ['client_id']},
    },
    {
        'name': 'search_inspections',
        'description': (
            'Filter inspections; every filter is optional and they combine. Returns summaries with '
            'inspection_ids for get_inspection / get_activity_log. Paper (PDF) imports are excluded '
            'unless searching by reference/property or include_paper_imports is set.'
        ),
        'input_schema': {'type': 'object', 'properties': {
            'reference_number': {'type': 'string', 'description': 'Full or partial, e.g. "INS-150"'},
            'property_id': _ID,
            'client_id': _ID,
            'inspection_type': {'type': 'string', 'enum': ['check_in', 'check_out', 'midterm', 'damage_report', 'heads_up']},
            'status': {'type': 'string', 'enum': INSPECTION_STATUSES},
            'date_from': {'type': 'string', 'description': 'ISO YYYY-MM-DD, inclusive'},
            'date_to': {'type': 'string', 'description': 'ISO YYYY-MM-DD, inclusive'},
            'inspector_name': {'type': 'string'},
            'tenant': {'type': 'string', 'description': "Tenant's name or email"},
            'invoice_paid': {'type': 'boolean'},
            'confirmed': {'type': 'boolean'},
            'unassigned_only': {'type': 'boolean'},
            'include_paper_imports': {'type': 'boolean'},
            'newest_first': {'type': 'boolean', 'description': 'Default true; set false for "next"/upcoming questions with date_from'},
        }, 'required': []},
    },
    {
        'name': 'get_inspection',
        'description': (
            'Everything about one inspection except the report contents — tenant/landlord/client '
            'emails, keys, deposit, notes, confirmation, invoice, signatures, template, who has it.'
        ),
        'input_schema': {'type': 'object', 'properties': {'inspection_id': _ID}, 'required': ['inspection_id']},
    },
    {
        'name': 'get_activity_log',
        'description': "An inspection's activity log: created, edited, fetched to phone, started, synced, completed, emails sent/failed — with who and when.",
        'input_schema': {'type': 'object', 'properties': {'inspection_id': _ID}, 'required': ['inspection_id']},
    },
    {
        'name': 'get_schedule',
        'description': (
            "The agenda: inspections booked for a day or date range (default today), soonest first, "
            "optionally for one clerk or only the unassigned ones. Use for 'what's on today/tomorrow/this week', "
            "'what's Sam doing Thursday', 'what's unassigned'."
        ),
        'input_schema': {'type': 'object', 'properties': {
            'date_from': {'type': 'string', 'description': 'ISO YYYY-MM-DD, inclusive (default today)'},
            'date_to': {'type': 'string', 'description': 'ISO YYYY-MM-DD, inclusive (default = date_from)'},
            'inspector_name': {'type': 'string'},
            'unassigned_only': {'type': 'boolean'},
        }, 'required': []},
    },
    {
        'name': 'get_availability',
        'description': "Which clerks are free on a day and what the busy ones are doing. Use for 'who's free tomorrow'.",
        'input_schema': {'type': 'object', 'properties': {
            'date': {'type': 'string', 'description': 'ISO YYYY-MM-DD (default today)'},
        }, 'required': []},
    },
    {
        'name': 'list_unpaid_invoices',
        'description': "Completed inspections whose invoice hasn't been marked paid, oldest first, optionally for one client (by name or client_id).",
        'input_schema': {'type': 'object', 'properties': {
            'client_name': {'type': 'string'},
            'client_id': _ID,
        }, 'required': []},
    },
    {
        'name': 'search_text',
        'description': (
            'Free-text search across property addresses/notes/meters, inspection notes, tenant '
            'names/emails, landlord emails, key locations, deposit refs and client contact details. '
            'Use for "anything mentioning X" or to find who an email address / phone number belongs to.'
        ),
        'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
        'cache_control': {'type': 'ephemeral'},
    },
]


def _run_tool(name: str, args: dict, user) -> str:
    from models import db
    impl = _IMPLS.get(name)
    if impl is None:
        return json.dumps({'error': f'Unknown tool {name}.'})
    try:
        return json.dumps(impl(user, **args), default=str)
    except TypeError as e:
        return json.dumps({'error': f'Bad arguments: {e}'})
    except Exception as e:
        db.session.rollback()
        print(f'[telegram_lookup] {name}({args}) failed: {e}')
        return json.dumps({'error': 'Lookup failed.'})


def _system_prompt(user) -> str:
    from routes.telegram_intent import _today_london
    today = _today_london().strftime('%A %d %B %Y')
    return (
        f"Today is {today} (UK). You answer questions from {user.name} (role: {user.role}) at a UK "
        "property inspection company, over Telegram, about their properties, clients and "
        "inspections. Use the tools to look things up — chain them as needed (e.g. "
        "search_properties then get_property then get_inspection). Rules:\n"
        "- Answer only from tool results. If nothing matches, say so plainly. Never guess an "
        "email, phone number, date or name.\n"
        "- If several records could match and the question doesn't say which, list the "
        "candidates briefly and ask which one.\n"
        "- The tools only return what this user is allowed to see; 'not found' may mean no access. "
        "Don't speculate about hidden records.\n"
        "- You are in a running conversation: earlier messages are above, so resolve follow-ups "
        "('and the tenant?', 'what about tomorrow?') from them. Their notes in [brackets] list the "
        "records you looked at — reuse those ids rather than searching again.\n"
        "- You cannot change anything. To add a property or book an inspection, tell the user to "
        "use /property or /inspection. You can't read report contents (room-by-room conditions) yet.\n"
        "- For schedule questions use get_schedule / get_availability; for unpaid invoices use "
        "list_unpaid_invoices.\n"
        "- Reply in plain text for Telegram: no markdown tables, no ** or #, short lines, "
        "at most ~10 list items (then say how many more and offer to narrow down).\n"
        "- Refer to inspections by reference number (or type + date + address), never by "
        "internal ids like inspection_id/property_id/client_id.\n"
        "- Be brief: answer the question asked, not everything you found."
    )


def _touched_note(touched: dict) -> str:
    """A bracketed memory aid appended to the stored (not the sent) reply: the records
    the model looked at, so a follow-up can go straight to get_* by id."""
    bits = [f'{kind} {", ".join(str(i) for i in ids)}' for kind, ids in touched.items() if ids]
    return f'\n[looked at: {"; ".join(bits)}]' if bits else ''


_ID_ARGS = {'property_id': 'property_id', 'client_id': 'client_id', 'inspection_id': 'inspection_id'}


def answer_lookup(question: str, user, history: list[dict] | None = None) -> tuple[str, str]:
    """history: the conversation so far as [{'role', 'content'}] (user first), so a
    follow-up like "and the tenant's email?" has something to refer to.

    Returns (reply_to_send, text_to_remember). The remembered text is the reply plus
    a note of the record ids looked at."""
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    system = [{'type': 'text', 'text': _system_prompt(user)}]
    touched: dict[str, list] = {key: [] for key in _ID_ARGS}

    messages = [{'role': h['role'], 'content': h['content']} for h in history or []]
    messages.append({'role': 'user', 'content': question})

    for _ in range(_MAX_ROUNDS):
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1200,
            system=system,
            tools=LOOKUP_TOOLS,
            messages=messages,
        )
        if response.stop_reason != 'tool_use':
            text = ''.join(b.text for b in response.content if b.type == 'text').strip()
            reply = (text or _NOT_PINNED_DOWN)[:_MAX_REPLY_CHARS]
            return reply, reply + _touched_note(touched)

        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for b in response.content:
            if b.type != 'tool_use':
                continue
            args = dict(b.input)
            for key in _ID_ARGS:
                if isinstance(args.get(key), int) and args[key] not in touched[key]:
                    touched[key].append(args[key])
            results.append({'type': 'tool_result', 'tool_use_id': b.id, 'content': _run_tool(b.name, args, user)})
        messages.append({'role': 'user', 'content': results})

    return _NOT_PINNED_DOWN, _NOT_PINNED_DOWN
