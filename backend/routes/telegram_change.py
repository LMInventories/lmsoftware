"""
routes/telegram_change.py
───────────────────────────
The conversational /change command for the Telegram bot: staff tell the bot, in
plain English, what to change on an existing inspection — "move INS-150 to Friday",
"give 12 Smith St check-in to Sam", "switch INS-201 to the furnished template",
"set the tenant email on INS-88 to ...".

Claude drives a small tool-use loop (find the inspection, look at clerks/templates),
but it never writes anything itself. Its only write tool, propose_change, validates
the request and parks it on the TelegramSession; telegram_integration.py then shows
a Confirm / Cancel card, and only a tap on Confirm sends the change — as an ordinary
PUT /api/inspections/<id> with a short-lived JWT for the linked user, so every role
check, sheet/calendar sync and the availability guard in routes/inspections.py apply.

Availability: if a change would leave the inspection on a clerk who is marked
unavailable at that date/time, propose_change does NOT stage it. It returns the
list of available clerks and the model asks the user whether to "override
availability" or "change to a new clerk". Overriding is staged as
override_availability=true, which the backend only honours for admins/managers.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import date as date_cls

import anthropic

from routes import telegram_lookup as lookup

_MAX_ROUNDS = 8
_MAX_REPLY_CHARS = 4000
_FALLBACK = "I couldn't work out what to change — try giving the inspection reference (e.g. INS-150) and what should change."

# Template swaps are only safe before the clerk has started: once report data exists it is
# keyed to the template's sections/items.
_TEMPLATE_CHANGE_STATUSES = ('created', 'assigned')

_EMAIL_RE = re.compile(r'^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$')

_READ_TOOLS = ('search_inspections', 'get_inspection', 'get_schedule')


class ChangeContext:
    """Per-turn scratch space: the staged change, if propose_change accepted one."""
    def __init__(self):
        self.pending = None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _clerks():
    from models import User
    from routes.telegram_flows import INSPECTOR_ROLES
    return User.query.filter(User.role.in_(INSPECTOR_ROLES)).order_by(User.name.asc()).all()


def _available_clerks(d, pref):
    """[{'name', 'jobs_that_day'}] for clerks not blocked at this date/slot."""
    from models import Inspection
    from routes.telegram_intent import _day_bounds
    from services.availability import unavailable_user_ids
    clerks = _clerks()
    away = unavailable_user_ids(d, pref, [c.id for c in clerks]) if d else set()
    load = {}
    if d and clerks:
        start, end = _day_bounds(d)
        rows = (Inspection.query
                .filter(Inspection.conduct_date >= start, Inspection.conduct_date < end,
                        Inspection.inspector_id.in_([c.id for c in clerks]), Inspection.pdf_import.is_(False))
                .with_entities(Inspection.inspector_id).all())
        for (cid,) in rows:
            load[cid] = load.get(cid, 0) + 1
    return [{'name': c.name, 'jobs_that_day': load.get(c.id, 0)} for c in clerks if c.id not in away]


def _resolve_clerk(name):
    """(User, None) or (None, error-dict)."""
    clerks = _clerks()
    needle = name.strip().lower()
    exact = [c for c in clerks if c.name.lower() == needle]
    matches = exact or [c for c in clerks if needle in c.name.lower()]
    if not matches:
        return None, {'error': f'No clerk matching "{name}".', 'clerks': [c.name for c in clerks]}
    if len(matches) > 1:
        return None, {'error': 'More than one clerk matches — ask which.', 'clerks': [c.name for c in matches]}
    return matches[0], None


def _resolve_template(inspection_type, name):
    from routes.telegram_flows import _templates_for
    templates = _templates_for(inspection_type)
    needle = name.strip().lower()
    exact = [t for t in templates if t.name.lower() == needle]
    matches = exact or [t for t in templates if needle in t.name.lower()]
    if not matches:
        return None, {'error': f'No {inspection_type.replace("_", " ")} template matching "{name}".',
                      'templates': [t.name for t in templates]}
    if len(matches) > 1:
        return None, {'error': 'More than one template matches — ask which.', 'templates': [t.name for t in matches]}
    return matches[0], None


def _insp_label(insp):
    from routes.telegram_lookup import _label
    ref = insp.reference_number or f'#{insp.id}'
    addr = insp.property.address if insp.property else 'unknown address'
    return f'{ref} ({_label(insp.inspection_type)}) at {addr}'


# ── Tools ───────────────────────────────────────────────────────────────────

def list_clerks(user, date: str = '', time: str = ''):
    """Every clerk with whether they're blocked on the day and how many jobs they have."""
    from models import Inspection
    from routes.telegram_intent import _day_bounds, normalize_time_preference
    from services.availability import unavailable_user_ids
    d = None
    if date:
        try:
            d = date_cls.fromisoformat(date)
        except ValueError:
            return {'error': 'Date must be ISO YYYY-MM-DD.'}
    pref = normalize_time_preference(time) if time else None
    clerks = _clerks()
    away = unavailable_user_ids(d, pref, [c.id for c in clerks]) if d else set()
    load = {}
    if d:
        start, end = _day_bounds(d)
        for (cid,) in (Inspection.query
                       .filter(Inspection.conduct_date >= start, Inspection.conduct_date < end,
                               Inspection.inspector_id.in_([c.id for c in clerks]), Inspection.pdf_import.is_(False))
                       .with_entities(Inspection.inspector_id).all()):
            load[cid] = load.get(cid, 0) + 1
    return {'clerks': [{'name': c.name, 'role': c.role,
                        **({'unavailable': c.id in away, 'jobs_that_day': load.get(c.id, 0)} if d else {})}
                       for c in clerks]}


