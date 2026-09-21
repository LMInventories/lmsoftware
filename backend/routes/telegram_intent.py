"""
routes/telegram_intent.py
───────────────────────────
Free-text intent parsing for the Telegram bot integration
(routes/telegram_integration.py).

Four write actions (create_property, book_inspection, update_inspection,
share_report) plus two read-only ones (query_schedule, query_availability).
Uses the Anthropic client (same pattern as backend/learning/proposal.py) with
native tool-use so model output is structured instead of ask-for-JSON-and-
strip-fences.

The read-only tools skip the resolve->confirm->write pipeline entirely —
there's nothing to roll back, so they answer directly from a single parse
(see READ_ONLY_TOOLS / ANSWERERS below and telegram_integration.py's
_handle_text_message, which branches on READ_ONLY_TOOLS before ever touching
session/confirmation state).

Also defines TEMPLATES — the fill-in-the-blanks messages sent by /property and
/inspection. The user copies the template, fills in the required fields and sends
it back; parse_template() reads the "Label: value" lines without the LLM (only a
free-text date goes through normalize_date_text) and hands the raw fields to the
same resolver/confirmation/payload-building code the free-text flow uses, so
anything missing or ambiguous falls into the usual one-question-at-a-time flow.

The LLM never sees or produces database IDs — it only extracts free-text
fields (a client name, a property address fragment, an inspector's name).
telegram_integration.py resolves those against real rows afterwards, so a
misheard or fuzzy phrase can never become a wrong foreign key on its own.
"""
from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import anthropic

_MODEL = 'claude-haiku-4-5'  # fast/cheap tier — bounded structured extraction, not open-ended reasoning

_TOOLS = [
    {
        'name': 'create_property',
        'description': 'Create a new property/rental unit under an existing client.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'address':       {'type': 'string', 'description': 'Full or partial property address'},
                'client_name':   {'type': 'string', 'description': "The letting agent / landlord this property belongs to"},
                'property_type': {'type': 'string', 'description': "e.g. 'residential', 'commercial'"},
                'bedrooms':      {'type': 'integer'},
                'bathrooms':     {'type': 'integer'},
                'furnished':     {'type': 'string', 'description': "'Furnished', 'Part Furnished', or 'Unfurnished'"},
                'parking':       {'type': 'boolean', 'description': 'True/false only if parking is explicitly mentioned'},
                'garden':        {'type': 'boolean', 'description': 'True/false only if a garden is explicitly mentioned'},
                'elevator':      {'type': 'boolean', 'description': 'True/false only if a lift/elevator is explicitly mentioned'},
                'detachment_type': {'type': 'string', 'description': "e.g. 'Terraced', 'Semi-Detached', 'Detached', 'Purpose Built Flat', 'Converted Flat', 'Bungalow', 'Penthouse', if mentioned"},
                'elevation':     {'type': 'string', 'description': "Floor, e.g. 'Ground Floor', '1st Floor', if mentioned"},
                'meter_electricity': {'type': 'string', 'description': 'Electricity meter location/reading, if mentioned'},
                'meter_gas':         {'type': 'string', 'description': 'Gas meter location/reading, if mentioned'},
                'meter_heat':        {'type': 'string', 'description': 'Heat meter location/reading, if mentioned'},
                'meter_water':       {'type': 'string', 'description': 'Water meter location/reading, if mentioned'},
                'notes':         {'type': 'string'},
            },
            'required': ['address', 'client_name'],
        },
    },
    {
        'name': 'book_inspection',
        'description': 'Book/create a new inspection for an existing property.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'property_address_fragment': {'type': 'string', 'description': 'Any part of the property address to look it up by'},
                'inspection_type': {
                    'type': 'string',
                    'enum': ['check_in', 'check_out', 'midterm', 'damage_report', 'heads_up'],
                    'description': "Defaults to 'check_in' if not mentioned",
                },
                'conduct_date': {
                    'type': 'string',
                    'description': "The inspection date normalized to ISO YYYY-MM-DD, resolved against the 'today' fact in the system prompt",
                },
                'conduct_time_preference': {'type': 'string', 'description': "Time as the user said it, e.g. 'AM', 'PM', 'afternoon', '2:30pm', 'anytime'"},
                'inspector_name': {
                    'type': 'string',
                    'description': (
                        'Name of the field inspector/clerk to assign, if mentioned — including '
                        'when given as "clerk <name>" or "inspector <name>", e.g. "Clerk Robyn" '
                        'means Robyn.'
                    ),
                },
                'tenant_email':   {'type': 'string'},
                'reference_number': {'type': 'string', 'description': 'A reference number/code for the inspection, if explicitly given, e.g. "reference number 13939" or "ref INS-4"'},
                'continue_from_previous': {
                    'type': 'boolean',
                    'description': (
                        'Only set this when the user is directly answering a yes/no question about '
                        "whether to continue this report from a previous inspection's report."
                    ),
                },
                'include_photos': {
                    'type': 'boolean',
                    'description': (
                        'Only set this when the user is directly answering a yes/no question about '
                        'including photos from a previous inspection.'
                    ),
                },
            },
            'required': ['property_address_fragment', 'conduct_date'],
        },
    },
    {
        'name': 'update_inspection',
        'description': "Change the date, time, assigned inspector, or tenant email of an existing inspection that hasn't been completed yet — e.g. a client rescheduling.",
        'input_schema': {
            'type': 'object',
            'properties': {
                'property_address_fragment':   {'type': 'string', 'description': 'Any part of the address the inspection being changed is for'},
                'new_conduct_date':            {'type': 'string', 'description': 'New ISO YYYY-MM-DD date, only if the date is changing'},
                'new_conduct_time_preference': {'type': 'string', 'description': "New time, only if it's changing"},
                'new_inspector_name':          {'type': 'string', 'description': "New inspector's name, only if reassigning"},
                'new_tenant_email':            {'type': 'string', 'description': 'New tenant email, only if changing'},
            },
            'required': ['property_address_fragment'],
        },
    },
    {
        'name': 'share_report',
        'description': "Email a completed inspection's PDF report to the client, the tenant, or another address.",
        'input_schema': {
            'type': 'object',
            'properties': {
                'property_address_fragment': {'type': 'string', 'description': 'Any part of the address of the completed report to share'},
                'recipients': {
                    'type': 'string',
                    'description': 'Who to send it to, if mentioned — "client", "tenant", "client and tenant", or an email address / comma-separated addresses',
                },
                'notes': {'type': 'string', 'description': 'A short note to include in the email, if mentioned'},
            },
            'required': ['property_address_fragment'],
        },
    },
    {
        'name': 'mark_invoice_paid',
        'description': (
            "Mark one or more inspections' invoices as paid. Each inspection can be "
            'identified by its reference number (e.g. "INS-101"), its property address, '
            'or both — optionally with a date to narrow down which inspection at that '
            'property. Supports several at once, e.g. "mark INS-101, INS-102 and 12 Smith '
            'St as paid".'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'items': {
                    'type': 'array',
                    'description': 'One entry per inspection to mark as paid',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'reference_number':          {'type': 'string', 'description': 'e.g. "INS-101", if mentioned'},
                            'property_address_fragment': {'type': 'string', 'description': 'Any part of the property address, if mentioned'},
                            'date': {'type': 'string', 'description': 'ISO YYYY-MM-DD, only if a date is mentioned to help tell apart multiple inspections at the same property'},
                        },
                        'required': [],
                    },
                },
            },
            'required': ['items'],
        },
    },
    {
        'name': 'query_schedule',
        'description': (
            "Answer a read-only question about what's scheduled or happening — a day's "
            "agenda, a specific property's inspection/report status, what a named inspector "
            "has on, or which inspections have no inspector assigned yet. Never changes "
            "anything."
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'date': {
                    'type': 'string',
                    'description': (
                        "Start date normalized to ISO YYYY-MM-DD, resolved against the "
                        "'today' fact in the system prompt. Leave unset if the question is "
                        "only about a property with no date mentioned."
                    ),
                },
                'date_range_end': {
                    'type': 'string',
                    'description': (
                        "End date (inclusive), ISO YYYY-MM-DD, only when the question spans "
                        "a range — e.g. 'this week' means the coming Monday to Sunday. Leave "
                        "unset for a single day or no date."
                    ),
                },
                'property_address_fragment': {'type': 'string', 'description': 'Any part of a property address, if the question is about a specific property'},
                'inspector_name': {'type': 'string', 'description': "A field inspector's name, if the question is about what a specific person has on"},
                'unassigned_only': {'type': 'boolean', 'description': 'True only for questions specifically about inspections with no inspector assigned yet'},
            },
            'required': [],
        },
    },
    {
        'name': 'query_inspection',
        'description': (
            "Look up the full details of a specific inspection, identified by its reference "
            "number (e.g. \"INS-150\") and/or a property address, optionally narrowed by "
            "inspection type or date — e.g. \"what inspection is INS-150?\" or \"when is 123 "
            "Test Property check in?\". Prefer this over query_schedule whenever the question "
            "is about one particular inspection rather than a day's agenda. Never changes anything."
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'reference_number': {'type': 'string', 'description': 'e.g. "INS-150", if mentioned'},
                'property_address_fragment': {'type': 'string', 'description': 'Any part of the property address, if mentioned'},
                'inspection_type': {
                    'type': 'string',
                    'enum': ['check_in', 'check_out', 'midterm', 'damage_report', 'heads_up'],
                    'description': 'Only if a type is mentioned, e.g. "check in", "check out"',
                },
                'date': {'type': 'string', 'description': 'ISO YYYY-MM-DD, only if a specific date is mentioned'},
            },
            'required': [],
        },
    },
    {
        'name': 'query_availability',
        'description': "Answer a read-only question about which field inspectors are free or busy on a given day, e.g. \"who's free tomorrow?\". Never changes anything.",
        'input_schema': {
            'type': 'object',
            'properties': {
                'date': {
                    'type': 'string',
                    'description': "Date normalized to ISO YYYY-MM-DD, resolved against the 'today' fact in the system prompt. Defaults to today if not mentioned.",
                },
            },
            'required': [],
        },
    },
]

