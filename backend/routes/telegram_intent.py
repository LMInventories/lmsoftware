"""
routes/telegram_intent.py
───────────────────────────
Free-text intent parsing for the Telegram bot integration
(routes/telegram_integration.py).

Three supported actions: create_property, book_inspection, update_inspection.
Uses the Anthropic client (same pattern as backend/learning/proposal.py) with
native tool-use so model output is structured instead of ask-for-JSON-and-
strip-fences.

Also defines WIZARD_STEPS — the deterministic, no-LLM step-by-step forms
behind the /property and /inspection commands. A wizard just walks its step
list collecting one field at a time (with inline-keyboard buttons for
enums/booleans); once every step is answered it hands the collected raw
fields to the same resolver/confirmation/payload-building code the free-text
flow uses, so both entry points converge on one confirmation step and one
write path.

The LLM never sees or produces database IDs — it only extracts free-text
fields (a client name, a property address fragment, an inspector's name).
telegram_integration.py resolves those against real rows afterwards, so a
misheard or fuzzy phrase can never become a wrong foreign key on its own.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

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
                'conduct_time_preference': {'type': 'string', 'description': "Free text time, e.g. '2pm', 'morning'"},
                'inspector_name': {'type': 'string', 'description': 'Name of the field inspector to assign, if mentioned'},
                'tenant_email':   {'type': 'string'},
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
        "inspections, create properties, reschedule or update existing inspections, and "
        "share completed reports by extracting structured data from free-text chat "
        "messages. Normalize relative dates (\"Thursday\", \"next week\") to ISO "
        "YYYY-MM-DD using today's date above. Use update_inspection whenever the message "
        "describes changing something about an inspection that likely already exists "
        "(moving a date, reassigning an inspector, changing a tenant email) rather than "
        "creating a new one. Use share_report when the message is about sending, emailing, "
        "or sharing a finished report. If the message doesn't relate to any of these, do "
        "not call any tool — just reply naturally, briefly explaining what you can help with."
    )


class ParsedIntent:
    def __init__(self, tool_name=None, args=None, reply_text=None):
        self.tool_name = tool_name
        self.args = args or {}
        self.reply_text = reply_text  # set only when the model didn't call a tool


def parse_message(text: str, *, forced_tool: str | None = None) -> ParsedIntent:
    """Run one Anthropic call to extract a tool call (or a plain reply) from `text`.

    forced_tool: when a slot-filling flow is already in progress, force the
    model to keep extracting args for that same tool rather than risking a
    fresh/ambiguous classification on a short follow-up reply like "2pm".
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    tool_choice = {'type': 'tool', 'name': forced_tool} if forced_tool else {'type': 'auto'}

    message = client.messages.create(
        model=_MODEL,
        max_tokens=1000,
        system=_system_prompt(),
        tools=_TOOLS,
        tool_choice=tool_choice,
        messages=[{'role': 'user', 'content': text}],
    )

    for block in message.content:
        if block.type == 'tool_use':
            return ParsedIntent(tool_name=block.name, args=dict(block.input))

    reply_text = ''.join(b.text for b in message.content if b.type == 'text').strip()
    return ParsedIntent(reply_text=reply_text or (
        "I can create a property, book an inspection, or reschedule/update one — tell me what "
        "you need, or try /property or /inspection for a step-by-step form."
    ))


