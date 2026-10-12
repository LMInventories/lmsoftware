"""
routes/telegram_flows.py
──────────────────────────
Guided, button-driven flows for the Telegram bot's /property and /inspection
commands. No LLM: every reply is routed by the step the flow is currently on.

A flow is an ordered list of steps. State is a small JSON-able dict kept in
TelegramSession.pending_action_json:

    {'flow': 'create_property' | 'book_inspection',
     'step': <current step name, or 'confirm' / 'edit'>,
     'data': {...answers so far...},
     'options': [...ids or strings behind the numbered buttons currently shown...]}

Each step has an `_ask_*` (the prompt and buttons, or None when the step is
already answered / not needed) and an `_accept_*` (apply a typed reply or a
tapped button; return None on success, or a (text, keyboard) to stay on the
step). After every answer `_advance` walks the steps in order and stops at the
first one still needing an answer, so editing an earlier answer only re-asks
what the change invalidated.

Button callback_data is "f:<step>:<value>" (Telegram caps it at 64 bytes), and
a button whose step is no longer the current one is ignored as stale.

Public API (all return (state, replies, action); replies is a list of
(text, inline_keyboard_or_None); action is None, 'execute' or 'cancelled'):
    start(flow)
    handle_text(state, text)
    handle_callback(state, step, value)
    build_resolved(state) -> the dict telegram_intent's SUMMARIZERS/BUILD_PAYLOAD expect
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from routes.telegram_intent import (
    SUMMARIZERS,
    TEMPLATELESS_TYPES,
    _UK_POSTCODE_RE,
    _day_bounds,
    _find_lifecycle_source,
    _find_property_matches,
    _today_london,
    format_time_preference,
    normalize_inspection_type,
    normalize_time_preference,
)

PROPERTY_FLOW = 'create_property'
INSPECTION_FLOW = 'book_inspection'

PROPERTY_STEPS = ['client', 'address', 'bedrooms', 'bathrooms', 'furnished', 'features', 'elevation', 'notes']
INSPECTION_STEPS = ['property', 'type', 'date', 'time', 'clerk', 'template', 'source', 'photos', 'tenant_email', 'reference']
STEPS = {PROPERTY_FLOW: PROPERTY_STEPS, INSPECTION_FLOW: INSPECTION_STEPS}

# Keys each step owns in `data` — cleared when the step is re-asked.
_STEP_KEYS = {
    'client': ['client_id', 'client_name'],
    'address': ['address', 'address_raw', 'address_options'],
    'bedrooms': ['bedrooms'],
    'bathrooms': ['bathrooms'],
    'furnished': ['furnished', 'furnished_done'],
    'features': ['parking', 'garden', 'elevator', 'features_done'],
    'elevation': ['elevation', 'elevation_done'],
    'notes': ['notes', 'notes_done'],
    'property': ['property_id', 'property_address'],
    'type': ['inspection_type'],
    'date': ['conduct_date'],
    'time': ['conduct_time_preference'],
    'clerk': ['inspector_id', 'inspector_name', 'clerk_done'],
    'template': ['template_id', 'template_name', 'template_done'],
    'source': ['continue', 'source_inspection_id', 'source_label'],
    'photos': ['include_photos'],
    'tenant_email': ['tenant_email', 'tenant_email_done'],
    'reference': ['reference_number', 'reference_done'],
}
# Answers that become invalid when an earlier one changes.
_DEPENDENTS = {
    'property': ['template', 'source', 'photos'],
    'type': ['template', 'source', 'photos'],
}

_EDIT_LABELS = {
    PROPERTY_FLOW: [('client', 'Client'), ('address', 'Address'), ('bedrooms', 'Bedrooms'), ('bathrooms', 'Bathrooms'),
                    ('furnished', 'Furnished'), ('features', 'Features'), ('elevation', 'Floor'), ('notes', 'Notes')],
    INSPECTION_FLOW: [('property', 'Property'), ('type', 'Type'), ('date', 'Date'), ('time', 'Time'),
                      ('clerk', 'Clerk'), ('tenant_email', 'Tenant email'), ('reference', 'Reference')],
}

_TYPE_LABELS = [('check_in', 'Check-in'), ('check_out', 'Check-out'), ('midterm', 'Midterm'),
                ('damage_report', 'Damage report'), ('heads_up', 'Heads-up')]

_MAX_OPTIONS = 8


# ── Small helpers ───────────────────────────────────────────────────────────

def _btn(text, step, value):
    return {'text': text, 'callback_data': f'f:{step}:{value}'}


def _keyboard(rows):
    return {'inline_keyboard': rows} if rows else None


def _chunk(buttons, per_row=2):
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _skip_row(step, label='Skip'):
    return [_btn(label, step, 'skip')]


def _clip(text, n=48):
    text = ' '.join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + '…'


def parse_date(text: str, today: date | None = None) -> date | None:
    """Deterministic date reading: today/tomorrow, weekday names ("thu", "next friday"),
    ISO, dd/mm[/yy[yy]], and "25 Sep"/"25th September [2026]". A year-less date that
    has already passed this year means next year. Returns None if unreadable."""
    today = today or _today_london()
    t = re.sub(r'\s+', ' ', (text or '').strip().lower()).replace(',', '')
    if not t:
        return None
    if t in ('today', 'tod'):
        return today
    if t in ('tomorrow', 'tmrw', 'tom', 'tmw'):
        return today + timedelta(days=1)

    weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    m = re.fullmatch(r'(?:next |this )?(mon|tue|wed|thu|fri|sat|sun)[a-z]*', t)
    if m:
        ahead = (weekdays.index(m.group(1)) - today.weekday()) % 7
        return today + timedelta(days=ahead or 7)  # a bare weekday means the next one, never today

    m = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    m = re.fullmatch(r'(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2}|\d{4}))?', t)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        return _build_date(day, month, year, today)

    months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    m = re.fullmatch(r'(\d{1,2})(?:st|nd|rd|th)? ([a-z]{3})[a-z]*(?: (\d{4}))?', t)
    if m and m.group(2) in months:
        return _build_date(int(m.group(1)), months.index(m.group(2)) + 1, m.group(3), today)
    m = re.fullmatch(r'([a-z]{3})[a-z]* (\d{1,2})(?:st|nd|rd|th)?(?: (\d{4}))?', t)
    if m and m.group(1) in months:
        return _build_date(int(m.group(2)), months.index(m.group(1)) + 1, m.group(3), today)
    return None


def _build_date(day, month, year, today):
    try:
        if year:
            y = int(year)
            return date(y + 2000 if y < 100 else y, month, day)
        d = date(today.year, month, day)
        return d if d >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def _yn_keyboard(step):
    return _keyboard([[_btn('Yes', step, 'y'), _btn('No', step, 'n')]])


# ── Step: client ────────────────────────────────────────────────────────────

def _ask_client(state):
    if 'client_id' in state['data']:
        return None
    return 'Which client is this property for? Type part of their name or company.', None


def _accept_client(state, text, value):
    from models import Client, db
    data = state['data']
    if value is not None:
        try:
            client = db.session.get(Client, state['options'][int(value)])
        except (ValueError, IndexError, TypeError):
            client = None
        if client is None:
            return 'That option has expired — type the client name again.', None
    else:
        q = (text or '').strip()
        if not q:
            return 'Type part of the client name.', None
        rows = (Client.query.filter(Client.name.ilike(f'%{q}%') | Client.company.ilike(f'%{q}%'))
                .order_by(Client.name.asc()).limit(_MAX_OPTIONS + 1).all())
        if not rows:
            return f'No client matching "{q}" — try another part of the name.', None
        if len(rows) > 1:
            rows = rows[:_MAX_OPTIONS]
            state['options'] = [c.id for c in rows]
            buttons = [_btn(_clip(c.name + (f' ({c.company})' if c.company else '')), 'client', i) for i, c in enumerate(rows)]
            return 'Which client?', _keyboard([[b] for b in buttons])
        client = rows[0]
    data['client_id'] = client.id
    data['client_name'] = client.name
    return None


# ── Step: address ───────────────────────────────────────────────────────────

def _ask_address(state):
    if 'address' in state['data']:
        return None
    return "What's the property's address? A full address with the postcode is best.", None


def _accept_address(state, text, value):
    data = state['data']
    if value is not None:
        if value == 'k':
            data['address'] = data.get('address_raw', '')
        else:
            try:
                data['address'] = data['address_options'][int(value)]
            except (ValueError, IndexError, KeyError, TypeError):
                return 'That option has expired — type the address again.', None
        data.pop('address_options', None)
        return None

    address = ' '.join((text or '').split())
    if len(address) < 5:
        return 'That looks too short — send the full address.', None
    data['address_raw'] = address
    has_full_postcode = _UK_POSTCODE_RE.search(address) and not _UK_POSTCODE_RE.fullmatch(address)
    if has_full_postcode:
        data['address'] = address
        return None
    try:
        from routes.address_lookup import search_suggestions
        options = [s['address'] for s in search_suggestions(address)[:5]]
    except Exception as e:  # lookup is a convenience — never block on it
        print(f'[telegram] address lookup failed: {e}')
        options = []
    if not options:
        data['address'] = address
        return None
    data['address_options'] = options
    rows = [[_btn(_clip(a, 60), 'address', i)] for i, a in enumerate(options)]
    rows.append([_btn('Keep as typed', 'address', 'k')])
    return f'"{address}" doesn\'t look like a full address. Did you mean:', _keyboard(rows)


# ── Steps: bedrooms / bathrooms ─────────────────────────────────────────────

def _count_buttons(step, labels):
    return _keyboard(_chunk([_btn(label, step, v) for v, label in labels], 3))


def _ask_bedrooms(state):
    if 'bedrooms' in state['data']:
        return None
    return 'How many bedrooms?', _count_buttons('bedrooms', [('0', 'Studio'), ('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'), ('5', '5')])


def _ask_bathrooms(state):
    if 'bathrooms' in state['data']:
        return None
    return 'How many bathrooms?', _count_buttons('bathrooms', [('1', '1'), ('2', '2'), ('3', '3'), ('4', '4')])


def _accept_count(key):
    def accept(state, text, value):
        raw = (value if value is not None else text or '').strip().lower()
        if key == 'bedrooms' and raw == 'studio':
            n = 0
        else:
            m = re.fullmatch(r'\d{1,2}', raw)
            if not m:
                return 'Send a number' + (' (or "studio")' if key == 'bedrooms' else '') + '.', None
            n = int(raw)
        state['data'][key] = n
        return None
    return accept


# ── Step: furnished ─────────────────────────────────────────────────────────

_FURNISHED = {'f': 'Furnished', 'p': 'Part Furnished', 'u': 'Unfurnished'}


def _ask_furnished(state):
    if state['data'].get('furnished_done'):
        return None
    rows = [[_btn(label, 'furnished', k) for k, label in _FURNISHED.items()], _skip_row('furnished')]
    return 'Furnished?', _keyboard(rows)


def _accept_furnished(state, text, value):
    data = state['data']
    raw = (value if value is not None else text or '').strip().lower()
    if raw in ('skip', ''):
        data['furnished'] = None
    elif raw in _FURNISHED:
        data['furnished'] = _FURNISHED[raw]
    elif raw.startswith('part') or raw.startswith('semi'):
        data['furnished'] = 'Part Furnished'
    elif raw.startswith('un') or raw.startswith('not'):
        data['furnished'] = 'Unfurnished'
    elif 'furn' in raw:
        data['furnished'] = 'Furnished'
    else:
        return 'Choose Furnished, Part Furnished, Unfurnished or Skip.', None
    data['furnished_done'] = True
    return None


# ── Step: features (parking / garden / lift) ────────────────────────────────

_FEATURES = [('p', 'parking', 'Parking'), ('g', 'garden', 'Garden'), ('l', 'elevator', 'Lift')]


def _features_keyboard(data):
    toggles = [_btn(('✅ ' if data.get(key) else '⬜ ') + label, 'features', k) for k, key, label in _FEATURES]
    return _keyboard([toggles, [_btn('Done', 'features', 'done')]])


def _ask_features(state):
    if state['data'].get('features_done'):
        return None
    return 'Any of these? Tap to toggle, then Done.', _features_keyboard(state['data'])


def _accept_features(state, text, value):
    data = state['data']
    if value in ('p', 'g', 'l'):
        key = next(k for c, k, _ in _FEATURES if c == value)
        data[key] = not data.get(key)
        return 'Any of these? Tap to toggle, then Done.', _features_keyboard(data)
    if value == 'done':
        data['features_done'] = True
        return None
    words = (text or '').lower()
    if words.strip() in ('done', 'none', 'no', 'skip', 'nothing'):
        data['features_done'] = True
        return None
    if not any(w in words for w in ('park', 'garden', 'lift', 'elevator')):
        return 'Tap the buttons, or say which apply (e.g. "parking and garden"), or Done.', _features_keyboard(data)
    data['parking'] = data.get('parking') or 'park' in words
    data['garden'] = data.get('garden') or 'garden' in words
    data['elevator'] = data.get('elevator') or 'lift' in words or 'elevator' in words
    data['features_done'] = True
    return None


# ── Step: elevation (floor) ─────────────────────────────────────────────────

_FLOORS = ['Ground Floor', '1st Floor', '2nd Floor', '3rd Floor']


def _ask_elevation(state):
    if state['data'].get('elevation_done'):
        return None
    rows = _chunk([_btn(f, 'elevation', i) for i, f in enumerate(_FLOORS)], 2) + [_skip_row('elevation')]
    return 'Which floor is it on? Tap one, or type it (e.g. "5th Floor").', _keyboard(rows)


def _accept_elevation(state, text, value):
    data = state['data']
    if value == 'skip':
        data['elevation'] = None
    elif value is not None:
        try:
            data['elevation'] = _FLOORS[int(value)]
        except (ValueError, IndexError):
            return 'Choose a floor, or type it.', None
    else:
        data['elevation'] = _clip((text or '').strip(), 50) or None
    data['elevation_done'] = True
    return None


# ── Step: notes ─────────────────────────────────────────────────────────────

def _ask_notes(state):
    if state['data'].get('notes_done'):
        return None
    return 'Any notes about the property (access, keys, quirks)? Type them, or Skip.', _keyboard([_skip_row('notes')])


def _accept_notes(state, text, value):
    data = state['data']
    data['notes'] = None if value == 'skip' else ((text or '').strip() or None)
    data['notes_done'] = True
    return None


# ── Step: property (inspection flow) ────────────────────────────────────────

def _ask_property(state):
    if 'property_id' in state['data']:
        return None
    return 'Which property is this for? Type part of the address.', None


def _accept_property(state, text, value):
    from models import Property, db
    data = state['data']
    if value is not None:
        try:
            prop = db.session.get(Property, state['options'][int(value)])
        except (ValueError, IndexError, TypeError):
            prop = None
        if prop is None:
            return 'That option has expired — type the address again.', None
    else:
        frag = (text or '').strip()
        if len(frag) < 2:
            return 'Type part of the address.', None
        matches, fuzzy = _find_property_matches(frag, limit=_MAX_OPTIONS)
        if not matches:
            return f'No property matching "{frag}" — try a different part of the address. (Use /property to add a new one.)', None
        if len(matches) == 1 and not fuzzy:
            prop = matches[0]
        else:
            state['options'] = [p.id for p in matches]
            lead = 'No exact match — did you mean:' if fuzzy else 'Which property?'
            return lead, _keyboard([[_btn(_clip(p.address, 60), 'property', i)] for i, p in enumerate(matches)])
    data['property_id'] = prop.id
    data['property_address'] = prop.address
    return None


# ── Step: type ──────────────────────────────────────────────────────────────

def _ask_type(state):
    if 'inspection_type' in state['data']:
        return None
    buttons = [_btn(label, 'type', code) for code, label in _TYPE_LABELS]
    return 'What type of inspection?', _keyboard(_chunk(buttons, 2))


def _accept_type(state, text, value):
    t = normalize_inspection_type(value if value is not None else text or '')
    if not t:
        return 'Choose a type with the buttons, or type check-in, check-out, midterm, damage report or heads-up.', None
    state['data']['inspection_type'] = t
    return None


# ── Step: date ──────────────────────────────────────────────────────────────

def _ask_date(state):
    if 'conduct_date' in state['data']:
        return None
    kb = _keyboard([[_btn('Today', 'date', 'today'), _btn('Tomorrow', 'date', 'tomorrow')]])
    return 'What date? Tap one, or type it (e.g. Thu, 25/09, 25 Sep).', kb


def _accept_date(state, text, value):
    d = parse_date(value if value is not None else text or '')
    if d is None:
        return 'I couldn\'t read that date — try "Thu", "25/09" or "25 Sep".', None
    if d < _today_london():
        return f'{d.strftime("%a %d %b %Y")} is in the past — what date did you mean?', None
    state['data']['conduct_date'] = d.isoformat()
    return None


# ── Step: time ──────────────────────────────────────────────────────────────

def _ask_time(state):
    if 'conduct_time_preference' in state['data']:
        return None
    kb = _keyboard([[_btn('Anytime', 'time', 'anytime'), _btn('AM', 'time', 'am'), _btn('PM', 'time', 'pm')]])
    return 'What time? Tap one, or type a specific time (e.g. 2:30pm).', kb


def _accept_time(state, text, value):
    pref = normalize_time_preference(value if value is not None else text or '')
    if not pref:
        return 'I didn\'t understand that time — say AM, PM, anytime, or a time like 2:30pm.', None
    state['data']['conduct_time_preference'] = pref
    return None


# ── Step: clerk ─────────────────────────────────────────────────────────────

def _clerks_with_load(data):
    from models import Inspection, User
    clerks = User.query.filter(User.role == 'clerk').order_by(User.name.asc()).all()
    load = {}
    if data.get('conduct_date') and clerks:
        start, end = _day_bounds(date.fromisoformat(data['conduct_date']))
        rows = (Inspection.query
                .filter(Inspection.conduct_date >= start, Inspection.conduct_date < end,
                        Inspection.inspector_id.in_([c.id for c in clerks]), Inspection.pdf_import.is_(False))
                .with_entities(Inspection.inspector_id).all())
        for (cid,) in rows:
            load[cid] = load.get(cid, 0) + 1
    return clerks, load


def _clerk_optional(data):
    return data.get('inspection_type') in TEMPLATELESS_TYPES


def _ask_clerk(state):
    data = state['data']
    if data.get('clerk_done'):
        return None
    clerks, load = _clerks_with_load(data)
    state['options'] = [c.id for c in clerks]
    rows = []
    for i, c in enumerate(clerks):
        n = load.get(c.id, 0)
        rows.append([_btn(c.name + (f' ({n} job{"s" if n != 1 else ""} that day)' if n else ' (free)'), 'clerk', i)])
    if _clerk_optional(data):
        rows.append([_btn('Unassigned', 'clerk', 'none')])
    if not clerks and not _clerk_optional(data):
        return 'There are no clerks set up to assign this to.', None
    return 'Who should do it?', _keyboard(rows)


def _accept_clerk(state, text, value):
    from models import User, db
    data = state['data']
    if value == 'none' and _clerk_optional(data):
        data.update(inspector_id=None, inspector_name=None, clerk_done=True)
        return None
    clerk = None
    if value is not None:
        try:
            clerk = db.session.get(User, state['options'][int(value)])
        except (ValueError, IndexError, TypeError):
            clerk = None
    else:
        q = (text or '').strip()
        matches = User.query.filter(User.role == 'clerk', User.name.ilike(f'%{q}%')).limit(2).all() if q else []
        clerk = matches[0] if len(matches) == 1 else None
    if clerk is None:
        return 'Tap a clerk from the list, or type their name.', None
    data.update(inspector_id=clerk.id, inspector_name=clerk.name, clerk_done=True)
    return None


# ── Step: template ──────────────────────────────────────────────────────────

def _templates_for(inspection_type):
    from models import Template
    return (Template.query
            .filter(Template.inspection_type == inspection_type,
                    (Template.is_transient == False) | (Template.is_transient == None))  # noqa: E712
            .order_by(Template.is_default.desc(), Template.name).all())


def _ask_template(state):
    data = state['data']
    if data.get('template_done'):
        return None
    t = data.get('inspection_type')
    templates = [] if t in TEMPLATELESS_TYPES else _templates_for(t)
    if len(templates) <= 1:  # nothing to choose — the backend falls back to the type's default
        data.update(template_id=templates[0].id if templates else None,
                    template_name=templates[0].name if templates else None, template_done=True)
        return None
    state['options'] = [tpl.id for tpl in templates]
    rows = [[_btn(_clip(tpl.name) + (' (default)' if tpl.is_default else ''), 'template', i)] for i, tpl in enumerate(templates)]
    return f'Which report template for this {t.replace("_", " ")}?', _keyboard(rows)


def _accept_template(state, text, value):
    from models import Template, db
    try:
        tpl = db.session.get(Template, state['options'][int(value)])
    except (ValueError, IndexError, TypeError):
        tpl = None
    if tpl is None:
        return 'Tap a template from the list.', None
    state['data'].update(template_id=tpl.id, template_name=tpl.name, template_done=True)
    return None


# ── Steps: source (continue from previous) / photos ─────────────────────────

def _source_for(data):
    from models import Property, db
    if data.get('inspection_type') not in ('check_in', 'check_out'):
        return None
    prop = db.session.get(Property, data['property_id'])
    return _find_lifecycle_source(prop, data['inspection_type']) if prop else None


def _source_label(source):
    date_label = source.conduct_date.strftime('%a %d %b %Y') if source.conduct_date else 'no date on record'
    return f"{source.inspection_type.replace('_', ' ').title()} on {date_label}"


def _ask_source(state):
    data = state['data']
    if 'continue' in data:
        return None
    source = _source_for(data)
    if source is None:
        data['continue'] = False
        return None
    data['source_inspection_id'] = source.id
    data['source_label'] = _source_label(source)
    return f'Continue this report from the {data["source_label"]}?', _yn_keyboard('source')


def _accept_source(state, text, value):
    raw = (value if value is not None else text or '').strip().lower()
    if raw in ('y', 'yes'):
        state['data']['continue'] = True
    elif raw in ('n', 'no'):
        state['data']['continue'] = False
        state['data'].pop('source_inspection_id', None)
        state['data'].pop('source_label', None)
    else:
        return 'Yes or No?', _yn_keyboard('source')
    return None


def _ask_photos(state):
    data = state['data']
    if 'include_photos' in data:
        return None
    if not data.get('continue'):
        data['include_photos'] = False
        return None
    return 'Include photos from that inspection?', _yn_keyboard('photos')


def _accept_photos(state, text, value):
    raw = (value if value is not None else text or '').strip().lower()
    if raw not in ('y', 'yes', 'n', 'no'):
        return 'Yes or No?', _yn_keyboard('photos')
    state['data']['include_photos'] = raw in ('y', 'yes')
    return None


# ── Steps: tenant email / reference ─────────────────────────────────────────

_EMAIL_RE = re.compile(r'^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$')


def _ask_tenant_email(state):
    if state['data'].get('tenant_email_done'):
        return None
    return "Tenant's email? (several can be comma-separated), or Skip.", _keyboard([_skip_row('tenant_email')])


def _accept_tenant_email(state, text, value):
    data = state['data']
    if value == 'skip':
        data.update(tenant_email=None, tenant_email_done=True)
        return None
    emails = [e.strip() for e in re.split(r'[,;\s]+', text or '') if e.strip()]
    if not emails or not all(_EMAIL_RE.match(e) for e in emails):
        return "That doesn't look like a valid email — try again, or Skip.", _keyboard([_skip_row('tenant_email')])
    data.update(tenant_email=', '.join(emails), tenant_email_done=True)
    return None


def _ask_reference(state):
    if state['data'].get('reference_done'):
        return None
    return 'Reference number? Type one, or tap Auto to use INS-<number>.', _keyboard([_skip_row('reference', 'Auto')])


def _accept_reference(state, text, value):
    data = state['data']
    ref = None if value == 'skip' else (text or '').strip()
    if ref and len(ref) > 50:
        return 'That reference is too long.', None
    data.update(reference_number=ref or None, reference_done=True)
    return None


_ASK = {
    'client': _ask_client, 'address': _ask_address, 'bedrooms': _ask_bedrooms, 'bathrooms': _ask_bathrooms,
    'furnished': _ask_furnished, 'features': _ask_features, 'elevation': _ask_elevation, 'notes': _ask_notes,
    'property': _ask_property, 'type': _ask_type, 'date': _ask_date, 'time': _ask_time, 'clerk': _ask_clerk,
    'template': _ask_template, 'source': _ask_source, 'photos': _ask_photos,
    'tenant_email': _ask_tenant_email, 'reference': _ask_reference,
}
_ACCEPT = {
    'client': _accept_client, 'address': _accept_address,
    'bedrooms': _accept_count('bedrooms'), 'bathrooms': _accept_count('bathrooms'),
    'furnished': _accept_furnished, 'features': _accept_features, 'elevation': _accept_elevation, 'notes': _accept_notes,
    'property': _accept_property, 'type': _accept_type, 'date': _accept_date, 'time': _accept_time,
    'clerk': _accept_clerk, 'template': _accept_template, 'source': _accept_source, 'photos': _accept_photos,
    'tenant_email': _accept_tenant_email, 'reference': _accept_reference,
}


# ── Confirm card ────────────────────────────────────────────────────────────

def build_resolved(state) -> dict:
    """The `resolved` dict telegram_intent's SUMMARIZERS / BUILD_PAYLOAD expect."""
    d = state['data']
    if state['flow'] == PROPERTY_FLOW:
        return {
            'address': d['address'], 'client_id': d['client_id'], 'client_name': d['client_name'],
            'property_type': 'residential', 'bedrooms': d['bedrooms'], 'bathrooms': d['bathrooms'],
            'furnished': d.get('furnished'), 'parking': bool(d.get('parking')), 'garden': bool(d.get('garden')),
            'elevator': bool(d.get('elevator')), 'elevation': d.get('elevation'), 'notes': d.get('notes'),
        }
    return {
        'property_id': d['property_id'], 'property_address': d['property_address'],
        'inspection_type': d['inspection_type'], 'conduct_date': datetime.fromisoformat(d['conduct_date']).isoformat(),
        'conduct_time_preference': d.get('conduct_time_preference'),
        'inspector_id': d.get('inspector_id'), 'inspector_name': d.get('inspector_name'),
        'tenant_email': d.get('tenant_email'), 'reference_number': d.get('reference_number'),
        'template_id': d.get('template_id'), 'template_name': d.get('template_name'),
        'source_inspection_id': d.get('source_inspection_id') if d.get('continue') else None,
        'source_label': d.get('source_label') if d.get('continue') else None,
        'include_photos': bool(d.get('include_photos')),
        'create_heads_up': bool(d.get('create_heads_up')),
    }