_DATE_TOOL = [{
    'name': 'normalize_date',
    'description': 'Extract a single date from free text, normalized to ISO YYYY-MM-DD.',
    'input_schema': {
        'type': 'object',
        'properties': {'date_iso': {'type': 'string', 'description': 'ISO YYYY-MM-DD'}},
        'required': ['date_iso'],
    },
}]


def _system_prompt() -> str:
    today = datetime.now(timezone.utc).astimezone().strftime('%A %d %B %Y')
    return (
        f"Today is {today}. You help staff at a UK property inspection company book "
        "inspections, create properties, reschedule or update existing inspections, share "
        "completed reports, and mark invoices paid by extracting structured data from "
        "free-text chat messages. Normalize relative dates (\"Thursday\", \"next week\") to ISO "
        "YYYY-MM-DD using today's date above. Use update_inspection whenever the message "
        "describes changing something about an inspection that likely already exists "
        "(moving a date, reassigning an inspector, changing a tenant email) rather than "
        "creating a new one. Use share_report when the message is about sending, emailing, "
        "or sharing a finished report. Use mark_invoice_paid when the message says an "
        "invoice has been paid, settled, or received — it accepts several inspections at "
        "once, identified by reference number and/or property address. Use query_inspection "
        "when asked about one specific inspection's details — by reference number (\"what is "
        "INS-150?\") or by property and type (\"when is 123 Test Property check in?\"). Use "
        "query_schedule for read-only questions about "
        "what's scheduled, happening, or done — a day's agenda, a property's status, an "
        "inspector's workload, or unassigned inspections — and query_availability only "
        "when asked who is free/available/busy on a given day. When a date range like "
        "\"this week\" is meant, expand it to the Monday–Sunday of that week using today's "
        "date above. Messages often pack several facts into short trailing sentences (e.g. "
        "\"...next Wednesday. Reference number 13939. Clerk Robyn\") — extract every field "
        "mentioned anywhere in the message, not just the first clause. If the message doesn't "
        "relate to any of these, do not call any tool — just reply naturally, briefly "
        "explaining what you can help with."
    )


class ParsedIntent:
    def __init__(self, tool_name=None, args=None, reply_text=None):
        self.tool_name = tool_name
        self.args = args or {}
        self.reply_text = reply_text  # set only when the model didn't call a tool


_REFERENCE_RE = re.compile(r'\bref(?:erence)?(?:\s*(?:number|no\.?|num|#))?\s*[:#=\-]?\s*([A-Za-z0-9\-_/]*\d[A-Za-z0-9\-_/]*)', re.I)