def list_templates(user, inspection_type: str):
    from routes.telegram_flows import _templates_for
    return {'templates': [{'name': t.name, 'default': bool(t.is_default)} for t in _templates_for(inspection_type)]}


def propose_change(user, ctx: ChangeContext, inspection_id: int, conduct_date: str = '',
                   conduct_time: str = '', clerk_name: str = '', unassign_clerk: bool = False,
                   template_name: str = '', reference_number: str = '', tenant_email: str = '',
                   key_location: str = '', internal_notes: str = '', override_availability: bool = False):
    from routes.telegram_intent import (TEMPLATELESS_TYPES, format_time_preference,
                                        normalize_time_preference)
    from services.availability import clerk_conflict

    insp = lookup._inspections(user).filter_by(id=inspection_id).first()
    if insp is None:
        return {'error': 'Inspection not found.'}
    if insp.status == 'complete':
        return {'error': 'That inspection is complete, so it can no longer be changed from here.'}

    payload, lines = {}, []
    new_date = insp.conduct_date.date() if insp.conduct_date else None
    new_pref = insp.conduct_time_preference
    new_clerk = insp.inspector
    schedule_touched = False

    if conduct_date:
        try:
            new_date = date_cls.fromisoformat(conduct_date)
        except ValueError:
            return {'error': 'conduct_date must be ISO YYYY-MM-DD.'}
        payload['conduct_date'] = f'{new_date.isoformat()}T00:00:00'
        lines.append(f"Date: {new_date.strftime('%a %d %b %Y')}")
        schedule_touched = True
    if conduct_time:
        pref = normalize_time_preference(conduct_time)
        if not pref:
            return {'error': 'Time must be AM, PM, anytime or a time like 2:30pm.'}
        new_pref = pref
        payload['conduct_time_preference'] = pref
        lines.append(f'Time: {format_time_preference(pref)}')
        schedule_touched = True
    if unassign_clerk:
        new_clerk = None
        payload['inspector_id'] = None
        lines.append('Clerk: Unassigned')
    elif clerk_name:
        c, err = _resolve_clerk(clerk_name)
        if err:
            return err
        new_clerk = c
        payload['inspector_id'] = c.id
        lines.append(f'Clerk: {c.name}')
        schedule_touched = True
    if template_name:
        if insp.inspection_type in TEMPLATELESS_TYPES:
            return {'error': 'That inspection type has no report template.'}
        if insp.status not in _TEMPLATE_CHANGE_STATUSES:
            return {'error': f'The template can only be changed before the clerk starts ("{insp.status}" now) — '
                             "the report data is tied to the current template."}
        tpl, err = _resolve_template(insp.inspection_type, template_name)
        if err:
            return err
        payload['template_id'] = tpl.id
        lines.append(f'Template: {tpl.name}')
    if reference_number:
        payload['reference_number'] = reference_number.strip()
        lines.append(f'Reference: {reference_number.strip()}')
    if tenant_email:
        if not _EMAIL_RE.match(tenant_email.strip()):
            return {'error': f'"{tenant_email}" doesn\'t look like an email address.'}
        payload['tenant_email'] = tenant_email.strip()
        lines.append(f'Tenant email: {tenant_email.strip()}')
    if key_location:
        payload['key_location'] = key_location.strip()
        lines.append(f'Key location: {key_location.strip()}')
    if internal_notes:
        payload['internal_notes'] = internal_notes.strip()
        lines.append(f'Internal notes: {internal_notes.strip()}')
    if not payload:
        return {'error': 'Nothing to change was given.'}

    warnings = []
    if schedule_touched and new_clerk is not None and new_date is not None:
        clash = clerk_conflict(new_clerk.id, new_date, new_pref)
        if clash:
            if not override_availability:
                return {
                    'status': 'clerk_unavailable',
                    'clerk': clash.name,
                    'date': new_date.strftime('%a %d %b %Y'),
                    'available_clerks': _available_clerks(new_date, new_pref),
                    'instruction': (
                        f'{clash.name} is marked unavailable then. Nothing has been staged. Tell the user, '
                        'and ask whether to "override availability" (keep ' + clash.name + ') or "change to a new '
                        'clerk" — list the available clerks. Then call propose_change again with the full '
                        'change set: override_availability=true, or the chosen clerk_name.'),
                }
            payload['override_availability'] = True
            warnings.append(f'⚠️ {clash.name} is marked unavailable then — this overrides their availability.')

    ctx.pending = {
        'id': secrets.token_hex(3),
        'inspection_id': insp.id,
        'label': _insp_label(insp),
        'payload': payload,
        'lines': lines,
        'warnings': warnings,
    }
    return {'status': 'awaiting_confirmation',
            'note': 'A Confirm/Cancel card is being shown to the user. Do NOT say the change is done; '
                    'at most add one short sentence.'}