def _warnings(state) -> list[str]:
    from models import Inspection, Property
    d = state['data']
    out = []
    try:
        if state['flow'] == PROPERTY_FLOW:
            if Property.query.filter(Property.client_id == d['client_id'], Property.address.ilike(d['address'])).first():
                out.append('⚠️ This client already has a property with that address.')
        else:
            start, end = _day_bounds(date.fromisoformat(d['conduct_date']))
            if d.get('inspector_id'):
                n = Inspection.query.filter(
                    Inspection.inspector_id == d['inspector_id'], Inspection.conduct_date >= start,
                    Inspection.conduct_date < end, Inspection.pdf_import.is_(False)).count()
                if n:
                    out.append(f'⚠️ {d["inspector_name"]} already has {n} job{"s" if n != 1 else ""} that day.')
            if Inspection.query.filter(
                    Inspection.property_id == d['property_id'], Inspection.inspection_type == d['inspection_type'],
                    Inspection.conduct_date >= start, Inspection.conduct_date < end).first():
                out.append('⚠️ There is already an inspection of this type at this property on that day.')
    except Exception as e:
        print(f'[telegram] confirm warnings failed: {e}')
    return out


def _confirm_reply(state):
    resolved = build_resolved(state)
    lines = [SUMMARIZERS[state['flow']](resolved)]
    if state['flow'] == INSPECTION_FLOW and resolved.get('create_heads_up'):
        lines.append('• Also creating a linked heads-up')
    lines += _warnings(state)
    kb = _keyboard([[_btn('✅ Confirm', 'confirm', 'yes'), _btn('✏️ Edit', 'confirm', 'edit'), _btn('❌ Cancel', 'confirm', 'no')]])
    return '\n'.join(lines), kb