def _context_prompt(context: dict) -> str:
    question = context.get('question')
    collected = json.dumps(context.get('collected') or {}, default=str)
    if question:
        lead = f'You just asked the user: "{question}" and their message is the reply. '
    else:
        lead = 'The user is reviewing a summary of what you are about to do, and their message is a correction. '
    return (
        '\n\nYou are partway through a conversation, not starting a new one. ' + lead +
        f'Fields collected so far: {collected}. Extract ONLY what this message provides and '
        'leave every other field unset. Never repeat, guess, or change a collected value unless '
        'the user explicitly corrects it. A short reply such as a bare name, number or address '
        'fragment answers the question you just asked — put it in the matching field.'
    )


def parse_message(text: str, *, forced_tool: str | None = None, context: dict | None = None) -> ParsedIntent:
    """Run one Anthropic call to extract a tool call (or a plain reply) from `text`.

    forced_tool: when a slot-filling flow is already in progress, force the
    model to keep extracting args for that same tool rather than risking a
    fresh/ambiguous classification on a short follow-up reply like "2pm".

    context: {'question': str|None, 'collected': dict} for that same in-progress
    flow. Without it the model sees a bare "Acme" with no idea what was asked and,
    because the forced tool has required fields, invents or overwrites values to
    satisfy them. With it, required-ness is dropped and the model is told what
    was asked and what is already known.
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    tool_choice = {'type': 'tool', 'name': forced_tool} if forced_tool else {'type': 'auto'}

    tools = _TOOLS
    system = _system_prompt()
    if context is not None:
        tools = copy.deepcopy(_TOOLS)
        for t in tools:
            t['input_schema']['required'] = []
        system += _context_prompt(context)

    message = client.messages.create(
        model=_MODEL,
        max_tokens=1000,
        system=system,
        tools=tools,
        tool_choice=tool_choice,
        messages=[{'role': 'user', 'content': text}],
    )

    for block in message.content:
        if block.type == 'tool_use':
            args = dict(block.input)
            if block.name == 'book_inspection' and not args.get('reference_number'):
                # Don't rely on the model alone to pick a reference out of a busy message.
                m = _REFERENCE_RE.search(text)
                if m:
                    args['reference_number'] = m.group(1)
            return ParsedIntent(tool_name=block.name, args=args)

    reply_text = ''.join(b.text for b in message.content if b.type == 'text').strip()
    return ParsedIntent(reply_text=reply_text or (
        "I can create a property, book an inspection, reschedule/update one, share a "
        "report, mark invoices paid, or answer schedule/status questions — tell me what "
        "you need, or try /property or /inspection for a fill-in template."
    ))


def normalize_date_text(text: str) -> str | None:
    """One-off helper for a template's free-text date, where the reply is nothing but a date
    phrase — a forced call on the full book_inspection/update_inspection tools would also
    force the model to guess unrelated required fields from that same short phrase."""
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    message = client.messages.create(
        model=_MODEL,
        max_tokens=200,
        system=_system_prompt(),
        tools=_DATE_TOOL,
        tool_choice={'type': 'tool', 'name': 'normalize_date'},
        messages=[{'role': 'user', 'content': text}],
    )
    for block in message.content:
        if block.type == 'tool_use':
            return block.input.get('date_iso')
    return None


_UK_POSTCODE_RE = re.compile(r'\b[A-Z]{1,2}[0-9][0-9A-Z]?\s*[0-9][A-Z]{2}\b', re.I)


def _confirm_address(raw: dict, address: str):
    """A new property's address should be a full one. If it has no postcode, look it up
    and let the user pick a match (or keep what they typed) before going further.
    Returns (address, question). Works on `raw` in place — the caller persists it, so
    the option list is fetched once and a numeric reply lands in raw['_address_pick']."""
    if raw.get('_address_confirmed') or _UK_POSTCODE_RE.search(address):
        return address, None

    options = raw.get('_address_options')
    if options is None:
        try:
            from routes.address_lookup import search_suggestions
            options = [s['address'] for s in search_suggestions(address)[:5]]
        except Exception as e:
            print(f'[telegram] address lookup failed: {e}')
            options = []
        raw['_address_options'] = options
        if not options:  # nothing to offer, so don't block on it
            raw['_address_confirmed'] = True
            return address, None

    pick = raw.pop('_address_pick', None)
    if pick is not None:
        try:
            idx = int(pick) - 1
            if idx < 0:
                raise IndexError
            raw['address'] = options[idx]
        except (ValueError, IndexError):
            return address, f"That's not one of the options — reply with a number from 1 to {len(options)}, or \"keep\" to use it as typed."
        raw['_address_confirmed'] = True
        return raw['address'], None

    lines = [f'"{address}" doesn\'t look like a full address. Did you mean:']
    lines += [f'{i}. {a}' for i, a in enumerate(options, 1)]
    lines.append('Reply with a number, or "keep" to use it as typed.')
    return address, '\n'.join(lines)


def _find_property_matches(frag: str):
    """(properties, fuzzy). Substring match first; if that finds nothing, fall back to
    matching every word independently, so "123 Test Property" still finds
    "123, Test Property Road" (punctuation/ordering differences)."""
    from models import Property
    from sqlalchemy import and_
    exact = Property.query.filter(Property.address.ilike(f'%{frag}%')).limit(6).all()
    if exact:
        return exact, False
    tokens = [t for t in re.split(r'\W+', frag) if t]
    if not tokens:
        return [], False
    loose = Property.query.filter(and_(*[Property.address.ilike(f'%{t}%') for t in tokens])).limit(6).all()
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


def resolve_create_property(raw: dict):
    """Returns (resolved: dict|None, question: str|None).
    `resolved` is None whenever something's still missing or ambiguous, in
    which case `question` is what to ask the user next."""
    address = (raw.get('address') or '').strip()
    if not address:
        return None, "What's the property address?"
    address, question = _confirm_address(raw, address)
    if question:
        return None, question

    client_name = (raw.get('client_name') or '').strip()
    if not client_name:
        return None, 'Which client/agent is this property for?'

    from models import Client
    matches = Client.query.filter(Client.name.ilike(f'%{client_name}%')).limit(6).all()
    if len(matches) == 0:
        return None, f'I couldn\'t find a client matching "{client_name}" — what\'s the exact client name?'
    if len(matches) > 1:
        names = ', '.join(f'"{c.name}"' for c in matches)
        return None, f'I found more than one client matching "{client_name}": {names}. Which one did you mean?'

    # Bedrooms/bathrooms are required for every property, same as address and
    # client — a studio flat is 0 bedrooms, so check for None, not falsiness.
    bedrooms = raw.get('bedrooms')
    if bedrooms is None:
        return None, 'How many bedrooms?'

    bathrooms = raw.get('bathrooms')
    if bathrooms is None:
        return None, 'How many bathrooms?'

    client = matches[0]
    resolved = {
        'address':           address,
        'client_id':         client.id,
        'client_name':       client.name,
        'property_type':     raw.get('property_type') or 'residential',
        'bedrooms':          bedrooms,
        'bathrooms':         bathrooms,
        'furnished':         raw.get('furnished'),
        'parking':           raw.get('parking'),
        'garden':            raw.get('garden'),
        'elevator':          raw.get('elevator'),
        'detachment_type':   raw.get('detachment_type'),
        'elevation':         raw.get('elevation'),
        'meter_electricity': raw.get('meter_electricity'),
        'meter_gas':         raw.get('meter_gas'),
        'meter_heat':        raw.get('meter_heat'),
        'meter_water':       raw.get('meter_water'),
        'notes':             raw.get('notes'),
    }
    return resolved, None


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


def resolve_book_inspection(raw: dict):
    frag = (raw.get('property_address_fragment') or '').strip()
    if not frag:
        return None, 'Which property is this for? (give me the address or part of it)'

    prop, question = _resolve_property(raw, frag)
    if question:
        return None, question

    date_str = (raw.get('conduct_date') or '').strip()
    if not date_str:
        return None, 'What date should the inspection be? (e.g. "Thursday", or "2026-09-25")'
    try:
        conduct_dt = datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None, f'I couldn\'t understand the date "{date_str}" — what date should the inspection be?'
    if conduct_dt.date() < datetime.now(timezone.utc).date():
        return None, f'That date ({conduct_dt.date().isoformat()}) is in the past — what date did you mean?'

    # A clerk must be assigned, same as the webapp's "Please assign a clerk"
    # requirement on this form — Telegram must not create unassigned
    # inspections just because the field was optional to extract.
    inspector_name = (raw.get('inspector_name') or '').strip()
    if not inspector_name:
        return None, 'Who should this be assigned to? (give me the inspector\'s name)'

    from models import User
    insp_matches = User.query.filter(User.role == 'clerk', User.name.ilike(f'%{inspector_name}%')).limit(6).all()
    if len(insp_matches) == 1:
        inspector_id = insp_matches[0].id
        inspector_name_display = insp_matches[0].name
    elif len(insp_matches) > 1:
        names = ', '.join(i.name for i in insp_matches)
        return None, f'I found more than one inspector matching "{inspector_name}": {names}. Which one did you mean?'
    else:
        return None, f'I couldn\'t find an inspector named "{inspector_name}" — who should this be assigned to?'

    time_pref = None
    raw_time = (raw.get('conduct_time_preference') or '').strip()
    if raw_time:
        time_pref = normalize_time_preference(raw_time)
        if not time_pref:
            raw.pop('conduct_time_preference', None)
            return None, f'I didn\'t understand the time "{raw_time}" — say AM, PM, anytime, or a specific time like 2:30pm.'

    # ── Lifecycle continuation (check_in <-> check_out) ───────────────────
    # Standalone types (midterm/damage_report/heads_up) are never offered
    # this — they're not part of the check_in -> check_out lifecycle.
    inspection_type = raw.get('inspection_type') or 'check_in'
    inspection_type = normalize_inspection_type(inspection_type) or inspection_type
    if inspection_type not in INSPECTION_TYPES:
        raw.pop('inspection_type', None)
        return None, (f'I don\'t recognise the inspection type "{inspection_type}" — is it a check-in, '
                      'check-out, midterm, damage report or heads-up?')
    source_inspection_id = None
    source_label = None
    include_photos = False
    if inspection_type in ('check_in', 'check_out'):
        source = _find_lifecycle_source(prop, inspection_type)
        if source:
            continue_from_previous = raw.get('continue_from_previous')
            date_label = source.conduct_date.strftime('%a %d %b %Y') if source.conduct_date else 'no date on record'
            source_label = f"{source.inspection_type.replace('_', ' ').title()} on {date_label}"
            if continue_from_previous is None:
                return None, f'Continue this report from the {source_label}? (yes/no)'
            if continue_from_previous:
                source_inspection_id = source.id
                include_photos = raw.get('include_photos')
                if include_photos is None:
                    return None, 'Include photos from that inspection? (yes/no)'

    resolved = {
        'property_id':             prop.id,
        'property_address':        prop.address,
        'inspection_type':         inspection_type,
        'conduct_date':            conduct_dt.isoformat(),
        'conduct_time_preference': time_pref,
        'inspector_id':            inspector_id,
        'inspector_name':          inspector_name_display,
        'tenant_email':            raw.get('tenant_email'),
        'reference_number':        (raw.get('reference_number') or '').strip() or None,
        'source_inspection_id':    source_inspection_id,
        'source_label':            source_label if source_inspection_id else None,
        'include_photos':          bool(include_photos),
    }
    return resolved, None


def resolve_update_inspection(raw: dict):
    """Find the inspection being changed and validate the requested change(s).

    Unlike the create resolvers, this one can also need a *pick*: when a
    property has more than one upcoming inspection, the caller stashes the
    user's numeric reply under raw['_pick'] (1-based) rather than re-running
    the LLM parser on a bare digit."""
    frag = (raw.get('property_address_fragment') or '').strip()
    if not frag:
        return None, "Which property's inspection do you want to change? (give me the address)"

    change_fields = ('new_conduct_date', 'new_conduct_time_preference', 'new_inspector_name', 'new_tenant_email')
    if not any((raw.get(f) or '').strip() for f in change_fields):
        return None, 'What would you like to change — the date, time, inspector, or tenant email?'

    prop, question = _resolve_property(raw, frag)
    if question:
        return None, question

    from models import Inspection
    candidates = (
        Inspection.query
        .filter(Inspection.property_id == prop.id, Inspection.status != 'complete', Inspection.pdf_import.is_(False))
        .order_by(Inspection.conduct_date.asc())
        .all()
    )
    if not candidates:
        return None, f'I couldn\'t find any upcoming inspection at "{prop.address}" to change.'

    pick = raw.get('_pick')
    if pick is not None:
        try:
            target = candidates[int(pick) - 1]
        except (ValueError, IndexError):
            return None, f'That\'s not one of the options — reply with a number from 1 to {len(candidates)}.'
    elif len(candidates) == 1:
        target = candidates[0]
    else:
        lines = [f'I found {len(candidates)} upcoming inspections at "{prop.address}" — which one?']
        for i, insp in enumerate(candidates, 1):
            date_label = insp.conduct_date.strftime('%a %d %b %Y') if insp.conduct_date else 'no date set'
            lines.append(f'{i}. {insp.inspection_type.replace("_", " ").title()} — {date_label}')
        lines.append('Reply with the number.')
        return None, '\n'.join(lines)

    new_inspector_id = None
    new_inspector_name_display = None
    new_inspector_name = (raw.get('new_inspector_name') or '').strip()
    if new_inspector_name:
        from models import User
        insp_matches = User.query.filter(User.role == 'clerk', User.name.ilike(f'%{new_inspector_name}%')).limit(6).all()
        if len(insp_matches) == 1:
            new_inspector_id = insp_matches[0].id
            new_inspector_name_display = insp_matches[0].name
        elif len(insp_matches) > 1:
            names = ', '.join(i.name for i in insp_matches)
            return None, f'I found more than one inspector matching "{new_inspector_name}": {names}. Which one did you mean?'
        else:
            return None, f'I couldn\'t find an inspector named "{new_inspector_name}" — who should this be reassigned to?'

    new_date_str = (raw.get('new_conduct_date') or '').strip()
    new_date_iso = None
    if new_date_str:
        try:
            new_date_iso = datetime.fromisoformat(new_date_str).isoformat()
        except (ValueError, TypeError):
            return None, f'I couldn\'t understand the date "{new_date_str}" — what date should it be changed to?'

    new_time_pref = None
    raw_time = (raw.get('new_conduct_time_preference') or '').strip()
    if raw_time:
        new_time_pref = normalize_time_preference(raw_time)
        if not new_time_pref:
            raw.pop('new_conduct_time_preference', None)
            return None, f'I didn\'t understand the time "{raw_time}" — say AM, PM, anytime, or a specific time like 2:30pm.'

    resolved = {
        'inspection_id':      target.id,
        'property_address':   prop.address,
        'inspection_type':    target.inspection_type,
        'old_conduct_date':   target.conduct_date.isoformat() if target.conduct_date else None,
        'old_time':           target.conduct_time_preference,
        'old_inspector_name': target.inspector.name if target.inspector else None,
        'new_conduct_date':            new_date_iso,
        'new_conduct_time_preference': new_time_pref,
        'new_inspector_id':            new_inspector_id,
        'new_inspector_name':          new_inspector_name_display,
        'new_tenant_email':            raw.get('new_tenant_email') or None,
    }
    return resolved, None


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


RESOLVERS = {
    'create_property':   resolve_create_property,
    'book_inspection':   resolve_book_inspection,
    'update_inspection': resolve_update_inspection,
    'share_report':      resolve_share_report,
    'mark_invoice_paid': resolve_mark_invoice_paid,
}


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
    lines.append('Reply YES to confirm, or tell me what to change.')
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
    if resolved.get('reference_number'):
        lines.append(f"• Reference: {resolved['reference_number']}")
    if resolved.get('source_inspection_id'):
        lines.append(f"• Continuing from: {resolved['source_label']}")
        lines.append(f"• Include photos: {'Yes' if resolved.get('include_photos') else 'No'}")
    lines.append('Reply YES to confirm, or tell me what to change.')
    return '\n'.join(lines)


def summarize_update_inspection(resolved: dict) -> str:
    lines = [f"Update this inspection at {resolved['property_address']} ({resolved['inspection_type'].replace('_', ' ').title()})?"]
    if resolved.get('old_conduct_date'):
        old_dt = datetime.fromisoformat(resolved['old_conduct_date'])
        current = f"• Currently: {old_dt.strftime('%a %d %b %Y')}"
        if resolved.get('old_time'):
            current += f" — {format_time_preference(resolved['old_time'])}"
        lines.append(current)
    if resolved.get('new_conduct_date'):
        new_dt = datetime.fromisoformat(resolved['new_conduct_date'])
        lines.append(f"• New date: {new_dt.strftime('%a %d %b %Y')}")
    if resolved.get('new_conduct_time_preference'):
        lines.append(f"• New time: {format_time_preference(resolved['new_conduct_time_preference'])}")
    if resolved.get('new_inspector_name'):
        lines.append(f"• New inspector: {resolved['new_inspector_name']} (was {resolved.get('old_inspector_name') or 'unassigned'})")
    if resolved.get('new_tenant_email'):
        lines.append(f"• New tenant email: {resolved['new_tenant_email']}")
    lines.append('Reply YES to confirm, or tell me what to change.')
    return '\n'.join(lines)


def summarize_share_report(resolved: dict) -> str:
    lines = [
        'Share this report?',
        f"• Property: {resolved['property_address']} ({resolved['inspection_type'].replace('_', ' ').title()})",
        f"• Send to: {', '.join(resolved['emails'])}",
    ]
    if resolved.get('notes'):
        lines.append(f"• Note: {resolved['notes']}")
    lines.append('Reply YES to confirm, or tell me what to change.')
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
    lines.append('Reply YES to confirm, or tell me what to change.')
    return '\n'.join(lines)


SUMMARIZERS = {
    'create_property':   summarize_property,
    'book_inspection':   summarize_inspection,
    'update_inspection': summarize_update_inspection,
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
        'source_inspection_id':    resolved.get('source_inspection_id'),
        'include_photos':          resolved.get('include_photos', False),
    }


def build_update_inspection_payload(resolved: dict) -> dict:
    """PATCH-style — only include fields actually being changed; the PUT
    endpoint only touches keys present in the payload."""
    payload = {}
    if resolved.get('new_conduct_date'):
        payload['conduct_date'] = resolved['new_conduct_date']
    if resolved.get('new_conduct_time_preference'):
        payload['conduct_time_preference'] = resolved['new_conduct_time_preference']
    if resolved.get('new_inspector_id'):
        payload['inspector_id'] = resolved['new_inspector_id']
    if resolved.get('new_tenant_email'):
        payload['tenant_email'] = resolved['new_tenant_email']
    return payload


def build_share_report_payload(resolved: dict) -> dict:
    payload = {'emails': resolved['emails']}
    if resolved.get('notes'):
        payload['notes'] = resolved['notes']
    return payload


BUILD_PAYLOAD = {
    'create_property':   build_property_payload,
    'book_inspection':   build_inspection_payload,
    'update_inspection': build_update_inspection_payload,
    'share_report':       build_share_report_payload,
}

# Each entry describes the internal HTTP call _execute_pending_action makes to
# apply a confirmed action — method + a path builder (update/share need the
# target inspection's id, resolved earlier by the corresponding resolver).
# mark_invoice_paid is NOT here — see MULTI_TARGET_TOOLS below, it needs one
# HTTP call per resolved item rather than a single method+path.
ACTION_CONFIG = {
    'create_property':   {'method': 'POST', 'path': lambda resolved: '/api/properties'},
    'book_inspection':   {'method': 'POST', 'path': lambda resolved: '/api/inspections'},
    'update_inspection': {'method': 'PUT',  'path': lambda resolved: f"/api/inspections/{resolved['inspection_id']}"},
    'share_report':       {'method': 'POST', 'path': lambda resolved: f"/api/inspections/{resolved['inspection_id']}/share-pdf"},
}

# Tools whose confirmed action means N separate writes (one per resolved item)
# rather than the single HTTP call ACTION_CONFIG describes. telegram_integration.py's
# _execute_pending_action branches on this before touching ACTION_CONFIG/BUILD_PAYLOAD.
MULTI_TARGET_TOOLS = {'mark_invoice_paid'}


# ── Read-only schedule/status queries ───────────────────────────────────────
# No resolve->confirm->write split here — these never change anything, so
# each ANSWERERS function runs its query and returns the reply text directly.

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


def _resolve_property_by_fragment(frag: str):
    """Read-only lookups can't ask a follow-up, so a single match — exact or loose — is
    used, and several are listed."""
    matches, _ = _find_property_matches(frag)
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        addrs = '; '.join(f'"{p.address}"' for p in matches)
        return None, f'I found more than one property matching "{frag}": {addrs}. Could you be more specific?'
    return None, f'I couldn\'t find a property matching "{frag}".'


def _resolve_inspector_by_name(name: str):
    from models import User
    matches = User.query.filter(User.role == 'clerk', User.name.ilike(f'%{name}%')).limit(6).all()
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        names = ', '.join(u.name for u in matches)
        return None, f'I found more than one inspector matching "{name}": {names}. Could you be more specific?'
    return None, f'I couldn\'t find an inspector named "{name}".'


def _resolve_query_range(raw: dict):
    """Returns (start: date|None, end: date|None, label: str|None, error: str|None).
    (None, None, None, None) means "no date filter" — only reachable when a property
    fragment was given and neither date field was extracted, so a pure status lookup
    like "is 12 Smith St's report done?" isn't silently narrowed to today."""
    date_str = (raw.get('date') or '').strip()
    end_str = (raw.get('date_range_end') or '').strip()
    has_property = bool((raw.get('property_address_fragment') or '').strip())

    if not date_str and not end_str:
        if has_property:
            return None, None, None, None
        today = _today_london()
        return today, today, 'today', None

    try:
        start = datetime.fromisoformat(date_str).date() if date_str else _today_london()
    except (ValueError, TypeError):
        return None, None, None, f'I couldn\'t understand the date "{date_str}".'

    end = start
    if end_str:
        try:
            end = datetime.fromisoformat(end_str).date()
        except (ValueError, TypeError):
            return None, None, None, f'I couldn\'t understand the date "{end_str}".'
    if end < start:
        start, end = end, start

    label = 'today' if start == end == _today_london() else (
        start.strftime('%a %d %b %Y') if start == end
        else f"{start.strftime('%a %d %b')} – {end.strftime('%a %d %b %Y')}"
    )
    return start, end, label, None