_IMPLS = {
    'list_clerks': list_clerks,
    'list_templates': list_templates,
}

_TOOLS = [t for t in lookup.LOOKUP_TOOLS if t['name'] in _READ_TOOLS] + [
    {
        'name': 'list_clerks',
        'description': 'All clerks (and managers/admins who can take jobs). With a date (and optional time), '
                       'shows who is marked unavailable then and how many jobs each already has that day.',
        'input_schema': {'type': 'object', 'properties': {
            'date': {'type': 'string', 'description': 'ISO YYYY-MM-DD'},
            'time': {'type': 'string', 'description': 'am, pm, anytime or e.g. 2:30pm'},
        }, 'required': []},
    },
    {
        'name': 'list_templates',
        'description': 'Report templates available for an inspection type.',
        'input_schema': {'type': 'object', 'properties': {
            'inspection_type': {'type': 'string', 'enum': ['check_in', 'check_out', 'midterm', 'damage_report']},
        }, 'required': ['inspection_type']},
    },
    {
        'name': 'propose_change',
        'description': (
            'Stage a change to ONE existing inspection for the user to confirm. Include only the fields '
            'that change, resolved to concrete values (e.g. an ISO date). Nothing is saved until the user '
            'taps Confirm. If the change would put the inspection on an unavailable clerk, it is not staged '
            'and you get the available clerks back instead.'
        ),
        'input_schema': {'type': 'object', 'properties': {
            'inspection_id': {'type': 'integer'},
            'conduct_date': {'type': 'string', 'description': 'New date, ISO YYYY-MM-DD'},
            'conduct_time': {'type': 'string', 'description': 'am, pm, anytime or e.g. 2:30pm'},
            'clerk_name': {'type': 'string', 'description': 'New clerk (name as listed by list_clerks)'},
            'unassign_clerk': {'type': 'boolean'},
            'template_name': {'type': 'string'},
            'reference_number': {'type': 'string'},
            'tenant_email': {'type': 'string'},
            'key_location': {'type': 'string'},
            'internal_notes': {'type': 'string'},
            'override_availability': {'type': 'boolean',
                                      'description': 'Only after the user explicitly chose to override an unavailable clerk'},
        }, 'required': ['inspection_id']},
        'cache_control': {'type': 'ephemeral'},
    },
]


