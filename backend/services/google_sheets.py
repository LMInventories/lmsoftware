"""
services/google_sheets.py
─────────────────────────
Google Sheets API helper for InspectPro.

Currently used to append a new row to the master job-records spreadsheet
whenever an inspection is created.

Column order written (must match your sheet's header row):
  A: Reference | B: Date | C: Type | D: Address | E: Bedrooms | F: Client | G: Clerk

Requires:
  • Google OAuth connected with the spreadsheets scope
    (Settings → Integrations → Connect Google)
  • google_master_sheet_id saved in system settings
    (Settings → Integrations → Master Sheet ID)
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Optional

_SHEETS_BASE = 'https://sheets.googleapis.com/v4/spreadsheets'


# ── Public entry point ────────────────────────────────────────────────────────

def append_inspection_row(inspection) -> tuple[bool, Optional[str]]:
    """
    Append one row for *inspection* to the configured master Google Sheet.

    Returns (True, None) on success, (False, error_message) on any failure.
    Safe to call fire-and-forget — never raises.
    """
    try:
        return _append(inspection)
    except Exception as exc:
        return False, str(exc)


# ── Internal ──────────────────────────────────────────────────────────────────

def _get_sheet_id() -> Optional[str]:
    from models import SystemSetting
    row = SystemSetting.query.filter_by(key='google_master_sheet_id').first()
    return (row.value or '').strip() if row else None


def _build_row(inspection) -> list:
    """Return the list of cell values to write, in column order."""
    # Reference
    ref = (inspection.reference_number or '').strip() or f'INS-{inspection.id}'

    # Date — prefer conduct_date, fall back to scheduled_date
    date_obj = inspection.conduct_date or inspection.scheduled_date
    date_str = date_obj.strftime('%d/%m/%Y') if date_obj else ''

    # Inspection type — human-readable
    type_map = {
        'check_in':      'Check In',
        'check_out':     'Check Out',
        'midterm':       'Mid-Term',
        'damage_report': 'Damage Report',
    }
    insp_type = type_map.get(inspection.inspection_type or '', inspection.inspection_type or '')

    # Property fields
    prop = inspection.property
    address  = prop.address  if prop else ''
    bedrooms = prop.bedrooms if prop else ''
    bedrooms = str(bedrooms) if bedrooms is not None else ''

    # Client — prefer company name, fall back to contact name
    client = prop.client if prop else None
    client_name = ''
    if client:
        client_name = (client.company or client.name or '').strip()

    # Clerk
    clerk_name = inspection.inspector.name if inspection.inspector else ''

    return [ref, date_str, insp_type, address, bedrooms, client_name, clerk_name]


def _append(inspection) -> tuple[bool, Optional[str]]:
    from routes.google import get_valid_access_token

    # Prerequisites
    sheet_id = _get_sheet_id()
    if not sheet_id:
        return False, 'google_master_sheet_id not configured'

    token = get_valid_access_token()
    if not token:
        return False, 'Google not connected (no valid access token)'

    row = _build_row(inspection)

    # Append to the first sheet, starting from column A
    # valueInputOption=USER_ENTERED lets Sheets parse dates / numbers
    # insertDataOption=INSERT_ROWS always adds a new row rather than overwriting
    url = (
        f'{_SHEETS_BASE}/{sheet_id}/values/A:G:append'
        f'?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS'
    )

    payload = json.dumps({'values': [row]}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        updated = result.get('updates', {}).get('updatedRows', 0)
        print(f'[sheets] appended {updated} row(s) to sheet {sheet_id} for inspection {inspection.id}')
        return True, None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        msg = f'Sheets API {e.code}: {body[:300]}'
        print(f'[sheets] ERROR: {msg}')
        return False, msg
    except Exception as exc:
        print(f'[sheets] ERROR: {exc}')
        return False, str(exc)