def _format_schedule_rows(rows, by_date: bool) -> str:
    """Agenda grouped by inspector, saying each thing once: the inspector's name, then
    "address - AM/PM/time" and the client per job. A date heading is added only when
    the answer spans several days."""
    days = {}
    for insp in rows:
        days.setdefault(insp.conduct_date.date() if insp.conduct_date else None, []).append(insp)

    blocks = []
    for day, day_rows in sorted(days.items(), key=lambda kv: (kv[0] is None, kv[0])):
        by_inspector = {}
        for insp in sorted(day_rows, key=lambda i: _time_sort_key(i.conduct_time_preference)):
            by_inspector.setdefault(insp.inspector.name if insp.inspector else 'Unassigned', []).append(insp)
        for name in sorted(by_inspector, key=lambda n: (n == 'Unassigned', n.lower())):
            lines = [name]
            for insp in by_inspector[name]:
                addr = insp.property.address if insp.property else 'Unknown property'
                time_label = format_time_preference(insp.conduct_time_preference)
                lines.append(addr if time_label == 'Anytime' else f'{addr} - {time_label}')
                client = insp.property.client.name if insp.property and insp.property.client else None
                if client:
                    lines.append(client)
            blocks.append('\n'.join(lines))
        if by_date:
            heading = day.strftime('%a %d %b') if day else 'No date'
            blocks[-len(by_inspector)] = heading + '\n' + blocks[-len(by_inspector)]
    return '\n\n'.join(blocks)