def normalize_date_text(text: str) -> str | None:
    """One-off helper for the wizard's date step, where the reply is nothing but a date
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


def resolve_create_property(raw: dict):
    """Returns (resolved: dict|None, question: str|None).
    `resolved` is None whenever something's still missing or ambiguous, in
    which case `question` is what to ask the user next."""
    address = (raw.get('address') or '').strip()
    if not address:
        return None, "What's the property address?"

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

    client = matches[0]
    resolved = {
        'address':       address,
        'client_id':     client.id,
        'client_name':   client.name,
        'property_type': raw.get('property_type') or 'residential',
        'bedrooms':      raw.get('bedrooms'),
        'bathrooms':     raw.get('bathrooms'),
        'furnished':     raw.get('furnished'),
        'notes':         raw.get('notes'),
    }
    return resolved, None


def resolve_book_inspection(raw: dict):
    frag = (raw.get('property_address_fragment') or '').strip()
    if not frag:
        return None, 'Which property is this for? (give me the address or part of it)'

    from models import Property
    matches = Property.query.filter(Property.address.ilike(f'%{frag}%')).limit(6).all()
    if len(matches) == 0:
        return None, f'I couldn\'t find a property matching "{frag}" — could you give me more of the address?'
    if len(matches) > 1:
        addrs = '; '.join(f'"{p.address}"' for p in matches)
        return None, f'I found more than one property matching "{frag}": {addrs}. Which one did you mean?'
    prop = matches[0]

    date_str = (raw.get('conduct_date') or '').strip()
    if not date_str:
        return None, 'What date should the inspection be? (e.g. "Thursday", or "2026-09-25")'
    try:
        conduct_dt = datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None, f'I couldn\'t understand the date "{date_str}" — what date should the inspection be?'
    if conduct_dt.date() < datetime.now(timezone.utc).date():
        return None, f'That date ({conduct_dt.date().isoformat()}) is in the past — what date did you mean?'

    inspector_id = None
    inspector_name_display = None
    inspector_name = (raw.get('inspector_name') or '').strip()
    if inspector_name:
        from models import User
        insp_matches = User.query.filter(User.role == 'clerk', User.name.ilike(f'%{inspector_name}%')).limit(6).all()
        if len(insp_matches) == 1:
            inspector_id = insp_matches[0].id
            inspector_name_display = insp_matches[0].name
        elif len(insp_matches) > 1:
            names = ', '.join(i.name for i in insp_matches)
            return None, f'I found more than one inspector matching "{inspector_name}": {names}. Which one did you mean?'
        else:
            return None, f'I couldn\'t find an inspector named "{inspector_name}" — who should this be assigned to? (or say "no inspector yet")'

    resolved = {
        'property_id':             prop.id,
        'property_address':        prop.address,
        'inspection_type':         raw.get('inspection_type') or 'check_in',
        'conduct_date':            conduct_dt.isoformat(),
        'conduct_time_preference': raw.get('conduct_time_preference'),
        'inspector_id':            inspector_id,
        'inspector_name':          inspector_name_display,
        'tenant_email':            raw.get('tenant_email'),
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

    from models import Property
    prop_matches = Property.query.filter(Property.address.ilike(f'%{frag}%')).limit(6).all()
    if len(prop_matches) == 0:
        return None, f'I couldn\'t find a property matching "{frag}" — could you give me more of the address?'
    if len(prop_matches) > 1:
        addrs = '; '.join(f'"{p.address}"' for p in prop_matches)
        return None, f'I found more than one property matching "{frag}": {addrs}. Which one did you mean?'
    prop = prop_matches[0]

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

    resolved = {
        'inspection_id':      target.id,
        'property_address':   prop.address,
        'inspection_type':    target.inspection_type,
        'old_conduct_date':   target.conduct_date.isoformat() if target.conduct_date else None,
        'old_time':           target.conduct_time_preference,
        'old_inspector_name': target.inspector.name if target.inspector else None,
        'new_conduct_date':            new_date_iso,
        'new_conduct_time_preference': raw.get('new_conduct_time_preference') or None,
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

    from models import Property
    prop_matches = Property.query.filter(Property.address.ilike(f'%{frag}%')).limit(6).all()
    if len(prop_matches) == 0:
        return None, f'I couldn\'t find a property matching "{frag}" — could you give me more of the address?'
    if len(prop_matches) > 1:
        addrs = '; '.join(f'"{p.address}"' for p in prop_matches)
        return None, f'I found more than one property matching "{frag}": {addrs}. Which one did you mean?'
    prop = prop_matches[0]

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


RESOLVERS = {
    'create_property':   resolve_create_property,
    'book_inspection':   resolve_book_inspection,
    'update_inspection': resolve_update_inspection,
    'share_report':      resolve_share_report,
}


def summarize_property(resolved: dict) -> str:
    lines = [
        'Create this property?',
        f"• Address: {resolved['address']}",
        f"• Client: {resolved['client_name']}",
    ]
    if resolved.get('bedrooms'):
        lines.append(f"• Bedrooms: {resolved['bedrooms']}")
    if resolved.get('bathrooms'):
        lines.append(f"• Bathrooms: {resolved['bathrooms']}")
    if resolved.get('furnished'):
        lines.append(f"• Furnished: {resolved['furnished']}")
    lines.append('Reply YES to confirm, or tell me what to change.')
    return '\n'.join(lines)


def summarize_inspection(resolved: dict) -> str:
    dt = datetime.fromisoformat(resolved['conduct_date'])
    date_line = f"• Date: {dt.strftime('%a %d %b %Y')}"
    if resolved.get('conduct_time_preference'):
        date_line += f" — {resolved['conduct_time_preference']}"
    lines = [
        'Book this inspection?',
        f"• Property: {resolved['property_address']}",
        f"• Type: {resolved['inspection_type'].replace('_', ' ').title()}",
        date_line,
    ]
    if resolved.get('inspector_name'):
        lines.append(f"• Inspector: {resolved['inspector_name']}")
    lines.append('Reply YES to confirm, or tell me what to change.')
    return '\n'.join(lines)


def summarize_update_inspection(resolved: dict) -> str:
    lines = [f"Update this inspection at {resolved['property_address']} ({resolved['inspection_type'].replace('_', ' ').title()})?"]
    if resolved.get('old_conduct_date'):
        old_dt = datetime.fromisoformat(resolved['old_conduct_date'])
        current = f"• Currently: {old_dt.strftime('%a %d %b %Y')}"
        if resolved.get('old_time'):
            current += f" — {resolved['old_time']}"
        lines.append(current)
    if resolved.get('new_conduct_date'):
        new_dt = datetime.fromisoformat(resolved['new_conduct_date'])
        lines.append(f"• New date: {new_dt.strftime('%a %d %b %Y')}")
    if resolved.get('new_conduct_time_preference'):
        lines.append(f"• New time: {resolved['new_conduct_time_preference']}")
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


SUMMARIZERS = {
    'create_property':   summarize_property,
    'book_inspection':   summarize_inspection,
    'update_inspection': summarize_update_inspection,
    'share_report':      summarize_share_report,
}


def build_property_payload(resolved: dict) -> dict:
    return {
        'address':       resolved['address'],
        'client_id':     resolved['client_id'],
        'property_type': resolved.get('property_type') or 'residential',
        'bedrooms':      resolved.get('bedrooms'),
        'bathrooms':     resolved.get('bathrooms'),
        'furnished':     resolved.get('furnished'),
        'notes':         resolved.get('notes'),
    }


def build_inspection_payload(resolved: dict) -> dict:
    return {
        'property_id':             resolved['property_id'],
        'inspection_type':         resolved.get('inspection_type') or 'check_in',
        'conduct_date':            resolved['conduct_date'],
        'conduct_time_preference': resolved.get('conduct_time_preference'),
        'inspector_id':            resolved.get('inspector_id'),
        'tenant_email':            resolved.get('tenant_email'),
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
ACTION_CONFIG = {
    'create_property':   {'method': 'POST', 'path': lambda resolved: '/api/properties'},
    'book_inspection':   {'method': 'POST', 'path': lambda resolved: '/api/inspections'},
    'update_inspection': {'method': 'PUT',  'path': lambda resolved: f"/api/inspections/{resolved['inspection_id']}"},
    'share_report':       {'method': 'POST', 'path': lambda resolved: f"/api/inspections/{resolved['inspection_id']}/share-pdf"},
}


# ── /property and /inspection guided forms ─────────────────────────────────
# Each step: 'field' (key stored in the wizard's collected dict), 'prompt',
# 'required' (blocks Skip and re-asks on empty input), and optionally
# 'options' (rendered as inline-keyboard buttons, also accepted as typed
# text), 'value_map' (button label -> stored value, e.g. 'Check-in' ->
# 'check_in'), 'type' ('int' | 'bool', default plain string), or
# 'freeform_date' (routes the reply through normalize_date_text()).
WIZARD_STEPS = {
    'create_property': [
        {'field': 'address', 'prompt': "What's the property address?", 'required': True},
        {'field': 'client_name', 'prompt': 'Which client/agent is this property for?', 'required': True},
        {'field': 'property_type', 'prompt': 'Property type?', 'options': ['Residential', 'Commercial'],
         'value_map': {'Residential': 'residential', 'Commercial': 'commercial'}},
        {'field': 'bedrooms', 'prompt': 'How many bedrooms? (or Skip)', 'type': 'int'},
        {'field': 'bathrooms', 'prompt': 'How many bathrooms? (or Skip)', 'type': 'int'},
        {'field': 'furnished', 'prompt': 'Furnished status?', 'options': ['Furnished', 'Part Furnished', 'Unfurnished']},
        {'field': 'parking', 'prompt': 'Parking available?', 'options': ['Yes', 'No'], 'type': 'bool'},
        {'field': 'garden', 'prompt': 'Garden?', 'options': ['Yes', 'No'], 'type': 'bool'},
        {'field': 'elevator', 'prompt': 'Lift/elevator?', 'options': ['Yes', 'No'], 'type': 'bool'},
        {'field': 'detachment_type', 'prompt': 'Detachment type? e.g. Terraced, Semi-Detached, Detached (or Skip)'},
        {'field': 'elevation', 'prompt': 'Floor/elevation? e.g. Ground Floor, 1st Floor (or Skip)'},
        {'field': 'meter_electricity', 'prompt': 'Electricity meter reading/number? (or Skip)'},
        {'field': 'meter_gas', 'prompt': 'Gas meter reading/number? (or Skip)'},
        {'field': 'meter_water', 'prompt': 'Water meter reading/number? (or Skip)'},
        {'field': 'notes', 'prompt': 'Any notes? (or Skip)'},
    ],
    'book_inspection': [
        {'field': 'property_address_fragment', 'prompt': 'Which property? (address or part of it)', 'required': True},
        {'field': 'inspection_type', 'prompt': 'Inspection type?',
         'options': ['Check-in', 'Check-out', 'Midterm', 'Damage Report', 'Heads-up'],
         'value_map': {'Check-in': 'check_in', 'Check-out': 'check_out', 'Midterm': 'midterm',
                        'Damage Report': 'damage_report', 'Heads-up': 'heads_up'}},
        {'field': 'conduct_date', 'prompt': 'What date? (e.g. "Thursday", or 2026-09-25)', 'required': True, 'freeform_date': True},
        {'field': 'conduct_time_preference', 'prompt': 'Preferred time? (or Skip)'},
        {'field': 'inspector_name', 'prompt': 'Assign an inspector? Give their name, or Skip'},
        {'field': 'tenant_email', 'prompt': "Tenant's email? (or Skip)"},
    ],
}


class WizardAnswer:
    def __init__(self, value=None, skipped=False, error=None):
        self.value = value
        self.skipped = skipped
        self.error = error


def coerce_wizard_answer(step: dict, raw_text: str) -> WizardAnswer:
    raw_text = (raw_text or '').strip()
    if not raw_text:
        return WizardAnswer(error='Please send a value.') if step.get('required') else WizardAnswer(skipped=True)
    if not step.get('required') and raw_text.lower() in ('skip', 'none', '-', 'n/a'):
        return WizardAnswer(skipped=True)

    if step.get('options'):
        matched = next((opt for opt in step['options'] if raw_text.lower() == opt.lower()), None)
        if not matched:
            return WizardAnswer(error=f"Please choose one of: {', '.join(step['options'])}")
        raw_text = step.get('value_map', {}).get(matched, matched)

    if step.get('type') == 'int':
        try:
            return WizardAnswer(value=int(raw_text))
        except ValueError:
            return WizardAnswer(error='Please send a number.')

    if step.get('type') == 'bool':
        return WizardAnswer(value=raw_text.lower() == 'yes')

    if step.get('freeform_date'):
        iso = normalize_date_text(raw_text)
        if not iso:
            return WizardAnswer(error='I couldn\'t understand that date — try again (e.g. "Thursday" or "2026-09-25").')
        return WizardAnswer(value=iso)

    return WizardAnswer(value=raw_text)