def _edit_reply(state):
    buttons = [_btn(label, 'edit', step) for step, label in _EDIT_LABELS[state['flow']]]
    if state['flow'] == INSPECTION_FLOW and state['data'].get('inspection_type') in ('check_in', 'check_out'):
        on = state['data'].get('create_heads_up')
        buttons.append(_btn(('✅ ' if on else '⬜ ') + 'Heads-up', 'edit', 'headsup'))
    rows = _chunk(buttons, 2) + [[_btn('« Back', 'edit', 'back')]]
    return 'What would you like to change?', _keyboard(rows)


# ── Engine ──────────────────────────────────────────────────────────────────

def start(flow: str):
    state = {'flow': flow, 'step': None, 'data': {}, 'options': []}
    return _advance(state, [])


def _advance(state, replies):
    """Walk the steps in order; stop at the first that still needs an answer."""
    for step in STEPS[state['flow']]:
        asked = _ASK[step](state)
        if asked is not None:
            state['step'] = step
            state['options'] = state.get('options') if step in ('client', 'property', 'clerk', 'template') else []
            return state, replies + [asked], None
    state['step'] = 'confirm'
    state['options'] = []
    return state, replies + [_confirm_reply(state)], None


def _reask(state, step):
    """Forget the answer to `step` (and anything depending on it) and ask it again."""
    for s in [step] + _DEPENDENTS.get(step, []):
        for k in _STEP_KEYS[s]:
            state['data'].pop(k, None)
    if step == 'type' and state['data'].get('inspection_type') is None and state['data'].get('clerk_done') \
            and state['data'].get('inspector_id') is None:
        # The new type may require a clerk, so don't carry "unassigned" across a type change.
        for k in _STEP_KEYS['clerk']:
            state['data'].pop(k, None)
    state['step'] = step