def _format_property_rows(rows) -> str:
    """Status view for a single property: the address is already known from the
    question, so each inspection is just date/type/time and who has it, and its status."""
    blocks = []
    for insp in rows:
        date_label = insp.conduct_date.strftime('%a %d %b') if insp.conduct_date else 'No date'
        kind = insp.inspection_type.replace('_', ' ').title()
        time_label = format_time_preference(insp.conduct_time_preference)
        head = f'{date_label} - {kind}' + ('' if time_label == 'Anytime' else f' - {time_label}')
        who = insp.inspector.name if insp.inspector else 'Unassigned'
        status = (insp.status or 'unknown').replace('_', ' ').title()
        blocks.append(f'{head}\n{who} - {status}')
    return '\n\n'.join(blocks)


def answer_query_schedule(raw: dict, user) -> str:
    from sqlalchemy.orm import selectinload
    from models import Inspection, Property
    from permissions import filter_inspections_for_user

    frag = (raw.get('property_address_fragment') or '').strip()
    inspector_name = (raw.get('inspector_name') or '').strip()
    unassigned_only = bool(raw.get('unassigned_only'))

    prop = inspector = None
    if frag:
        prop, err = _resolve_property_by_fragment(frag)
        if err:
            return err
    if inspector_name:
        inspector, err = _resolve_inspector_by_name(inspector_name)
        if err:
            return err

    start, end, label, err = _resolve_query_range(raw)
    if err:
        return err

    # filter_inspections_for_user already applies the same role-scoping the
    # webapp uses (admin/manager: everything; clerk: own assigned jobs;
    # typist: own processing jobs; client: own properties) — no new
    # permission logic needed here.
    query = filter_inspections_for_user(Inspection.query, user)
    query = query.filter(Inspection.pdf_import.is_(False))  # backdated paper imports aren't "scheduled" work
    if start is not None:
        range_start, _ = _day_bounds(start)
        _, range_end = _day_bounds(end)
        query = query.filter(Inspection.conduct_date >= range_start, Inspection.conduct_date < range_end)
    if prop is not None:
        query = query.filter(Inspection.property_id == prop.id)
    if inspector is not None:
        query = query.filter(Inspection.inspector_id == inspector.id)
    if unassigned_only:
        query = query.filter(Inspection.inspector_id.is_(None))

    # Property-only, no date ("is 12 Smith St's report done?") — most recent
    # first, small cap, since the useful answer is the latest status, not
    # the full history.
    no_date_property_lookup = (start is None and prop is not None)
    query = query.options(selectinload(Inspection.property).selectinload(Property.client), selectinload(Inspection.inspector))
    query = query.order_by(Inspection.conduct_date.desc() if no_date_property_lookup else Inspection.conduct_date.asc())

    cap = 8 if no_date_property_lookup else 25
    rows = query.limit(cap + 1).all()
    if not rows:
        if prop is not None:
            return f'No inspections found at "{prop.address}"' + (f' for {label}.' if label else '.')
        if unassigned_only:
            return 'No unassigned inspections' + (f' for {label}.' if label else '.')
        if inspector is not None:
            return f'{inspector.name} has nothing scheduled' + (f' for {label}.' if label else '.')
        return 'Nothing scheduled' + (f' for {label}.' if label else '.')

    truncated = len(rows) > cap
    rows = rows[:cap]

    if prop is not None:
        text = _format_property_rows(rows)
    else:
        text = _format_schedule_rows(rows, by_date=(start is None or start != end))
    if truncated:
        text += '\n\n…and more — narrow it down by date, property, or inspector for the full list.'
    return text


