"""
routes/telegram_intent.py
───────────────────────────
Free-text intent parsing for the Telegram bot integration
(routes/telegram_integration.py).

Two supported actions: create_property, book_inspection. Uses the Anthropic
client (same pattern as backend/learning/proposal.py) with native tool-use so
model output is structured instead of ask-for-JSON-and-strip-fences.

The LLM never sees or produces database IDs — it only extracts free-text
fields (a client name, a property address fragment, an inspector's name).
telegram_integration.py resolves those against real rows afterwards, so a
misheard or fuzzy phrase can never become a wrong foreign key on its own.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import anthropic

_MODEL = 'claude-haiku-4-5-20251001'  # fast/cheap tier — bounded structured extraction, not open-ended reasoning

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
]


def _system_prompt() -> str:
    today = datetime.now(timezone.utc).astimezone().strftime('%A %d %B %Y')
    return (
        f"Today is {today}. You help staff at a UK property inspection company book "
        "inspections and create properties by extracting structured data from free-text "
        "chat messages. Normalize relative dates (\"Thursday\", \"next week\") to ISO "
        "YYYY-MM-DD using today's date above. If the message doesn't relate to creating "
        "a property or booking an inspection, do not call any tool — just reply naturally, "
        "briefly explaining what you can help with."
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
        "I can create a property or book an inspection — try telling me the address and what you need."
    ))


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


RESOLVERS = {
    'create_property': resolve_create_property,
    'book_inspection':  resolve_book_inspection,
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


SUMMARIZERS = {
    'create_property': summarize_property,
    'book_inspection':  summarize_inspection,
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


BUILD_PAYLOAD = {
    'create_property': build_property_payload,
    'book_inspection':  build_inspection_payload,
}

API_ENDPOINT = {
    'create_property': '/api/properties',
    'book_inspection':  '/api/inspections',
}
