"""
routes/telegram_intent.py
───────────────────────────
Deterministic building blocks for the Telegram bot: address/property/lifecycle
lookups, summaries of what is about to be written, the payloads and internal
HTTP calls that apply a confirmed action, and the inspection-type / time
normalizers. No LLM is involved here.

The conversational /lookup lives in telegram_lookup.py; the guided
/property and /inspection flows in telegram_flows.py build their `resolved`
dicts and hand them to the SUMMARIZERS / BUILD_PAYLOAD / ACTION_CONFIG below.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_UK_POSTCODE_RE = re.compile(r'\b[A-Z]{1,2}[0-9][0-9A-Z]?\s*[0-9][A-Z]{2}\b', re.I)


def _find_property_matches(frag: str, base_query=None, limit: int = 6):
    """(properties, fuzzy). Substring match first; if that finds nothing, fall back to
    matching every word independently, so "123 Test Property" still finds
    "123, Test Property Road" (punctuation/ordering differences).

    base_query lets telegram_lookup.py pass an already permission-scoped query."""
    from models import Property
    from sqlalchemy import and_
    if base_query is None:
        base_query = Property.query
    exact = base_query.filter(Property.address.ilike(f'%{frag}%')).limit(limit).all()
    if exact:
        return exact, False
    tokens = [t for t in re.split(r'\W+', frag) if t]
    if not tokens:
        return [], False
    loose = base_query.filter(and_(*[Property.address.ilike(f'%{t}%') for t in tokens])).limit(limit).all()
    return loose, True


def _resolve_property(raw: dict, frag: str):
    """Shared property lookup for book/update/share. Returns (property, question).
    A lone exact match is used straight away; several matches, or any loose match, are
    listed for the user to pick by number (raw['_property_pick']), never guessed."""
    from models import db, Property

    pid = raw.get('_property_id')
    if pid:
        prop = db.session.get(Property, pid)
        if prop:
            return prop, None

    options = raw.get('_property_options')
    pick = raw.pop('_property_pick', None)
    if options and pick is not None:
        try:
            idx = int(pick) - 1
            if idx < 0:
                raise IndexError
            prop = db.session.get(Property, options[idx])
        except (ValueError, IndexError):
            return None, f"That's not one of the options — reply with a number from 1 to {len(options)}."
        if prop:
            raw['_property_id'] = prop.id
            return prop, None

    matches, fuzzy = _find_property_matches(frag)
    if not matches:
        raw.pop('_property_options', None)
        return None, f'I couldn\'t find a property matching "{frag}" — could you give me more of the address?'
    if len(matches) == 1 and not fuzzy:
        return matches[0], None

    raw['_property_options'] = [p.id for p in matches]
    if fuzzy:
        lead = f'I couldn\'t find an exact match for "{frag}" — did you mean:'
        tail = 'Reply with a number, or send a fuller address.'
    else:
        lead = f'I found more than one property matching "{frag}":'
        tail = 'Reply with the number.'
    lines = [lead] + [f'{i}. {p.address}' for i, p in enumerate(matches, 1)] + [tail]
    return None, '\n'.join(lines)

def _find_lifecycle_source(prop, inspection_type):
    """Mirrors InspectionsView.vue's auto-suggested "work from previous report"
    lookup: a check_out continues from the most recently created check_in at
    the property (regardless of whether it has report data yet — the link is
    what matters); a check_in continues from the most recently created
    check_out that has report data, falling back to the most recent check_in
    with report data if there's no check_out on record (e.g. a tenant who
    never had a move-out done). Standalone types (midterm/damage_report/
    heads_up) never have a source — callers only call this for check_in/
    check_out."""
    from models import Inspection

    if inspection_type == 'check_out':
        return (
            Inspection.query
            .filter(Inspection.property_id == prop.id, Inspection.inspection_type == 'check_in')
            .order_by(Inspection.created_at.desc())
            .first()
        )

    source = (
        Inspection.query
        .filter(Inspection.property_id == prop.id, Inspection.inspection_type == 'check_out',
                Inspection.report_data.isnot(None))
        .order_by(Inspection.created_at.desc())
        .first()
    )
    if source:
        return source
    return (
        Inspection.query
        .filter(Inspection.property_id == prop.id, Inspection.inspection_type == 'check_in',
                Inspection.report_data.isnot(None))
        .order_by(Inspection.created_at.desc())
        .first()
    )


# Types the webapp's Add Inspection form offers no room template for — they use
# sections configured in Settings instead.
TEMPLATELESS_TYPES = ('midterm', 'heads_up')

def _parse_recipients(raw_value, client_email, tenant_email):
    """Returns (emails: list[str]|None, error: str|None).
    emails is None when we still need to ask who to send it to."""
    if not raw_value:
        return None, None
    v = raw_value.strip().lower()
    if v == 'client':
        if client_email:
            return [client_email], None
        return None, 'No client email is on file — who should I send it to instead?'
    if v == 'tenant':
        if tenant_email:
            return [tenant_email], None
        return None, 'No tenant email is on file — who should I send it to instead?'
    if v in ('both', 'client and tenant', 'tenant and client', 'client & tenant'):
        emails = [e for e in (client_email, tenant_email) if e]
        if emails:
            return emails, None
        return None, 'Neither a client nor tenant email is on file — who should I send it to?'
    if '@' in raw_value:
        import re
        found = re.findall(r'[^\s,;]+@[^\s,;]+\.[^\s,;]+', raw_value)
        if found:
            return found, None
        return None, "That doesn't look like a valid email address — who should I send it to?"
    return None, None


def resolve_share_report(raw: dict):
    """Find the completed report being shared and who to send it to.

    Like resolve_update_inspection, supports a numeric raw['_pick'] (1-based)
    when a property has more than one completed report to disambiguate."""
    frag = (raw.get('property_address_fragment') or '').strip()
    if not frag:
        return None, "Which property's report do you want to share? (give me the address)"

    prop, question = _resolve_property(raw, frag)
    if question:
        return None, question

    from models import Inspection
    candidates = (
        Inspection.query
        .filter(Inspection.property_id == prop.id, Inspection.status == 'complete', Inspection.report_data.isnot(None))
        .order_by(Inspection.conduct_date.desc())
        .all()
    )
    if not candidates:
        return None, f'I couldn\'t find a completed report at "{prop.address}" to share.'

    pick = raw.get('_pick')
    if pick is not None:
        try:
            target = candidates[int(pick) - 1]
        except (ValueError, IndexError):
            return None, f'That\'s not one of the options — reply with a number from 1 to {len(candidates)}.'
    elif len(candidates) == 1:
        target = candidates[0]
    else:
        lines = [f'I found {len(candidates)} completed reports at "{prop.address}" — which one?']
        for i, insp in enumerate(candidates, 1):
            date_label = insp.conduct_date.strftime('%a %d %b %Y') if insp.conduct_date else 'no date'
            lines.append(f'{i}. {insp.inspection_type.replace("_", " ").title()} — {date_label}')
        lines.append('Reply with the number.')
        return None, '\n'.join(lines)

    client_email = (prop.client.email if prop.client else None) or None
    tenant_email = target.tenant_email or None

    emails, err = _parse_recipients(raw.get('recipients'), client_email, tenant_email)
    if err:
        return None, err
    if emails is None:
        options = []
        if client_email:
            options.append(f'"client" for {prop.client.name} ({client_email})')
        if tenant_email:
            options.append(f'"tenant" for {tenant_email}')
        if options:
            prompt = 'Who should I send the report to? Reply ' + ' or '.join(options) + ', or type an email address directly.'
        else:
            prompt = 'No client or tenant email is on file for this property — what email address should I send the report to?'
        return None, prompt

    resolved = {
        'inspection_id':    target.id,
        'property_address': prop.address,
        'inspection_type':  target.inspection_type,
        'emails':            emails,
        'notes':             (raw.get('notes') or '').strip() or None,
    }
    return resolved, None


def _resolve_invoice_item(item: dict):
    """Resolve one {reference_number?, property_address_fragment?, date?} entry to a
    single Inspection row. Returns (inspection, reason) — reason is a short phrase
    (not a full sentence) so several failures can be listed together in one summary,
    e.g. "12 Smith St: more than one inspection matches"."""
    ref = (item.get('reference_number') or '').strip()
    frag = (item.get('property_address_fragment') or '').strip()
    date_str = (item.get('date') or '').strip()

    if not ref and not frag:
        return None, 'give me a reference number or property address'

    from models import Inspection
    if ref:
        matches = Inspection.query.filter(Inspection.reference_number.ilike(ref)).all()
        if not matches:
            matches = Inspection.query.filter(Inspection.reference_number.ilike(f'%{ref}%')).limit(6).all()
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            refs = ', '.join(m.reference_number for m in matches)
            return None, f'more than one inspection matches reference "{ref}" ({refs})'
        if not frag:
            return None, f'no inspection found with reference "{ref}"'

    from models import Property
    prop_matches = Property.query.filter(Property.address.ilike(f'%{frag}%')).limit(6).all()
    if len(prop_matches) == 0:
        return None, f'no property matching "{frag}"'
    if len(prop_matches) > 1:
        addrs = '; '.join(f'"{p.address}"' for p in prop_matches)
        return None, f'more than one property matches "{frag}" ({addrs})'
    prop = prop_matches[0]

    insp_query = Inspection.query.filter(Inspection.property_id == prop.id, Inspection.pdf_import.is_(False))
    if date_str:
        try:
            target_date = datetime.fromisoformat(date_str).date()
        except (ValueError, TypeError):
            return None, f'couldn\'t understand the date "{date_str}"'
        day_start = datetime.combine(target_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        insp_query = insp_query.filter(Inspection.conduct_date >= day_start, Inspection.conduct_date < day_end)

    candidates = insp_query.order_by(Inspection.conduct_date.desc()).all()
    if len(candidates) == 0:
        return None, f'no inspection found at "{prop.address}"' + (f' on {date_str}' if date_str else '')
    if len(candidates) == 1:
        return candidates[0], None
    return None, (
        f'more than one inspection at "{prop.address}"'
        + (f' on {date_str}' if date_str else '')
        + ' — add a date or reference number'
    )


def resolve_mark_invoice_paid(raw: dict):
    """Batch resolver — unlike the single-target resolvers above, this doesn't return
    a single "question" on partial failure. Items that resolve go to confirmation;
    items that don't are listed as failures alongside them, so a batch of 5 with one
    typo'd address doesn't block marking the other 4 paid. Only returns (None,
    question) when NOTHING in the batch could be resolved."""
    items = raw.get('items') or []
    if not items:
        return None, ('Which inspection(s) should I mark as paid? Give me a reference '
                       'number or property address — you can list several at once.')

    resolved_items = []
    failures = []
    seen_ids = set()
    for item in items:
        insp, reason = _resolve_invoice_item(item)
        if insp is None:
            label = item.get('reference_number') or item.get('property_address_fragment') or '(unspecified)'
            failures.append(f'{label}: {reason}')
            continue
        if insp.id in seen_ids:
            continue
        seen_ids.add(insp.id)
        resolved_items.append({
            'inspection_id':    insp.id,
            'reference_number': insp.reference_number or f'#{insp.id}',
            'property_address': insp.property.address if insp.property else 'Unknown property',
            'already_paid':     bool(insp.invoice_paid),
        })

    if not resolved_items:
        return None, 'I couldn\'t find any of those:\n' + '\n'.join(f'• {f}' for f in failures)

    return {'items': resolved_items, 'failures': failures}, None




def summarize_property(resolved: dict) -> str:
    lines = [
        'Create this property?',
        f"• Address: {resolved['address']}",
        f"• Client: {resolved['client_name']}",
    ]
    if resolved.get('bedrooms') is not None:
        lines.append(f"• Bedrooms: {resolved['bedrooms']}")
    if resolved.get('bathrooms') is not None:
        lines.append(f"• Bathrooms: {resolved['bathrooms']}")
    if resolved.get('furnished'):
        lines.append(f"• Furnished: {resolved['furnished']}")
    if resolved.get('detachment_type'):
        lines.append(f"• Type: {resolved['detachment_type']}")
    if resolved.get('elevation'):
        lines.append(f"• Floor: {resolved['elevation']}")
    features = [name for name, key in (('Parking', 'parking'), ('Garden', 'garden'), ('Lift', 'elevator')) if resolved.get(key)]
    if features:
        lines.append(f"• Features: {', '.join(features)}")
    meters = [f"{label} ({resolved[key]})" for label, key in (
        ('Electricity', 'meter_electricity'), ('Gas', 'meter_gas'),
        ('Heat', 'meter_heat'), ('Water', 'meter_water'),
    ) if resolved.get(key)]
    if meters:
        lines.append(f"• Meters: {', '.join(meters)}")
    if resolved.get('notes'):
        lines.append(f"• Notes: {resolved['notes']}")
    return '\n'.join(lines)


def summarize_inspection(resolved: dict) -> str:
    dt = datetime.fromisoformat(resolved['conduct_date'])
    date_line = f"• Date: {dt.strftime('%a %d %b %Y')}"
    if resolved.get('conduct_time_preference'):
        date_line += f" — {format_time_preference(resolved['conduct_time_preference'])}"
    lines = [
        'Book this inspection?',
        f"• Property: {resolved['property_address']}",
        f"• Type: {resolved['inspection_type'].replace('_', ' ').title()}",
        date_line,
    ]
    if resolved.get('inspector_name'):
        lines.append(f"• Inspector: {resolved['inspector_name']}")
    if resolved.get('template_name'):
        lines.append(f"• Template: {resolved['template_name']}")
    if resolved.get('reference_number'):
        lines.append(f"• Reference: {resolved['reference_number']}")
    if resolved.get('source_inspection_id'):
        lines.append(f"• Continuing from: {resolved['source_label']}")
        lines.append(f"• Include photos: {'Yes' if resolved.get('include_photos') else 'No'}")
    return '\n'.join(lines)


def summarize_share_report(resolved: dict) -> str:
    lines = [
        'Share this report?',
        f"• Property: {resolved['property_address']} ({resolved['inspection_type'].replace('_', ' ').title()})",
        f"• Send to: {', '.join(resolved['emails'])}",
    ]
    if resolved.get('notes'):
        lines.append(f"• Note: {resolved['notes']}")
    return '\n'.join(lines)


def summarize_mark_invoice_paid(resolved: dict) -> str:
    items = resolved.get('items', [])
    failures = resolved.get('failures', [])

    lines = ['Mark invoice paid for:']
    for it in items:
        tag = ' (already marked paid)' if it.get('already_paid') else ''
        lines.append(f"• {it['reference_number']} — {it['property_address']}{tag}")
    if failures:
        lines.append('')
        lines.append('Couldn\'t identify:')
        for f in failures:
            lines.append(f'• {f}')
    lines.append('')
    return '\n'.join(lines)


SUMMARIZERS = {
    'create_property':   summarize_property,
    'book_inspection':   summarize_inspection,
    'share_report':      summarize_share_report,
    'mark_invoice_paid': summarize_mark_invoice_paid,
}

def build_property_payload(resolved: dict) -> dict:
    return {
        'address':           resolved['address'],
        'client_id':         resolved['client_id'],
        'property_type':     resolved.get('property_type') or 'residential',
        'bedrooms':          resolved.get('bedrooms'),
        'bathrooms':         resolved.get('bathrooms'),
        'furnished':         resolved.get('furnished'),
        'parking':           resolved.get('parking'),
        'garden':            resolved.get('garden'),
        'elevator':          resolved.get('elevator'),
        'detachment_type':   resolved.get('detachment_type'),
        'elevation':         resolved.get('elevation'),
        'meter_electricity': resolved.get('meter_electricity'),
        'meter_gas':         resolved.get('meter_gas'),
        'meter_heat':        resolved.get('meter_heat'),
        'meter_water':       resolved.get('meter_water'),
        'notes':             resolved.get('notes'),
    }


def build_inspection_payload(resolved: dict) -> dict:
    return {
        'property_id':             resolved['property_id'],
        'inspection_type':         resolved.get('inspection_type') or 'check_in',
        'conduct_date':            resolved['conduct_date'],
        'conduct_time_preference': resolved.get('conduct_time_preference'),
        'inspector_id':            resolved.get('inspector_id'),
        'tenant_email':            resolved.get('tenant_email'),
        'reference_number':        resolved.get('reference_number'),
        'template_id':             resolved.get('template_id'),
        'source_inspection_id':    resolved.get('source_inspection_id'),
        'include_photos':          resolved.get('include_photos', False),
        'create_heads_up':         bool(resolved.get('create_heads_up')),
    }


def build_share_report_payload(resolved: dict) -> dict:
    payload = {'emails': resolved['emails']}
    if resolved.get('notes'):
        payload['notes'] = resolved['notes']
    return payload


BUILD_PAYLOAD = {
    'create_property': build_property_payload,
    'book_inspection': build_inspection_payload,
    'share_report':    build_share_report_payload,
}

# Each entry describes the internal HTTP call _execute_pending_action makes to
# apply a confirmed action — method + a path builder (share needs the target
# inspection's id, resolved earlier). mark_invoice_paid is NOT here — it needs
# one HTTP call per resolved item (MULTI_TARGET_TOOLS below).
ACTION_CONFIG = {
    'create_property': {'method': 'POST', 'path': lambda resolved: '/api/properties'},
    'book_inspection': {'method': 'POST', 'path': lambda resolved: '/api/inspections'},
    'share_report':    {'method': 'POST', 'path': lambda resolved: f"/api/inspections/{resolved['inspection_id']}/share-pdf"},
}

MULTI_TARGET_TOOLS = {'mark_invoice_paid'}

_LONDON = ZoneInfo('Europe/London')


def _today_london():
    """conduct_date is a naive local wall-clock column — resolve_book_inspection and
    the /api/inspections POST/PUT handlers both write it via datetime.fromisoformat()
    with no timezone shift, so it holds the literal calendar date the user meant, not
    a UTC instant. "Today" therefore has to come from the Europe/London calendar day,
    and the query boundaries below stay naive/unshifted to match how it was written —
    do NOT apply the UTC-conversion pattern used elsewhere for genuinely-UTC columns
    like InspectionActivity.created_at."""
    return datetime.now(_LONDON).date()


def _day_bounds(d):
    start = datetime.combine(d, datetime.min.time())
    return start, start + timedelta(days=1)

INSPECTION_TYPES = ('check_in', 'check_out', 'midterm', 'damage_report', 'heads_up')

_INSPECTION_TYPE_ALIASES = {
    'check_in':      ('ci', 'check in', 'checkin', 'inventory', 'fresh'),
    'check_out':     ('co', 'check out', 'checkout'),
    'midterm':       ('mt', 'mid term', 'midterm'),
    'damage_report': ('dr', 'damage', 'damage report'),
    'heads_up':      ('heads up', 'headsup'),
}
_INSPECTION_TYPE_LOOKUP = {a: t for t, aliases in _INSPECTION_TYPE_ALIASES.items() for a in aliases}


def normalize_inspection_type(value: str) -> str | None:
    """Map "CI", "Check In", "inventory", "damage", etc. to a canonical inspection_type,
    or None if it isn't recognised."""
    key = re.sub(r'[\s_\-/]+', ' ', (value or '').strip().lower())
    return _INSPECTION_TYPE_LOOKUP.get(key) or (key.replace(' ', '_') if key.replace(' ', '_') in INSPECTION_TYPES else None)