def answer_query_availability(raw: dict, user) -> str:
    from permissions import is_admin_or_manager
    if not is_admin_or_manager(user):
        return "You don't have permission to do that — availability is visible to managers only."

    from sqlalchemy.orm import selectinload
    from models import Inspection, User

    date_str = (raw.get('date') or '').strip()
    try:
        d = datetime.fromisoformat(date_str).date() if date_str else _today_london()
    except (ValueError, TypeError):
        return f'I couldn\'t understand the date "{date_str}".'
    label = 'today' if d == _today_london() else d.strftime('%a %d %b %Y')
    range_start, range_end = _day_bounds(d)

    roster = User.query.filter(User.role == 'clerk').order_by(User.name.asc()).all()
    if not roster:
        return 'No field inspectors are set up yet.'

    busy_rows = (
        Inspection.query
        .filter(
            Inspection.conduct_date >= range_start,
            Inspection.conduct_date < range_end,
            Inspection.inspector_id.isnot(None),
            Inspection.pdf_import.is_(False),
        )
        .options(selectinload(Inspection.property))
        .order_by(Inspection.conduct_date.asc())
        .all()
    )
    busy_by_inspector = {}
    for insp in busy_rows:
        busy_by_inspector.setdefault(insp.inspector_id, []).append(insp)

    free = [u for u in roster if u.id not in busy_by_inspector]
    busy = [u for u in roster if u.id in busy_by_inspector]

    lines = [f'Availability for {label}:', 'Free: ' + (', '.join(u.name for u in free) if free else 'nobody')]
    if busy:
        lines.append('Busy:')
        for u in busy:
            job_bits = []
            for insp in busy_by_inspector[u.id]:
                addr = insp.property.address if insp.property else 'Unknown'
                time_bit = f' {insp.conduct_time_preference}' if insp.conduct_time_preference else ''
                job_bits.append(f'{addr}{time_bit}')
            lines.append(f'• {u.name} — {"; ".join(job_bits)}')
    return '\n'.join(lines)


