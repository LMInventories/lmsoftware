"""
services/google_calendar.py
────────────────────────────
Create, update, and delete Google Calendar events for inspections.

Triggered automatically from routes/inspections.py on create/update/delete
when Google Calendar is connected and the inspection has a conduct_date.

Usage:
    from services.google_calendar import push_calendar_event, delete_calendar_event, is_calendar_connected
    if is_calendar_connected() and inspection.conduct_date:
        ok, result = push_calendar_event(inspection)
"""

from __future__ import annotations

import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import timedelta

_CALENDAR_EVENTS_URL = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'


def is_calendar_connected() -> bool:
    """True if Google is connected and the calendar scope was granted."""
    try:
        from routes.google import is_connected, _load_tokens
        if not is_connected():
            return False
        tokens = _load_tokens()
        return 'calendar' in tokens.get('google_scopes', '')
    except Exception:
        return False


def _api_request(method: str, url: str, access_token: str,
                 body: bytes | None = None) -> dict:
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept':        'application/json',
    }
    if body is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def _build_event(inspection) -> dict:
    """Build the Calendar event body from an inspection."""
    prop    = inspection.property
    address = (prop.address if prop else 'Unknown Property').strip()
    insp_type = (inspection.inspection_type or 'inspection').replace('_', ' ').title()

    summary = f'{insp_type} — {address}'

    lines = []
    if inspection.reference_number:
        lines.append(f'Ref: {inspection.reference_number}')
    if inspection.inspector and inspection.inspector.name:
        lines.append(f'Clerk: {inspection.inspector.name}')
    if inspection.tenant_name:
        lines.append(f'Tenant: {inspection.tenant_name}')
    if inspection.conduct_time_preference:
        lines.append(f'Time preference: {inspection.conduct_time_preference}')
    description = '\n'.join(lines)

    # All-day event — conduct_date has no precise time stored
    date_str     = inspection.conduct_date.strftime('%Y-%m-%d')
    end_date_str = (inspection.conduct_date + timedelta(days=1)).strftime('%Y-%m-%d')

    event: dict = {
        'summary':     summary,
        'description': description,
        'start':       {'date': date_str},
        'end':         {'date': end_date_str},
    }

    if inspection.inspector and inspection.inspector.email:
        event['attendees'] = [{'email': inspection.inspector.email}]

    return event


def push_calendar_event(inspection) -> tuple[bool, str]:
    """
    Create or update the Google Calendar event for an inspection.

    If inspection.calendar_event_id is already set, updates the existing
    event. Otherwise creates a new one and persists the returned ID.

    Returns (True, event_id) on success or (False, error_message) on failure.
    """
    from routes.google import get_valid_access_token
    from models import db

    if not inspection.conduct_date:
        return False, 'no conduct_date set'

    access_token = get_valid_access_token()
    if not access_token:
        return False, 'Google not connected or token refresh failed'

    try:
        body_bytes  = json.dumps(_build_event(inspection)).encode()
        was_update  = bool(inspection.calendar_event_id)

        if was_update:
            url    = f'{_CALENDAR_EVENTS_URL}/{urllib.parse.quote(inspection.calendar_event_id, safe="")}'
            result = _api_request('PUT', url, access_token, body=body_bytes)
        else:
            result = _api_request('POST', _CALENDAR_EVENTS_URL, access_token, body=body_bytes)

        event_id = result.get('id', inspection.calendar_event_id or '')

        if event_id and event_id != inspection.calendar_event_id:
            inspection.calendar_event_id = event_id
            db.session.commit()

        action = 'updated' if was_update else 'created'
        print(f'[calendar] event {action} — id={event_id}')
        return True, event_id

    except urllib.error.HTTPError as e:
        err_body = ''
        try:
            err_body = e.read().decode('utf-8')[:300]
        except Exception:
            pass

        if e.code == 404 and inspection.calendar_event_id:
            # Event was deleted from Calendar externally — clear the stale ID
            # and retry as a create
            print(f'[calendar] event {inspection.calendar_event_id} not found; re-creating')
            inspection.calendar_event_id = None
            db.session.commit()
            return push_calendar_event(inspection)

        msg = f'Calendar API HTTP {e.code}: {err_body}'
        print(f'[calendar] push error: {msg}')
        return False, msg

    except Exception as e:
        print(f'[calendar] push error: {e}')
        return False, str(e)


def delete_calendar_event(event_id: str) -> bool:
    """
    Delete a Google Calendar event by ID.
    Returns True on success (including 404 — already gone).
    """
    from routes.google import get_valid_access_token

    access_token = get_valid_access_token()
    if not access_token:
        return False

    try:
        url = f'{_CALENDAR_EVENTS_URL}/{urllib.parse.quote(event_id, safe="")}'
        req = urllib.request.Request(
            url,
            headers={'Authorization': f'Bearer {access_token}'},
            method='DELETE',
        )
        urllib.request.urlopen(req, timeout=30)
        print(f'[calendar] event deleted — id={event_id}')
        return True

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return True  # already gone
        print(f'[calendar] delete error: HTTP {e.code}')
        return False

    except Exception as e:
        print(f'[calendar] delete error: {e}')
        return False