def normalize_time_preference(value: str) -> str | None:
    """Turn what a person types into what the webapp stores in conduct_time_preference:
    'am', 'pm', 'anytime' or 'specific:HH_MM'. The webapp doesn't understand free
    text like "afternoon" (it falls back to showing Anytime), so anything unrecognised
    returns None and the caller asks again."""
    v = (value or '').strip().lower()
    if not v:
        return None
    if re.fullmatch(r'specific:\d{1,2}_\d{2}', v) or v in ('am', 'pm', 'anytime'):
        return v
    flat = re.sub(r'[^a-z0-9]', '', v)
    if flat in ('any', 'anytime', 'allday', 'flexible', 'none'):
        return 'anytime'
    if flat in ('am', 'morning', 'inthemorning', 'amslot'):
        return 'am'
    if flat in ('pm', 'afternoon', 'intheafternoon', 'pmslot', 'evening'):
        return 'pm'

    if 'noon' in v or 'midday' in v:
        hour, minute = 12, 0
    else:
        m = re.search(r'\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?m?\b', v) or re.search(r'\b(\d{1,2})[:.](\d{2})()\b', v)
        if not m:
            m = re.search(r'\b(?:at\s+)?(\d{1,2})()()\b', v)
        if not m:
            return None
        hour, minute, suffix = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or '')
        if hour > 23 or minute > 59:
            return None
        if suffix == 'p' and hour < 12:
            hour += 12
        elif suffix == 'a' and hour == 12:
            hour = 0
        elif not suffix and 1 <= hour <= 8:
            hour += 12  # a bare "2" means mid-afternoon on a working day
    minute = min(45, round(minute / 15) * 15) if minute < 53 else 45  # the webapp's picker steps in 15s
    return f'specific:{hour:02d}_{minute:02d}'


def format_time_preference(pref: str | None) -> str:
    p = (pref or '').strip().lower()
    if p in ('am', 'pm'):
        return p.upper()
    if p.startswith('specific:'):
        try:
            hour, minute = p.split(':', 1)[1].split('_')
            return f'{int(hour):02d}:{minute}'
        except ValueError:
            return p
    return 'Anytime' if not p or p == 'anytime' else p


def _time_sort_key(pref: str | None) -> int:
    p = (pref or '').strip().lower()
    if p == 'am':
        return 540
    if p == 'pm':
        return 780
    if p.startswith('specific:'):
        try:
            hour, minute = p.split(':', 1)[1].split('_')
            return int(hour) * 60 + int(minute)
        except ValueError:
            pass
    return 1440