def _format_inspection_details(insp, show_internal: bool) -> str:
    prop = insp.property
    client = prop.client if prop else None
    kind = (insp.inspection_type or 'unknown').replace('_', ' ').title()
    date_label = insp.conduct_date.strftime('%a %d %b %Y') if insp.conduct_date else 'No date set'
    time_label = format_time_preference(insp.conduct_time_preference)

    lines = [f"{insp.reference_number or f'#{insp.id}'} — {kind}"]
    lines.append(f"Property: {prop.address if prop else 'Unknown property'}")
    if client:
        lines.append(f"Client: {client.name}" + (f' ({client.company})' if client.company else ''))
    lines.append(f"Date: {date_label}" + ('' if time_label == 'Anytime' else f' - {time_label}'))
    lines.append(f"Status: {(insp.status or 'unknown').replace('_', ' ').title()}")
    lines.append(f"Inspector: {insp.inspector.name if insp.inspector else 'Unassigned'}")
    if insp.typist:
        lines.append(f"Typist: {insp.typist.name}")
    if insp.tenant_name:
        lines.append(f"Tenant: {insp.tenant_name}")
    if insp.tenant_email:
        lines.append(f"Tenant email: {insp.tenant_email}")
    if insp.landlord_email:
        lines.append(f"Landlord email: {insp.landlord_email}")
    if insp.key_location:
        lines.append(f"Key location: {insp.key_location}")
    if insp.key_return:
        lines.append(f"Key return: {insp.key_return}")
    lines.append(f"Confirmed: {'Yes' if insp.confirmed else 'No'}")
    lines.append(f"Invoice paid: {'Yes' if insp.invoice_paid else 'No'}")
    if insp.deposit_amount is not None:
        dep = f"£{insp.deposit_amount}"
        if insp.deposit_scheme:
            dep += f" ({insp.deposit_scheme}"
            dep += f", ref {insp.deposit_ref})" if insp.deposit_ref else ')'
        lines.append(f"Deposit: {dep}")
    if insp.notes:
        lines.append(f"Notes: {insp.notes}")
    if show_internal and insp.internal_notes:
        lines.append(f"Internal notes: {insp.internal_notes}")
    return '\n'.join(lines)