def _run_tool(name, args, user, ctx):
    from models import db
    try:
        if name == 'propose_change':
            return json.dumps(propose_change(user, ctx, **args), default=str)
        if name in _IMPLS:
            return json.dumps(_IMPLS[name](user, **args), default=str)
        return lookup._run_tool(name, args, user)
    except TypeError as e:
        return json.dumps({'error': f'Bad arguments: {e}'})
    except Exception as e:
        db.session.rollback()
        print(f'[telegram_change] {name}({args}) failed: {e}')
        return json.dumps({'error': 'That failed.'})


def _system_prompt(user) -> str:
    from routes.telegram_intent import _today_london
    today = _today_london().strftime('%A %d %B %Y')
    return (
        f"Today is {today} (UK). You help {user.name} (role: {user.role}) at a UK property inspection "
        "company change existing inspections, over Telegram. You can change: the date, the time (AM/PM/"
        "anytime/specific), the clerk (or unassign), the report template, the reference number, the tenant "
        "email, key location and internal notes.\n"
        "- Identify the inspection first (search_inspections / get_schedule / get_inspection). If more than "
        "one could match, list them briefly and ask which. Never guess.\n"
        "- Convert relative dates ('Friday', 'next Tuesday') to an ISO date from today's date.\n"
        "- When the request is clear, call propose_change with only the changed fields. Nothing is saved "
        "until the user taps Confirm on the card the bot shows; never claim a change is done.\n"
        "- If propose_change returns status clerk_unavailable, tell the user that clerk is unavailable and "
        "offer two options: 'override availability' or 'change to a new clerk', listing the available clerks "
        "(name and jobs that day). When they answer, call propose_change again with the whole change set "
        "(override_availability=true, or the chosen clerk_name). Only set override_availability after the user "
        "explicitly chooses it.\n"
        "- You can't create inspections or properties (/inspection, /property) and can't change completed ones.\n"
        "- Plain text for Telegram, short lines, no markdown. Refer to inspections by reference number, never "
        "internal ids. One change at a time is fine; ask a brief question if something is missing."
    )


def answer_change(text: str, user, history: list[dict] | None = None):
    """Returns (reply_text, stored_text, pending_or_None)."""
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    system = [{'type': 'text', 'text': _system_prompt(user)}]
    ctx = ChangeContext()
    touched: dict[str, list] = {'inspection_id': []}

    messages = [{'role': h['role'], 'content': h['content']} for h in history or []]
    messages.append({'role': 'user', 'content': text})

    for _ in range(_MAX_ROUNDS):
        response = client.messages.create(model=lookup._MODEL, max_tokens=1200, system=system,
                                          tools=_TOOLS, messages=messages)
        if response.stop_reason != 'tool_use':
            reply = ''.join(b.text for b in response.content if b.type == 'text').strip()
            if not reply and not ctx.pending:
                reply = _FALLBACK
            note = ''
            if touched['inspection_id']:
                note = f"\n[looked at: inspection {', '.join(str(i) for i in touched['inspection_id'])}]"
            return reply[:_MAX_REPLY_CHARS], reply[:_MAX_REPLY_CHARS] + note, ctx.pending

        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for b in response.content:
            if b.type != 'tool_use':
                continue
            args = dict(b.input)
            iid = args.get('inspection_id')
            if isinstance(iid, int) and iid not in touched['inspection_id']:
                touched['inspection_id'].append(iid)
            results.append({'type': 'tool_result', 'tool_use_id': b.id,
                            'content': _run_tool(b.name, args, user, ctx)})
        messages.append({'role': 'user', 'content': results})

    return _FALLBACK, _FALLBACK, ctx.pending


def confirm_card(pending):
    """(text, inline_keyboard) for a staged change."""
    text = f"Change {pending['label']}?\n\n" + '\n'.join(f'• {l}' for l in pending['lines'])
    if pending['warnings']:
        text += '\n\n' + '\n'.join(pending['warnings'])
    kb = {'inline_keyboard': [[
        {'text': '✅ Confirm', 'callback_data': f"c:yes:{pending['id']}"},
        {'text': '✖️ Cancel', 'callback_data': f"c:no:{pending['id']}"},
    ]]}
    return text, kb