def handle_text(state, text):
    step = state['step']
    if step == 'confirm':
        return state, [('Use the buttons to Confirm, Edit or Cancel — or /cancel.', _confirm_reply(state)[1])], None
    if step == 'edit':
        return state, [_edit_reply(state)], None
    return _apply(state, step, text=text)


def handle_callback(state, step, value):
    cur = state['step']
    if step == 'confirm':
        if cur != 'confirm':
            return state, [], None
        if value == 'yes':
            return state, [], 'execute'
        if value == 'no':
            return state, [], 'cancelled'
        state['step'] = 'edit'
        return state, [_edit_reply(state)], None
    if step == 'edit':
        if cur != 'edit':
            return state, [], None
        if value == 'back':
            return _advance(state, [])
        if value == 'headsup':
            state['data']['create_heads_up'] = not state['data'].get('create_heads_up')
            return state, [_edit_reply(state)], None
        if value in _STEP_KEYS:
            _reask(state, value)  # dependents are cleared too, so _advance re-asks only what's missing
            return _advance(state, [])
        return state, [], None
    if step != cur:  # a button from an earlier question
        return state, [], None
    return _apply(state, step, value=value)


def _apply(state, step, text=None, value=None):
    stay = _ACCEPT[step](state, text, value)
    if stay is not None:
        return state, [stay], None
    return _advance(state, [])