def answer_query_inspection(raw: dict, user) -> str:
    from sqlalchemy.orm import selectinload
    from models import Inspection, Property
    from permissions import filter_inspections_for_user, is_admin_or_manager

    ref = (raw.get('reference_number') or '').strip()
    frag = (raw.get('property_address_fragment') or '').strip()
    insp_type = normalize_inspection_type(raw.get('inspection_type') or '') if raw.get('inspection_type') else None
    date_str = (raw.get('date') or '').strip()

    if not ref and not frag:
        return 'Which inspection? Give me a reference number (e.g. INS-150) or a property address.'

    query = filter_inspections_for_user(Inspection.query, user).options(
        selectinload(Inspection.property).selectinload(Property.client),
        selectinload(Inspection.inspector),
        selectinload(Inspection.typist),
    )

    if ref:
        rows = query.filter(Inspection.reference_number.ilike(ref)).all()
        if not rows:
            rows = query.filter(Inspection.reference_number.ilike(f'%{ref}%')).limit(6).all()
        if not rows:
            return f'I couldn\'t find an inspection with reference "{ref}".'
        label = f'reference "{ref}"'
    else:
        prop, err = _resolve_property_by_fragment(frag)
        if err:
            return err
        query = query.filter(Inspection.property_id == prop.id)
        if insp_type:
            query = query.filter(Inspection.inspection_type == insp_type)
        if date_str:
            try:
                d = datetime.fromisoformat(date_str).date()
            except (ValueError, TypeError):
                return f'I couldn\'t understand the date "{date_str}".'
            day_start, day_end = _day_bounds(d)
            query = query.filter(Inspection.conduct_date >= day_start, Inspection.conduct_date < day_end)
        rows = query.order_by(Inspection.conduct_date.desc()).limit(4).all()
        if not rows:
            kind = f' {insp_type.replace("_", " ")}' if insp_type else ''
            return f'I couldn\'t find a{kind} inspection at "{prop.address}".'
        label = f'"{prop.address}"'

    show_internal = is_admin_or_manager(user)
    shown, extra = rows[:3], len(rows) > 3
    text = '\n\n'.join(_format_inspection_details(i, show_internal) for i in shown)
    if len(rows) > 1 and ref:
        text = f'{len(rows)} inspections match {label}:\n\n' + text
    elif extra:
        text += f'\n\n…and more at {label} — add a type or date to narrow it down.'
    return text


READ_ONLY_TOOLS = {'query_schedule', 'query_availability', 'query_inspection'}

ANSWERERS = {
    'query_inspection':   answer_query_inspection,
    'query_schedule':     answer_query_schedule,
    'query_availability': answer_query_availability,
}


# ── /property and /inspection fill-in templates ───────────────────────────
# Only the required fields — everything optional can still be added in free
# text, or is asked for when the resolver needs it. Each entry is
# (label, arg name, type); type is 'int', 'date' (routed through
# normalize_date_text unless already ISO), 'type' (inspection type) or 'str'.
TEMPLATES = {
    'create_property': [
        ('Address', 'address', 'str'),
        ('Client', 'client_name', 'str'),
        ('Bedrooms', 'bedrooms', 'int'),
        ('Bathrooms', 'bathrooms', 'int'),
    ],
    'book_inspection': [
        ('Property', 'property_address_fragment', 'str'),
        ('Type', 'inspection_type', 'type'),
        ('Date', 'conduct_date', 'date'),
        ('Inspector', 'inspector_name', 'str'),
        ('Reference', 'reference_number', 'str'),
    ],
}

_TEMPLATE_ALIASES = {
    'client': 'client', 'agent': 'client', 'client/agent': 'client',
    'address': 'address', 'property': 'property', 'property address': 'property',
    'bedrooms': 'bedrooms', 'beds': 'bedrooms', 'bathrooms': 'bathrooms', 'baths': 'bathrooms',
    'date': 'date', 'inspector': 'inspector', 'clerk': 'inspector',
    'type': 'type', 'inspection type': 'type',
    'reference': 'reference', 'reference number': 'reference', 'ref': 'reference', 'ref no': 'reference',
}

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


def render_template(tool_name: str) -> str:
    lines = [f'{label}:' for label, _, _ in TEMPLATES[tool_name]]
    heading = 'new property' if tool_name == 'create_property' else 'inspection booking'
    text = f'Copy this, fill it in and send it back for the {heading}:\n\n' + '\n'.join(lines)
    if tool_name == 'book_inspection':
        text += '\n\nOptions for Type: check-in, check-out, midterm, damage report or heads-up (leave blank for check-in). Shorthand like CI, CO, MT and DR works too.\nReference is autofilled if left blank.'
    return text


def parse_template(tool_name: str, text: str) -> dict | None:
    """Read a filled-in template. Returns the raw args found (blank lines omitted), or
    None if the text has no recognisable "Label: value" lines at all — i.e. the user
    ignored the template and wrote a normal sentence, which the caller should parse
    as free text instead."""
    fields = {label.lower(): (arg, kind) for label, arg, kind in TEMPLATES[tool_name]}
    found_label = False
    args = {}
    for line in text.splitlines():
        label, sep, value = line.partition(':')
        label = label.strip().lower().lstrip('•-* ')
        if not sep or _TEMPLATE_ALIASES.get(label, label) not in fields:
            continue
        found_label = True
        value = value.strip()
        if not value or (value.startswith('(') and value.endswith(')')):
            continue
        arg, kind = fields[_TEMPLATE_ALIASES.get(label, label)]
        if kind == 'int':
            m = re.search(r'\d+', value)
            if m:
                args[arg] = int(m.group())
            elif value.lower() == 'studio':
                args[arg] = 0
        elif kind == 'type':
            # Unrecognised text is kept as-is so the resolver asks, not silently defaulted.
            args[arg] = normalize_inspection_type(value) or value
        elif kind == 'date':
            try:
                datetime.fromisoformat(value)
                args[arg] = value
            except ValueError:
                iso = normalize_date_text(value)
                if iso:
                    args[arg] = iso
        else:
            args[arg] = value
    return args if found_label else None
